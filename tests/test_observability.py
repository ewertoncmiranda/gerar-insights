import json
import logging
import urllib.request
from unittest.mock import Mock, patch

from app.config.observability import ObservabilityMetrics, iniciar_servidor_observabilidade
from app.core.core_processor import CoreProcessor


class MetricasFake:
    def __init__(self):
        self.mensagens = []
        self.latencias = 0
        self.recomendacoes = []

    def registrar_mensagem(self, fila, resultado):
        self.mensagens.append((fila, resultado))

    def registrar_recomendacao(self, recomendacao):
        self.recomendacoes.append(recomendacao)

    def observar_latencia(self, fila):
        def concluir():
            self.latencias += 1

        return concluir


def test_servidor_observabilidade_expoe_health():
    servidor = iniciar_servidor_observabilidade(
        0,
        logging.getLogger("teste"),
        ObservabilityMetrics(),
    )
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{servidor.server_port}/health",
            timeout=2,
        ) as resposta:
            assert resposta.status == 200
            assert resposta.read() == b"ok\n"
    finally:
        servidor.shutdown()
        servidor.server_close()


def test_core_registra_metricas_de_processamento():
    metricas = MetricasFake()
    core = CoreProcessor(*[Mock() for _ in range(7)], metricas=metricas)
    session = Mock()
    core.session_factory.return_value.__enter__ = Mock(return_value=session)
    core.session_factory.return_value.__exit__ = Mock(return_value=False)
    client = core.aws.get_sqs_client.return_value
    client.receive_message.return_value = {
        "Messages": [
            {
                "ReceiptHandle": "receipt",
                "Body": json.dumps({"symbol": "PETR4", "regularMarketPrice": 30}),
            }
        ]
    }

    with patch("app.core.core_processor.reservar_evento", return_value=True):
        core._consumir_fila("ativos", "fila", Mock())

    assert metricas.mensagens == [("ativos", "processada")]
    assert metricas.latencias == 1


def test_core_registra_payload_invalido():
    metricas = MetricasFake()
    core = CoreProcessor(*[Mock() for _ in range(7)], metricas=metricas)
    client = core.aws.get_sqs_client.return_value
    client.receive_message.return_value = {
        "Messages": [{"ReceiptHandle": "receipt", "Body": "{invalido"}]
    }

    core._consumir_fila("ativos", "fila", Mock())

    assert metricas.mensagens == [("ativos", "invalida")]
    assert metricas.latencias == 1
