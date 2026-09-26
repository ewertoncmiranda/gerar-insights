from unittest.mock import Mock

from app.external.database.insight_repository import InsightRepository
from app.external.database.repository_history import HistoricoRepository


class TestRepositoriosParticipamDaUnidadeDeTrabalho:

    def test_historico_faz_flush_sem_commit(self):
        sessao = Mock()
        entidade = object()

        resultado = HistoricoRepository().salvar(sessao, entidade)

        assert resultado is entidade
        sessao.add.assert_called_once_with(entidade)
        sessao.flush.assert_called_once_with()
        sessao.commit.assert_not_called()

    def test_insight_faz_flush_sem_commit(self):
        sessao = Mock()
        entidade = Mock(simbolo="PETR4", dedup_key=None)
        logger = Mock()

        resultado = InsightRepository(logger=logger).salvar(sessao, entidade)

        assert resultado is entidade
        sessao.add.assert_called_once_with(entidade)
        sessao.flush.assert_called_once_with()
        sessao.commit.assert_not_called()
