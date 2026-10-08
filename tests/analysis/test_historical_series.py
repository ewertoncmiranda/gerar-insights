from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.core.mapper.historical_series import extrair_candles


def test_extrai_candle_de_results_e_converte_tipos():
    timestamp = int(datetime(2026, 1, 2, 15, 0, tzinfo=timezone.utc).timestamp())
    candles = extrair_candles(
        {
            "results": [
                {
                    "symbol": "PETR4",
                    "data": {
                        "usedInterval": "1d",
                        "usedRange": "1mo",
                        "historicalDataPrice": [
                            {
                                "date": timestamp,
                                "open": 30.1,
                                "high": "31.2",
                                "low": 29,
                                "close": 30.8,
                                "adjustedClose": None,
                                "volume": "1000.9",
                            }
                        ],
                    },
                }
            ]
        }
    )

    assert len(candles) == 1
    candle = candles[0]
    assert candle.simbolo == "PETR4"
    assert candle.data_pregao == date(2026, 1, 2)
    assert candle.abertura == Decimal("30.1")
    assert candle.maxima == Decimal("31.2")
    assert candle.fechamento_ajustado is None
    assert candle.volume == 1000
    assert candle.intervalo == "1d"
    assert candle.range_usado == "1mo"


def test_aceita_formato_de_resultado_unico_e_data_formatada():
    [candle] = extrair_candles(
        {
            "requestedSymbol": "VALE3",
            "data": {
                "historicalDataPrice": [
                    {"dataFormatada": "08/10/2026", "close": 62.5}
                ]
            },
        }
    )

    assert candle.simbolo == "VALE3"
    assert candle.data_pregao == date(2026, 10, 8)
    assert candle.intervalo == "1d"
    assert candle.fechamento == Decimal("62.5")


@pytest.mark.parametrize(
    ("payload", "mensagem"),
    [
        ({}, "lista results valida"),
        ({"results": [{}]}, "sem symbol"),
        ({"results": [{"symbol": "TEST3", "data": {"historicalDataPrice": [{}]}}]}, "Candle sem"),
    ],
)
def test_rejeita_payload_historico_invalido(payload, mensagem):
    with pytest.raises(ValueError, match=mensagem):
        extrair_candles(payload)
