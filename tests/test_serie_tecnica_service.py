"""
Testes unitários para SerieTecnicaService.
Usa um repositorio fake (injetado via construtor) para nao depender de banco real.
"""

from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.service.serie_tecnica_service import SerieTecnicaService, JANELA_MINIMA


class _CandleFake:
    def __init__(self, fechamento: float, volume: int):
        self.fechamento = fechamento
        self.volume = volume


class _RepositorioFake:
    def __init__(self, candles):
        self._candles = candles

    def listar_ultimos_fechamentos(self, db, simbolo, intervalo="1d", limite=20):
        return self._candles[-limite:]


def _snapshot(price: float, low_52w: float = 4.0, high_52w: float = 6.5) -> MarketSnapshot:
    return MarketSnapshot(
        symbol="MGLU3",
        price=price,
        earnings_per_share=1.0,
        price_earnings=10.0,
        open_price=price,
        previous_close=price,
        day_high=price,
        day_low=price,
        volume=1000,
        market_cap=1000000,
        fifty_two_week_low=low_52w,
        fifty_two_week_high=high_52w,
    )


class TestSerieTecnicaService:

    def test_sem_candles_suficientes_retorna_none(self):
        candles = [_CandleFake(5.0, 1000) for _ in range(JANELA_MINIMA - 1)]
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(db=None, snapshot=_snapshot(price=5.0))

        assert resultado is None

    def test_serie_estavel_gera_sinal_neutro(self):
        candles = [_CandleFake(5.0, 1000) for _ in range(JANELA_MINIMA)]
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(db=None, snapshot=_snapshot(price=5.0, low_52w=1.0, high_52w=9.0))

        assert resultado is not None
        assert resultado["sinal_momentum"] == "NEUTRO_TECNICO"
        assert resultado["sinal_reversao"] == "NEUTRO_TECNICO"

    def test_preco_proximo_da_maxima_52w_gera_sinal_de_venda_na_reversao(self):
        candles = [_CandleFake(5.0 + i * 0.05, 1000) for i in range(JANELA_MINIMA)]
        preco_atual = candles[-1].fechamento
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(
            db=None,
            snapshot=_snapshot(price=preco_atual, low_52w=4.0, high_52w=preco_atual * 0.96),
        )

        assert resultado["sinal_reversao"] == "VENDA_TECNICA"
