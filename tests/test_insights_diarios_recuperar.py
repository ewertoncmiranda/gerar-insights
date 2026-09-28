"""Recuperacao dos insights diarios: pregoes perdidos com a maquina desligada."""

import logging
from datetime import date

from app.core.service.insights_diarios_service import InsightsDiariosService, ResumoInsightsDiarios

PREGOES = [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]


class CotahistFake:
    def ultimo_pregao_ate(self, db, limite):
        anteriores = [d for d in PREGOES if d <= limite]
        return anteriores[-1] if anteriores else None

    def pregoes_entre(self, db, depois_de, ate):
        return [d for d in PREGOES if depois_de < d <= ate]


def servico(ultimo_com_insight):
    s = InsightsDiariosService(
        logging.getLogger("teste"),
        cotahist=CotahistFake(),
        insights=object(),
        analisador=object(),
        ultimo_com_insight=lambda db: ultimo_com_insight,
    )
    executados = []

    def executar(db, dia=None):
        executados.append(dia)
        return ResumoInsightsDiarios(data_pregao=dia)

    s.executar = executar
    return s, executados


def test_gera_cada_pregao_posterior_ao_ultimo_insight():
    s, executados = servico(ultimo_com_insight=date(2026, 9, 25))

    resumos = s.recuperar(None, hoje=date(2026, 9, 30))

    assert executados == [date(2026, 9, 28), date(2026, 9, 29), date(2026, 9, 30)]
    assert [r.data_pregao for r in resumos] == executados


def test_sem_pendencia_nao_executa_nada():
    s, executados = servico(ultimo_com_insight=date(2026, 9, 30))

    assert s.recuperar(None, hoje=date(2026, 9, 30)) == []
    assert executados == []


def test_respeita_o_limite_pegando_os_mais_recentes():
    s, executados = servico(ultimo_com_insight=date(2026, 9, 1))

    s.recuperar(None, hoje=date(2026, 9, 30), limite=2)

    assert executados == [date(2026, 9, 29), date(2026, 9, 30)]


def test_base_sem_insight_gera_so_o_ultimo_pregao():
    s, executados = servico(ultimo_com_insight=None)

    s.recuperar(None, hoje=date(2026, 9, 30))

    assert executados == [date(2026, 9, 30)]
