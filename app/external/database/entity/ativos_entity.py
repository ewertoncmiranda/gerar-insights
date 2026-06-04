from sqlalchemy import Column, Integer, String, DECIMAL, DateTime
from app.config.database_config import Base


class AtivoEntity(Base):
    __tablename__ = "ativos"

    id = Column(Integer, primary_key=True, autoincrement=True)

    symbol = Column(String(50))
    currency = Column(String(20))

    short_name = Column(String(255))
    long_name = Column(String(255))

    market_cap = Column(DECIMAL(20, 2))
    market_change = Column(DECIMAL(20, 2))
    market_change_percent = Column(DECIMAL(20, 2))

    regular_market_time = Column(DateTime)

    regular_market_price = Column(DECIMAL(20, 2))
    regular_market_day_high = Column(DECIMAL(20, 2))
    regular_market_day_low = Column(DECIMAL(20, 2))
    regular_market_day_range = Column(String(100))

    regular_market_volume = Column(DECIMAL(20, 2))
    regular_market_previous_close = Column(DECIMAL(20, 2))
    regular_market_open = Column(DECIMAL(20, 2))

    fifty_two_week_range = Column(String(100))
    fifty_two_week_low = Column(DECIMAL(20, 2))
    fifty_two_week_high = Column(DECIMAL(20, 2))

    price_earnings = Column(DECIMAL(20, 2))
    earnings_per_share = Column(DECIMAL(20, 2))

    logo_url = Column(String(255))

    def __repr__(self):
        return (
            f"<Ativo(symbol={self.symbol}, price={self.regular_market_price}, "
            f"open={self.regular_market_open}, high={self.regular_market_day_high}, "
            f"low={self.regular_market_day_low}, volume={self.regular_market_volume})>"
        )
