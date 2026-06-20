from logging import Logger

from app.core.analysis.insight_payload import InsightPayloadBuilder
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import ValuationAnalyzer


class FinancialAnalyzerService:
    def __init__(
        self,
        logger: Logger,
        valuation_analyzer: ValuationAnalyzer | None = None,
        technical_analyzer: TechnicalContextAnalyzer | None = None,
        recommendation_policy: RecommendationPolicy | None = None,
        payload_builder: InsightPayloadBuilder | None = None,
    ):
        self.logger = logger
        self.valuation_analyzer = valuation_analyzer or ValuationAnalyzer()
        self.technical_analyzer = technical_analyzer or TechnicalContextAnalyzer()
        self.recommendation_policy = recommendation_policy or RecommendationPolicy()
        self.payload_builder = payload_builder or InsightPayloadBuilder()

    def gerar_insight_fundamentalista(self, ativo: dict) -> dict:
        snapshot = MarketSnapshot.from_payload(ativo)
        self.logger.info(
            f"Analisando ativo {snapshot.symbol} "
            f"(Preco: {snapshot.price}, LPA: {snapshot.earnings_per_share})"
        )

        if not snapshot.has_valid_fundamentals():
            return self._resultado_nulo(snapshot.symbol)

        valuation = self.valuation_analyzer.analyze(snapshot)
        technical_context = self.technical_analyzer.analyze(snapshot)
        recommendation = self.recommendation_policy.evaluate(snapshot, valuation, technical_context)
        details = self.payload_builder.build(snapshot, valuation, technical_context, recommendation)
        base_scenario = valuation["cenario_base"]

        return {
            "simbolo": snapshot.symbol,
            "preco_justo_graham": base_scenario["preco_justo"],
            "margem_seguranca_percent": base_scenario["margem_seguranca_percent"],
            "recomendacao": recommendation["recomendacao"],
            "detalhes_json": details,
        }

    def _resultado_nulo(self, simbolo: str) -> dict:
        return {
            "simbolo": simbolo,
            "preco_justo_graham": None,
            "margem_seguranca_percent": None,
            "recomendacao": "SEM_DADOS",
            "detalhes_json": {
                "versao_payload": "2.0",
                "aviso": "Dados fundamentais insuficientes ou lucro negativo",
            },
        }
