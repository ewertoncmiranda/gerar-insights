# valuation_strategy.py
class ValuationStrategy:
    """
    Estratégia de Valuation baseada em múltiplos.

    Compra empresas baratas comparadas ao setor:
    priceEarnings < media_setorial * 0.80

    É um dos métodos mais usados por analistas fundamentalistas e value investors.
    """

    def should_buy(self, price_earnings: float, sector_pe: float) -> bool:
        """
        Compra quando:
        - O P/L é pelo menos 20% menor que o P/L médio do setor
        """
        return price_earnings < sector_pe * 0.80

    def should_sell(self, price_earnings: float, sector_pe: float) -> bool:
        """
        Vende quando:
        - A ação deixou de estar barata e voltou ao valor justo
        """
        return price_earnings > sector_pe * 1.1
