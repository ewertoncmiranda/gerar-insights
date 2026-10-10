"""Regra de saida (OPR-INS-3, DEC-OPR-1). Puro.

Decisao no fechamento do pregao D, execucao simulada na abertura de D+1 (quem executa e o diario).
Mais de um motivo no mesmo pregao: vale o primeiro da PRIORIDADE.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

EVENTO, STOP, LIQUIDEZ, SINAL, PRAZO = "EVENTO", "STOP", "LIQUIDEZ", "SINAL", "PRAZO"
PRIORIDADE = (EVENTO, STOP, LIQUIDEZ, SINAL, PRAZO)
OPINIOES_DE_SAIDA = ("SINAL_NEGATIVO", "SEM_BASE")


@dataclass(frozen=True)
class ParametrosSaida:
    stop_atr: Decimal
    trailing_atr: Decimal
    trailing_armado_apos_atr: Decimal
    dias_iliquido_saida: int

    @classmethod
    def de_parametros(cls, parametros: dict) -> ParametrosSaida:
        s, liq = parametros.get("saida") or {}, parametros.get("liquidez") or {}
        return cls(stop_atr=Decimal(str(s.get("stop_atr", 2))), trailing_atr=Decimal(str(s.get("trailing_atr", 3))),
                   trailing_armado_apos_atr=Decimal(str(s.get("trailing_armado_apos_atr", 1))),
                   dias_iliquido_saida=int(liq.get("dias_iliquido_saida", 5)))


@dataclass(frozen=True)
class EstadoDoDia:
    """O que se sabe do ativo no fechamento do pregao (nada depois dele)."""

    fechamento: Decimal | None
    maxima: Decimal | None
    fato_relevante_hoje: bool
    salto_sem_evento: bool
    dias_insuficiente_seguidos: int
    opiniao_do_horizonte: str | None
    pregoes_desde_entrada: int


@dataclass(frozen=True)
class Avaliacao:
    motivo: str | None
    detalhe: dict
    stop_atual: Decimal
    maxima_desde_entrada: Decimal


def avaliar_saida(p: ParametrosSaida, *, preco_entrada: Decimal, atr_entrada: Decimal, stop_atual: Decimal,
                  maxima_desde_entrada: Decimal, horizonte_pregoes: int, dia: EstadoDoDia) -> Avaliacao:
    """Atualiza a maxima e o stop movel e diz se sai (e por que) neste pregao."""
    maxima = max(maxima_desde_entrada, dia.maxima or maxima_desde_entrada)
    stop = stop_atual
    if maxima >= preco_entrada + p.trailing_armado_apos_atr * atr_entrada:  # stop movel armado
        stop = max(stop, maxima - p.trailing_atr * atr_entrada)

    gatilhos: dict[str, dict] = {}
    if dia.fato_relevante_hoje or dia.salto_sem_evento:
        gatilhos[EVENTO] = {"fato_relevante": dia.fato_relevante_hoje, "salto_sem_evento": dia.salto_sem_evento}
    if dia.fechamento is not None and dia.fechamento < stop:
        gatilhos[STOP] = {"fechamento": str(dia.fechamento), "stop": str(stop),
                          "movel": stop > stop_atual or stop > preco_entrada - p.stop_atr * atr_entrada}
    if dia.dias_insuficiente_seguidos >= p.dias_iliquido_saida:
        gatilhos[LIQUIDEZ] = {"dias_insuficiente": dia.dias_insuficiente_seguidos, "limite": p.dias_iliquido_saida}
    if dia.opiniao_do_horizonte in OPINIOES_DE_SAIDA:
        gatilhos[SINAL] = {"opiniao": dia.opiniao_do_horizonte}
    if dia.pregoes_desde_entrada >= horizonte_pregoes:
        gatilhos[PRAZO] = {"pregoes": dia.pregoes_desde_entrada, "horizonte": horizonte_pregoes}

    motivo = next((m for m in PRIORIDADE if m in gatilhos), None)
    detalhe = {"motivo": motivo, "gatilhos": gatilhos} if motivo else {}
    return Avaliacao(motivo, detalhe, stop, maxima)
