"""Testes de point-in-time (TASK-40).

Invariante central: no dia D, so sao visiveis os balancxos cuja
data_entrega (DT_RECEB da CVM) e <= D.  Qualquer atalho aqui vira
um backtest bonito e falso.
"""

from datetime import date, timedelta

import pytest

from app.validacao.ponto_no_tempo import Balanco, DadosPontoNoTempo

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SIM = "TEST3"


def _dados(balancos=None, cdi=None, ipca=None, selic=None):
    """Constroi DadosPontoNoTempo diretamente (sem DB)."""
    return DadosPontoNoTempo(
        balancos={_SIM: balancos or []},
        cdi=cdi or {},
        ipca=ipca or {},
        selic=selic or {},
    )


def _anual(entrega: date, periodo: date, lpa: float, vpa: float | None = None) -> Balanco:
    return Balanco(data_entrega=entrega, periodo=periodo, tipo_periodo="ANUAL", lpa=lpa, vpa=vpa)


def _ttm(entrega: date, periodo: date, lpa: float) -> Balanco:
    return Balanco(data_entrega=entrega, periodo=periodo, tipo_periodo="TTM", lpa=lpa)


# ---------------------------------------------------------------------------
# lpa_em — invariante DT_RECEB <= t
# ---------------------------------------------------------------------------

def test_balanco_entregue_antes_visivel():
    entrega = date(2022, 1, 15)
    d = _dados([_anual(entrega, date(2021, 12, 31), lpa=2.0)])
    lpa, fonte = d.lpa_em(_SIM, date(2022, 1, 15))
    assert lpa == 2.0
    assert "ANUAL" in fonte


def test_balanco_entregue_no_dia_visivel():
    entrega = date(2022, 3, 1)
    d = _dados([_anual(entrega, date(2021, 12, 31), lpa=2.0)])
    lpa, _ = d.lpa_em(_SIM, date(2022, 3, 1))
    assert lpa == 2.0


def test_balanco_entregue_depois_nao_visivel():
    """Viés de futuro: entrega amanhã não pode entrar hoje."""
    entrega = date(2022, 3, 2)
    d = _dados([_anual(entrega, date(2021, 12, 31), lpa=2.0)])
    lpa, fonte = d.lpa_em(_SIM, date(2022, 3, 1))
    assert lpa is None
    assert fonte == "SEM_BALANCO"


def test_apenas_balanco_mais_recente_disponivel_usado():
    b1 = _anual(date(2022, 1, 10), date(2021, 12, 31), lpa=1.0)  # DFP 2021
    b2 = _anual(date(2022, 8, 5), date(2022, 6, 30), lpa=2.5)    # DFP 2022 (semi-anual)
    d = _dados([b1, b2])
    # No dia 2022-01-20: so b1 esta entregue
    lpa, _ = d.lpa_em(_SIM, date(2022, 1, 20))
    assert lpa == 1.0
    # No dia 2022-09-01: b2 tambem esta entregue; b2 tem periodo mais recente
    lpa, _ = d.lpa_em(_SIM, date(2022, 9, 1))
    assert lpa == 2.5


def test_ttm_vence_anual_quando_mais_recente():
    b_anual = _anual(date(2022, 3, 1), date(2021, 12, 31), lpa=1.0)
    b_ttm = _ttm(date(2022, 5, 15), date(2022, 3, 31), lpa=1.8)
    d = _dados([b_anual, b_ttm])
    lpa, fonte = d.lpa_em(_SIM, date(2022, 6, 1))
    assert lpa == 1.8
    assert "TTM" in fonte


def test_ttm_entregue_depois_do_dia_nao_visivel():
    b_anual = _anual(date(2022, 3, 1), date(2021, 12, 31), lpa=1.0)
    b_ttm = _ttm(date(2022, 5, 15), date(2022, 3, 31), lpa=1.8)
    d = _dados([b_anual, b_ttm])
    # Dia anterior a entrega do TTM: so o anual esta disponivel
    lpa, fonte = d.lpa_em(_SIM, date(2022, 5, 14))
    assert lpa == 1.0
    assert "ANUAL" in fonte


def test_sem_balanco_retorna_none():
    d = _dados([])
    lpa, fonte = d.lpa_em(_SIM, date(2022, 1, 1))
    assert lpa is None
    assert fonte == "SEM_BALANCO"


def test_simbolo_desconhecido_retorna_none():
    d = _dados([_anual(date(2022, 1, 1), date(2021, 12, 31), lpa=1.0)])
    lpa, fonte = d.lpa_em("OUTR3", date(2022, 6, 1))
    assert lpa is None


# ---------------------------------------------------------------------------
# anuais_em — filtro DT_RECEB e limite de 5 anos
# ---------------------------------------------------------------------------

def test_anuais_em_so_anuais_entregues():
    b1 = _anual(date(2021, 3, 1), date(2020, 12, 31), lpa=1.0, vpa=10.0)
    b2 = _anual(date(2022, 3, 1), date(2021, 12, 31), lpa=2.0, vpa=12.0)
    b_ttm = _ttm(date(2022, 4, 1), date(2022, 3, 31), lpa=2.5)
    d = _dados([b1, b2, b_ttm])
    lpas, vpa = d.anuais_em(_SIM, date(2022, 6, 1))
    assert lpas == [2.0, 1.0]  # mais recente primeiro, so anuais
    assert vpa == 12.0


def test_anuais_em_futuro_excluido():
    b_passado = _anual(date(2022, 1, 1), date(2021, 12, 31), lpa=1.0)
    b_futuro = _anual(date(2022, 4, 1), date(2022, 3, 31), lpa=2.0)
    d = _dados([b_passado, b_futuro])
    lpas, _ = d.anuais_em(_SIM, date(2022, 3, 1))
    assert lpas == [1.0]  # b_futuro nao entregue ainda


def test_anuais_em_limite_5_anos():
    balancos = [
        _anual(date(2016 + i, 3, 1), date(2015 + i, 12, 31), lpa=float(i + 1))
        for i in range(7)  # 7 anos entregues
    ]
    d = _dados(balancos)
    lpas, _ = d.anuais_em(_SIM, date(2025, 1, 1), anos=5)
    assert len(lpas) == 5


# ---------------------------------------------------------------------------
# selic_em, juros_em, ipca_12m_em
# ---------------------------------------------------------------------------

def test_selic_em_usa_ultimo_antes_ou_igual_ao_dia():
    d = _dados(selic={date(2022, 1, 1): 9.25, date(2022, 6, 1): 13.25})
    assert d.selic_em(date(2022, 3, 1)) == 9.25
    assert d.selic_em(date(2022, 6, 1)) == 13.25
    assert d.selic_em(date(2022, 6, 2)) == 13.25


def test_selic_em_none_antes_do_inicio():
    d = _dados(selic={date(2022, 1, 1): 9.25})
    assert d.selic_em(date(2021, 12, 31)) is None


def test_juros_em_retorna_cdi_anualizado():
    cdi_diario = 0.05  # ~18% a.a.
    d = _dados(cdi={date(2022, 1, 3): cdi_diario})
    juros = d.juros_em(date(2022, 3, 1))
    assert juros is not None and juros > 10.0


def test_ipca_12m_requer_12_meses():
    """Com menos de 12 meses de historico, retorna None."""
    ipca = {date(2022, 1, 1) - timedelta(days=30 * i): 0.5 for i in range(10)}
    d = _dados(ipca=ipca)
    assert d.ipca_12m_em(date(2022, 6, 1)) is None


def test_ipca_12m_com_historico_suficiente():
    ipca = {date(2021, 1, 1) + timedelta(days=31 * i): 0.5 for i in range(18)}
    d = _dados(ipca=ipca)
    resultado = d.ipca_12m_em(date(2022, 6, 1))
    assert resultado is not None and resultado > 0
