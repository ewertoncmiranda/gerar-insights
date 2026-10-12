from datetime import date, timedelta
from decimal import Decimal
from logging import getLogger

from app.simulador.momento_puro import MomentoPuroService


class Pregao:
    def __init__(self, data, fechamento):
        self.data = data
        self.fechamento = Decimal(fechamento)


def test_momento_puro_sem_dados_suficientes_retorna_none():
    servico = MomentoPuroService(getLogger("test"))

    retorno = servico._calcular_retorno_12_1([], date(2026, 10, 12))

    assert retorno is None


def test_momento_puro_calcula_retorno_12_1():
    servico = MomentoPuroService(getLogger("test"))
    dia = date(2026, 10, 12)
    serie = [
        Pregao(dia - timedelta(days=252), "10"),
        *[Pregao(dia - timedelta(days=251 - i), "11") for i in range(230)],
        Pregao(dia - timedelta(days=21), "15"),
        *[Pregao(dia - timedelta(days=20 - i), "16") for i in range(21)],
    ]

    retorno = servico._calcular_retorno_12_1(serie, dia)

    assert retorno == Decimal("50.0")


def test_momento_puro_quintis_ignoram_sem_retorno():
    servico = MomentoPuroService(getLogger("test"))
    dia = date(2026, 10, 12)
    from app.simulador.momento_puro import ResultadoMomento

    resultados = [
        ResultadoMomento(1, "AAA3", dia, Decimal("1"), None, Decimal("1"), {}),
        ResultadoMomento(2, "BBB3", dia, Decimal("5"), None, Decimal("5"), {}),
        ResultadoMomento(3, "CCC3", dia, None, None, None, {}),
    ]

    servico._calcular_quintis(resultados)

    assert resultados[0].quintil == 1
    assert resultados[1].quintil == 3
    assert resultados[2].quintil is None
