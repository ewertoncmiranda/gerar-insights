"""
Testes unitários para TradingService.
Valida cálculo de indicadores, decisões e insights.
"""

import pytest
from decimal import Decimal
from app.core.service.trading_service import TradingService


class TestTradingService:

    @pytest.fixture
    def service(self):
        """Fixture: instância de TradingService"""
        return TradingService()

    @pytest.fixture
    def sample_ativo_buy(self):
        """Fixture: ativo com condição de COMPRA"""
        return {
            "symbol": "PETR4",
            "regularMarketPrice": 30.0,
            "regularMarketOpen": 28.0,
            "regularMarketDayHigh": 31.0,
            "regularMarketDayLow": 27.5,
            "regularMarketVolume": 1000000,
            "priceEarnings": 8.0,  # Bom P/L
            "earningsPerShare": 4.0,
            "fiftyTwoWeekHigh": 45.0,
            "fiftyTwoWeekLow": 15.0,
            "marketCap": 100000000,
        }

    @pytest.fixture
    def sample_ativo_sell(self):
        """Fixture: ativo com condição de VENDA"""
        return {
            "symbol": "VALE3",
            "regularMarketPrice": 50.0,
            "regularMarketOpen": 53.0,  # Queda de -5.7%
            "regularMarketDayHigh": 54.0,
            "regularMarketDayLow": 49.0,
            "regularMarketVolume": 500000,
            "priceEarnings": 15.0,
            "earningsPerShare": 2.0,
            "fiftyTwoWeekHigh": 60.0,
            "fiftyTwoWeekLow": 30.0,
            "marketCap": 200000000,
        }

    @pytest.fixture
    def sample_ativo_hold(self):
        """Fixture: ativo neutro para MANTER"""
        return {
            "symbol": "MGLU3",
            "regularMarketPrice": 20.0,
            "regularMarketOpen": 20.5,
            "regularMarketDayHigh": 21.0,
            "regularMarketDayLow": 19.5,
            "regularMarketVolume": 2000000,
            "priceEarnings": 12.0,
            "earningsPerShare": 1.0,
            "fiftyTwoWeekHigh": 40.0,
            "fiftyTwoWeekLow": 10.0,
            "marketCap": 50000000,
        }

    # ======================== TESTES DE INDICADORES ========================

    def test_calcular_indicadores_returns_dict(self, service, sample_ativo_buy):
        """Testa se indicadores retorna um dicionário"""
        resultado = service.calcular_indicadores(sample_ativo_buy)
        assert isinstance(resultado, dict)

    def test_calcular_indicadores_tem_chaves_obrigatorias(self, service, sample_ativo_buy):
        """Testa se indicadores tem todas as chaves esperadas"""
        resultado = service.calcular_indicadores(sample_ativo_buy)

        chaves_esperadas = [
            "oscilacao_dia_percentual",
            "variacao_abertura",
            "pl",
            "lpa",
            "earnings_yield",
            "valor_mercado",
            "range_52_semanas",
            "posicao_no_range_52w_percent",
            "volume_hoje",
        ]

        for chave in chaves_esperadas:
            assert chave in resultado

    def test_earnings_yield_calculo_correto(self, service, sample_ativo_buy):
        """Testa cálculo correto do earnings yield"""
        resultado = service.calcular_indicadores(sample_ativo_buy)

        # earnings_yield = (lpa / preco) * 100
        # = (4.0 / 30.0) * 100 = 13.33%
        expected = (4.0 / 30.0) * 100
        assert abs(resultado["earnings_yield"] - expected) < 0.01

    def test_posicao_range_52w_calculo_correto(self, service, sample_ativo_buy):
        """Testa cálculo correto da posição no range de 52 semanas"""
        resultado = service.calcular_indicadores(sample_ativo_buy)

        # (30 - 15) / (45 - 15) * 100 = 50%
        expected = (30.0 - 15.0) / (45.0 - 15.0) * 100
        assert abs(resultado["posicao_no_range_52w_percent"] - expected) < 0.01

    # ======================== TESTES DE DECISÃO ========================

    def test_decisao_comprar(self, service, sample_ativo_buy):
        """Testa decisão COMPRAR com earnings_yield > 12%"""
        indicadores = service.calcular_indicadores(sample_ativo_buy)
        decisao = service.calcular_decisao(indicadores)
        assert decisao == "COMPRAR"

    def test_decisao_vender(self, service, sample_ativo_sell):
        """Testa decisão VENDER com queda > 3%"""
        indicadores = service.calcular_indicadores(sample_ativo_sell)
        decisao = service.calcular_decisao(indicadores)
        assert decisao == "VENDER"

    def test_decisao_manter(self, service, sample_ativo_hold):
        """Testa decisão MANTER (nenhuma regra acionada)"""
        indicadores = service.calcular_indicadores(sample_ativo_hold)
        decisao = service.calcular_decisao(indicadores)
        assert decisao == "MANTER"

    # ======================== TESTES DE INSIGHTS ========================

    def test_gerar_insights_retorna_lista(self, service, sample_ativo_buy):
        """Testa se insights retorna uma lista"""
        indicadores = service.calcular_indicadores(sample_ativo_buy)
        insights = service.gerar_insights(indicadores)
        assert isinstance(insights, list)
        assert len(insights) > 0

    def test_gerar_insights_valido_earnings_yield(self, service, sample_ativo_buy):
        """Testa se gera insight sobre earnings_yield alto"""
        indicadores = service.calcular_indicadores(sample_ativo_buy)
        insights = service.gerar_insights(indicadores)

        # Deve ter insight sobre ação barata
        assert any("barata" in insight.lower() or "lucro" in insight.lower()
                   for insight in insights)

    def test_gerar_insights_proximidade_max_52w(self, service):
        """Testa se gera insight sobre proximidade de máxima de 52 semanas"""
        ativo_alto = {
            "symbol": "TEST1",
            "regularMarketPrice": 44.0,  # Muito perto do máximo
            "regularMarketOpen": 43.0,
            "regularMarketDayHigh": 44.5,
            "regularMarketDayLow": 42.0,
            "regularMarketVolume": 1000000,
            "priceEarnings": 10.0,
            "earningsPerShare": 2.0,
            "fiftyTwoWeekHigh": 45.0,
            "fiftyTwoWeekLow": 10.0,
            "marketCap": 100000000,
        }

        indicadores = service.calcular_indicadores(ativo_alto)
        insights = service.gerar_insights(indicadores)

        # Deve ter insight sobre preço perto da máxima
        assert any("máxima" in insight.lower() or "52 semanas" in insight.lower()
                   for insight in insights)

    def test_gerar_insights_nenhum_sinal_forte(self, service):
        """Testa fallback quando nenhum sinal forte"""
        ativo_neutro = {
            "symbol": "NEUT",
            "regularMarketPrice": 25.0,
            "regularMarketOpen": 25.1,
            "regularMarketDayHigh": 25.5,
            "regularMarketDayLow": 24.5,
            "regularMarketVolume": 500000,
            "priceEarnings": 10.0,
            "earningsPerShare": 2.5,
            "fiftyTwoWeekHigh": 50.0,
            "fiftyTwoWeekLow": 20.0,
            "marketCap": 75000000,
        }

        indicadores = service.calcular_indicadores(ativo_neutro)
        insights = service.gerar_insights(indicadores)

        # Deve ter insight default
        assert any("nenhum sinal" in insight.lower() for insight in insights)

    # ======================== TESTES INTEGRADOS ========================

    def test_processar_ativo_completo(self, service, sample_ativo_buy):
        """Testa fluxo completo: processar_ativo"""
        decisao, indicadores, insights = service.processar_ativo(sample_ativo_buy)

        assert decisao == "COMPRAR"
        assert isinstance(indicadores, dict)
        assert isinstance(insights, list)
        assert len(insights) > 0

    def test_processar_ativo_com_dados_incompletos(self, service):
        """Testa processamento com alguns campos faltando"""
        ativo_incompleto = {
            "symbol": "INCO",
            # Campos faltando
        }

        # Não deve lançar exceção, apenas retornar valores None
        decisao, indicadores, insights = service.processar_ativo(ativo_incompleto)
        assert decisao == "MANTER"  # Default
        assert indicators_contém_nones(indicadores)


def indicators_contém_nones(indicadores: dict) -> bool:
    """Helper para verificar se há Nones nos indicadores"""
    return any(v is None for v in indicadores.values())

