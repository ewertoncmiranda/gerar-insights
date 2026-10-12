from datetime import date
from decimal import Decimal
from logging import getLogger

from app.simulador import __main__ as etapa_simulador
from app.simulador.baixo_spread import BaixoSpreadService


class ResultadoExecucao:
    def __init__(self, valor=None):
        self._valor = valor

    def scalar(self):
        return self._valor


class SessaoFake:
    def __init__(self, existente=None):
        self.existente = existente
        self.execucoes = []

    def execute(self, consulta, parametros):
        self.execucoes.append((str(consulta), parametros))
        return ResultadoExecucao(self.existente if len(self.execucoes) == 1 else None)


class ContextoSessaoFake:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *_):
        return None


def test_baixo_spread_sem_spread_nao_gera_score():
    servico = BaixoSpreadService(getLogger("test"))

    resultado = servico._resultado_para(
        {"id": 1, "simbolo": "PETR4"},
        date(2026, 10, 12),
        None,
        Decimal("25"),
    )

    assert resultado.score is None
    assert resultado.quintil is None
    assert resultado.parametros_json["erro"] == "spread_estimado_ausente"


def test_baixo_spread_sem_spread_grava_resultado_nulo():
    servico = BaixoSpreadService(getLogger("test"))
    resultado = servico._resultado_para(
        {"id": 1, "simbolo": "PETR4"},
        date(2026, 10, 12),
        None,
        Decimal("25"),
    )
    db = SessaoFake()

    gravou = servico._gravar_resultado(db, resultado)

    assert gravou is True
    assert len(db.execucoes) == 2
    parametros_insert = db.execucoes[1][1]
    assert parametros_insert["quintil"] is None
    assert parametros_insert["score"] is None


def test_baixo_spread_nao_duplica_resultado_existente():
    servico = BaixoSpreadService(getLogger("test"))
    resultado = servico._resultado_para(
        {"id": 1, "simbolo": "PETR4"},
        date(2026, 10, 12),
        Decimal("0.01"),
        None,
    )
    db = SessaoFake(existente=123)

    gravou = servico._gravar_resultado(db, resultado)

    assert gravou is False
    assert len(db.execucoes) == 1


def test_baixo_spread_menor_spread_fica_em_quintil_melhor():
    servico = BaixoSpreadService(getLogger("test"))
    dia = date(2026, 10, 12)
    resultados = [
        servico._resultado_para({"id": 1, "simbolo": "AAA3"}, dia, Decimal("0.0300"), None),
        servico._resultado_para({"id": 2, "simbolo": "BBB3"}, dia, Decimal("0.0200"), None),
        servico._resultado_para({"id": 3, "simbolo": "CCC3"}, dia, Decimal("0.0100"), None),
        servico._resultado_para({"id": 4, "simbolo": "DDD3"}, dia, Decimal("0.0400"), None),
        servico._resultado_para({"id": 5, "simbolo": "EEE3"}, dia, Decimal("0.0500"), None),
    ]

    servico._calcular_quintis(resultados)

    por_simbolo = {r.simbolo: r.quintil for r in resultados}
    assert por_simbolo["EEE3"] == 1
    assert por_simbolo["CCC3"] == 5


def test_baixo_spread_margem_graham_entra_so_como_desempate():
    servico = BaixoSpreadService(getLogger("test"))
    dia = date(2026, 10, 12)
    sem_margem = servico._resultado_para({"id": 1, "simbolo": "AAA3"}, dia, Decimal("0.0100"), None)
    com_margem = servico._resultado_para({"id": 2, "simbolo": "BBB3"}, dia, Decimal("0.0100"), Decimal("50"))

    assert com_margem.score > sem_margem.score
    assert abs(com_margem.score - sem_margem.score) < Decimal("0.001")


def test_etapa_diaria_executa_as_duas_estrategias_sem_argumentos(monkeypatch):
    db = object()
    chamadas = []

    class ConfigFake:
        def session(self):
            return ContextoSessaoFake(db)

    class ServicoFake:
        def __init__(self, nome):
            self.nome = nome

        def executar(self, sessao):
            chamadas.append((self.nome, sessao))
            return []

    monkeypatch.setattr(etapa_simulador, "setup_logger", lambda: getLogger("test"))
    monkeypatch.setattr(etapa_simulador, "ConfigDatabase", ConfigFake)
    monkeypatch.setattr(etapa_simulador, "MomentoPuroService", lambda _logger: ServicoFake("momento"))
    monkeypatch.setattr(etapa_simulador, "BaixoSpreadService", lambda _logger: ServicoFake("spread"))

    codigo = etapa_simulador.main()

    assert codigo == 0
    assert chamadas == [("momento", db), ("spread", db)]
