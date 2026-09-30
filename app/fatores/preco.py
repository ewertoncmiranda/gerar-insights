"""Fatores de preco (LAC-INS-3). Puro.

Todos sobre o preco ajustado (ajuste_preco.py) e SO com pregoes anteriores ao
de referencia (o primeiro do mes): quem calcula o fator do mes M nao ve o
preco do proprio dia de referencia, nem nada depois.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from datetime import date

PREGOES_ANO = 252
PREGOES_MES = 21
PREGOES_TRIMESTRE = 63


@dataclass(frozen=True)
class PregaoFator:
    data: date
    fechamento: float
    volume_financeiro: float | None = None
    preco_medio: float | None = None
    oferta_compra: float | None = None
    oferta_venda: float | None = None


def retornos_diarios(serie: list[PregaoFator]) -> dict[date, float]:
    """Retorno log de fechamento a fechamento, pela data do pregao final."""
    return {
        atual.data: math.log(atual.fechamento / anterior.fechamento)
        for anterior, atual in zip(serie, serie[1:])
        if anterior.fechamento > 0 and atual.fechamento > 0
    }


def media_do_universo(retornos: dict[str, dict[date, float]]) -> dict[date, float]:
    """Retorno diario medio (igual peso) do universo: o 'mercado' do beta."""
    por_dia: dict[date, list[float]] = {}
    for serie in retornos.values():
        for dia, r in serie.items():
            por_dia.setdefault(dia, []).append(r)
    return {d: sum(v) / len(v) for d, v in por_dia.items() if len(v) >= 5}


def calcular(serie: list[PregaoFator], referencia: date, mercado: dict[date, float] | None = None) -> dict[str, float]:
    """Fatores do papel na data de referencia. Fator sem historico suficiente
    fica de fora do dicionario (nao vira zero)."""
    passado = [p for p in serie if p.data < referencia]
    fatores: dict[str, float] = {}
    if len(passado) < 2:
        return fatores
    fech = [p.fechamento for p in passado]

    if len(passado) > PREGOES_ANO:
        inicio, fim = fech[-PREGOES_ANO - 1], fech[-PREGOES_MES - 1]
        if inicio > 0:
            fatores["MOMENTO_12_1"] = fim / inicio - 1

    ano = passado[-PREGOES_ANO - 1:]
    retornos = retornos_diarios(ano)
    if len(retornos) >= PREGOES_ANO * 0.8:
        fatores["VOLATILIDADE_12M"] = statistics.stdev(retornos.values()) * math.sqrt(PREGOES_ANO)
        maximo = max(p.fechamento for p in ano)
        if maximo > 0:
            fatores["DRAWDOWN_12M"] = ano[-1].fechamento / maximo - 1
        if mercado:
            comuns = [d for d in retornos if d in mercado]
            if len(comuns) >= PREGOES_ANO * 0.8:
                beta = _beta([retornos[d] for d in comuns], [mercado[d] for d in comuns])
                if beta is not None:
                    fatores["BETA_12M"] = beta

    trimestre = passado[-PREGOES_TRIMESTRE:]
    volumes = [p.volume_financeiro for p in trimestre if p.volume_financeiro is not None]
    if len(volumes) >= PREGOES_TRIMESTRE * 0.8:
        fatores["LIQUIDEZ_63D"] = sum(volumes) / len(volumes)

    spread = spread_mediano(trimestre)
    if spread is not None:
        fatores["SPREAD_MEDIANO_63D"] = spread

    ultimo = passado[-1]
    if ultimo.preco_medio:
        fatores["DISTANCIA_VWAP"] = ultimo.fechamento / ultimo.preco_medio
    return fatores


def spread_mediano(pregoes: list[PregaoFator]) -> float | None:
    """(melhor oferta de venda - melhor de compra) / preco medio, mediana.
    Metade de pregoes sem oferta registrada: sem valor."""
    spreads = [
        (p.oferta_venda - p.oferta_compra) / p.preco_medio
        for p in pregoes
        if p.oferta_compra and p.oferta_venda and p.preco_medio and p.oferta_venda >= p.oferta_compra
    ]
    if len(spreads) < max(1, len(pregoes) * 0.5):
        return None
    return statistics.median(spreads)


def _beta(ativo: list[float], mercado: list[float]) -> float | None:
    media_a, media_m = sum(ativo) / len(ativo), sum(mercado) / len(mercado)
    variancia = sum((m - media_m) ** 2 for m in mercado)
    if variancia == 0:
        return None
    covariancia = sum((a - media_a) * (m - media_m) for a, m in zip(ativo, mercado))
    return covariancia / variancia
