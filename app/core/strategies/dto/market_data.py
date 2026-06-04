"""
  Representa o payload de dados do ativo vindo da B3.

  Cada atributo corresponde a um indicador essencial usado por analistas de investimentos,
  traders, quants e gestores para avaliar preço, risco, volatilidade, liquidez e valor.
  """

class MarketData:

    def __init__(self, payload: dict):
        self.symbol = payload["symbol"]
        self.price = payload["regularMarketPrice"]
        self.prev_close = payload["regularMarketPreviousClose"]
        self.open_price = payload["regularMarketOpen"]
        self.day_low = payload["regularMarketDayLow"]
        self.day_high = payload["regularMarketDayHigh"]
        self.day_volume = payload["regularMarketVolume"]
        self.fifty_two_week_low = payload["fiftyTwoWeekLow"]
        self.fifty_two_week_high = payload["fiftyTwoWeekHigh"]
        self.price_earnings = payload["priceEarnings"]
        self.earnings_per_share = payload["earningsPerShare"]
