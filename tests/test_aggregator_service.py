"""
Testes unitários para AggregatorService.
Valida agregação de dados de histórico.
"""

import pytest
from unittest.mock import Mock
from app.core.service.aggregator_service import AggregatorService


class TestAggregatorService:

    @pytest.fixture
    def mock_snapshot(self):
        """Fixture: snapshot mock com atributos"""
        snapshot = Mock()
        snapshot.regular_market_price = 30.0
        snapshot.regular_market_open = 28.0
        snapshot.regular_market_day_high = 31.0
        snapshot.regular_market_day_low = 27.5
        snapshot.regular_market_volume = 1000000
        snapshot.price_earnings = 8.0
        snapshot.earnings_per_share = 4.0
        snapshot.market_cap = 100000000
        snapshot.fifty_two_week_low = 15.0
        snapshot.fifty_two_week_high = 45.0
        return snapshot

    @pytest.fixture
    def mock_historico(self):
        """Fixture: lista de registros históricos mock"""
        records = []
        for i in range(30):
            record = Mock()
            record.preco_fechamento = 25.0 + i * 0.1
            record.volume = 1000000 + i * 10000
            records.append(record)
        return records

    def test_aggregate_retorna_dict(self, mock_snapshot, mock_historico):
        """Testa se aggregate retorna um dicionário"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        assert isinstance(resultado, dict)

    def test_aggregate_tem_estrutura_esperada(self, mock_snapshot, mock_historico):
        """Testa se resultado tem chaves principais"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        assert "symbol" in resultado
        assert "snapshot" in resultado
        assert "historico" in resultado

    def test_aggregate_snapshot_estrutura(self, mock_snapshot, mock_historico):
        """Testa estrutura do snapshot agregado"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        snapshot_agg = resultado["snapshot"]
        assert snapshot_agg["preco"] == 30.0
        assert snapshot_agg["abertura"] == 28.0
        assert snapshot_agg["max_dia"] == 31.0
        assert snapshot_agg["min_dia"] == 27.5
        assert snapshot_agg["volume"] == 1000000
        assert snapshot_agg["pl"] == 8.0
        assert snapshot_agg["lpa"] == 4.0
        assert snapshot_agg["marketcap"] == 100000000
        assert snapshot_agg["min_52"] == 15.0
        assert snapshot_agg["max_52"] == 45.0

    def test_aggregate_historico_estrutura(self, mock_snapshot, mock_historico):
        """Testa estrutura do histórico agregado"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        historico_agg = resultado["historico"]
        assert "ultimos_precos" in historico_agg
        assert "ultimos_volumes" in historico_agg
        assert "media_20" in historico_agg
        assert "max_30dias" in historico_agg
        assert "min_30dias" in historico_agg
        assert "vol_medio_30d" in historico_agg

    def test_aggregate_media_20_dias(self, mock_snapshot, mock_historico):
        """Testa cálculo da média de 20 dias"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        media_20 = resultado["historico"]["media_20"]
        assert media_20 is not None
        assert isinstance(media_20, float)

    def test_aggregate_max_min_30_dias(self, mock_snapshot, mock_historico):
        """Testa cálculo de máximo e mínimo de 30 dias"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        max_30 = resultado["historico"]["max_30dias"]
        min_30 = resultado["historico"]["min_30dias"]

        assert max_30 is not None
        assert min_30 is not None
        assert max_30 >= min_30

    def test_aggregate_volume_medio(self, mock_snapshot, mock_historico):
        """Testa cálculo do volume médio"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, mock_historico)

        vol_medio = resultado["historico"]["vol_medio_30d"]
        assert vol_medio is not None
        assert isinstance(vol_medio, float)

    def test_aggregate_com_historico_vazio(self, mock_snapshot):
        """Testa agregação com histórico vazio"""
        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, [])

        historico_agg = resultado["historico"]
        assert historico_agg["media_20"] is None
        assert historico_agg["max_30dias"] is None
        assert historico_agg["min_30dias"] is None
        assert historico_agg["vol_medio_30d"] is None

    def test_aggregate_com_historico_insuficiente(self, mock_snapshot):
        """Testa agregação com menos de 20 registros"""
        records = []
        for i in range(15):
            record = Mock()
            record.preco_fechamento = 25.0 + i * 0.1
            record.volume = 1000000
            records.append(record)

        resultado = AggregatorService.aggregate("PETR4", mock_snapshot, records)

        # media_20 deve ser None pois temos apenas 15 registros
        assert resultado["historico"]["media_20"] is None

    def test_aggregate_simbolo_correto(self, mock_snapshot, mock_historico):
        """Testa se o símbolo é mantido corretamente"""
        resultado = AggregatorService.aggregate("VALE3", mock_snapshot, mock_historico)

        assert resultado["symbol"] == "VALE3"

