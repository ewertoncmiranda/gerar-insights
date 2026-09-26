from sqlalchemy.orm import Session

from app.external.database.entity.historico_entity import HistoricoAcaoEntity


class HistoricoRepository:

    def salvar(self, db: Session, entidade: HistoricoAcaoEntity):
        if getattr(entidade, "dedup_key", None):
            existente = (
                db.query(HistoricoAcaoEntity)
                .filter(HistoricoAcaoEntity.dedup_key == entidade.dedup_key)
                .one_or_none()
            )
            if existente is not None:
                return existente
        db.add(entidade)
        db.flush()
        return entidade
