from app.core.analysis.insight_payload import InsightPayloadBuilder
from app.core.analysis.market_snapshot import MarketSnapshot


def test_payload_inclui_sinal_tecnico_no_bloco_e_no_topo():
    snapshot = MarketSnapshot("TEST3", 10.0, 2.0, 5.0, 9.0, 9.5, 11.0, 8.0, 100, 1_000, 5.0, 15.0)
    valuation = {
        "earnings_yield_percent": 20.0,
        "classificacao_pl": "BAIXO_COM_ATENCAO",
        "classificacao_earnings_yield": "ATRATIVO",
        "cenarios_graham": {},
        "taxa_livre_risco_percent": 10.0,
        "fonte_taxa_livre_risco": "SELIC",
        "fator_juros": 0.44,
        "cenarios_graham_sem_ajuste_juros": {},
        "lpa_atual": 2.0,
        "lpa_usado": 2.0,
        "lpa_medio": None,
        "fonte_lpa": "LPA_ATUAL",
        "vpa": None,
        "graham_number": None,
        "preco_ate_graham_number": None,
        "multiplo_base": 8.5,
        "crescimento_base": 3.0,
    }
    sinal_tecnico = {
        "media_movel": 9.5,
        "z_score_fechamento": 1.2,
        "score_volume": 1.4,
    }

    payload = InsightPayloadBuilder().build(
        snapshot,
        valuation,
        {"_raw": {"interno": True}, "desconto_maxima_52w_percent": 33.3333},
        {
            "recomendacao": "COMPRA_FORTE",
            "nivel_risco": "BAIXO",
            "confianca_score": 90,
            "insights": [],
            "fatores_decisao": {},
        },
        sinal_tecnico,
    )

    assert "_raw" not in payload["contexto_tecnico"]
    assert payload["contexto_tecnico_serie"] == sinal_tecnico
    assert payload["media_movel"] == 9.5
    assert payload["z_score_fechamento"] == 1.2
    assert payload["score_volume"] == 1.4
