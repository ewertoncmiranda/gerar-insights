from logging import Logger

from sqlalchemy.orm import Session

from app.core.analysis.insight_payload import InsightPayloadBuilder
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import ValuationAnalyzer
from app.core.service.fundamentos_cvm_service import FundamentosCvmService
from app.core.service.serie_tecnica_service import SerieTecnicaService
from app.core.service.taxa_juros_service import TaxaJurosService


class FinancialAnalyzerService:
    def __init__(
        self,
        logger: Logger,
        valuation_analyzer: ValuationAnalyzer | None = None,
        technical_analyzer: TechnicalContextAnalyzer | None = None,
        recommendation_policy: RecommendationPolicy | None = None,
        payload_builder: InsightPayloadBuilder | None = None,
        serie_tecnica_service: SerieTecnicaService | None = None,
        taxa_juros_service: TaxaJurosService | None = None,
        fundamentos_cvm_service: FundamentosCvmService | None = None,
    ):
        self.logger = logger
        self.valuation_analyzer = valuation_analyzer or ValuationAnalyzer()
        self.technical_analyzer = technical_analyzer or TechnicalContextAnalyzer()
        self.recommendation_policy = recommendation_policy or RecommendationPolicy()
        self.payload_builder = payload_builder or InsightPayloadBuilder()
        self.serie_tecnica_service = serie_tecnica_service or SerieTecnicaService()
        self.taxa_juros_service = taxa_juros_service or TaxaJurosService()
        self.fundamentos_cvm_service = fundamentos_cvm_service or FundamentosCvmService()

    def gerar_insight_fundamentalista(self, db: Session, ativo: dict) -> dict:
        snapshot = MarketSnapshot.from_payload(ativo)
        self.logger.info(
            f"Analisando ativo {snapshot.symbol} "
            f"(Preco: {snapshot.price}, LPA: {snapshot.earnings_per_share})"
        )

        if not snapshot.has_valid_fundamentals():
            return self._resultado_nulo(snapshot.symbol, ativo.get("dedupKey"))

        # DEC-02: sem Selic no banco nao ha Y; SEM_DADOS em vez de cair na
        # formula sem juros e misturar duas regras sob a mesma versao.
        taxa = self.taxa_juros_service.taxa_vigente(db)
        if taxa is None:
            self.logger.warning(f"Sem Selic em indice_macro; {snapshot.symbol} fica SEM_DADOS")
            return self._resultado_nulo(
                snapshot.symbol, ativo.get("dedupKey"), "Taxa livre de risco (Selic) indisponivel"
            )

        lpas_anuais, vpa = self.fundamentos_cvm_service.historico(db, snapshot.symbol)
        # Modos G_NOMINAL e Y_REAL usam o IPCA 12m ja divulgado (TASK-54, DEC-08).
        precisa_ipca = self.valuation_analyzer.limiares.modo_juros != "G_REAL"
        ipca = self.taxa_juros_service.ipca_12m(db) if precisa_ipca else None
        valuation = self.valuation_analyzer.analyze(
            snapshot, taxa[0], f"SELIC_META {taxa[1].isoformat()}", lpas_anuais, vpa, ipca
        )
        if not valuation["valido"]:
            # Media dos ultimos exercicios negativa: sem lucro normalizado nao
            # ha preco justo (ISS-F2).
            return self._resultado_nulo(
                snapshot.symbol, ativo.get("dedupKey"),
                "IPCA 12m indisponivel" if valuation["modo_juros"] != "G_REAL" and ipca is None
                else f"LPA normalizado nao positivo ({valuation['fonte_lpa']})",
            )
        technical_context = self.technical_analyzer.analyze(snapshot)
        recommendation = self.recommendation_policy.evaluate(snapshot, valuation, technical_context)
        sinal_tecnico = self.serie_tecnica_service.avaliar(db, snapshot)
        details = self.payload_builder.build(snapshot, valuation, technical_context, recommendation, sinal_tecnico)
        base_scenario = valuation["cenario_base"]

        return {
            "dedup_key": ativo.get("dedupKey"),
            "simbolo": snapshot.symbol,
            "preco_justo_graham": base_scenario["preco_justo"],
            "margem_seguranca_percent": base_scenario["margem_seguranca_percent"],
            "recomendacao": recommendation["recomendacao"],
            "detalhes_json": details,
        }

    def _resultado_nulo(
        self,
        simbolo: str,
        dedup_key: str | None,
        aviso: str = "Dados fundamentais insuficientes ou lucro negativo",
    ) -> dict:
        return {
            "dedup_key": dedup_key,
            "simbolo": simbolo,
            "preco_justo_graham": None,
            "margem_seguranca_percent": None,
            "recomendacao": "SEM_DADOS",
            "detalhes_json": {
                "schemaVersion": "2.1",
                "versao_payload": "2.1",
                "resumo": {"recomendacao": "SEM_DADOS"},
                "aviso": aviso,
            },
        }
