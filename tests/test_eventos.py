import json
from unittest.mock import Mock, patch

import pytest
from jsonschema import ValidationError

from app.core.core_processor import CoreProcessor
from app.core.event_contracts import preparar_evento, validar_insight


def snapshot(**extras):
    return {"symbol": "PETR4", "regularMarketPrice": 30, **extras}


def test_legado_recebe_versao_e_chave_estavel():
    assert preparar_evento("ativos", snapshot()) == preparar_evento("ativos", snapshot())


@pytest.mark.parametrize("extras", [{"schemaVersion": "99"}, {"schemaVersion": "1.0"}, {"regularMarketPrice": "erro"}])
def test_rejeita_versao_chave_ou_tipo_invalido(extras):
    with pytest.raises(ValidationError):
        preparar_evento("ativos", snapshot(**extras))


def test_enum_compartilhado_rejeita_recomendacao_inventada():
    with pytest.raises(ValidationError):
        validar_insight({"schemaVersion": "2.1", "versao_payload": "2.1", "resumo": {"recomendacao": "COMPRAR_TUDO"}})


def test_serie_legada_ignora_metadados_de_transporte():
    serie = {"results": [{"symbol": "PETR4", "data": {"historicalDataPrice": [{"date": 1, "close": 30}]}}]}
    a = preparar_evento("series_historicas", {**serie, "took": 1})
    b = preparar_evento("series_historicas", {**serie, "took": 2})
    assert a["dedupKey"] == b["dedupKey"]


def consumer():
    core = CoreProcessor(*[Mock() for _ in range(7)])
    session = Mock()
    core.session_factory.return_value.__enter__ = Mock(return_value=session)
    core.session_factory.return_value.__exit__ = Mock(return_value=False)
    client = core.aws.get_sqs_client.return_value
    client.receive_message.return_value = {"Messages": [{"ReceiptHandle": "receipt", "Body": json.dumps(snapshot())}]}
    return core, session, client


@pytest.mark.parametrize("novo", [True, False])
def test_confirma_antes_de_apagar_e_duplicata_nao_reprocessa(novo):
    core, session, client = consumer()
    handler = Mock()
    ordem = []
    session.commit.side_effect = lambda: ordem.append("commit")
    client.delete_message.side_effect = lambda **kw: ordem.append("ack")
    with patch("app.core.core_processor.reservar_evento", return_value=novo):
        core._consumir_fila("ativos", "fila", handler)
    assert handler.call_count == int(novo)
    assert ordem == ["commit", "ack"]


def test_falha_rollback_e_nao_apaga_mensagem():
    core, session, client = consumer()
    with patch("app.core.core_processor.reservar_evento", return_value=True):
        core._consumir_fila("ativos", "fila", Mock(side_effect=RuntimeError("falha")))
    session.rollback.assert_called_once()
    session.commit.assert_not_called()
    client.delete_message.assert_not_called()


def test_versao_desconhecida_nao_abre_transacao_nem_apaga():
    core, session, client = consumer()
    client.receive_message.return_value["Messages"][0]["Body"] = json.dumps(snapshot(schemaVersion="99"))
    core._consumir_fila("ativos", "fila", Mock())
    core.session_factory.assert_not_called()
    client.delete_message.assert_not_called()
