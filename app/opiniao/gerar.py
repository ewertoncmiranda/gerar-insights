"""Opiniao por horizonte (curto, medio, longo) a partir do insight deterministico.

    python -m app.opiniao.gerar [--data AAAA-MM-DD] [--simbolo PETR4 ...] [--sem-llm] [--sem-limite]

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

from app.opiniao.cliente_ia import (
    ErroDoServicoIA,
    Identidade,
    RotaNaoEncontrada,
    ServicoIA,
    pedido_do_ativo,
    pedido_do_dossie,
)
from app.opiniao.prioridade import priorizar
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
    priorizados: int = 0
    chamadas: int = 0
    reaproveitadas: int = 0
    sem_cota: int = 0
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


def _registro(simbolo: str, data_pregao: date, horizonte: int, resposta: dict, origem: str, tentativas: int,
              modelo: str, versao_prompt: str, versao_regra: str, dossie_hash: str, insight_id: int,
              ausentes: list[str], d: DossieDeHorizonte, evidencias: list[dict]) -> dict:
    return {
        "simbolo": simbolo, "data_pregao": data_pregao, "horizonte_pregoes": horizonte,
        "opiniao": resposta["opiniao"], "risco": resposta["risco"],
        "justificativa_json": json.dumps([dict(j) for j in resposta["justificativa"]], ensure_ascii=False),
        "invalida_json": json.dumps(resposta["o_que_invalida"], ensure_ascii=False),
        "dados_ausentes_json": json.dumps(ausentes + ([d.motivo_sem_base] if d.motivo_sem_base else []),
                                          ensure_ascii=False),
        "evidencias_json": json.dumps(evidencias, ensure_ascii=False),
        "modelo": modelo, "versao_prompt": versao_prompt,
        "versao_regra": versao_regra, "origem": origem, "tentativas": tentativas,
        "dossie_hash": dossie_hash, "insight_id": insight_id,
    }


def _gravar_regra_local(repo: RepositorioOpiniao, db, simbolo: str, data_pregao: date, insight: dict,
                        dossie: dict[int, DossieDeHorizonte], ausentes: list[str],
                        hash_dossie: str, versao_regra: str, resumo: Resumo) -> None:
    for horizonte in HORIZONTES:
        if repo.ja_existe(db, simbolo, data_pregao, horizonte, MODELO_REGRA, VERSAO_PROMPT):
            resumo.ja_existiam += 1
            continue
        d = dossie[horizonte]
        pedido = pedido_do_dossie(simbolo, data_pregao, d, ausentes, versao_regra)
        registro = _registro(
            simbolo, data_pregao, horizonte, resposta_de_regra(d), "REGRA", 0,
            MODELO_REGRA, VERSAO_PROMPT, versao_regra, hash_dossie, insight["id"],
            ausentes, d, pedido["evidencias"],
        )
        if repo.gravar(db, registro):
            resumo.gravadas += 1
            resumo.de_regra += 1


def _reaproveitar(repo: RepositorioOpiniao, db, simbolo: str, data_pregao: date, hash_dossie: str,
                  insight_id: int, resumo: Resumo) -> bool:
    if not hasattr(repo, "opinioes_modelo_por_hash"):
        return False
    anteriores = repo.opinioes_modelo_por_hash(db, simbolo, data_pregao, hash_dossie)
    if len(anteriores) < len(HORIZONTES):
        return False
    for registro in anteriores:
        registro["insight_id"] = insight_id
        if repo.gravar(db, registro):
            resumo.gravadas += 1
            resumo.do_modelo += 1
            resumo.reaproveitadas += 1
    return True


def _opinar_ativo_ou_v1(servico: ServicoIA | None, simbolo: str, data_pregao: date,
                        dossie: dict[int, DossieDeHorizonte], ausentes: list[str], versao_regra: str,
                        identidade: Identidade, logger: Logger, resumo: Resumo) -> tuple[list[dict], dict]:
    if servico is not None and hasattr(servico, "opinar_ativo"):
        try:
            resumo.chamadas += 1
            resposta = servico.opinar_ativo(pedido_do_ativo(simbolo, data_pregao, dossie, ausentes, versao_regra))
            skills_versao = resposta.get("skills_versao")
            if skills_versao:
                for item in resposta["itens"]:
                    item.setdefault("skills_versao", skills_versao)
            for item in resposta["itens"]:
                item["_via_ativo"] = True
            return resposta["itens"], resposta.get("cota") or {}
        except RotaNaoEncontrada:
            logger.info("Servico IA sem /opiniao/ativo; usando /opiniao v1.0 por horizonte para %s", simbolo)
            resumo.chamadas -= 1
        except ErroDoServicoIA as erro:
            resumo.falhas_do_servico += 1
            logger.warning("Opiniao %s: %s; gravando pela regra local", simbolo, erro)
            return [], {}

    itens = []
    for horizonte in HORIZONTES:
        d = dossie[horizonte]
        pedido = pedido_do_dossie(simbolo, data_pregao, d, ausentes, versao_regra)
        resposta, origem, tentativas = opinar(servico, pedido, d, logger, resumo)
        if servico is not None:
            resumo.chamadas += 1
        itens.append({**resposta, "horizonte_pregoes": horizonte, "origem": origem,
                      "modelo": identidade.modelo, "skills_versao": identidade.skills_versao,
                      "tentativas": tentativas, "_via_ativo": False})
    return itens, {}


def gerar_do_ativo(db, repo: RepositorioOpiniao, simbolo: str, data_pregao: date,
                   servico: ServicoIA | None, identidade: Identidade, logger: Logger, resumo: Resumo,
                   usar_modelo: bool = True, reaproveitar_hash: bool = True) -> bool:
    insight = repo.ultimo_insight(db, simbolo, data_pregao)
    if insight is None:
        resumo.sem_insight.append(simbolo)
        return True
    fatores = repo.fatores_recentes(db, simbolo)
    fatos = repo.fatos_relevantes_30d(db, simbolo, data_pregao)
    dossie, ausentes = montar_dossie(insight["detalhes"], fatores, fatos, data_pregao)
    hash_dossie = hash_do_dossie(simbolo, data_pregao, dossie)
    versao_regra = str(insight["detalhes"].get("versao_regra") or "")
    resumo.ativos += 1

    if usar_modelo and all(
        repo.ja_existe(db, simbolo, data_pregao, h, identidade.modelo, identidade.skills_versao)
        for h in HORIZONTES
    ):
        resumo.ja_existiam += len(HORIZONTES)
        return True
    if reaproveitar_hash and usar_modelo and _reaproveitar(
        repo, db, simbolo, data_pregao, hash_dossie, insight["id"], resumo
    ):
        db.commit()
        return True
    if not usar_modelo or servico is None:
        _gravar_regra_local(repo, db, simbolo, data_pregao, insight, dossie, ausentes, hash_dossie, versao_regra, resumo)
        db.commit()
        return True

    itens, cota = _opinar_ativo_ou_v1(servico, simbolo, data_pregao, dossie, ausentes, versao_regra,
                                      identidade, logger, resumo)
    if not itens:
        _gravar_regra_local(repo, db, simbolo, data_pregao, insight, dossie, ausentes, hash_dossie, versao_regra, resumo)
    for item in itens:
        horizonte = int(item["horizonte_pregoes"])
        d = dossie[horizonte]
        origem = str(item["origem"])
        modelo = (
            MODELO_REGRA
            if origem == "REGRA" and item.get("_via_ativo")
            else str(item.get("modelo") or identidade.modelo)
        )
        versao_prompt = str(item.get("skills_versao") or identidade.skills_versao)
        if repo.ja_existe(db, simbolo, data_pregao, horizonte, modelo, versao_prompt):
            resumo.ja_existiam += 1
            continue
        if origem == "MODELO":
            resumo.do_modelo += 1
        else:
            resumo.de_regra += 1
        pedido = pedido_do_dossie(simbolo, data_pregao, d, ausentes, versao_regra)
        registro = _registro(
            simbolo, data_pregao, horizonte, item, origem, int(item.get("tentativas") or 0),
            modelo, versao_prompt, versao_regra, hash_dossie, insight["id"], ausentes, d, pedido["evidencias"],
        )
        if repo.gravar(db, registro):
            resumo.gravadas += 1
    db.commit()
    return not (cota and cota.get("gemini_disponivel") is False)


def resolver_identidade(servico: ServicoIA | None, logger: Logger) -> tuple[ServicoIA | None, Identidade]:
    """Servico no ar: modelo e skills dele. Fora do ar: segue o lote pelas regras locais."""
    if servico is None:
        return None, IDENTIDADE_LOCAL
    try:
        return servico, servico.identidade()
    except ErroDoServicoIA as erro:
        logger.warning("Servico de IA fora do ar (%s); opinioes pelas regras locais", erro)
        return None, IDENTIDADE_LOCAL
    except AttributeError:
        return servico, IDENTIDADE_LOCAL


def executar(db, logger: Logger, data_pregao: date | None, simbolos: list[str] | None,
             servico: ServicoIA | None, lote_max_gemini: int = 25, sem_limite: bool = False) -> Resumo:
    repo = RepositorioOpiniao()
    data_pregao = data_pregao or repo.ultimo_pregao_com_insight(db)
    resumo = Resumo(data_pregao=data_pregao)
    if data_pregao is None:
        return resumo
    servico, identidade = resolver_identidade(servico, logger)
    alvo = [s.upper() for s in (simbolos or repo.simbolos_do_pregao(db, data_pregao))]
    limite = None if (sem_limite or simbolos) else lote_max_gemini
    fila = alvo if simbolos else priorizar(repo, db, data_pregao, alvo, limite)
    resumo.priorizados = len(fila)
    fila_set = set(fila)
    sem_cota = False
    for simbolo in alvo:
        usar_modelo = simbolo in fila_set and not sem_cota
        if simbolo in fila_set and sem_cota:
            resumo.sem_cota += 1
        continua = gerar_do_ativo(db, repo, simbolo, data_pregao, servico, identidade, logger, resumo,
                                  usar_modelo=usar_modelo)
        if usar_modelo and not continua:
            sem_cota = True
    return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opiniao por horizonte (servico de IA)")
    parser.add_argument("--data", type=date.fromisoformat, help="pregao (padrao: o ultimo com insight)")
    parser.add_argument("--simbolo", action="append", help="limita a um ativo (repita para varios)")
    parser.add_argument("--sem-llm", action="store_true", help="grava so a opiniao pelas regras locais")
    parser.add_argument("--sem-limite", action="store_true", help="ignora LOTE_MAX_GEMINI e envia todos ao servico")
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.config.settings import Settings

    logger = setup_logger()
    cfg = Settings()
    servico = None if argumentos.sem_llm else ServicoIA(cfg.ia_url, timeout_s=cfg.ia_timeout_s)
    with ConfigDatabase().session() as db:
        r = executar(db, logger, argumentos.data, argumentos.simbolo, servico,
                     lote_max_gemini=cfg.lote_max_gemini, sem_limite=argumentos.sem_limite)
    logger.info(
        "Opiniao %s | ativos=%d | priorizados=%d | chamadas=%d | gravadas=%d | ja existiam=%d | "
        "reaproveitadas=%d | sem_cota=%d | modelo=%d | regra=%d | falhas_do_servico=%d | sem insight=%s",
        r.data_pregao, r.ativos, r.priorizados, r.chamadas, r.gravadas, r.ja_existiam,
        r.reaproveitadas, r.sem_cota, r.do_modelo, r.de_regra, r.falhas_do_servico, r.sem_insight,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
