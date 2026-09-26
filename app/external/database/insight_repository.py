from dataclasses import dataclass
from logging import Logger
from sqlalchemy.orm import Session
from app.external.database.entity.insight_entity import InsightEntity


@dataclass
class InsightRepository:

    def __init__(self, logger: Logger):
        self.logger = logger

    def salvar(self, db: Session, entidade: InsightEntity):
        if getattr(entidade, "dedup_key", None):
            existente = (
                db.query(InsightEntity)
                .filter(InsightEntity.dedup_key == entidade.dedup_key)
                .one_or_none()
            )
            if existente is not None:
                self.logger.info(
                    f"Insight duplicado para {entidade.simbolo} ignorado ({entidade.dedup_key})"
                )
                return existente
        db.add(entidade)
        db.flush()
        self.logger.info(f"Insight para o ativo {entidade.simbolo} salvo no banco com sucesso.")
        return entidade
