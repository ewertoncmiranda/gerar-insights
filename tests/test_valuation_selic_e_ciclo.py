"""Casos de aceite do plano que complementam test_valuation.py e
test_recommendation.py: Selic alta x baixa no preco justo (ISS-F1), insight
SEM_DADOS sem Selic, ciclica no pico sem COMPRA_FORTE (ISS-F2), faixa
calibrada (DEC-07) e multiplo base configuravel (ISS-F3)."""

from logging import getLogger

import pytest

from app.core.analysis.limiares import LIMIARES_ATUAIS
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
    analisador = ValuationAnalyzer()
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
    politica, analisador = RecommendationPolicy(), ValuationAnalyzer()
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


def test_faixa_calibrada_so_vende_abaixo_de_menos_100():
    assert LIMIARES_ATUAIS.margem_venda == -100.0
    politica = RecommendationPolicy()
    assert politica.define_recommendation(_margem_base(-60), 50) == "MANTER"
    assert politica.define_recommendation(_margem_base(-120), 50) == "VENDA_VALUATION"


def test_multiplo_base_configuravel():
    padrao = GrahamValuation().calculate_scenarios(2, 10, 4.4)["conservador"]["preco_justo"]
    maior = GrahamValuation(multiplo_base=12.0).calculate_scenarios(2, 10, 4.4)["conservador"]["preco_justo"]
    assert (padrao, maior) == (pytest.approx(17.0), pytest.approx(24.0))


def test_lpa_zero_do_etl_conta_como_ausente_e_nao_derruba_a_media():
    from app.core.analysis.valuation import normalizar_lpa

    lpa, fonte, media = normalizar_lpa(1.2, [0.0, 0.0, 0.76, 1.1, 0.9, 1.0])
    assert media == pytest.approx((0.76 + 1.1 + 0.9 + 1.0) / 4)
    assert fonte.startswith("LPA_ATUAL") or fonte.startswith("MEDIA_4")
