from sqlalchemy.orm import Session

from app.config.config_logger import setup_logger
from app.external.database.entity.historico_entity import HistoricoAcaoEntity
logger = setup_logger()


class HistoricoRepository:

    def salvar(self, db: Session, entidade: HistoricoAcaoEntity):
        db.add(entidade)
        db.commit()
        db.refresh(entidade)
        return entidade
