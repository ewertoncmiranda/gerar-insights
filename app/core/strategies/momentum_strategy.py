from app.core.strategies.dto.market_data import MarketData


# momentum_strategy.py
class MomentumStrategy:
    """
    Estratégia Momentum.

    Aproveita tendências de alta confirmadas por volume, típica de fundos quantitativos.
    A lógica identifica quando o preço cruza a média móvel e quando o volume confirma.
    """

    def should_buy(self, data: MarketData, ma20, volume_score):
        """
        Compra quando:
        - Preço cruza a média móvel de 20 períodos
        - Volume acima da média indica força compradora
        """
        return data.price > ma20 and volume_score > 1.3

    def should_sell(self, data: MarketData, ma20, volume_score):
        """
        Vende quando:
        - Preço cruza para baixo da média móvel
        - Volume baixo indica enfraquecimento da tendência
        """
        return data.price < ma20 and volume_score < 0.7
