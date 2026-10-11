"""Testes da trava de operabilidade (OPR-INS-6).

Quatro estados:
  NAO_OPERAVEL          — pregoes_no_diario == 0
  BLOQUEADO             — drawdown_maximo < drawdown_max_bloqueio  (prioridade maxima)
  EM_OBSERVACAO         — pelo menos um criterio nao atendido
  PAPER_TRADING_ELEGIVEL— todos os criterios atendidos
"""

from decimal import Decimal

import pytest

from app.operacional.status import (
    BLOQUEADO,
    EM_OBSERVACAO,
    NAO_OPERAVEL,
    PAPER_TRADING_ELEGIVEL,
    ParametrosTrava,
    ResultadoStatus,
    calcular,
)

_P = ParametrosTrava.de_parametros({})  # defaults DEC-OPR-1

# Valores que satisfazem todos os criterios com os defaults (base "elegivel")
_ELEGIVEL = dict(
    pregoes_no_diario=63,
    retorno_liquido_acumulado=Decimal("0.10"),
    cdi_liquido_ir_acumulado=Decimal("0.05"),
    drawdown_maximo=Decimal("-0.05"),   # > -0.15 (elegivel) e > -0.25 (bloqueio)
    violacoes_liquidez_total=0,
    operacoes_encerradas=10,
    parametros=_P,
)


def _calc(**kw):
    base = dict(_ELEGIVEL)
    base.update(kw)
    return calcular(**base)


# ---------------------------------------------------------------------------
# NAO_OPERAVEL
# ---------------------------------------------------------------------------

def test_nao_operavel_quando_zero_pregoes():
    r = _calc(pregoes_no_diario=0)
    assert r.status == NAO_OPERAVEL
    assert r.pregoes_avaliados == 0
    assert "sem_pregoes_no_diario" in r.criterios_nao_atendidos


# ---------------------------------------------------------------------------
# BLOQUEADO (prioridade sobre EM_OBSERVACAO)
# ---------------------------------------------------------------------------

def test_bloqueado_quando_drawdown_abaixo_do_limite():
    r = _calc(drawdown_maximo=Decimal("-0.26"))
    assert r.status == BLOQUEADO
    assert any("drawdown_maximo" in c for c in r.criterios_nao_atendidos)


def test_bloqueado_exato_no_limite_nao_bloqueia():
    # drawdown == drawdown_max_bloqueio: nao e *menor que*, entao nao bloqueia
    r = _calc(drawdown_maximo=Decimal("-0.25"))
    assert r.status != BLOQUEADO


def test_bloqueado_prevalece_sobre_outros_criterios():
    # mesmo que tivesse pregoes insuficientes, BLOQUEADO vem primeiro
    r = _calc(drawdown_maximo=Decimal("-0.30"), pregoes_no_diario=5, operacoes_encerradas=0)
    assert r.status == BLOQUEADO


# ---------------------------------------------------------------------------
# PAPER_TRADING_ELEGIVEL
# ---------------------------------------------------------------------------

def test_elegivel_quando_todos_criterios_atendidos():
    r = _calc()
    assert r.status == PAPER_TRADING_ELEGIVEL
    assert r.criterios_nao_atendidos == []
    assert r.pregoes_avaliados == 63


def test_elegivel_retorno_exatamente_acima_do_cdi():
    r = _calc(
        retorno_liquido_acumulado=Decimal("0.051"),
        cdi_liquido_ir_acumulado=Decimal("0.050"),
    )
    assert r.status == PAPER_TRADING_ELEGIVEL


# ---------------------------------------------------------------------------
# EM_OBSERVACAO — cada criterio individualmente
# ---------------------------------------------------------------------------

def test_observacao_pregoes_insuficientes():
    r = _calc(pregoes_no_diario=62)
    assert r.status == EM_OBSERVACAO
    assert any("pregoes=" in c for c in r.criterios_nao_atendidos)


def test_observacao_operacoes_insuficientes():
    r = _calc(operacoes_encerradas=9)
    assert r.status == EM_OBSERVACAO
    assert any("operacoes_encerradas=" in c for c in r.criterios_nao_atendidos)


def test_observacao_retorno_abaixo_do_cdi():
    r = _calc(retorno_liquido_acumulado=Decimal("0.04"), cdi_liquido_ir_acumulado=Decimal("0.05"))
    assert r.status == EM_OBSERVACAO
    assert any("retorno_liq=" in c for c in r.criterios_nao_atendidos)


def test_observacao_retorno_igual_ao_cdi_nao_basta():
    # retorno <= cdi => nao elegivel
    r = _calc(
        retorno_liquido_acumulado=Decimal("0.05"),
        cdi_liquido_ir_acumulado=Decimal("0.05"),
    )
    assert r.status == EM_OBSERVACAO


def test_observacao_drawdown_abaixo_de_elegivel():
    r = _calc(drawdown_maximo=Decimal("-0.16"))
    assert r.status == EM_OBSERVACAO
    assert any("drawdown_maximo=" in c for c in r.criterios_nao_atendidos)


def test_observacao_violacoes_liquidez():
    r = _calc(violacoes_liquidez_total=1)
    assert r.status == EM_OBSERVACAO
    assert any("violacoes_liquidez=" in c for c in r.criterios_nao_atendidos)


def test_observacao_multiplos_criterios_acumulam():
    r = _calc(pregoes_no_diario=10, operacoes_encerradas=2, violacoes_liquidez_total=3)
    assert r.status == EM_OBSERVACAO
    assert len(r.criterios_nao_atendidos) >= 3


# ---------------------------------------------------------------------------
# ParametrosTrava.de_parametros — defaults e customizacao
# ---------------------------------------------------------------------------

def test_defaults_dec_opr_1():
    p = ParametrosTrava.de_parametros({})
    assert p.min_pregoes == 63
    assert p.min_operacoes_encerradas == 10
    assert p.drawdown_max_elegivel == Decimal("-0.15")
    assert p.drawdown_max_bloqueio == Decimal("-0.25")


def test_parametros_customizados():
    p = ParametrosTrava.de_parametros({"trava": {"min_pregoes": 21, "drawdown_max_bloqueio": "-0.30"}})
    assert p.min_pregoes == 21
    assert p.drawdown_max_bloqueio == Decimal("-0.30")
    assert p.min_operacoes_encerradas == 10  # default mantido
