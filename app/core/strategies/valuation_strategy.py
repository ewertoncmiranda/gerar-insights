class ValuationStrategy:
    """Estratégia setorial desativada por ausência de fonte confiável.

    A regra antiga comparava P/L do ativo com um P/L setorial recebido de fora
    (`priceEarnings < media_setorial * 0.80`). O ecossistema ainda nao tem uma
    fonte point-in-time validada para P/L setorial, entao a estrategia fica
    neutra ate que uma nova tarefa implemente a fonte ou substitua a regra por
    fatores setoriais medidos no backtest.
    """

    ativa = False
    motivo_inativa = "sem fonte point-in-time validada para P/L setorial"

    def should_buy(self, price_earnings: float, sector_pe: float) -> bool:
        """Sem fonte setorial confiável, a regra nunca gera compra."""
        return False

    def should_sell(self, price_earnings: float, sector_pe: float) -> bool:
        """Sem fonte setorial confiável, a regra nunca gera venda."""
        return False
