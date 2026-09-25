from sqlalchemy.orm import Session

from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.technical_series import TechnicalSeriesAnalyzer
from app.core.strategies.mean_reversion_strategy import MeanReversionStrategy
from app.core.strategies.momentum_strategy import MomentumStrategy
from app.external.database.serie_historica_repository import SerieHistoricaRepository

JANELA_MINIMA = 20


class SerieTecnicaService:

    def __init__(
        self,
        repository: SerieHistoricaRepository | None = None,
        analyzer: TechnicalSeriesAnalyzer | None = None,
        momentum: MomentumStrategy | None = None,
        mean_reversion: MeanReversionStrategy | None = None,
    ):
        self.repository = repository or SerieHistoricaRepository()
        self.analyzer = analyzer or TechnicalSeriesAnalyzer()
        self.momentum = momentum or MomentumStrategy()
        self.mean_reversion = mean_reversion or MeanReversionStrategy()

    def avaliar(self, db: Session, snapshot: MarketSnapshot) -> dict | None:
        candles = self.repository.listar_ultimos_fechamentos(db, snapshot.symbol, limite=JANELA_MINIMA)
        if len(candles) < JANELA_MINIMA:
            return None

        closes = [float(c.fechamento) for c in candles if c.fechamento is not None]
        volumes = [float(c.volume) for c in candles if c.volume is not None]

        metricas = self.analyzer.analyze(closes, volumes)
        if metricas is None or snapshot.price is None:
            return None

        volume_score = metricas["score_volume"] if metricas["score_volume"] is not None else 0.0

        sinal_momentum = self._classificar(
            self.momentum.should_buy(snapshot.price, metricas["media_movel"], volume_score),
            self.momentum.should_sell(snapshot.price, metricas["media_movel"], volume_score),
        )
        sinal_reversao = self._classificar(
            self.mean_reversion.should_buy(
                snapshot.price, metricas["z_score_fechamento"], snapshot.fifty_two_week_low
            ),
            self.mean_reversion.should_sell(
                snapshot.price, metricas["z_score_fechamento"], snapshot.fifty_two_week_high
            ),
        )

        return {
            **metricas,
            "sinal_momentum": sinal_momentum,
            "sinal_reversao": sinal_reversao,
        }

    @staticmethod
    def _classificar(comprar: bool, vender: bool) -> str:
        if comprar:
            return "COMPRA_TECNICA"
        if vender:
            return "VENDA_TECNICA"
        return "NEUTRO_TECNICO"
