from sqlalchemy.orm import Session

from app.core.mapper.historical_series import CandleDiario, extrair_candles
from app.external.database.entity.serie_historica_entity import SerieHistoricaEntity
from app.external.database.serie_historica_repository import SerieHistoricaRepository


class SerieHistoricaService:

    def __init__(self, repository: SerieHistoricaRepository | None = None):
        self.repository = repository or SerieHistoricaRepository()

    def registrar_payload(self, db: Session, payload: dict) -> int:
        candles = extrair_candles(payload)
        for candle in candles:
            self.repository.upsert(db, self._para_entidade(candle))
        return len(candles)

    def _para_entidade(self, candle: CandleDiario) -> SerieHistoricaEntity:
        return SerieHistoricaEntity(
            simbolo=candle.simbolo,
            data_pregao=candle.data_pregao,
            intervalo=candle.intervalo,
            range_usado=candle.range_usado,
            abertura=candle.abertura,
            maxima=candle.maxima,
            minima=candle.minima,
            fechamento=candle.fechamento,
            fechamento_ajustado=candle.fechamento_ajustado,
            volume=candle.volume,
            fonte="BRAPI",
            detalhes_json=candle.detalhes_json,
        )
