"""
Testes unitários para SerieTecnicaService.
Usa um repositorio fake (injetado via construtor) para nao depender de banco real.
"""

from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.service.serie_tecnica_service import SerieTecnicaService, JANELA_MINIMA


class _CandleFake:
    def __init__(self, fechamento: float, volume: int, fechamento_ajustado=None):
        self.fechamento = fechamento
        self.volume = volume
        # None simula candle sem adjustedClose vindo da BRAPI
        self.fechamento_ajustado = fechamento_ajustado


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


class TestAjustePorProventos:
    """O preco ajustado e o que deve alimentar o calculo tecnico.

    Dividendo e desdobramento derrubam o preco sem ninguem vender. Usando o
    fechamento bruto, a media movel e o z-score passam a medir o provento em
    vez do comportamento do papel.
    """

    def test_usa_o_fechamento_ajustado_quando_existe(self):
        # bruto constante em 10, ajustado constante em 9: a media tem que ser 9
        candles = [_CandleFake(10.0, 1000, fechamento_ajustado=9.0) for _ in range(JANELA_MINIMA)]
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(db=None, snapshot=_snapshot(price=9.0))

        assert resultado["media_movel"] == 9.0

    def test_cai_para_o_bruto_quando_nao_ha_ajustado(self):
        candles = [_CandleFake(10.0, 1000) for _ in range(JANELA_MINIMA)]
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(db=None, snapshot=_snapshot(price=10.0))

        assert resultado["media_movel"] == 10.0

    def test_degrau_de_provento_no_bruto_nao_contamina_o_z_score(self):
        """Serie ajustada estavel, bruta com degrau no ex-dividendo.

        Sem a correcao o z-score enxergaria uma anomalia que nao existe.
        """
        candles = []
        for i in range(JANELA_MINIMA):
            # bruto salta de 10 para 11 na metade; ajustado fica sempre em 10
            bruto = 10.0 if i < JANELA_MINIMA // 2 else 11.0
            candles.append(_CandleFake(bruto, 1000, fechamento_ajustado=10.0))

        service = SerieTecnicaService(repository=_RepositorioFake(candles))
        resultado = service.avaliar(db=None, snapshot=_snapshot(price=10.0))

        assert resultado["media_movel"] == 10.0
        # serie ajustada constante -> desvio zero -> z-score zero
        assert resultado["z_score_fechamento"] == 0.0

    def test_mistura_de_candles_com_e_sem_ajustado_nao_quebra(self):
        candles = [
            _CandleFake(10.0, 1000, fechamento_ajustado=10.0 if i % 2 == 0 else None)
            for i in range(JANELA_MINIMA)
        ]
        service = SerieTecnicaService(repository=_RepositorioFake(candles))

        resultado = service.avaliar(db=None, snapshot=_snapshot(price=10.0))

        assert resultado["amostras"] == JANELA_MINIMA
