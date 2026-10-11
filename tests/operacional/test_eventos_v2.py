import json
from datetime import date

import pytest

from app.operacional import eventos_v2
from app.operacional.eventos import PayloadInvalido


def _consenso():
    return {
        "direcaoAnalitica": "POSITIVA",
        "operabilidade": "OPERAVEL",
        "resumo": "Sinais consistentes para acompanhamento operacional simulado.",
        "sinais": [
            {
                "fonte": "REGRA_PRINCIPAL",
                "valor": "COMPRA_MODERADA",
                "direcao": "POSITIVO",
                "peso": 3,
                "detalhe": "Regra principal positiva.",
            }
        ],
        "divergencias": [],
    }


def _tese():
    return {
        "aviso": "Operacao simulada para estudo; nao e recomendacao de investimento.",
        "positivos": [{"codigo": "MARGEM", "descricao": "Margem operacional resiliente.", "severidade": "BAIXA"}],
        "negativos": [],
        "riscos": [],
        "invalidadores": [],
        "dadosAusentes": [],
    }


def _snapshot(**extras):
    return {
        "simbolo": "PETR4",
        "dataPregao": "2026-10-09",
        "versaoRegra": "OPR-2026.10.10-1",
        "statusOperacional": "PAPER_TRADING_ELEGIVEL",
        "faixaLiquidez": "ALTA",
        "setorGrupo": "PETROLEO",
        "sinalPrincipal": "COMPRA_MODERADA",
        "sinalTecnico": {"momentum": "COMPRA_TECNICA", "reversao": "NEUTRO_TECNICO"},
        "sinalV2Sombra": "SINAL_POSITIVO",
        "opiniaoIa": None,
        "confiancaScore": 82,
        "confiancaFaixa": "NAO_CALIBRADA",
        "posicao": None,
        "ultimoEvento": None,
        "motivosBloqueio": [],
        "consenso": _consenso(),
        "tese": _tese(),
        **extras,
    }


def test_projeta_snapshot_so_com_campos_do_contrato_e_schema_version():
    projetado = eventos_v2.projetar("snapshot-ticker", _snapshot(campoInterno="nao_publicar"))

    assert projetado["schemaVersion"] == "operacional.snapshot-ticker.v2"
    assert "campoInterno" not in projetado
    eventos_v2.validar("snapshot-ticker", projetado)


def test_valida_contrato_v2_rejeita_sinal_inventado():
    invalido = eventos_v2.projetar("snapshot-ticker", _snapshot(sinalPrincipal="COMPRA_TOTAL"))

    with pytest.raises(PayloadInvalido):
        eventos_v2.validar("snapshot-ticker", invalido)


class _Resultado:
    def __init__(self, linhas=None):
        self._linhas = linhas or []

    def mappings(self):
        return self._linhas


class _DbFake:
    def __init__(self):
        self.commits = 0
        self.updates = []

    def execute(self, comando, params=None):
        sql = str(comando)
        if "SELECT * FROM evento_operacional_v2" in sql:
            return _Resultado([
                {
                    "id": 7,
                    "event_id": "evt-1",
                    "contrato": "snapshot-ticker",
                    "versao_regra": "OPR-2026.10.10-1",
                    "data_pregao": date(2026, 10, 9),
                    "payload_json": json.dumps(eventos_v2.projetar("snapshot-ticker", _snapshot()), ensure_ascii=False),
                }
            ])
        if "UPDATE evento_operacional_v2" in sql:
            self.updates.append(params["i"])
            return _Resultado()
        raise AssertionError(f"SQL inesperado: {sql}")

    def commit(self):
        self.commits += 1


class _SqsFake:
    def __init__(self):
        self.mensagens = []

    def get_queue_url(self, QueueName):
        assert QueueName == "fila-v2"
        return {"QueueUrl": "http://localstack/fila-v2"}

    def send_message(self, **kwargs):
        self.mensagens.append(kwargs)


def test_publica_pendente_v2_com_envelope_e_marca_publicado():
    db = _DbFake()
    sqs = _SqsFake()

    resumo = eventos_v2.publicar_pendentes_v2(db, cliente_sqs=sqs, fila="fila-v2")

    assert resumo == {"publicados": 1, "pendentes": 0}
    envelope = json.loads(sqs.mensagens[0]["MessageBody"])
    assert envelope["schemaVersion"] == "2"
    assert envelope["evento"] == "operacional.snapshot-ticker.v2"
    assert envelope["dados"]["schemaVersion"] == "operacional.snapshot-ticker.v2"
    assert db.updates == [7]
    assert db.commits == 1
