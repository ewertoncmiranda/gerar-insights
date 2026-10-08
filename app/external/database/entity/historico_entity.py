from sqlalchemy import Column, Integer, String, DateTime, DECIMAL, BigInteger, UniqueConstraint
from app.config.database_config import Base
from datetime import datetime, timezone


def agora_utc():
    return datetime.now(timezone.utc)


class HistoricoAcaoEntity(Base):
    __tablename__ = "historico_acoes"
    __table_args__ = (UniqueConstraint("dedup_key", name="uq_historico_acoes_dedup_key"),)

    id = Column(Integer, primary_key=True, autoincrement=True)
    dedup_key = Column(String(64))

    simbolo = Column(String(10), nullable=False)
    timestamp = Column(DateTime, default=agora_utc, nullable=False)

    preco_abertura = Column(DECIMAL(12, 4))
    preco_fechamento = Column(DECIMAL(12, 4))
    preco_maximo = Column(DECIMAL(12, 4))
    preco_minimo = Column(DECIMAL(12, 4))

    volume = Column(BigInteger)

    minima_52_semanas = Column(DECIMAL(12, 4))
    maxima_52_semanas = Column(DECIMAL(12, 4))

    valor_mercado = Column(BigInteger)
    preco_lucro = Column(DECIMAL(10, 4))
    lucro_por_acao = Column(DECIMAL(10, 4))

    criado_em = Column(DateTime, default=agora_utc)
