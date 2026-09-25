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

    def should_buy(self, price: float, z_score: float, fifty_two_week_low: float | None) -> bool:
        """
        Compra quando:
        - z-score indica desconto anormal
        - Preço está próximo ao mínimo de 52 semanas
        """
        if fifty_two_week_low is None:
            return False
        return z_score < -1.5 and price <= fifty_two_week_low * 1.1

    def should_sell(self, price: float, z_score: float, fifty_two_week_high: float | None) -> bool:
        """
        Vende quando:
        - z-score indica sobrecompra
        - Preço está próximo ao topo de 52 semanas
        """
        if z_score > 1.5:
            return True
        if fifty_two_week_high is None:
            return False
        return price >= fifty_two_week_high * 0.95
