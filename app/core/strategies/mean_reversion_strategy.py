from app.core.strategies.dto.market_data import MarketData


# mean_reversion_strategy.py
class MeanReversionStrategy:
    """
    Estratégia de Reversão à Média.

    Compra quando:
    - Preço se aproxima do 52 week low
    - Z-score indica que o preço está muito baixo (-1.5 ou menor)

    Vende quando:
    - Preço se aproxima do 52 week high
    - Z-score indica que o preço está esticado (+1.5 ou maior)
    """

    def should_buy(self, data: MarketData, z_score):
        """
        Compra quando:
        - z-score indica desconto anormal
        - Preço está próximo ao mínimo de 52 semanas
        """
        return z_score < -1.5 and data.price <= data.fifty_two_week_low * 1.1

    def should_sell(self, data: MarketData, z_score):
        """
        Vende quando:
        - z-score indica sobrecompra
        - Preço está próximo ao topo de 52 semanas
        """
        return z_score > 1.5 or data.price >= data.fifty_two_week_high * 0.95
