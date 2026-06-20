from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.number_utils import percent
from app.core.analysis.number_utils import range_position
from app.core.analysis.number_utils import round_metric


class TechnicalContextAnalyzer:
    def analyze(self, snapshot: MarketSnapshot) -> dict:
        discount_from_high = (
            percent(snapshot.fifty_two_week_high - snapshot.price, snapshot.fifty_two_week_high)
            if snapshot.fifty_two_week_high else None
        )
        distance_from_low = (
            percent(snapshot.price - snapshot.fifty_two_week_low, snapshot.fifty_two_week_low)
            if snapshot.fifty_two_week_low else None
        )
        range_52w_position = range_position(
            snapshot.price,
            snapshot.fifty_two_week_low,
            snapshot.fifty_two_week_high,
        )
        change_from_open = (
            percent(snapshot.price - snapshot.open_price, snapshot.open_price)
            if snapshot.open_price else None
        )
        change_from_previous_close = (
            percent(snapshot.price - snapshot.previous_close, snapshot.previous_close)
            if snapshot.previous_close else None
        )
        intraday_range = (
            percent(snapshot.day_high - snapshot.day_low, snapshot.price)
            if snapshot.day_high and snapshot.day_low else None
        )

        return {
            "variacao_desde_abertura_percent": round_metric(change_from_open),
            "variacao_vs_fechamento_anterior_percent": round_metric(change_from_previous_close),
            "amplitude_intradiaria_percent": round_metric(intraday_range),
            "posicao_range_52w_percent": round_metric(range_52w_position),
            "desconto_maxima_52w_percent": round_metric(discount_from_high),
            "distancia_minima_52w_percent": round_metric(distance_from_low),
            "zona_52w": self.classify_52w_zone(range_52w_position),
            "_raw": {
                "posicao_52w": range_52w_position,
                "amplitude_intradiaria": intraday_range,
                "desconto_maxima_52w": discount_from_high,
            },
        }

    def classify_52w_zone(self, range_52w_position: float | None) -> str:
        if range_52w_position is None:
            return "NAO_DISPONIVEL"
        if range_52w_position <= 25:
            return "PROXIMO_DA_MINIMA"
        if range_52w_position >= 85:
            return "PROXIMO_DA_MAXIMA"
        return "MEIO_DO_RANGE"
