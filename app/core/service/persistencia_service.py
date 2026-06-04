from sqlalchemy.orm import Session

from app.core.mapper.equity_snapshot import SnapshotAcao
from app.external.database.repository_history import HistoricoRepository
from app.external.database.entity.historico_entity import HistoricoAcaoEntity
class PersistenciaHistoricoService:

    def __init__(self):
        self.repository = HistoricoRepository()

    def registrar_snapshot(self, db: Session, snapshot: SnapshotAcao):
        entidade = HistoricoAcaoEntity(
            simbolo=snapshot.simbolo,
            preco_abertura=snapshot.preco_abertura,
            preco_fechamento=snapshot.preco_fechamento,
            preco_maximo=snapshot.preco_maximo,
            preco_minimo=snapshot.preco_minimo,
            volume=snapshot.volume,
            minima_52_semanas=snapshot.minima_52_semanas,
            maxima_52_semanas=snapshot.maxima_52_semanas,
            valor_mercado=snapshot.valor_mercado,
            preco_lucro=snapshot.preco_lucro,
            lucro_por_acao=snapshot.lucro_por_acao
        )

        return self.repository.salvar(db, entidade)

