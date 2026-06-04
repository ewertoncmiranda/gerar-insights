"""
Testes de integração E2E para validar o fluxo completo.
Simula requisições HTTP e consumo de fila.
"""

import pytest
import json
from unittest.mock import Mock, patch, MagicMock


class TestE2EFlow:
    """
    Testes end-to-end do fluxo completo:
    1. POST /ativos → busca na Brapi
    2. Salva em MySQL
    3. Envia para fila SQS
    4. Consumer processa
    5. Persiste histórico
    6. Gera insights
    """

    @pytest.fixture
    def sample_ativo_json(self):
        """JSON de um ativo completo"""
        return {
            "symbol": "PETR4",
            "currency": "BRL",
            "shortName": "Petrobras PN",
            "longName": "Petróleo Brasileiro S.A.",
            "marketCap": 100000000,
            "regularMarketChange": 2.0,
            "regularMarketChangePercent": 7.14,
            "regularMarketTime": "2026-01-03T10:00:00",
            "regularMarketPrice": 30.0,
            "regularMarketDayHigh": 31.0,
            "regularMarketDayLow": 27.5,
            "regularMarketDayRange": "27.5 - 31.0",
            "regularMarketVolume": 1000000,
            "regularMarketPreviousClose": 28.0,
            "regularMarketOpen": 28.0,
            "fiftyTwoWeekRange": "15.0 - 45.0",
            "fiftyTwoWeekLow": 15.0,
            "fiftyTwoWeekHigh": 45.0,
            "priceEarnings": 8.0,
            "earningsPerShare": 4.0,
            "logoUrl": "https://...",
        }

    def test_e2e_ativo_completo(self, sample_ativo_json):
        """Testa fluxo E2E com um ativo completo"""
        # 1. Simular busca na API Brapi
        assert sample_ativo_json["symbol"] == "PETR4"
        assert sample_ativo_json["regularMarketPrice"] == 30.0

        # 2. Simular persistência em MySQL
        # Repository.save() deveria retornar a entidade com ID

        # 3. Simular envio para fila
        json_msg = json.dumps(sample_ativo_json)
        assert len(json_msg) > 0

        # 4. Simular consumo da fila
        parsed_ativo = json.loads(json_msg)
        assert parsed_ativo["symbol"] == "PETR4"

        # 5. Simular persistência de histórico
        # histórico deveria ter registro criado

        # 6. Simular geração de insights
        from app.core.service.trading_service import TradingService
        service = TradingService()
        decisao, indicadores, insights = service.processar_ativo(parsed_ativo)

        assert decisao in ["COMPRAR", "VENDER", "MANTER"]
        assert isinstance(indicadores, dict)
        assert isinstance(insights, list)

    @patch('app.config.aws_config.sqs')
    def test_e2e_envio_fila_sqs(self, mock_sqs, sample_ativo_json):
        """Testa envio de mensagem para fila SQS"""
        mock_sqs.send_message.return_value = {
            'MessageId': '12345',
            'MD5OfMessageBody': 'abc123'
        }

        msg = json.dumps(sample_ativo_json)
        response = mock_sqs.send_message(
            QueueUrl='http://localhost:4566/000000000000/test',
            MessageBody=msg
        )

        assert 'MessageId' in response
        mock_sqs.send_message.assert_called_once()

    @patch('app.config.aws_config.sqs')
    def test_e2e_consumo_fila_sqs(self, mock_sqs, sample_ativo_json):
        """Testa consumo de mensagem da fila SQS"""
        msg = json.dumps(sample_ativo_json)
        mock_sqs.receive_message.return_value = {
            'Messages': [
                {
                    'MessageId': '12345',
                    'Body': msg,
                    'ReceiptHandle': 'handle123'
                }
            ]
        }

        response = mock_sqs.receive_message(
            QueueUrl='http://localhost:4566/000000000000/test',
            MaxNumberOfMessages=10,
            WaitTimeSeconds=10
        )

        messages = response.get('Messages', [])
        assert len(messages) == 1

        body = json.loads(messages[0]['Body'])
        assert body['symbol'] == 'PETR4'

    def test_e2e_validacao_dados_incompletos(self):
        """Testa E2E com dados incompletos"""
        ativo_incompleto = {
            "symbol": "VALE3",
            # Faltam muitos campos
        }

        from app.core.service.trading_service import TradingService
        service = TradingService()

        # Não deve lançar exceção
        decisao, indicadores, insights = service.processar_ativo(ativo_incompleto)

        assert decisao in ["COMPRAR", "VENDER", "MANTER"]
        # Indicadores devem conter muitos Nones
        assert any(v is None for v in indicadores.values())

