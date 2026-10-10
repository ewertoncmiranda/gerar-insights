"""Testes do sizing teorico (OPR-INS-2).

Capital de R$ 1 M como base: produz posicoes acima da posicao_minima (R$ 500)
nos redutores mais agressivos sem exigir parametros artificiais.
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

# Limites padrao DEC-OPR-1 (sem banco).
_LIMITES = LimitesSizing.de_parametros({})

# Capital teorico de R$ 1 M para que os redutores nao gerem posicoes abaixo do minimo.
_CAP = Decimal("1000000")


def _calc(**kw):
    """Atalho: preenche os defaults e deixa o teste sobrescrever so o que importa.

    Com capital=1M, preco=50, atr14=1:
      qtd_risco = (1_000_000 * 0.005) / (2 * 1 * 50) = 50 acoes => R$ 2.500
    """
    defaults = dict(
        capital=_CAP,
        caixa=_CAP,
        preco=Decimal("50"),
        atr14=Decimal("1"),
        faixa=ALTA,
        percentil_volatilidade=None,
        vol21d=Decimal("10000000"),  # 1% de 10M = 100k / 50 = 2000 acoes > 50: nao limita
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
    # qtd_risco = (1M*0.005)/(2*1*50) = 50 acoes; valor = 50*50 = R$ 2.500 >= R$ 500
    r = _calc()
    assert r.elegivel is True
    assert r.motivo_bloqueio is None
    assert r.redutores_aplicados == []


def test_caso_base_quantidade():
    # 50 acoes: inteira = 0 (< 100), fracionaria = 50, valor = 2_500
    r = _calc()
    assert r.quantidade_inteira == 0
    assert r.quantidade_fracionaria == 50
    assert r.valor_financeiro == Decimal("2500")


def test_arredondamento_lote_100_e_fracionario():
    # preco=10, atr14=2: qtd_risco = 5000/(4*10) = 125 acoes => inteira=100, frac=25
    r = _calc(preco=Decimal("10"), atr14=Decimal("2"))
    assert r.elegivel is True
    assert r.quantidade_inteira == 100
    assert r.quantidade_fracionaria == 25
    assert r.valor_financeiro == Decimal("1250")  # 125 * 10


def test_quantidade_zero_quando_qtd_risco_fracionaria_zero():
    # qtd_risco exatamente 100: inteira=100, fracionaria=0
    # (1M*0.005)/(2*atr14*preco) = 100 => atr14*preco = 25 => preco=25, atr14=1
    r = _calc(preco=Decimal("25"), atr14=Decimal("1"))
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
    # atr14=200 => stop = 400 => qtd_risco = 5000/(400*50) = 0.25 => 0 acoes => valor = 0
    r = _calc(atr14=Decimal("200"))
    assert r.elegivel is False
    assert r.motivo_bloqueio == POSICAO_ABAIXO_DO_MINIMO


def test_caixa_insuficiente_bloqueia():
    # caixa=100 < posicao_minima=500
    r = _calc(caixa=Decimal("100"))
    assert r.elegivel is False
    assert r.motivo_bloqueio == CAIXA_INSUFICIENTE


# ---------------------------------------------------------------------------
# Limites (passo 2 do algoritmo)
# ---------------------------------------------------------------------------

def test_limite_por_ativo_corta_quantidade():
    # max_ativo = 5% * 1M = 50_000; com 49_000 alocados => espaco R$ 1.000 => 20 acoes
    # qtd_risco = 50; min(50, 20) = 20 acoes; valor = 20*50 = R$ 1.000 >= R$ 500
    r = _calc(exposicao_atual_ativo=Decimal("49000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 20  # 1000/50 = 20


def test_limite_por_ativo_quase_cheio():
    # espaco R$ 500 => 10 acoes; min(50, 10) = 10; valor = 10*50 = R$ 500 >= R$ 500
    r = _calc(exposicao_atual_ativo=Decimal("49500"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 10


def test_limite_por_setor_corta_quantidade():
    # max_setor = 20% * 1M = 200_000; com 199_000 alocados => espaco R$ 1.000 => 20 acoes
    r = _calc(exposicao_atual_setor=Decimal("199000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 20


def test_limite_adtv_corta_quantidade():
    # max_adtv = 1% * 150_000 = R$ 1.500 / 50 = 30 acoes; min(50, 30) = 30; valor = R$ 1.500
    r = _calc(vol21d=Decimal("150000"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 30


def test_sem_vol21d_nao_aplica_limite_adtv():
    # sem vol21d: o cap de ADTV nao entra; qtd_risco = 50 prevalece
    r = _calc(vol21d=None)
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 50


def test_caixa_parcialmente_alocado_limita():
    # caixa = 500: valor max = 500; 500/50 = 10 acoes; min(50, 10) = 10
    r = _calc(caixa=Decimal("500"))
    assert r.elegivel is True
    assert r.quantidade_fracionaria == 10


# ---------------------------------------------------------------------------
# Redutores (passo 3)
# ---------------------------------------------------------------------------

def test_redutor_liquidez_media():
    # faixa MEDIA: qtd=50 * 0.5 = 25 acoes fracionarias; valor = 25*50 = R$ 1.250
    r = _calc(faixa=MEDIA)
    assert "LIQUIDEZ_MEDIA" in r.redutores_aplicados
    assert r.quantidade_fracionaria == 25
    assert r.valor_financeiro == Decimal("1250")


def test_redutor_volatilidade_p80():
    # percentil 0.85: qtd=50 * 0.75 = 37 acoes; valor = R$ 1.850
    r = _calc(percentil_volatilidade=Decimal("0.85"))
    assert "VOL_P80" in r.redutores_aplicados
    assert r.quantidade_fracionaria == 37
    assert r.valor_financeiro == Decimal("1850")


def test_dois_redutores_combinados():
    # MEDIA + VOL_P80: 50 * 0.5 * 0.75 = 18.75 => 18 acoes; valor = R$ 900
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
    # elegibilidade.py ja filtra INSUFICIENTE antes de chamar risco.py;
    # o sizing nao rejeita por faixa: responsabilidade do servico (OPR-INS-4)
    r = _calc(faixa=INSUFICIENTE)
    assert r.elegivel is True


# ---------------------------------------------------------------------------
# Limiar de posicoes abertas
# ---------------------------------------------------------------------------

def test_posicao_aberta_14_nao_bloqueia():
    assert _calc(posicoes_abertas=14).elegivel is True


def test_posicao_aberta_15_bloqueia():
    assert _calc(posicoes_abertas=15).elegivel is False
    assert _calc(posicoes_abertas=15).motivo_bloqueio == LIMITE_POSICOES_ABERTAS


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
    assert lim.risco_por_operacao == Decimal("0.005")  # default preservado


def test_capital_de_100k_com_posicao_minima_menor_funciona():
    # Verifica que capital menor + posicao_minima menor -> elegivel
    lim = LimitesSizing.de_parametros({"sizing": {"posicao_minima": "100"}})
    r = calcular(
        capital=Decimal("100000"),
        caixa=Decimal("100000"),
        preco=Decimal("50"),
        atr14=Decimal("1"),
        faixa=ALTA,
        percentil_volatilidade=None,
        vol21d=Decimal("10000000"),
        exposicao_atual_ativo=Decimal("0"),
        exposicao_atual_setor=Decimal("0"),
        posicoes_abertas=0,
        limites=lim,
    )
    assert r.elegivel is True
    # qtd_risco = (100k*0.005)/(2*1*50) = 5 acoes; valor = R$ 250 >= R$ 100
    assert r.quantidade_fracionaria == 5
    assert r.valor_financeiro == Decimal("250")
