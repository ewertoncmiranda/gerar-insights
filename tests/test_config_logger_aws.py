"""ISS-08 (LOG_LEVEL respeitado, sem handler duplicado) e ISS-09 (um cliente SQS por processo)."""

import json
import logging
from unittest import mock

from app.config import aws_config, config_logger


def test_logger_respeita_log_level(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    assert config_logger.setup_logger().level == logging.DEBUG
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    assert config_logger.setup_logger().level == logging.WARNING


def test_logger_nivel_invalido_cai_para_info(monkeypatch):
    monkeypatch.setenv("LOG_LEVEL", "barulhento")
    assert config_logger.setup_logger().level == logging.INFO


def test_logger_chamado_varias_vezes_tem_um_handler_so():
    for _ in range(3):
        logger = config_logger.setup_logger()
    nossos = [h for h in logger.handlers if getattr(h, "_b3_handler", False)]
    assert len(nossos) == 1


def test_logger_emite_json(monkeypatch):
    import io

    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = config_logger.setup_logger()
    handler = next(h for h in logger.handlers if getattr(h, "_b3_handler", False))
    stream = io.StringIO()
    antigo_stream = handler.stream
    handler.stream = stream
    try:
        logger.info("evento de teste", extra={"simbolo": "WEGE3"})
    finally:
        handler.stream = antigo_stream

    evento = json.loads(stream.getvalue())
    assert evento["levelname"] == "INFO"
    assert evento["name"] == config_logger.NOME_LOGGER
    assert evento["message"] == "evento de teste"
    assert evento["simbolo"] == "WEGE3"


def test_cliente_sqs_criado_uma_vez_e_reaproveitado():
    aws_config.AwsConfig.descartar_cliente()
    with mock.patch.object(aws_config.boto3, "client", return_value=object()) as fabrica:
        primeiro = aws_config.AwsConfig().get_sqs_client()
        segundo = aws_config.AwsConfig().get_sqs_client()
        terceiro = aws_config.AwsConfig().get_sqs_client()
    assert primeiro is segundo is terceiro
    assert fabrica.call_count == 1
    aws_config.AwsConfig.descartar_cliente()
