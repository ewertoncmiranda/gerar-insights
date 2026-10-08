"""Opiniao por horizonte (curto, medio, longo) a partir do insight deterministico.

    python -m app.opiniao.gerar [--data AAAA-MM-DD] [--simbolo PETR4 ...] [--sem-llm]

Roda depois dos insights diarios. Para cada ativo e horizonte: monta o dossie (evidencias,
opinioes permitidas e risco, tudo calculado por regra), manda ao servico de IA (`POST /opiniao`,
insider-ia-b3-ecossytem, TASK-IA-03) e grava a resposta em opiniao_ia (so inclusao). O servico
decide entre modelo e reserva por regra; o worker nao conhece prompt nem modelo. Com `--sem-llm`,
ou com o servico fora do ar, grava a opiniao pelas regras locais (origem=REGRA), igual a do
servico. Regra experimental: nenhuma opiniao aqui e recomendacao de investimento.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.opiniao.cliente_ia import ErroDoServicoIA, Identidade, ServicoIA, pedido_do_dossie
from app.opiniao.regras import HORIZONTES, VERSAO_PROMPT, DossieDeHorizonte, montar_dossie
from app.opiniao.repositorio import RepositorioOpiniao
from app.opiniao.reserva import resposta_de_regra

MODELO_REGRA = "regra"
# Sem servico de IA: mesma chave de antes (modelo "regra" + versao das regras locais).
IDENTIDADE_LOCAL = Identidade(MODELO_REGRA, VERSAO_PROMPT)


@dataclass
class Resumo:
    data_pregao: date | None = None
    ativos: int = 0
    gravadas: int = 0
    ja_existiam: int = 0
    do_modelo: int = 0
    de_regra: int = 0
    falhas_do_servico: int = 0
    sem_insight: list[str] = field(default_factory=list)


def hash_do_dossie(simbolo: str, data_pregao: date, dossie: dict[int, DossieDeHorizonte]) -> str:
    base = {"s": simbolo, "d": data_pregao.isoformat(), "h": {
        str(h): {"permitidas": list(d.permitidas), "risco": d.risco,
                 "e": [[e.id, e.valor, e.direcao] for e in d.evidencias]} for h, d in dossie.items()}}
    return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def opinar(servico: ServicoIA | None, pedido: dict, d: DossieDeHorizonte, logger: Logger,
           resumo: Resumo) -> tuple[dict, str, int]:
    """(resposta, origem, tentativas). Servico fora do ar nao derruba o lote: cai na regra local."""
    if servico is not None:
        try:
            resposta = servico.opinar(pedido)
            return resposta, str(resposta["origem"]), int(resposta.get("tentativas") or 0)
        except ErroDoServicoIA as erro:
            resumo.falhas_do_servico += 1
            logger.warning("Opiniao %s h=%d: %s; gravando pela regra local",
                           pedido["simbolo"], d.pregoes, erro)
    return resposta_de_regra(d), "REGRA", 0


def gerar_do_ativo(db, repo: RepositorioOpiniao, simbolo: str, data_pregao: date,
                   servico: ServicoIA | None, identidade: Identidade, logger: Logger, resumo: Resumo) -> None:
    insight = repo.ultimo_insight(db, simbolo, data_pregao)
    if insight is None:
        resumo.sem_insight.append(simbolo)
        return
    fatores = repo.fatores_recentes(db, simbolo)
    fatos = repo.fatos_relevantes_30d(db, simbolo, data_pregao)
    dossie, ausentes = montar_dossie(insight["detalhes"], fatores, fatos, data_pregao)
    hash_dossie = hash_do_dossie(simbolo, data_pregao, dossie)
    versao_regra = str(insight["detalhes"].get("versao_regra") or "")
    resumo.ativos += 1

    for horizonte in HORIZONTES:
        # Idempotencia por (ativo, pregao, horizonte, modelo, versao das skills): rodar de novo nao duplica.
        if repo.ja_existe(db, simbolo, data_pregao, horizonte, identidade.modelo, identidade.skills_versao):
            resumo.ja_existiam += 1
            continue
        d = dossie[horizonte]
        pedido = pedido_do_dossie(simbolo, data_pregao, d, ausentes, versao_regra)
        resposta, origem, tentativas = opinar(servico, pedido, d, logger, resumo)
        if origem == "MODELO":
            resumo.do_modelo += 1
        else:
            resumo.de_regra += 1
        registro = {
            "simbolo": simbolo, "data_pregao": data_pregao, "horizonte_pregoes": horizonte,
            "opiniao": resposta["opiniao"], "risco": resposta["risco"],
            # Item inteiro, como o servico devolveu (DEC-IA-03): evidencia_id ou trecho_id, e para
            # trecho tambem `fonte` e `trecho`, congelados na geracao. Nada e filtrado aqui.
            "justificativa_json": json.dumps([dict(j) for j in resposta["justificativa"]], ensure_ascii=False),
            "invalida_json": json.dumps(resposta["o_que_invalida"], ensure_ascii=False),
            "dados_ausentes_json": json.dumps(ausentes + ([d.motivo_sem_base] if d.motivo_sem_base else []),
                                              ensure_ascii=False),
            "evidencias_json": json.dumps(pedido["evidencias"], ensure_ascii=False),
            # A chave da linha e a identidade do lote (a mesma do ja_existe), mesmo quando um
            # horizonte caiu na regra local por falha pontual do servico.
            "modelo": identidade.modelo, "versao_prompt": identidade.skills_versao,
            "versao_regra": versao_regra, "origem": origem, "tentativas": tentativas,
            "dossie_hash": hash_dossie, "insight_id": insight["id"],
        }
        if repo.gravar(db, registro):
            resumo.gravadas += 1
    db.commit()


def resolver_identidade(servico: ServicoIA | None, logger: Logger) -> tuple[ServicoIA | None, Identidade]:
    """Servico no ar: modelo e skills dele. Fora do ar: segue o lote pelas regras locais."""
    if servico is None:
        return None, IDENTIDADE_LOCAL
    try:
        return servico, servico.identidade()
    except ErroDoServicoIA as erro:
        logger.warning("Servico de IA fora do ar (%s); opinioes pelas regras locais", erro)
        return None, IDENTIDADE_LOCAL


def executar(db, logger: Logger, data_pregao: date | None, simbolos: list[str] | None,
             servico: ServicoIA | None) -> Resumo:
    repo = RepositorioOpiniao()
    data_pregao = data_pregao or repo.ultimo_pregao_com_insight(db)
    resumo = Resumo(data_pregao=data_pregao)
    if data_pregao is None:
        return resumo
    servico, identidade = resolver_identidade(servico, logger)
    alvo = simbolos or repo.simbolos_do_pregao(db, data_pregao)
    for simbolo in alvo:
        gerar_do_ativo(db, repo, simbolo.upper(), data_pregao, servico, identidade, logger, resumo)
    return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opiniao por horizonte (servico de IA)")
    parser.add_argument("--data", type=date.fromisoformat, help="pregao (padrao: o ultimo com insight)")
    parser.add_argument("--simbolo", action="append", help="limita a um ativo (repita para varios)")
    parser.add_argument("--sem-llm", action="store_true", help="grava so a opiniao pelas regras locais")
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.config.settings import Settings

    logger = setup_logger()
    cfg = Settings()
    servico = None if argumentos.sem_llm else ServicoIA(cfg.ia_url, timeout_s=cfg.ia_timeout_s)
    with ConfigDatabase().session() as db:
        r = executar(db, logger, argumentos.data, argumentos.simbolo, servico)
    logger.info(
        "Opiniao %s | ativos=%d | gravadas=%d | ja existiam=%d | modelo=%d | regra=%d | falhas do servico=%d"
        " | sem insight=%s",
        r.data_pregao, r.ativos, r.gravadas, r.ja_existiam, r.do_modelo, r.de_regra, r.falhas_do_servico,
        r.sem_insight,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
