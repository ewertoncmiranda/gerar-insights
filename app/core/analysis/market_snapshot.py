from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSnapshot:
    symbol: str
    price: float | None
    earnings_per_share: float | None
    price_earnings: float | None
    open_price: float | None
    previous_close: float | None
    day_high: float | None
    day_low: float | None
    volume: int | None
    market_cap: int | None
    fifty_two_week_low: float | None
    fifty_two_week_high: float | None

    @classmethod
    def from_payload(cls, payload: dict) -> "MarketSnapshot":
        return cls(
            symbol=payload.get("symbol", "UNKNOWN"),
            price=payload.get("regularMarketPrice"),
            earnings_per_share=payload.get("earningsPerShare"),
            price_earnings=payload.get("priceEarnings"),
            open_price=payload.get("regularMarketOpen"),
            previous_close=payload.get("regularMarketPreviousClose"),
            day_high=payload.get("regularMarketDayHigh"),
            day_low=payload.get("regularMarketDayLow"),
            volume=payload.get("regularMarketVolume"),
            market_cap=payload.get("marketCap"),
            fifty_two_week_low=payload.get("fiftyTwoWeekLow"),
            fifty_two_week_high=payload.get("fiftyTwoWeekHigh"),
        )

    def has_valid_fundamentals(self) -> bool:
        return bool(self.price and self.earnings_per_share and self.earnings_per_share > 0)

    def to_payload(self) -> dict:
        return {
            "preco": self.price,
            "abertura": self.open_price,
            "fechamento_anterior": self.previous_close,
            "maxima_dia": self.day_high,
            "minima_dia": self.day_low,
            "volume": self.volume,
            "valor_mercado": self.market_cap,
            "preco_lucro": self.price_earnings,
            "lucro_por_acao": self.earnings_per_share,
            "minima_52w": self.fifty_two_week_low,
            "maxima_52w": self.fifty_two_week_high,
        }
