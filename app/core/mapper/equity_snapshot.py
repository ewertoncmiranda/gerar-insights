class SnapshotAcao:

    def __init__(self, payload: dict):
        self.simbolo = payload.get("symbol")
        self.preco_abertura = payload.get("regularMarketOpen")
        self.preco_fechamento = payload.get("regularMarketPrice")
        self.preco_maximo = payload.get("regularMarketDayHigh")
        self.preco_minimo = payload.get("regularMarketDayLow")
        self.volume = payload.get("regularMarketVolume")
        self.minima_52_semanas = payload.get("fiftyTwoWeekLow")
        self.maxima_52_semanas = payload.get("fiftyTwoWeekHigh")
        self.valor_mercado = payload.get("marketCap")
        self.preco_lucro = payload.get("priceEarnings")
        self.lucro_por_acao = payload.get("earningsPerShare")

    def __repr__(self):
        return (
            f"SnapshotAcao(simbolo={self.simbolo}, abertura={self.preco_abertura}, "
            f"fechamento={self.preco_fechamento}, max={self.preco_maximo}, "
            f"min={self.preco_minimo}, volume={self.volume})"
        )

    def __str__(self):
        return (
            f"SnapshotAcao(simbolo={self.simbolo}, abertura={self.preco_abertura}, "
            f"fechamento={self.preco_fechamento}, max={self.preco_maximo}, "
            f"min={self.preco_minimo}, volume={self.volume})"
        )
