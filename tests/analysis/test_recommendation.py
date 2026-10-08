from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy


def _snapshot(price_earnings=10.0):
    return MarketSnapshot(
        symbol="TEST3",
        price=50.0,
        earnings_per_share=5.0,
        price_earnings=price_earnings,
        open_price=48.0,
        previous_close=49.0,
        day_high=55.0,
        day_low=45.0,
        volume=1_000,
        market_cap=1_000_000,
        fifty_two_week_low=20.0,
        fifty_two_week_high=60.0,
    )


def _valuation(conservador, base, earnings_yield, preco_ate_graham_number=None):
    return {
        "cenarios_graham": {
            "conservador": {"margem_seguranca_percent": conservador},
            "base": {"margem_seguranca_percent": base},
        },
        "earnings_yield": earnings_yield,
        "preco_ate_graham_number": preco_ate_graham_number,
    }


def _contexto(posicao, amplitude):
    return {"_raw": {"posicao_52w": posicao, "amplitude_intradiaria": amplitude}}


def test_evaluate_compra_forte_reune_sinais_positivos_e_alertas():
    resultado = RecommendationPolicy().evaluate(
        _snapshot(price_earnings=25.0),
        _valuation(25.0, 30.0, 13.0, True),
        _contexto(95.0, 10.0),
    )

    assert resultado["recomendacao"] == "COMPRA_FORTE"
    assert resultado["nivel_risco"] == "ALTO"
    assert resultado["confianca_score"] == 70
    assert {item["tipo"] for item in resultado["insights"]} == {
        "MARGEM_SEGURANCA",
        "EARNINGS_YIELD",
        "PRECO_LUCRO",
        "CONTEXTO_TECNICO",
        "VOLATILIDADE",
    }
    assert resultado["fatores_decisao"] == {
        "positivos": ["margem_conservadora_acima_20", "earnings_yield_acima_12"],
        "negativos": ["pl_acima_20", "proximo_maxima_52w"],
        "neutros": [],
    }


def test_evaluate_compra_moderada_perto_da_minima():
    resultado = RecommendationPolicy().evaluate(
        _snapshot(price_earnings=5.0),
        _valuation(5.0, 25.0, 9.0),
        _contexto(10.0, 4.0),
    )

    assert resultado["recomendacao"] == "COMPRA_MODERADA"
    assert resultado["nivel_risco"] == "BAIXO"
    assert resultado["confianca_score"] == 68
    assert [item["severidade"] for item in resultado["insights"]] == [
        "POSITIVO_MODERADO",
        "NEUTRO",
    ]
    assert resultado["fatores_decisao"]["positivos"] == ["margem_base_acima_20"]
    assert resultado["fatores_decisao"]["neutros"] == [
        "pl_baixo_pode_indicar_desconto_ou_risco",
        "proximo_minima_52w",
    ]


def test_evaluate_venda_com_valuation_e_earnings_yield_negativos():
    resultado = RecommendationPolicy().evaluate(
        _snapshot(price_earnings=None),
        _valuation(-10.0, -200.0, 5.0),
        _contexto(50.0, 8.0),
    )

    assert resultado["recomendacao"] == "VENDA_VALUATION"
    assert resultado["nivel_risco"] == "ALTO"
    assert resultado["confianca_score"] == 20
    assert [item["tipo"] for item in resultado["insights"]] == [
        "VALUATION",
        "EARNINGS_YIELD",
        "VOLATILIDADE",
    ]
    assert resultado["fatores_decisao"]["negativos"] == [
        "preco_acima_valor_justo_base",
        "earnings_yield_abaixo_6",
    ]


def test_evaluate_sem_sinal_forte_e_risco_medio():
    resultado = RecommendationPolicy().evaluate(
        _snapshot(),
        _valuation(-5.0, 5.0, 7.0),
        _contexto(50.0, 4.0),
    )

    assert resultado["recomendacao"] == "MANTER"
    assert resultado["nivel_risco"] == "MEDIO"
    assert resultado["confianca_score"] == 55
    assert resultado["insights"][0]["tipo"] == "SEM_SINAL_FORTE"
    assert resultado["fatores_decisao"] == {"positivos": [], "negativos": [], "neutros": []}


def test_risco_medio_por_amplitude_e_confianca_sem_contexto_52w():
    policy = RecommendationPolicy()
    valuation = _valuation(5.0, 5.0, 9.0)

    assert policy.classify_risk(valuation, None, 8.0) == "MEDIO"
    assert policy.calculate_confidence(valuation, None, None) == 68
