from app.core.analysis.market_snapshot import MarketSnapshot


class InsightPayloadBuilder:
    def build(self, snapshot: MarketSnapshot, valuation: dict, technical_context: dict, recommendation: dict) -> dict:
        context_payload = dict(technical_context)
        context_payload.pop("_raw", None)

        return {
            "versao_payload": "2.0",
            "resumo": {
                "recomendacao": recommendation["recomendacao"],
                "nivel_risco": recommendation["nivel_risco"],
                "confianca_score": recommendation["confianca_score"],
                "cenario_referencia": "base",
            },
            "snapshot_mercado": snapshot.to_payload(),
            "valuation": {
                "earnings_yield_percent": valuation["earnings_yield_percent"],
                "classificacao_pl": valuation["classificacao_pl"],
                "classificacao_earnings_yield": valuation["classificacao_earnings_yield"],
                "cenarios_graham": valuation["cenarios_graham"],
            },
            "contexto_tecnico": context_payload,
            "insights": recommendation["insights"],
            "fatores_decisao": recommendation["fatores_decisao"],
            "earnings_yield_percent": valuation["earnings_yield_percent"],
            "desconto_maxima_52w_percent": technical_context["desconto_maxima_52w_percent"],
            "crescimento_projetado_utilizado": valuation["crescimento_base"],
        }
