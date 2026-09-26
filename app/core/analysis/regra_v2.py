"""Regra v2 da recomendacao - roda em MODO SOMBRA.

Nao substitui a v1 (recommendation.py) nos insights da tela. O diario de
sinais grava as duas versoes no mesmo pregao e o backtest mede as duas nas
mesmas janelas: a v2 so vira a regra oficial se o placar mostrar que ela e
melhor. Tres mudancas em relacao a v1, cada uma com um defeito catalogado
(gerar-insights ISS-F1, ISS-F2, ISS-F3):

  1. Graham com juros: V = LPA x (8,5 + 2g) x 4,4 / Y. A formula revisada de
     Graham divide pelo rendimento corrente (Y) o que em 1962 era 4,4%. Sem
     isso, com o CDI brasileiro na casa dos dois digitos, o valor justo sai
     varias vezes inflado e quase tudo parece barato. Y e o CDI anualizado do
     dia (nominal), entao o crescimento g tambem e nominal: cenario real
     (0/3/5%) + IPCA dos ultimos 12 meses.
  2. Lucro dos ultimos 12 meses (TTM) quando a CVM ja publicou: o lucro do
     ultimo exercicio fechado envelhece ate 15 meses e faz ciclica no pico
     parecer barata.
  3. Faixa neutra: so e VENDA_VALUATION com margem base abaixo de -30%. Na
     v1 qualquer margem negativa virava venda, o que condena toda empresa de
     qualidade ou de crescimento.

Pura: sem banco, sem relogio. Quem chama busca LPA, CDI e IPCA respeitando a
data (point-in-time) - o diario pela data do pregao, o backtest pela data de
cada sinal.
"""

from __future__ import annotations

from dataclasses import dataclass

VERSAO_REGRA_V2 = "2026.09.26-2"

TAXA_REFERENCIA_GRAHAM = 4.4
MULTIPLO_SEM_CRESCIMENTO = 8.5
CENARIOS_REAIS = {"conservador": 0.0, "base": 3.0, "otimista": 5.0}
# Sem IPCA disponivel, a meta de inflacao do CMN (3%) mais a folga historica.
IPCA_PADRAO = 4.0
# Abaixo disso o fator 4,4/Y explode (juros proximos de zero): piso de sanidade.
JUROS_MINIMO = 2.0
LIMITE_VENDA = -30.0


@dataclass(frozen=True)
class EntradaV2:
    preco: float
    lpa: float | None
    juros_anual_percent: float | None
    ipca_12m_percent: float | None = None
    posicao_52w: float | None = None
    fonte_lpa: str = "DESCONHECIDA"


@dataclass(frozen=True)
class SaidaV2:
    recomendacao: str
    margem_conservadora: float | None
    margem_base: float | None
    preco_justo_base: float | None
    earnings_yield: float | None
    juros_usado: float | None
    ipca_usado: float | None
    fonte_lpa: str

    def como_dict(self) -> dict:
        return {
            "versao_regra": VERSAO_REGRA_V2,
            "recomendacao": self.recomendacao,
            "margem_conservadora_percent": _r(self.margem_conservadora),
            "margem_base_percent": _r(self.margem_base),
            "preco_justo_base": _r(self.preco_justo_base),
            "earnings_yield_percent": _r(self.earnings_yield),
            "juros_usado_percent": _r(self.juros_usado),
            "ipca_usado_percent": _r(self.ipca_usado),
            "fonte_lpa": self.fonte_lpa,
        }


def recomendar_v2(entrada: EntradaV2) -> SaidaV2:
    """SEM_DADOS quando falta preco, LPA positivo ou juros: sem Y a formula
    revisada nao existe, e voltar para a v1 escondido misturaria as regras."""
    if not entrada.preco or not entrada.lpa or entrada.lpa <= 0 or not entrada.juros_anual_percent:
        return SaidaV2("SEM_DADOS", None, None, None, None, entrada.juros_anual_percent,
                       entrada.ipca_12m_percent, entrada.fonte_lpa)

    juros = max(entrada.juros_anual_percent, JUROS_MINIMO)
    ipca = entrada.ipca_12m_percent if entrada.ipca_12m_percent is not None else IPCA_PADRAO
    fator = TAXA_REFERENCIA_GRAHAM / juros

    margens = {}
    justo_base = None
    for nome, real in CENARIOS_REAIS.items():
        crescimento = real + ipca
        justo = entrada.lpa * (MULTIPLO_SEM_CRESCIMENTO + 2 * crescimento) * fator
        margens[nome] = (justo - entrada.preco) / justo * 100
        if nome == "base":
            justo_base = justo

    earnings_yield = entrada.lpa / entrada.preco * 100
    conservadora, base = margens["conservador"], margens["base"]

    if conservadora >= 20 and earnings_yield >= 12:
        recomendacao = "COMPRA_FORTE"
    elif base >= 20 and earnings_yield >= 8:
        recomendacao = "COMPRA_MODERADA"
    elif base <= LIMITE_VENDA:
        recomendacao = "VENDA_VALUATION"
    elif entrada.posicao_52w is not None and entrada.posicao_52w >= 90 and base <= 10:
        recomendacao = "ALERTA_RISCO"
    else:
        recomendacao = "MANTER"

    return SaidaV2(recomendacao, conservadora, base, justo_base, earnings_yield, juros, ipca,
                   entrada.fonte_lpa)


def juros_anual_de_cdi_diario(taxa_diaria_percent: float | None) -> float | None:
    """CDI do SGS 12 vem em % ao dia; anualiza em 252 dias uteis."""
    if taxa_diaria_percent is None:
        return None
    return ((1 + taxa_diaria_percent / 100) ** 252 - 1) * 100


def posicao_no_range(preco: float, minima: float | None, maxima: float | None) -> float | None:
    if minima is None or maxima is None or maxima <= minima:
        return None
    return (preco - minima) / (maxima - minima) * 100


def _r(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 4)
