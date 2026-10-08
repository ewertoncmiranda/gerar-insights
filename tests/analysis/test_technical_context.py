from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.technical_context import TechnicalContextAnalyzer


def _snapshot(**changes):
    values = {
        "symbol": "TEST3",
        "price": 50.0,
        "earnings_per_share": 5.0,
        "price_earnings": 10.0,
        "open_price": 40.0,
        "previous_close": 45.0,
        "day_high": 55.0,
        "day_low": 45.0,
        "volume": 1_000,
        "market_cap": 1_000_000,
        "fifty_two_week_low": 20.0,
        "fifty_two_week_high": 60.0,
    }
    values.update(changes)
    return MarketSnapshot(**values)


def test_analyze_calcula_percentuais_e_zona_do_range():
    resultado = TechnicalContextAnalyzer().analyze(_snapshot())

    assert resultado["variacao_desde_abertura_percent"] == 25.0
    assert resultado["variacao_vs_fechamento_anterior_percent"] == 11.1111
    assert resultado["amplitude_intradiaria_percent"] == 20.0
    assert resultado["posicao_range_52w_percent"] == 75.0
    assert resultado["desconto_maxima_52w_percent"] == 16.6667
    assert resultado["distancia_minima_52w_percent"] == 150.0
    assert resultado["zona_52w"] == "MEIO_DO_RANGE"


def test_analyze_tolera_dados_opcionais_ausentes():
    resultado = TechnicalContextAnalyzer().analyze(
        _snapshot(
            open_price=None,
            previous_close=None,
            day_high=None,
            day_low=None,
            fifty_two_week_low=None,
            fifty_two_week_high=None,
        )
    )

    assert resultado["variacao_desde_abertura_percent"] is None
    assert resultado["variacao_vs_fechamento_anterior_percent"] is None
    assert resultado["amplitude_intradiaria_percent"] is None
    assert resultado["zona_52w"] == "NAO_DISPONIVEL"


def test_classifica_extremos_do_range_52_semanas():
    analyzer = TechnicalContextAnalyzer()
    assert analyzer.classify_52w_zone(25.0) == "PROXIMO_DA_MINIMA"
    assert analyzer.classify_52w_zone(85.0) == "PROXIMO_DA_MAXIMA"
