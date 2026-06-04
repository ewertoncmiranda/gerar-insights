from dataclasses import dataclass
from logging import Logger
from sqlalchemy.orm import Session
from app.external.database.entity.insight_entity import InsightEntity


@dataclass
class InsightRepository:

    def __init__(self, logger: Logger):
        self.logger = logger

    def salvar(self, db: Session, entidade: InsightEntity):
        db.add(entidade)
        db.commit()
        db.refresh(entidade)
        self.logger.info(f"Insight para o ativo {entidade.simbolo} salvo no banco com sucesso.")
        return entidade
