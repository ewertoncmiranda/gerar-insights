"""Opiniao por horizonte (curto, medio, longo) a partir do insight deterministico.

    python -m app.opiniao.gerar [--data AAAA-MM-DD] [--simbolo PETR4 ...] [--sem-llm]

Roda depois dos insights diarios. Para cada ativo e horizonte: monta o dossie (evidencias,
opinioes permitidas e risco, tudo calculado por regra), pergunta ao modelo (Ollama) so quando
ha o que escolher, valida a resposta e grava em opiniao_ia (so inclusao). Sem modelo, ou com
resposta rejeitada duas vezes, grava a opiniao pelas regras (origem=REGRA). Regra experimental:
nenhuma opiniao aqui e recomendacao de investimento.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import date
from logging import Logger

from app.opiniao.modelo_llm import (
    SCHEMA_DA_RESPOSTA,
    SISTEMA,
    ErroDoProvedor,
    ProvedorLLM,
    montar_pedido,
    resposta_de_regra,
    validar,
)
from app.opiniao.regras import (
    HORIZONTES,
    SEM_BASE,
    VERSAO_PROMPT,
    DossieDeHorizonte,
    montar_dossie,
)
from app.opiniao.repositorio import RepositorioOpiniao

MODELO_REGRA = "regra"
TENTATIVAS = 2


@dataclass
class Resumo:
    data_pregao: date | None = None
    ativos: int = 0
    gravadas: int = 0
    ja_existiam: int = 0
    do_modelo: int = 0
    de_regra: int = 0
    rejeitadas: int = 0
    sem_insight: list[str] = field(default_factory=list)


def hash_do_dossie(simbolo: str, data_pregao: date, dossie: dict[int, DossieDeHorizonte]) -> str:
    base = {"s": simbolo, "d": data_pregao.isoformat(), "h": {
        str(h): {"permitidas": list(d.permitidas), "risco": d.risco,
                 "e": [[e.id, e.valor, e.direcao] for e in d.evidencias]} for h, d in dossie.items()}}
    return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def consultar_modelo(provedor: ProvedorLLM, simbolo: str, dossie: DossieDeHorizonte,
                     logger: Logger) -> tuple[dict | None, int]:
    """(resposta valida ou None, tentativas feitas). Falha do provedor nao derruba o lote."""
    pedido = montar_pedido(simbolo, dossie)
    erros_anteriores: list[str] = []
    for tentativa in range(1, TENTATIVAS + 1):
        usuario = pedido if not erros_anteriores else (
            pedido + "\n\nSua resposta anterior foi rejeitada: " + "; ".join(erros_anteriores)
            + ". Corrija e responda de novo.")
        try:
            bruto = provedor.gerar(SISTEMA, usuario, SCHEMA_DA_RESPOSTA)
        except ErroDoProvedor as erro:
            logger.warning("Opiniao %s h=%d: %s", simbolo, dossie.pregoes, erro)
            return None, tentativa
        try:
            resposta = json.loads(bruto)
        except json.JSONDecodeError:
            erros_anteriores = ["resposta não é JSON válido"]
            continue
        valida, erros = validar(resposta, dossie)
        if valida is not None:
            return valida, tentativa
        erros_anteriores = erros
        logger.info("Opiniao %s h=%d rejeitada (tentativa %d): %s", simbolo, dossie.pregoes, tentativa, erros)
    return None, TENTATIVAS


def gerar_do_ativo(db, repo: RepositorioOpiniao, simbolo: str, data_pregao: date,
                   provedor: ProvedorLLM | None, logger: Logger, resumo: Resumo) -> None:
    insight = repo.ultimo_insight(db, simbolo, data_pregao)
    if insight is None:
        resumo.sem_insight.append(simbolo)
        return
    fatores = repo.fatores_recentes(db, simbolo)
    fatos = repo.fatos_relevantes_30d(db, simbolo, data_pregao)
    dossie, ausentes = montar_dossie(insight["detalhes"], fatores, fatos, data_pregao)
    hash_dossie = hash_do_dossie(simbolo, data_pregao, dossie)
    modelo = provedor.nome if provedor else MODELO_REGRA
    versao_regra = str(insight["detalhes"].get("versao_regra") or "")
    resumo.ativos += 1

    for horizonte in HORIZONTES:
        if repo.ja_existe(db, simbolo, data_pregao, horizonte, modelo, VERSAO_PROMPT):
            resumo.ja_existiam += 1
            continue
        d = dossie[horizonte]
        resposta, tentativas, origem = None, 0, "REGRA"
        # So pergunta ao modelo quando ha o que escolher: SEM_BASE forcado dispensa a chamada.
        if provedor is not None and d.permitidas != (SEM_BASE,):
            resposta, tentativas = consultar_modelo(provedor, simbolo, d, logger)
            if resposta is None:
                resumo.rejeitadas += 1
        if resposta is None:
            resposta = resposta_de_regra(d)
            resumo.de_regra += 1
        else:
            origem = "MODELO"
            resumo.do_modelo += 1
        registro = {
            "simbolo": simbolo, "data_pregao": data_pregao, "horizonte_pregoes": horizonte,
            "opiniao": resposta["opiniao"], "risco": resposta["risco"],
            "justificativa_json": json.dumps(resposta["justificativa"], ensure_ascii=False),
            "invalida_json": json.dumps(resposta["o_que_invalida"], ensure_ascii=False),
            "dados_ausentes_json": json.dumps(ausentes + ([d.motivo_sem_base] if d.motivo_sem_base else []),
                                              ensure_ascii=False),
            "evidencias_json": json.dumps([{"id": e.id, "rotulo": e.rotulo, "valor": e.valor,
                                            "direcao": e.direcao} for e in d.evidencias], ensure_ascii=False),
            "modelo": modelo, "versao_prompt": VERSAO_PROMPT, "versao_regra": versao_regra,
            "origem": origem, "tentativas": tentativas, "dossie_hash": hash_dossie,
            "insight_id": insight["id"],
        }
        if repo.gravar(db, registro):
            resumo.gravadas += 1
    db.commit()


def executar(db, logger: Logger, data_pregao: date | None, simbolos: list[str] | None,
             provedor: ProvedorLLM | None) -> Resumo:
    repo = RepositorioOpiniao()
    data_pregao = data_pregao or repo.ultimo_pregao_com_insight(db)
    resumo = Resumo(data_pregao=data_pregao)
    if data_pregao is None:
        return resumo
    alvo = simbolos or repo.simbolos_do_pregao(db, data_pregao)
    for simbolo in alvo:
        gerar_do_ativo(db, repo, simbolo.upper(), data_pregao, provedor, logger, resumo)
    return resumo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Opiniao por horizonte (Ollama)")
    parser.add_argument("--data", type=date.fromisoformat, help="pregao (padrao: o ultimo com insight)")
    parser.add_argument("--simbolo", action="append", help="limita a um ativo (repita para varios)")
    parser.add_argument("--sem-llm", action="store_true", help="grava so a opiniao pelas regras")
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.config.settings import Settings
    from app.opiniao.modelo_llm import OllamaProvedor

    logger = setup_logger()
    cfg = Settings()
    provedor = None if argumentos.sem_llm else OllamaProvedor(
        cfg.ollama_url, cfg.ollama_modelo, timeout_s=cfg.ollama_timeout_s)
    with ConfigDatabase().session() as db:
        r = executar(db, logger, argumentos.data, argumentos.simbolo, provedor)
    logger.info(
        "Opiniao %s | ativos=%d | gravadas=%d | ja existiam=%d | modelo=%d | regra=%d | rejeitadas=%d | sem insight=%s",
        r.data_pregao, r.ativos, r.gravadas, r.ja_existiam, r.do_modelo, r.de_regra, r.rejeitadas, r.sem_insight,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
