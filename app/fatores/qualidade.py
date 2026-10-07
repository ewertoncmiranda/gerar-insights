"""Fatores de qualidade e valor (LAC-INS-4). Puro.

Ponto no tempo: na data de referencia so vale o balanco ja ENTREGUE a CVM
(data_entrega <= referencia), o de maior data de entrega - a mesma regra de
DadosPontoNoTempo.

Valor (EARNINGS_YIELD, BOOK_TO_MARKET, DIVIDEND_YIELD) usa o preco BRUTO do
dia: LPA, VPA e provento por acao sao da quantidade de acoes daquela epoca;
dividir pelo preco ajustado a escala de hoje erraria o fator em todo
desdobramento posterior.

Piotroski precisa de dois exercicios anuais completos (inclusive as 4 contas
novas da V16); faltou um campo, o escore fica de fora - sem valor parcial.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Balanco:
    periodo: date
    tipo_periodo: str  # ANUAL | TTM
    data_entrega: date
    lucro_liquido: float | None = None
    patrimonio_liquido: float | None = None
    receita_liquida: float | None = None
    ebit: float | None = None
    divida_bruta: float | None = None
    caixa: float | None = None
    fluxo_caixa_operacional: float | None = None
    acoes: float | None = None
    lpa: float | None = None
    vpa: float | None = None
    ativo_total: float | None = None
    ativo_circulante: float | None = None
    passivo_circulante: float | None = None
    lucro_bruto: float | None = None


def vigente(balancos: list[Balanco], referencia: date, tipo: str | None = None) -> Balanco | None:
    """O balanco entregue mais recentemente ate a referencia (opcionalmente
    so de um tipo); em entrega no mesmo dia, o periodo mais novo."""
    conhecidos = [b for b in balancos if b.data_entrega <= referencia and (tipo is None or b.tipo_periodo == tipo)]
    return max(conhecidos, key=lambda b: (b.data_entrega, b.periodo), default=None)


def anterior_ao(balancos: list[Balanco], atual: Balanco, referencia: date) -> Balanco | None:
    """Mesmo tipo, periodo um ano antes, ja entregue ate a referencia.

    Casa por ano e mes, nao pela data: exercicio que fecha em fevereiro
    (CAML3) alterna 28 e 29/02, e `replace(year=...)` em 29/02 nem existe."""
    candidatos = [
        b for b in balancos
        if b.tipo_periodo == atual.tipo_periodo
        and (b.periodo.year, b.periodo.month) == (atual.periodo.year - 1, atual.periodo.month)
        and b.data_entrega <= referencia
    ]
    return max(candidatos, key=lambda b: b.data_entrega, default=None)


def calcular(
    balancos: list[Balanco],
    referencia: date,
    preco_bruto: float | None,
    proventos_12m_por_acao: float | None = None,
) -> dict[str, float]:
    fatores: dict[str, float] = {}
    atual = vigente(balancos, referencia)
    if atual is None:
        return fatores

    divida_liquida = _sub(atual.divida_bruta, atual.caixa)
    capital = _soma(atual.patrimonio_liquido, divida_liquida)
    # Capital ou patrimonio negativo invertem o sinal do indice: ficam de fora.
    _por(fatores, "ROIC", atual.ebit, capital, so_positivo=True)
    _por(fatores, "ALAVANCAGEM", divida_liquida, atual.patrimonio_liquido, so_positivo=True)
    _por(fatores, "MARGEM_BRUTA", atual.lucro_bruto, atual.receita_liquida)
    _por(fatores, "ACCRUALS", _sub(atual.lucro_liquido, atual.fluxo_caixa_operacional), atual.ativo_total)

    anterior = anterior_ao(balancos, atual, referencia)
    if anterior is not None and atual.lpa is not None and anterior.lpa and anterior.lpa > 0:
        fatores["CRESCIMENTO_LPA"] = atual.lpa / anterior.lpa - 1

    anual = vigente(balancos, referencia, "ANUAL")
    anual_anterior = anterior_ao(balancos, anual, referencia) if anual else None
    escore = piotroski(anual, anual_anterior) if anual and anual_anterior else None
    if escore is not None:
        fatores["PIOTROSKI"] = float(escore)

    if preco_bruto and preco_bruto > 0:
        if atual.lpa is not None:
            fatores["EARNINGS_YIELD"] = atual.lpa / preco_bruto
        if atual.vpa is not None:
            fatores["BOOK_TO_MARKET"] = atual.vpa / preco_bruto
        if proventos_12m_por_acao is not None:
            fatores["DIVIDEND_YIELD"] = proventos_12m_por_acao / preco_bruto
    return fatores


def piotroski(atual: Balanco, anterior: Balanco) -> int | None:
    """Escore F (0 a 9) com dois exercicios anuais. None se faltar dado."""
    campos = ("lucro_liquido", "fluxo_caixa_operacional", "ativo_total", "divida_bruta",
              "ativo_circulante", "passivo_circulante", "acoes", "lucro_bruto", "receita_liquida")
    for b in (atual, anterior):
        if any(getattr(b, c) is None for c in campos) or not b.ativo_total or not b.passivo_circulante \
                or not b.receita_liquida:
            return None

    def roa(b: Balanco) -> float:
        return b.lucro_liquido / b.ativo_total

    testes = [
        roa(atual) > 0,
        atual.fluxo_caixa_operacional > 0,
        roa(atual) > roa(anterior),
        atual.fluxo_caixa_operacional > atual.lucro_liquido,
        atual.divida_bruta / atual.ativo_total < anterior.divida_bruta / anterior.ativo_total,
        atual.ativo_circulante / atual.passivo_circulante > anterior.ativo_circulante / anterior.passivo_circulante,
        atual.acoes <= anterior.acoes,
        atual.lucro_bruto / atual.receita_liquida > anterior.lucro_bruto / anterior.receita_liquida,
        atual.receita_liquida / atual.ativo_total > anterior.receita_liquida / anterior.ativo_total,
    ]
    return sum(testes)


def _sub(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def _soma(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a + b


def _por(saida: dict[str, float], codigo: str, numerador: float | None, denominador: float | None,
         so_positivo: bool = False) -> None:
    if numerador is not None and denominador and (denominador > 0 or not so_positivo):
        saida[codigo] = numerador / denominador
