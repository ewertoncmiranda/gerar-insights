"""Testes do sizing teorico (OPR-INS-2).

Formula: qtd_risco = (capital * risco_por_operacao) / (stop_atr * atr14).
stop_reais = stop_atr * atr14 ja e R$/acao; dividir por ele diretamente da acoes.

Defaults: capital=100k, preco=50, atr14=5
  valor_risco = 100k * 0.005 = 500
  stop_reais  = 2 * 5 = 10  (R$/acao)
  qtd_risco   = 500 / 10 = 50 acoes  (abaixo de max_ativo=100, limite nao binda)
  valor       = 50 * 50 = R$ 2.500 >= posicao_minima (R$ 500)
"""

from decimal import Decimal

import pytest

from app.operacional.elegibilidade import ALTA, MEDIA, INSUFICIENTE
from app.operacional.risco import (
    CAIXA_INSUFICIENTE,
    LIMITE_POSICOES_ABERTAS,
    POSICAO_ABAIXO_DO_MINIMO,
    SEM_ATR_SIZING,
    LimitesSizing,
    calcular,
)

_LIMITES = LimitesSizing.de_parametros({})
_CAP = Decimal("100000")


def _calc(**kw):
    """Atalho com defaults que deixam qtd_risco=50 como limite (acima de posicao_minima)."""
    defaults = dict(
        capital=_CAP,
        caixa=_CAP,
        preco=Decimal("50"),
        atr14=Decimal("5"),         # stop_reais = 2*5 = 10; qtd_risco = 500/10 = 50
        faixa=ALTA,
        percentil_volatilidade=None,
        vol21d=Decimal("10000000"), # 1% de 10M = 100k / 50 = 2000 acoes > 50: nao limita
        exposicao_atual_ativo=Decimal("0"),
        exposicao_atual_setor=Decimal("0"),
        posicoes_abertas=0,
        limites=_LIMITES,
    )
    defaults.update(kw)
    return calcular(**defaults)


# ---------------------------------------------------------------------------
# Caso base
# ---------------------------------------------------------------------------

def test_caso_base_retorna_elegivel():
    r = _calc()
    assert r.elegivel is True
    assert r.motivo_bloqueio is None
    assert r.redutores_aplicados == []


def test_caso_base_quantidade():
    # qtd_risco=50 < max_ativo=100; inteira=0 (< 100), fracionaria=50, valor=2.500
    r = _calc()
    assert r.quantidade_inteira == 0
    assert r.quantidade_fracionaria == 50
    assert r.valor_financeiro == Decimal("2500")


def test_arredondamento_lote_100_e_fracionario():
    # atr14=2: stop_reais=4; qtd_risco=500/4=125 acoes => inteira=100, frac=25
    # preco=10: max_ativo=5%*100k/10=500 (nao limita)
    r = _calc(preco=Decimal("10"), atr14=Decimal("2"))
    assert r.elegivel is True
    assert r.quantidade_inteira == 100
    assert r.quantidade_fracionaria == 25
    assert r.valor_financeiro == Decimal("1250")  # 125 * 10


def test_qtd_risco_exatamente_100():
    # atr14=2.5: stop=5; qtd_risco=500/5=100 acoes => inteira=100, frac=0
    r = _calc(preco=Decimal("25"), atr14=Decimal("2.5"))
    assert r.elegivel is True
    assert r.quantidade_inteira == 100
    assert r.quantidade_fracionaria == 0
    assert r.valor_financeiro == Decimal("2500")


# ---------------------------------------------------------------------------
# Bloqueios
# ---------------------------------------------------------------------------

def test_sem_atr_bloqueia():
    r = _calc(atr14=None)
    assert r.elegivel is False
    assert r.motivo_bloqueio == SEM_ATR_SIZING


def test_atr_zero_bloqueia():
    r = _calc(atr14=Decimal("0"))
    assert r.elegivel is False
    assert r.motivo_bloqueio == SEM_ATR_SIZING


def test_limite_posicoes_abertas_15_bloqueia():
    r = _calc(posicoes_abertas=15)
    assert r.elegivel is False
    assert r.motivo_bloqueio == LIMITE_POSICOES_ABERTAS


def test_posicao_abaixo_do_minimo():
    # atr14=500: stop_reais=1000; qtd_risco=500/1000=0.5 => int=0 => valor=0
    r = _calc(atr14=Decimal("500"))
    assert r.elegivel is False
    assert r.motivo_bloqueio == POSICAO_ABAIXO_DO_MINIMO


def test_caixa_insuficiente_bloqueia():
    # caixa=100 < posicao_minima=500
    r = _calc(caixa=Decimal("100"))
    assert r.elegivel is False
    assert r.motivo_bloqueio == CAIXA_INSUFICIENTE


# ---------------------------------------------------------------------------
# Limites (passo 2)
# ---------------------------------------------------------------------------

def test_limite_por_ativo_corta_quantidade():
    # max_ativo = 5%*100k = 5000; exposicao=3000 => espaco=2000 => 2000/50=40 acoes
    # min(50, 40) = 40; valor = 40*50 = R$ 2.000 >= R$ 500
    r = _calc(exposicao_atual_ativo=Decimal("3000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 40


def test_limite_por_ativo_quase_cheio():
    # exposicao=4500 => espaco=500 => 10 acoes; valor=500 >= 500
    r = _calc(exposicao_atual_ativo=Decimal("4500"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 10


def test_limite_por_setor_corta_quantidade():
    # max_setor = 20%*100k = 20000; exposicao_setor=18000 => espaco=2000 => 40 acoes
    r = _calc(exposicao_atual_setor=Decimal("18000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 40


def test_limite_adtv_corta_quantidade():
    # max_adtv = 1%*150k = 1500 / 50 = 30 acoes; min(50, 30) = 30; valor=1.500
    r = _calc(vol21d=Decimal("150000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 30


def test_sem_vol21d_nao_aplica_limite_adtv():
    r = _calc(vol21d=None)
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 50


def test_caixa_parcialmente_alocado_limita():
    # caixa=500: qtd_teto=10 acoes; valor=500 >= 500
    r = _calc(caixa=Decimal("500"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 10


# ---------------------------------------------------------------------------
# Redutores (passo 3)
# ---------------------------------------------------------------------------

def test_redutor_liquidez_media():
    # 50 * 0.5 = 25 acoes fracionarias; valor = 25*50 = R$ 1.250
    r = _calc(faixa=MEDIA)
    assert "LIQUIDEZ_MEDIA" in r.redutores_aplicados
    assert r.quantidade_fracionaria == 25
    assert r.valor_financeiro == Decimal("1250")


def test_redutor_volatilidade_p80():
    # 50 * 0.75 = 37 acoes; valor = R$ 1.850
    r = _calc(percentil_volatilidade=Decimal("0.85"))
    assert "VOL_P80" in r.redutores_aplicados
    assert r.quantidade_fracionaria == 37
    assert r.valor_financeiro == Decimal("1850")


def test_dois_redutores_combinados():
    # 50 * 0.5 * 0.75 = 18.75 => 18 acoes; valor = R$ 900
    r = _calc(faixa=MEDIA, percentil_volatilidade=Decimal("0.90"))
    assert set(r.redutores_aplicados) == {"LIQUIDEZ_MEDIA", "VOL_P80"}
    assert r.quantidade_fracionaria == 18
    assert r.valor_financeiro == Decimal("900")


def test_percentil_exato_80_nao_aplica_redutor():
    # percentil == 0.80: nao e *acima* de 0.80; redutor nao entra
    r = _calc(percentil_volatilidade=Decimal("0.80"))
    assert "VOL_P80" not in r.redutores_aplicados
    assert r.quantidade_fracionaria == 50


def test_faixa_insuficiente_nao_bloqueia_sizing():
    # elegibilidade.py filtra INSUFICIENTE antes de chamar risco.py;
    # o sizing nao rejeita por faixa
    r = _calc(faixa=INSUFICIENTE)
    assert r.elegivel is True


# ---------------------------------------------------------------------------
# Limiar de posicoes abertas
# ---------------------------------------------------------------------------

def test_posicao_aberta_14_nao_bloqueia():
    assert _calc(posicoes_abertas=14).elegivel is True


def test_posicao_aberta_15_bloqueia():
    r = _calc(posicoes_abertas=15)
    assert r.elegivel is False
    assert r.motivo_bloqueio == LIMITE_POSICOES_ABERTAS


# ---------------------------------------------------------------------------
# LimitesSizing.de_parametros
# ---------------------------------------------------------------------------

def test_parametros_padrao_dec_opr_1():
    lim = LimitesSizing.de_parametros({})
    assert lim.risco_por_operacao == Decimal("0.005")
    assert lim.stop_atr == Decimal("2")
    assert lim.exposicao_max_ativo == Decimal("0.05")
    assert lim.exposicao_max_setor == Decimal("0.20")
    assert lim.max_participacao_adtv == Decimal("0.01")
    assert lim.max_posicoes == 15
    assert lim.posicao_minima == Decimal("500")
    assert lim.redutor_liquidez_media == Decimal("0.5")
    assert lim.redutor_vol_p80 == Decimal("0.75")


def test_parametros_customizados_sobrescrevem():
    lim = LimitesSizing.de_parametros({"sizing": {"max_posicoes": 10, "posicao_minima": "1000"}})
    assert lim.max_posicoes == 10
    assert lim.posicao_minima == Decimal("1000")
    assert lim.risco_por_operacao == Decimal("0.005")


def test_formula_abev3_like():
    # Reproduz o cenario do relato: patrimonio=100k, ATR14=0.352, preco=11.58
    # qtd_risco = 500 / (2 * 0.352) = 500 / 0.704 ≈ 710 acoes
    # max_ativo = 5%*100k / 11.58 ≈ 431 acoes => limite binda em 431
    # valor = 431 * 11.58 ≈ R$ 4.991 >= R$ 500 => elegivel
    lim = LimitesSizing.de_parametros({})
    r = calcular(
        capital=Decimal("100000"),
        caixa=Decimal("100000"),
        preco=Decimal("11.58"),
        atr14=Decimal("0.352"),
        faixa=ALTA,
        percentil_volatilidade=None,
        vol21d=Decimal("50000000"),
        exposicao_atual_ativo=Decimal("0"),
        exposicao_atual_setor=Decimal("0"),
        posicoes_abertas=0,
        limites=lim,
    )
    assert r.elegivel is True
    # qtd_risco = 500 / 0.704 ≈ 710 => max_ativo = 5000/11.58 ≈ 431 (limite)
    qtd_max_ativo = int(Decimal("5000") / Decimal("11.58"))  # 431
    assert r.quantidade_inteira + r.quantidade_fracionaria == qtd_max_ativo
