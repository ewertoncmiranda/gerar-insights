from datetime import date

from app.opiniao.prioridade import priorizar


class RepoPrioridadeFake:
    def favoritos_para_gemini(self, db):
        return ["AAA3", "BBB4"]

    def monitorados_ativos(self, db):
        return ["BBB4", "CCC3"]

    def com_mudanca_de_opiniao(self, db, data_pregao, simbolos):
        return ["DDD3", "AAA3"]

    def com_variacao_incomum(self, db, data_pregao, simbolos):
        return ["EEE3", "CCC3"]

    def por_liquidez(self, db, simbolos):
        return ["FFF3", "DDD3", "GGG3"]


def test_prioridade_respeita_os_cinco_criterios_sem_repetir_e_com_corte():
    simbolos = ["AAA3", "BBB4", "CCC3", "DDD3", "EEE3", "FFF3", "GGG3", "HHH3"]
    assert priorizar(RepoPrioridadeFake(), None, date(2026, 10, 8), simbolos, limite=6) == [
        "AAA3", "BBB4", "CCC3", "DDD3", "EEE3", "FFF3"
    ]


def test_prioridade_sem_limite_mantem_todos_os_simbolos():
    simbolos = ["AAA3", "BBB4", "CCC3", "DDD3", "EEE3", "FFF3", "GGG3", "HHH3"]
    assert priorizar(RepoPrioridadeFake(), None, date(2026, 10, 8), simbolos, limite=None)[-1] == "HHH3"
