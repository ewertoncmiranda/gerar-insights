"""TASK-32: estratégia setorial não pode influenciar sem fonte de P/L setorial."""

from app.core.strategies.valuation_strategy import ValuationStrategy


def test_valuation_strategy_setorial_fica_inativa_sem_fonte_confiavel():
    estrategia = ValuationStrategy()

    assert estrategia.ativa is False
    assert "P/L setorial" in estrategia.motivo_inativa
    assert estrategia.should_buy(price_earnings=5, sector_pe=20) is False
    assert estrategia.should_sell(price_earnings=40, sector_pe=20) is False
