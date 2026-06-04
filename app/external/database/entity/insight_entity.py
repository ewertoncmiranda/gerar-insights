from sqlalchemy import Column, Integer, String, DateTime, Numeric, JSON
from sqlalchemy.sql import func
from app.config.database_config import Base

class InsightEntity(Base):
    __tablename__ = 'insight_acao'

    id = Column(Integer, primary_key=True, autoincrement=True)
    simbolo = Column(String(10), nullable=False)
    data_analise = Column(DateTime, default=func.now(), nullable=False)
    preco_justo_graham = Column(Numeric(12, 4))
    margem_seguranca_percent = Column(Numeric(10, 4))
    recomendacao = Column(String(20))
    detalhes_json = Column(JSON)
