from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.versao_regra import VERSAO_REGRA
from app.contracts.sinal_quantitativo import como_sinal_quantitativo

# Recomendar compra ou venda a terceiros e atividade de analista credenciado
# (CVM Res. 20/2021): todo insight sai com o aviso, para quem quer que o exiba.
AVISO_LEGAL = (
    "Sinal quantitativo gerado por regras automaticas para estudo, nao recomendacao de "
    "investimento. Nao considera sua situacao, impostos nem custos; decisoes sao suas."
)
VERSAO_PAYLOAD = "3.0"


class InsightPayloadBuilder:
    def build(
        self,
        snapshot: MarketSnapshot,
        valuation: dict,
        technical_context: dict,
        recommendation: dict,
        sinal_tecnico: dict | None = None,
    ) -> dict:
        context_payload = dict(technical_context)
        context_payload.pop("_raw", None)

        sinal = como_sinal_quantitativo(recommendation["recomendacao"])
        payload = {
            "schemaVersion": VERSAO_PAYLOAD,
            "versao_payload": VERSAO_PAYLOAD,
            # Qual regra produziu este insight; o diario de sinais agrupa por ela.
            "versao_regra": VERSAO_REGRA,
            "aviso_legal": AVISO_LEGAL,
            "resumo": {
                "sinal_quantitativo": sinal,
                # Alias temporario para consumidores v2: o nome do campo e
                # preservado, mas o valor ja usa a linguagem neutra do v3.
                "recomendacao": sinal,
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
                # Y do Graham ajustado (DEC-02) e a formula de 1962 so como referencia.
                "taxa_livre_risco_percent": valuation["taxa_livre_risco_percent"],
                "fonte_taxa_livre_risco": valuation["fonte_taxa_livre_risco"],
                "fator_juros": valuation["fator_juros"],
                "cenarios_graham_sem_ajuste_juros": valuation["cenarios_graham_sem_ajuste_juros"],
                # LPA normalizado e Graham Number (ISS-F2); multiplo base (ISS-F3).
                "lpa_atual": valuation["lpa_atual"],
                "lpa_usado": valuation["lpa_usado"],
                "lpa_medio": valuation["lpa_medio"],
                "fonte_lpa": valuation["fonte_lpa"],
                "vpa": valuation["vpa"],
                "graham_number": valuation["graham_number"],
                "preco_ate_graham_number": valuation["preco_ate_graham_number"],
                "multiplo_base": valuation["multiplo_base"],
            },
            "contexto_tecnico": context_payload,
            "insights": recommendation["insights"],
            "fatores_decisao": recommendation["fatores_decisao"],
            "earnings_yield_percent": valuation["earnings_yield_percent"],
            "desconto_maxima_52w_percent": technical_context["desconto_maxima_52w_percent"],
            "crescimento_projetado_utilizado": valuation["crescimento_base"],
        }

        if sinal_tecnico is not None:
            payload["contexto_tecnico_serie"] = sinal_tecnico
            # Hoisting para o nivel de topo: ConsolidadorAnaliseAcao.java so calcula media
            # de campos numericos de primeiro nivel de detalhes_json (nao entra em objetos aninhados).
            payload["media_movel"] = sinal_tecnico["media_movel"]
            payload["z_score_fechamento"] = sinal_tecnico["z_score_fechamento"]
            payload["score_volume"] = sinal_tecnico["score_volume"]

        return payload
