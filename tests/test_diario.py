"""Diario de sinais (app/validacao/diario.py), com repositorio falso em memoria."""

import logging
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from decimal import Decimal

from app.validacao.avaliador import Pregao
from app.validacao.diario import (
    DiarioDeSinais,
    abertura_em_utc,
    extrair_sinal,
    janela_do_sinal,
)

SEXTA = date(2026, 9, 25)
SEGUNDA = date(2026, 9, 28)
VERSAO = "2026.09.26-1"


def detalhes(versao=VERSAO):
    return {
        "versao_regra": versao,
        "resumo": {"nivel_risco": "BAIXO", "confianca_score": 75},
        "contexto_tecnico_serie": {"sinal_momentum": "COMPRA_TECNICA", "sinal_reversao": "NEUTRO_TECNICO"},
    }


class _Sessao:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _RepoFake:
    def __init__(self):
        self.candles: dict[str, list[Pregao]] = {}
        self.insights: list[dict] = []  # {id, simbolo, quando_utc, recomendacao, detalhes}
        self.sinais: list[dict] = []
        self.resultados: dict[tuple[int, int], object] = {}
        self.cdi: dict[date, Decimal] = {}

    # --- leitura de precos
    def fechamentos_do_pregao(self, db, dia):
        return {s: p.fechamento for s, serie in self.candles.items() for p in serie if p.data == dia}

    def _datas(self):
        return sorted({p.data for serie in self.candles.values() for p in serie})

    def ultimo_pregao_ate(self, db, limite):
        datas = [d for d in self._datas() if d <= limite]
        return datas[-1] if datas else None

    def proximo_pregao(self, db, dia):
        datas = [d for d in self._datas() if d > dia]
        return datas[0] if datas else None

    def serie_de_precos(self, db, simbolo, desde):
        return [p for p in self.candles.get(simbolo, []) if p.data >= desde]

    def cdi_diario(self, db, desde):
        return {d: v for d, v in self.cdi.items() if d >= desde}

    # --- insights
    def ultimo_insight(self, db, simbolo, ini, fim):
        candidatos = [
            i for i in self.insights
            if i["simbolo"] == simbolo and ini <= i["quando_utc"] < fim and i["recomendacao"] != "SEM_DADOS"
        ]
        return max(candidatos, key=lambda i: (i["quando_utc"], i["id"]), default=None)

    # --- escrita
    def inserir_sinal(self, db, sinal):
        chave = (sinal["simbolo"], sinal["data_pregao"], sinal["versao_regra"])
        if any((s["simbolo"], s["data_pregao"], s["versao_regra"]) == chave for s in self.sinais):
            return False
        self.sinais.append({**sinal, "id": len(self.sinais) + 1})
        return True

    def sinais_com_horizonte_pendente(self, db, total):
        return [
            s for s in self.sinais
            if sum(1 for (sid, _h) in self.resultados if sid == s["id"]) < total
        ]

    def horizontes_avaliados(self, db, sinal_id):
        return {h for (sid, h) in self.resultados if sid == sinal_id}

    def inserir_resultado(self, db, sinal_id, resultado):
        self.resultados[(sinal_id, resultado.horizonte)] = resultado


def diario(repo, horizontes=(21, 63, 126)):
    sessao = _Sessao()

    @contextmanager
    def fabrica():
        yield sessao

    return DiarioDeSinais(repo, fabrica, logging.getLogger("teste"), horizontes), sessao


def pregoes(simbolo_inicio, n, preco=Decimal("10")):
    dias, dia = [], simbolo_inicio
    while len(dias) < n:
        if dia.weekday() < 5:
            dias.append(dia)
        dia += timedelta(days=1)
    return [Pregao(d, preco, preco) for d in dias]


def insight(id_, simbolo, quando_utc, recomendacao="COMPRA_FORTE", versao=VERSAO):
    return {"id": id_, "simbolo": simbolo, "quando_utc": quando_utc,
            "recomendacao": recomendacao, "detalhes": detalhes(versao)}


# --- regras puras ------------------------------------------------------------

def test_abertura_da_b3_em_utc():
    assert abertura_em_utc(SEXTA) == datetime(2026, 9, 25, 13, 0)


def test_janela_vai_da_abertura_do_pregao_ate_a_abertura_do_seguinte():
    inicio, fim = janela_do_sinal(SEXTA, SEGUNDA, agora_utc=datetime(2026, 9, 30))
    assert inicio == datetime(2026, 9, 25, 13, 0)
    assert fim == datetime(2026, 9, 28, 13, 0)


def test_sem_pregao_seguinte_a_janela_termina_agora():
    agora = datetime(2026, 9, 25, 22, 0)
    assert janela_do_sinal(SEXTA, None, agora)[1] == agora


def test_insight_sem_versao_de_regra_nao_vira_sinal():
    assert extrair_sinal({"resumo": {}}) is None
    assert extrair_sinal(detalhes())["sinal_momentum"] == "COMPRA_TECNICA"


# --- registrar ---------------------------------------------------------------

def test_registra_o_ultimo_insight_da_janela_e_o_fechamento_oficial():
    repo = _RepoFake()
    repo.candles["PETR4"] = [Pregao(SEXTA, Decimal("48.21"), Decimal("48.00"))]
    repo.insights = [
        insight(1, "PETR4", datetime(2026, 9, 25, 14, 0), "MANTER"),          # durante o pregao
        insight(2, "PETR4", datetime(2026, 9, 26, 20, 0), "COMPRA_MODERADA"),  # sabado, preco de sexta
    ]
    d, sessao = diario(repo)

    resumo = d.registrar(SEXTA, agora_utc=datetime(2026, 9, 26, 21, 0))

    assert resumo.registrados == ["PETR4"]
    [sinal] = repo.sinais
    assert sinal["recomendacao"] == "COMPRA_MODERADA"
    assert sinal["insight_id"] == 2
    assert sinal["preco_fechamento"] == Decimal("48.00")
    assert sinal["versao_regra"] == VERSAO
    assert sessao.commits == 1


def test_insight_da_manha_seguinte_apos_a_abertura_nao_entra():
    """Depois das 10h do pregao seguinte o insight ja usa preco novo."""
    repo = _RepoFake()
    repo.candles["PETR4"] = [Pregao(SEXTA, Decimal(48), Decimal(48)), Pregao(SEGUNDA, Decimal(49), Decimal(49))]
    repo.insights = [insight(1, "PETR4", datetime(2026, 9, 28, 13, 30))]  # segunda 10h30 BRT
    d, _ = diario(repo)

    resumo = d.registrar(SEXTA, agora_utc=datetime(2026, 9, 28, 22, 0))

    assert resumo.sem_insight == ["PETR4"]
    assert repo.sinais == []


def test_registrar_duas_vezes_nao_duplica_nem_altera():
    repo = _RepoFake()
    repo.candles["PETR4"] = [Pregao(SEXTA, Decimal(48), Decimal(48))]
    repo.insights = [insight(1, "PETR4", datetime(2026, 9, 25, 21, 0))]
    d, _ = diario(repo)

    d.registrar(SEXTA, datetime(2026, 9, 25, 22, 0))
    repo.insights.append(insight(2, "PETR4", datetime(2026, 9, 25, 21, 30), "VENDA_VALUATION"))
    segundo = d.registrar(SEXTA, datetime(2026, 9, 25, 23, 0))

    assert segundo.ja_existiam == ["PETR4"]
    assert [s["recomendacao"] for s in repo.sinais] == ["COMPRA_FORTE"]


def test_versao_nova_de_regra_gera_sinal_novo_no_mesmo_pregao():
    repo = _RepoFake()
    repo.candles["PETR4"] = [Pregao(SEXTA, Decimal(48), Decimal(48))]
    repo.insights = [insight(1, "PETR4", datetime(2026, 9, 25, 21, 0))]
    d, _ = diario(repo)
    d.registrar(SEXTA, datetime(2026, 9, 25, 22, 0))

    repo.insights.append(insight(2, "PETR4", datetime(2026, 9, 25, 21, 30), versao="2026.10.01-1"))
    d.registrar(SEXTA, datetime(2026, 9, 25, 23, 0))

    assert sorted(s["versao_regra"] for s in repo.sinais) == ["2026.09.26-1", "2026.10.01-1"]


def test_sem_candle_no_dia_nao_registra_nada():
    """Candle ausente = nao houve pregao (feriado, fim de semana)."""
    repo = _RepoFake()
    repo.insights = [insight(1, "PETR4", datetime(2026, 9, 26, 20, 0))]
    d, _ = diario(repo)
    assert d.registrar(date(2026, 9, 26), datetime(2026, 9, 26, 21, 0)).registrados == []


def test_sem_data_usa_o_ultimo_pregao_ate_hoje_em_brasilia():
    """Sabado 00h30 UTC ainda e sexta 21h30 em Brasilia."""
    repo = _RepoFake()
    repo.candles["PETR4"] = [Pregao(SEXTA, Decimal(48), Decimal(48))]
    repo.insights = [insight(1, "PETR4", datetime(2026, 9, 25, 23, 0))]
    d, _ = diario(repo)

    resumo = d.registrar(None, agora_utc=datetime(2026, 9, 26, 0, 30))

    assert resumo.data_pregao == SEXTA
    assert resumo.registrados == ["PETR4"]


def test_benchmark_nao_vira_sinal_e_insight_sem_versao_e_contado():
    repo = _RepoFake()
    repo.candles["BOVA11"] = [Pregao(SEXTA, Decimal(130), Decimal(130))]
    repo.candles["VALE3"] = [Pregao(SEXTA, Decimal(60), Decimal(60))]
    repo.insights = [insight(1, "VALE3", datetime(2026, 9, 25, 21, 0), versao=None)]
    d, _ = diario(repo)

    resumo = d.registrar(SEXTA, datetime(2026, 9, 25, 22, 0))

    assert resumo.sem_versao == ["VALE3"]
    assert repo.sinais == []


# --- avaliar ------------------------------------------------------------------

def test_avalia_so_os_horizontes_que_ja_venceram():
    repo = _RepoFake()
    repo.candles["PETR4"] = pregoes(SEXTA, 30)  # 29 pregoes depois do sinal: so o de 21 vence
    repo.sinais = [{"id": 1, "simbolo": "PETR4", "data_pregao": SEXTA, "recomendacao": "COMPRA_FORTE"}]
    d, sessao = diario(repo)

    resumo = d.avaliar()

    assert set(repo.resultados) == {(1, 21)}
    assert resumo.resultados_gravados == 1
    assert resumo.sinais_pendentes == 1
    assert sessao.commits == 1


def test_avaliar_de_novo_nao_regrava_o_horizonte_ja_avaliado():
    repo = _RepoFake()
    repo.candles["PETR4"] = pregoes(SEXTA, 30)
    repo.sinais = [{"id": 1, "simbolo": "PETR4", "data_pregao": SEXTA, "recomendacao": "COMPRA_FORTE"}]
    d, _ = diario(repo)

    d.avaliar()
    segundo = d.avaliar()

    assert segundo.resultados_gravados == 0
    assert len(repo.resultados) == 1


def test_avaliacao_usa_bova11_e_cdi_quando_existem():
    repo = _RepoFake()
    repo.candles["PETR4"] = pregoes(SEXTA, 25, Decimal("10"))
    repo.candles["BOVA11"] = pregoes(SEXTA, 25, Decimal("130"))
    repo.cdi = {p.data: Decimal("0.05") for p in repo.candles["PETR4"]}
    repo.sinais = [{"id": 1, "simbolo": "PETR4", "data_pregao": SEXTA, "recomendacao": "COMPRA_FORTE"}]
    d, _ = diario(repo, horizontes=(21,))

    d.avaliar()

    resultado = repo.resultados[(1, 21)]
    assert resultado.retorno_bova11 == Decimal("0")
    assert resultado.retorno_cdi > 0
    assert resultado.excesso_cdi < 0  # preco parado perde para o CDI
