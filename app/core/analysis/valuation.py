from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.number_utils import percent
from app.core.analysis.number_utils import round_metric


class GrahamValuation:
    SCENARIOS = {
        "conservador": 0,
        "base": 3,
        "otimista": 5,
    }

    def calculate_scenarios(self, earnings_per_share: float, price: float) -> dict:
        scenarios = {}
        for name, growth in self.SCENARIOS.items():
            implied_earnings_multiple = 8.5 + 2 * growth
            fair_price = earnings_per_share * implied_earnings_multiple
            scenarios[name] = {
                "crescimento_percent": growth,
                "multiplo_lucro_implicito": round_metric(implied_earnings_multiple),
                "preco_justo": round_metric(fair_price),
                "margem_seguranca_percent": round_metric(percent(fair_price - price, fair_price)),
            }
        return scenarios


class ValuationAnalyzer:
    def __init__(self, graham: GrahamValuation | None = None):
        self.graham = graham or GrahamValuation()

    def analyze(self, snapshot: MarketSnapshot) -> dict:
        earnings_yield = percent(snapshot.earnings_per_share, snapshot.price)
        scenarios = self.graham.calculate_scenarios(snapshot.earnings_per_share, snapshot.price)

        return {
            "earnings_yield": earnings_yield,
            "earnings_yield_percent": round_metric(earnings_yield),
            "classificacao_pl": self.classify_price_earnings(snapshot.price_earnings),
            "classificacao_earnings_yield": self.classify_earnings_yield(earnings_yield),
            "cenarios_graham": scenarios,
            "cenario_base": scenarios["base"],
            "crescimento_base": self.graham.SCENARIOS["base"],
        }

    def classify_price_earnings(self, price_earnings: float | None) -> str:
        if price_earnings is None or price_earnings <= 0:
            return "NAO_DISPONIVEL"
        if price_earnings < 8:
            return "BAIXO_COM_ATENCAO"
        if price_earnings <= 15:
            return "SAUDAVEL"
        if price_earnings <= 20:
            return "ESTICADO"
        return "EXIGENTE"

    def classify_earnings_yield(self, earnings_yield: float) -> str:
        if earnings_yield >= 12:
            return "ATRATIVO"
        if earnings_yield >= 8:
            return "RAZOAVEL"
        if earnings_yield >= 6:
            return "BAIXO"
        return "MUITO_BAIXO"
