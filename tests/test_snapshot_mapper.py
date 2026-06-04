"""
Testes unitários para SnapshotAcao Mapper.
Valida mapeamento de dados do payload para a entidade.
"""

import pytest
from app.core.mapper.equity_snapshot import SnapshotAcao


class TestSnapshotAcao:

    @pytest.fixture
    def payload_completo(self):
        """Fixture: payload completo de um ativo"""
        return {
            "symbol": "PETR4",
            "regularMarketOpen": 28.0,
            "regularMarketPrice": 30.0,
            "regularMarketDayHigh": 31.0,
            "regularMarketDayLow": 27.5,
            "regularMarketVolume": 1000000,
            "fiftyTwoWeekLow": 15.0,
            "fiftyTwoWeekHigh": 45.0,
            "marketCap": 100000000,
            "priceEarnings": 8.0,
            "earningsPerShare": 4.0,
        }

    @pytest.fixture
    def payload_parcial(self):
        """Fixture: payload com alguns campos faltando"""
        return {
            "symbol": "VALE3",
            "regularMarketPrice": 50.0,
            # Outros campos ausentes
        }

    def test_snapshot_criacao_completa(self, payload_completo):
        """Testa criação de snapshot com dados completos"""
        snapshot = SnapshotAcao(payload_completo)

        assert snapshot.simbolo == "PETR4"
        assert snapshot.preco_abertura == 28.0
        assert snapshot.preco_fechamento == 30.0
        assert snapshot.preco_maximo == 31.0
        assert snapshot.preco_minimo == 27.5
        assert snapshot.volume == 1000000
        assert snapshot.minima_52_semanas == 15.0
        assert snapshot.maxima_52_semanas == 45.0
        assert snapshot.valor_mercado == 100000000
        assert snapshot.preco_lucro == 8.0
        assert snapshot.lucro_por_acao == 4.0

    def test_snapshot_criacao_parcial(self, payload_parcial):
        """Testa criação de snapshot com dados parciais"""
        snapshot = SnapshotAcao(payload_parcial)

        assert snapshot.simbolo == "VALE3"
        assert snapshot.preco_fechamento == 50.0
        assert snapshot.preco_abertura is None
        assert snapshot.volume is None

    def test_snapshot_repr(self, payload_completo):
        """Testa representação em string do snapshot"""
        snapshot = SnapshotAcao(payload_completo)
        repr_str = repr(snapshot)

        assert "SnapshotAcao" in repr_str
        assert "PETR4" in repr_str
        assert "30.0" in repr_str  # preco_fechamento

    def test_snapshot_com_payload_vazio(self):
        """Testa comportamento com payload vazio"""
        snapshot = SnapshotAcao({})

        assert snapshot.simbolo is None
        assert snapshot.preco_fechamento is None
        # Todos os atributos devem ser None

    def test_snapshot_com_simbolo_nao_existente(self):
        """Testa snapshot quando symbol key não existe"""
        payload = {
            "regularMarketPrice": 30.0,
            # symbol não existe
        }
        snapshot = SnapshotAcao(payload)

        assert snapshot.simbolo is None
        assert snapshot.preco_fechamento == 30.0

