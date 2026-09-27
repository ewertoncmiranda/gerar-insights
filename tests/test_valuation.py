"""Graham ajustado por juros (ISS-F1/TASK-20), LPA normalizado e Graham
Number (ISS-F2). Sem teste ate aqui - a logica existia so em codigo."""

from app.core.analysis.limiares import Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.valuation import (
    GrahamValuation,
    ValuationAnalyzer,
    fator_de_juros,
    graham_number,
    normalizar_lpa,
)

# Estes testes cobrem Graham Number, referencia sem juros e validade - nao o
# modo de juros (TASK-54). Fixam o modo G_REAL para nao depender do IPCA.
MODO_FIXO = Limiares(modo_juros="G_REAL")


def snapshot(price=10.0, eps=2.0, pl=None):
    return MarketSnapshot(
        symbol="TESTE3",
        price=price,
        earnings_per_share=eps,
        price_earnings=pl,
        open_price=price,
        previous_close=price,
        day_high=price,
        day_low=price,
        volume=1000,
        market_cap=1_000_000,
        fifty_two_week_low=price * 0.8,
        fifty_two_week_high=price * 1.2,
    )


# --- fator_de_juros -----------------------------------------------------

def test_fator_de_juros_com_taxa_referencia_e_neutro():
    assert fator_de_juros(4.4) == 1.0


def test_fator_de_juros_cai_quando_juros_sobe():
    assert fator_de_juros(8.8) == 0.5


def test_fator_de_juros_respeita_piso_de_sanidade():
    # Y abaixo do piso (2.0) usa o piso, nao explode o fator.
    assert fator_de_juros(0.5) == fator_de_juros(2.0)


# --- GrahamValuation: criterios de aceite do TASK-20 ---------------------

def test_criterio_aceite_task20_taxa_referencia():
    """Dado LPA=2, g=3, Y=4,4, entao V=29 (criterio de TASK-20)."""
    graham = GrahamValuation()
    cenarios = graham.calculate_scenarios(earnings_per_share=2.0, price=10.0, taxa_juros=4.4)
    assert cenarios["base"]["preco_justo"] == 29.0


def test_criterio_aceite_task20_taxa_dobrada():
    """Dado o mesmo LPA/g, mas Y=8,8, entao V=14,5 - metade do caso anterior."""
    graham = GrahamValuation()
    cenarios = graham.calculate_scenarios(earnings_per_share=2.0, price=10.0, taxa_juros=8.8)
    assert cenarios["base"]["preco_justo"] == 14.5


def test_margem_seguranca_negativa_quando_preco_acima_do_justo():
    graham = GrahamValuation()
    cenarios = graham.calculate_scenarios(earnings_per_share=1.0, price=100.0, taxa_juros=4.4)
    assert cenarios["conservador"]["margem_seguranca_percent"] < 0


# --- normalizar_lpa (ISS-F2) ---------------------------------------------

def test_normalizar_lpa_sem_historico_suficiente_usa_lpa_atual():
    lpa, fonte, media = normalizar_lpa(lpa_atual=5.0, lpas_anuais=[4.0])
    assert lpa == 5.0
    assert "insuficiente" in fonte
    assert media is None


def test_normalizar_lpa_usa_o_atual_quando_esta_abaixo_da_media():
    """Lucro caindo: o atual (mais conservador) vence a media dos anos bons."""
    lpa, fonte, media = normalizar_lpa(lpa_atual=2.0, lpas_anuais=[5.0, 4.0, 3.0])
    assert lpa == 2.0
    assert media == 4.0
    assert fonte.startswith("LPA_ATUAL")


def test_normalizar_lpa_usa_a_media_quando_atual_esta_no_pico():
    """Ciclica no pico do lucro: a media dos ultimos anos e mais conservadora."""
    lpa, fonte, media = normalizar_lpa(lpa_atual=10.0, lpas_anuais=[4.0, 3.0, 2.0])
    assert lpa == 3.0
    assert fonte == "MEDIA_3_ANOS"


def test_normalizar_lpa_respeita_o_teto_de_anos():
    limiares = Limiares(anos_lpa_min=3, anos_lpa_max=3)
    lpa, fonte, media = normalizar_lpa(
        lpa_atual=10.0, lpas_anuais=[4.0, 4.0, 4.0, 100.0, 100.0], limiares=limiares
    )
    # Os dois ultimos anos (fora do teto) nao entram na media.
    assert media == 4.0


# --- graham_number (ISS-F2, segunda trava de COMPRA_FORTE) --------------

def test_graham_number_formula():
    # sqrt(22.5 * 2 * 8) = sqrt(360) ~ 18.97
    numero = graham_number(lpa=2.0, vpa=8.0)
    assert round(numero, 2) == 18.97


def test_graham_number_none_sem_vpa():
    assert graham_number(lpa=2.0, vpa=None) is None


def test_graham_number_none_com_lpa_negativo():
    assert graham_number(lpa=-1.0, vpa=8.0) is None


# --- ValuationAnalyzer: integracao ---------------------------------------

def test_analyze_marca_preco_ate_graham_number():
    analyzer = ValuationAnalyzer(limiares=MODO_FIXO)
    resultado = analyzer.analyze(
        snapshot=snapshot(price=10.0, eps=2.0),
        taxa_juros=4.4,
        lpas_anuais=None,
        vpa=8.0,
    )
    assert resultado["valido"] is True
    # Graham Number = sqrt(22.5*2*8) ~ 18.97 >= preco 10 -> dentro do teto.
    assert resultado["preco_ate_graham_number"] is True


def test_analyze_sinaliza_quando_preco_passa_do_graham_number():
    analyzer = ValuationAnalyzer(limiares=MODO_FIXO)
    resultado = analyzer.analyze(
        snapshot=snapshot(price=50.0, eps=2.0),
        taxa_juros=4.4,
        lpas_anuais=None,
        vpa=1.0,  # Graham Number pequeno: sqrt(22.5*2*1) ~ 6.7
    )
    assert resultado["preco_ate_graham_number"] is False


def test_analyze_mantem_cenario_sem_ajuste_como_referencia():
    """A formula de 1962 (Y=4,4) continua calculada, mas so como referencia -
    nao decide a recomendacao (isso e feito com o cenario ajustado)."""
    analyzer = ValuationAnalyzer(limiares=MODO_FIXO)
    resultado = analyzer.analyze(snapshot=snapshot(price=10.0, eps=2.0), taxa_juros=8.8)
    assert resultado["cenarios_graham"]["base"]["preco_justo"] == 14.5
    assert resultado["cenarios_graham_sem_ajuste_juros"]["base"]["preco_justo"] == 29.0


def test_analyze_invalido_sem_lpa():
    analyzer = ValuationAnalyzer(limiares=MODO_FIXO)
    resultado = analyzer.analyze(snapshot=snapshot(price=10.0, eps=None), taxa_juros=4.4)
    assert resultado["valido"] is False
    assert resultado["cenarios_graham"] is None
