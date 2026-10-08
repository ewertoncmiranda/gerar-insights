from datetime import datetime, timezone

from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, JSON, Numeric, String, UniqueConstraint

from app.config.database_config import Base


def agora_utc():
    return datetime.now(timezone.utc)


class SerieHistoricaEntity(Base):
    __tablename__ = "serie_historica"
    __table_args__ = (
        UniqueConstraint("simbolo", "data_pregao", "intervalo", name="uq_serie_historica_dia"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    simbolo = Column(String(10), nullable=False)
    data_pregao = Column(Date, nullable=False)
    intervalo = Column(String(10), nullable=False, default="1d")
    range_usado = Column(String(10))

    abertura = Column(Numeric(12, 4))
    maxima = Column(Numeric(12, 4))
    minima = Column(Numeric(12, 4))
    fechamento = Column(Numeric(12, 4))
    fechamento_ajustado = Column(Numeric(12, 4))
    volume = Column(BigInteger)

    fonte = Column(String(30), nullable=False, default="BRAPI")
    detalhes_json = Column(JSON)
    criado_em = Column(DateTime, default=agora_utc, nullable=False)
    atualizado_em = Column(DateTime, default=agora_utc, onupdate=agora_utc, nullable=False)
