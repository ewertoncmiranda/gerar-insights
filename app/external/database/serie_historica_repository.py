from sqlalchemy.orm import Session

from app.external.database.entity.serie_historica_entity import SerieHistoricaEntity


class SerieHistoricaRepository:

    def listar_ultimos_fechamentos(
        self, db: Session, simbolo: str, intervalo: str = "1d", limite: int = 20
    ) -> list[SerieHistoricaEntity]:
        candles_desc = (
            db.query(SerieHistoricaEntity)
            .filter(
                SerieHistoricaEntity.simbolo == simbolo,
                SerieHistoricaEntity.intervalo == intervalo,
            )
            .order_by(SerieHistoricaEntity.data_pregao.desc())
            .limit(limite)
            .all()
        )
        return list(reversed(candles_desc))

    def upsert(self, db: Session, entidade: SerieHistoricaEntity):
        existente = (
            db.query(SerieHistoricaEntity)
            .filter(
                SerieHistoricaEntity.simbolo == entidade.simbolo,
                SerieHistoricaEntity.data_pregao == entidade.data_pregao,
                SerieHistoricaEntity.intervalo == entidade.intervalo,
            )
            .one_or_none()
        )

        if existente is None:
            db.add(entidade)
            return entidade

        existente.range_usado = entidade.range_usado
        existente.abertura = entidade.abertura
        existente.maxima = entidade.maxima
        existente.minima = entidade.minima
        existente.fechamento = entidade.fechamento
        existente.fechamento_ajustado = entidade.fechamento_ajustado
        existente.volume = entidade.volume
        existente.fonte = entidade.fonte
        existente.detalhes_json = entidade.detalhes_json
        return existente
