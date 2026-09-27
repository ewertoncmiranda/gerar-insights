"""Casos de aceite do plano que complementam test_valuation.py e
test_recommendation.py: Selic alta x baixa no preco justo (ISS-F1), insight
SEM_DADOS sem Selic, ciclica no pico sem COMPRA_FORTE (ISS-F2), faixa
calibrada (DEC-07) e multiplo base configuravel (ISS-F3)."""

from logging import getLogger

import pytest

from app.core.analysis.limiares import LIMIARES_ATUAIS, Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.valuation import GrahamValuation, ValuationAnalyzer
from app.core.service.financial_analyzer_service import FinancialAnalyzerService


def snapshot(preco, lpa, minima=None, maxima=None):
    return MarketSnapshot(
        symbol="TEST3", price=preco, earnings_per_share=lpa, price_earnings=preco / lpa,
        open_price=None, previous_close=None, day_high=None, day_low=None, volume=None, market_cap=None,
        fifty_two_week_low=minima, fifty_two_week_high=maxima,
    )


def test_selic_alta_derruba_o_preco_justo_na_proporcao_da_taxa():
    # Proporcao exata so no modo G_REAL (g fixo); o G_NOMINAL tem teste proprio abaixo.
    analisador = ValuationAnalyzer(limiares=Limiares(modo_juros="G_REAL"))
    baixa = analisador.analyze(snapshot(20, 2), taxa_juros=5.0)
    alta = analisador.analyze(snapshot(20, 2), taxa_juros=15.0)

    assert alta["cenario_base"]["preco_justo"] == pytest.approx(baixa["cenario_base"]["preco_justo"] / 3, rel=1e-3)
    assert alta["cenario_base"]["margem_seguranca_percent"] < baixa["cenario_base"]["margem_seguranca_percent"]


def test_sem_selic_o_insight_sai_sem_dados_em_vez_de_cair_na_formula_antiga():
    class SemSelic:
        def taxa_vigente(self, db, dia=None):
            return None

    servico = FinancialAnalyzerService(getLogger("teste"), taxa_juros_service=SemSelic())
    resultado = servico.gerar_insight_fundamentalista(
        None, {"symbol": "TEST3", "regularMarketPrice": 20, "earningsPerShare": 2}
    )
    assert resultado["recomendacao"] == "SEM_DADOS"
    assert "Selic" in resultado["detalhes_json"]["aviso"]


def test_ciclica_no_pico_nao_sai_compra_forte_com_o_lucro_normalizado():
    # P/L 2 no pico: barata pelo lucro do ano, cara pela media do ciclo.
    politica, analisador = RecommendationPolicy(), ValuationAnalyzer(limiares=Limiares(modo_juros="G_REAL"))
    pico = snapshot(20, 10, minima=15, maxima=40)
    so_o_pico = analisador.analyze(pico, taxa_juros=4.4)
    com_historico = analisador.analyze(pico, taxa_juros=4.4, lpas_anuais=[10.0, 1.0, 0.5, 1.0, 0.5])

    assert politica.define_recommendation(so_o_pico, 20) == "COMPRA_FORTE"
    assert politica.define_recommendation(com_historico, 20) != "COMPRA_FORTE"


def _margem_base(margem):
    return {
        "cenarios_graham": {
            "conservador": {"margem_seguranca_percent": margem - 10},
            "base": {"margem_seguranca_percent": margem},
        },
        "earnings_yield": 5.0,
    }


def test_faixa_calibrada_so_vende_abaixo_de_menos_150():
    assert LIMIARES_ATUAIS.margem_venda == -150.0
    politica = RecommendationPolicy()
    assert politica.define_recommendation(_margem_base(-120), 50) == "MANTER"
    assert politica.define_recommendation(_margem_base(-160), 50) == "VENDA_VALUATION"


def test_multiplo_base_configuravel():
    padrao = GrahamValuation().calculate_scenarios(2, 10, 4.4)["conservador"]["preco_justo"]
    maior = GrahamValuation(multiplo_base=12.0).calculate_scenarios(2, 10, 4.4)["conservador"]["preco_justo"]
    assert (padrao, maior) == (pytest.approx(17.0), pytest.approx(24.0))


def test_lpa_zero_do_etl_conta_como_ausente_e_nao_derruba_a_media():
    from app.core.analysis.valuation import normalizar_lpa

    lpa, fonte, media = normalizar_lpa(1.2, [0.0, 0.0, 0.76, 1.1, 0.9, 1.0])
    assert media == pytest.approx((0.76 + 1.1 + 0.9 + 1.0) / 4)
    assert fonte.startswith("LPA_ATUAL") or fonte.startswith("MEDIA_4")


# --- TASK-54: juros e crescimento na mesma base (DEC-08) ---------------------


def test_g_nominal_soma_o_ipca_ao_crescimento():
    from app.core.analysis.valuation import MODO_G_NOMINAL, MODO_G_REAL

    graham = GrahamValuation()
    real = graham.calculate_scenarios(2, 10, taxa_juros=13.75, modo=MODO_G_REAL)["base"]
    nominal = graham.calculate_scenarios(2, 10, taxa_juros=13.75, ipca=4.5, modo=MODO_G_NOMINAL)["base"]
    # base: g = 3 (real) contra 3 + 4,5 (nominal) -> multiplo 14,5 contra 23,5
    assert real["preco_justo"] == pytest.approx(2 * 14.5 * 4.4 / 13.75, rel=1e-3)
    assert nominal["preco_justo"] == pytest.approx(2 * 23.5 * 4.4 / 13.75, rel=1e-3)
    assert nominal["crescimento_percent"] == pytest.approx(7.5)


def test_y_real_desconta_o_ipca_da_taxa_com_piso():
    from app.core.analysis.valuation import MODO_Y_REAL

    graham = GrahamValuation()
    base = graham.calculate_scenarios(2, 10, taxa_juros=13.75, ipca=4.75, modo=MODO_Y_REAL)["base"]
    assert base["taxa_usada_percent"] == pytest.approx(9.0)
    piso = graham.calculate_scenarios(2, 10, taxa_juros=3.0, ipca=4.0, modo=MODO_Y_REAL)["base"]
    assert piso["taxa_usada_percent"] == pytest.approx(2.0)


def test_modo_com_ipca_sem_ipca_e_invalido_e_nao_troca_de_regra():
    analisador = ValuationAnalyzer()  # modo atual: G_NOMINAL
    assert LIMIARES_ATUAIS.modo_juros == "G_NOMINAL"
    sem_ipca = analisador.analyze(snapshot(20, 2), taxa_juros=13.75)
    com_ipca = analisador.analyze(snapshot(20, 2), taxa_juros=13.75, ipca_12m=4.5)
    assert sem_ipca["valido"] is False
    assert com_ipca["valido"] is True
    assert com_ipca["modo_juros"] == "G_NOMINAL"


def test_juros_altos_nao_derrubam_mais_o_preco_justo_na_proporcao_da_selic():
    """O defeito da DEC-07: com g real, Selic 5% -> 15% cortava o preco justo
    em 3x. Com g nominal o corte e menor, porque inflacao alta sobe os dois."""
    analisador = ValuationAnalyzer()
    baixa = analisador.analyze(snapshot(20, 2), taxa_juros=5.0, ipca_12m=3.0)["cenario_base"]["preco_justo"]
    alta = analisador.analyze(snapshot(20, 2), taxa_juros=15.0, ipca_12m=6.0)["cenario_base"]["preco_justo"]
    assert baixa / alta < 3

