"""Diario no preco oficial: so insight do COTAHIST e recuperacao de dia parcial."""

from datetime import date, datetime

from app.validacao.repositorio_diario_oficial import RepositorioDiarioOficial

PREGOES = [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28)]


class Resultado:
    def __init__(self, valor):
        self._valor = valor

    def scalar(self):
        return self._valor

    def first(self):
        return self._valor


class DbFake:
    def __init__(self, valor):
        self.valor = valor
        self.consultas = []

    def execute(self, consulta, parametros=None):
        self.consultas.append(str(consulta))
        return Resultado(self.valor)


class CotahistFake:
    def pregoes_entre(self, db, depois_de, ate):
        return [d for d in PREGOES if depois_de < d <= ate]

    def ultimo_pregao_ate(self, db, limite):
        return max(d for d in PREGOES if d <= limite)


def test_sem_insight_do_cotahist_nao_cai_para_o_intradiario_da_brapi():
    # AXIA3 em 28/09: so havia o insight da BRAPI, que antes virava sinal.
    repo = RepositorioDiarioOficial(cotahist=CotahistFake())
    db = DbFake(valor=None)

    insight = repo.ultimo_insight(
        db, "AXIA3", datetime(2026, 9, 28, 13), datetime(2026, 9, 29, 13), data_pregao=date(2026, 9, 28)
    )

    assert insight is None
    assert len(db.consultas) == 1  # nenhuma segunda busca pela janela de horario


def test_revisita_os_ultimos_pregoes_ja_registrados():
    # 28/09 registrado pela metade: MAX(data_pregao) = 28/09 o escondia.
    repo = RepositorioDiarioOficial(cotahist=CotahistFake())
    db = DbFake(valor=date(2026, 9, 24))  # o mais antigo dos ultimos registrados

    pregoes = repo.pregoes_a_registrar(db, ate=date(2026, 9, 28))

    assert pregoes == [date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 28)]


def test_diario_vazio_registra_so_o_ultimo_pregao():
    repo = RepositorioDiarioOficial(cotahist=CotahistFake())

    assert repo.pregoes_a_registrar(DbFake(valor=None), ate=date(2026, 9, 28)) == [date(2026, 9, 28)]
