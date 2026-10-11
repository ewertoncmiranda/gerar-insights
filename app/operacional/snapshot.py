"""Snapshot operacional por ticker (OPRV2-INS-1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.operacional.consenso import montar_consenso
from app.operacional.tese import montar_tese


@dataclass(frozen=True)
class EntradaSnapshot:
    simbolo: str
    data_pregao: date
    versao_regra: str
    status_operacional: str | None
    status_sistema: str | None = None
    faixa_liquidez: str | None = None
    sinal_principal: str | None = None
    sinal_momentum: str | None = None
    sinal_reversao: str | None = None
    sinal_v2: str | None = None
    opiniao_ia: str | None = None
    confianca_score: float | int | None = None
    confianca_tem_evidencia: bool = False
    posicao: dict | None = None
    ultimo_evento: dict | None = None
    motivos_bloqueio: list[dict] = field(default_factory=list)
    ressalvas_elegibilidade: list[dict] = field(default_factory=list)
    setor_grupo: str | None = None


def montar_snapshot(entrada: EntradaSnapshot) -> dict:
    confianca_faixa = faixa_confianca(entrada.confianca_score, entrada.confianca_tem_evidencia)
    consenso = montar_consenso(
        sinal_principal=entrada.sinal_principal,
        sinal_momentum=entrada.sinal_momentum,
        sinal_reversao=entrada.sinal_reversao,
        sinal_v2=entrada.sinal_v2,
        opiniao_ia=entrada.opiniao_ia,
        status_operacional=entrada.status_operacional,
        motivos_bloqueio=entrada.motivos_bloqueio,
    )
    snapshot = {
        "schemaVersion": "operacional.snapshot-ticker.v2",
        "simbolo": entrada.simbolo,
        "dataPregao": entrada.data_pregao.isoformat(),
        "versaoRegra": entrada.versao_regra,
        "statusSistema": entrada.status_sistema,
        "statusOperacional": entrada.status_operacional,
        "faixaLiquidez": entrada.faixa_liquidez,
        "setorGrupo": entrada.setor_grupo,
        "sinalPrincipal": entrada.sinal_principal,
        "sinalTecnico": {
            "momentum": entrada.sinal_momentum,
            "reversao": entrada.sinal_reversao,
        },
        "sinalV2Sombra": entrada.sinal_v2,
        "opiniaoIa": entrada.opiniao_ia,
        "confiancaScore": entrada.confianca_score,
        "confiancaFaixa": confianca_faixa,
        "posicao": entrada.posicao,
        "ultimoEvento": entrada.ultimo_evento,
        "motivosBloqueio": entrada.motivos_bloqueio,
        "elegibilidadeTicker": {
            "elegivel": entrada.status_operacional in {"EM_OBSERVACAO", "PAPER_TRADING_ELEGIVEL"},
            "faixaLiquidez": entrada.faixa_liquidez,
            "bloqueios": entrada.motivos_bloqueio,
            "ressalvas": entrada.ressalvas_elegibilidade,
        },
        "consenso": consenso.como_dict(),
    }
    snapshot["tese"] = montar_tese(snapshot, snapshot["consenso"])
    return snapshot


def faixa_confianca(score: float | int | None, tem_evidencia_real: bool) -> str:
    if score is None or not tem_evidencia_real:
        return "NAO_CALIBRADA"
    if score >= 80:
        return "ALTA"
    if score >= 60:
        return "MEDIA"
    return "BAIXA"
