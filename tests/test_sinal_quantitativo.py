from app.contracts.sinal_quantitativo import como_sinal_quantitativo
from app.core.analysis.insight_payload import AVISO_LEGAL, InsightPayloadBuilder
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.event_contracts import validar_insight
from app.validacao.avaliador import SEM_DIRECAO, VENDA, direcao


def _snapshot():
    return MarketSnapshot("TEST3", 10, 2, 5, None, None, None, None, None, None, None, None)


def _valuation():
    return {
        "earnings_yield_percent": 20,
        "classificacao_pl": "BAIXO",
        "classificacao_earnings_yield": "ALTO",
        "cenarios_graham": {},
        "taxa_livre_risco_percent": 15,
        "fonte_taxa_livre_risco": "SELIC",
        "fator_juros": 0.2933,
        "cenarios_graham_sem_ajuste_juros": {},
        "lpa_atual": 2,
        "lpa_usado": 2,
        "lpa_medio": None,
        "fonte_lpa": "SNAPSHOT",
        "vpa": None,
        "graham_number": None,
        "preco_ate_graham_number": None,
        "multiplo_base": 8.5,
        "crescimento_base": 3,
    }


def test_payload_v3_expoe_sinal_neutro_e_alias_compativel():
    payload = InsightPayloadBuilder().build(
        _snapshot(),
        _valuation(),
        {"_raw": {}, "desconto_maxima_52w_percent": None},
        {
            "recomendacao": "VENDA_VALUATION",
            "nivel_risco": "ALTO",
            "confianca_score": 20,
            "insights": [],
            "fatores_decisao": {},
        },
    )

    assert payload["schemaVersion"] == payload["versao_payload"] == "3.0"
    assert payload["aviso_legal"] == AVISO_LEGAL
    assert payload["resumo"]["sinal_quantitativo"] == "SEM_MARGEM"
    assert payload["resumo"]["recomendacao"] == "SEM_MARGEM"
    validar_insight(payload)


def test_nomenclatura_nova_e_historico_tem_direcoes_distintas():
    assert como_sinal_quantitativo("COMPRA_FORTE") == "SINAL_POSITIVO_FORTE"
    assert como_sinal_quantitativo("COMPRA_MODERADA") == "SINAL_POSITIVO"
    assert como_sinal_quantitativo("MANTER") == "NEUTRO"
    assert direcao("SEM_MARGEM") == SEM_DIRECAO
    assert direcao("VENDA_VALUATION") == VENDA  # histórico v2.x continua legível
