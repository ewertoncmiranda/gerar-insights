from datetime import date

from app.operacional.consenso import montar_consenso
from app.operacional.elegibilidade import Elegibilidade, Motivo
from app.operacional.snapshot import EntradaSnapshot, faixa_confianca, montar_snapshot
from app.operacional.timeline import montar_timeline
from app.operacional.v2 import (
    OperabilidadeV2,
    RepositorioOperabilidadeV2,
    _motivos_bloqueio,
    _status_operacional_ticker,
)


def test_consenso_separa_sinal_positivo_de_operabilidade_bloqueada():
    consenso = montar_consenso(
        sinal_principal="COMPRA_MODERADA",
        sinal_momentum="COMPRA_TECNICA",
        sinal_reversao="NEUTRO_TECNICO",
        opiniao_ia="SINAL_POSITIVO",
        status_operacional="EM_OBSERVACAO",
        motivos_bloqueio=[{"codigo": "SEM_FUNDAMENTO_VIGENTE"}],
    )

    assert consenso.direcao_analitica == "POSITIVA"
    assert consenso.operabilidade == "NAO_OPERAVEL"
    assert consenso.divergencias[0]["codigo"] == "SINAL_POSITIVO_NAO_OPERAVEL"


def test_snapshot_sem_curva_real_mantem_confianca_nao_calibrada_e_tese_com_aviso():
    snapshot = montar_snapshot(
        EntradaSnapshot(
            simbolo="WEGE3",
            data_pregao=date(2026, 10, 9),
            versao_regra="OPR-2026.10.10-1",
            status_sistema="EM_OBSERVACAO",
            status_operacional="EM_OBSERVACAO",
            faixa_liquidez="ALTA",
            sinal_principal="COMPRA_MODERADA",
            setor_grupo="PETROLEO",
            confianca_score=92,
            confianca_tem_evidencia=False,
        )
    )

    assert snapshot["confiancaFaixa"] == "NAO_CALIBRADA"
    assert snapshot["statusSistema"] == "EM_OBSERVACAO"
    assert snapshot["setorGrupo"] == "PETROLEO"
    assert snapshot["elegibilidadeTicker"]["elegivel"] is True
    assert snapshot["consenso"]["direcaoAnalitica"] == "POSITIVA"
    assert "nao e recomendacao" in snapshot["tese"]["aviso"].lower()
    assert any(r["codigo"] == "CONFIANCA_NAO_CALIBRADA" for r in snapshot["tese"]["riscos"])


def test_faixa_confianca_so_classifica_com_evidencia_real():
    assert faixa_confianca(95, False) == "NAO_CALIBRADA"
    assert faixa_confianca(95, True) == "ALTA"
    assert faixa_confianca(70, True) == "MEDIA"
    assert faixa_confianca(40, True) == "BAIXA"


def test_timeline_deduplica_ordena_e_classifica_eventos():
    eventos = [
        {
            "event_id": "e2",
            "tipo": "POSICAO_FECHADA",
            "simbolo": "PETR4",
            "data_pregao": date(2026, 10, 10),
            "payload": {"motivo_saida": "STOP"},
        },
        {
            "event_id": "e1",
            "tipo": "BLOQUEIO_DADO",
            "simbolo": "PETR4",
            "data_pregao": date(2026, 10, 9),
            "payload": {"motivos": [{"codigo": "SEM_FUNDAMENTO_VIGENTE"}]},
        },
        {
            "event_id": "e1",
            "tipo": "BLOQUEIO_DADO",
            "simbolo": "PETR4",
            "data_pregao": date(2026, 10, 9),
            "payload": {"motivos": [{"codigo": "SEM_FUNDAMENTO_VIGENTE"}]},
        },
    ]

    timeline = montar_timeline(eventos)

    assert [e["eventId"] for e in timeline] == ["e1", "e2"]
    assert timeline[0]["severidade"] == "ATENCAO"
    assert timeline[0]["categoria"] == "DADO"
    assert timeline[1]["titulo"] == "Posicao simulada fechada (STOP)"


def test_motivos_de_bloqueio_refletem_o_pregao_atual_e_nao_eventos_antigos():
    motivos = _motivos_bloqueio([
        {"tipo": "BLOQUEIO_DADO", "data_pregao": date(2026, 10, 9),
         "payload": {"motivos": [{"codigo": "SEM_FUNDAMENTO_VIGENTE"}]}},
        {"tipo": "BLOQUEIO_LIQUIDEZ", "data_pregao": date(2026, 10, 8),
         "payload": {"motivos": [{"codigo": "VOLUME_BAIXO"}]}},
    ], date(2026, 10, 9))

    assert [motivo["codigo"] for motivo in motivos] == ["SEM_FUNDAMENTO_VIGENTE"]


def test_status_operacional_do_ticker_separa_trava_global_de_elegibilidade():
    elegivel = Elegibilidade("PETR4", date(2026, 10, 9), True, "ALTA")
    bloqueado = Elegibilidade("ABCD3", date(2026, 10, 9), False, "INSUFICIENTE",
                              bloqueios=[Motivo("VOLUME_BAIXO", "volume baixo")])

    assert _status_operacional_ticker("PAPER_TRADING_ELEGIVEL", elegivel) == "PAPER_TRADING_ELEGIVEL"
    assert _status_operacional_ticker("EM_OBSERVACAO", elegivel) == "EM_OBSERVACAO"
    assert _status_operacional_ticker("PAPER_TRADING_ELEGIVEL", bloqueado) == "BLOQUEADO"
    assert _status_operacional_ticker("BLOQUEADO", elegivel) == "BLOQUEADO"


class RepoFake:
    def __init__(self, disponivel=True):
        self.disponivel = disponivel
        self.snapshots = []
        self.timelines = []

    def tabelas_v2_disponiveis(self, db):
        return self.disponivel

    def status_do_pregao(self, db, data_pregao, versao):
        return "EM_OBSERVACAO"

    def liquidez(self, db, data_pregao):
        return {"PETR4": {"volume_financeiro_medio_63d": 10_000_000, "negocios_medio_63d": 5_000}}

    def setores(self, db):
        return {"PETR4": "PETROLEO"}

    def elegibilidades(self, db, data_pregao, versao):
        return {"PETR4": Elegibilidade("PETR4", data_pregao, True, "MEDIA",
                                       ressalvas=[Motivo("SPREAD_AUSENTE", "sem spread")])}

    def insights(self, db, data_pregao):
        return {"PETR4": {"sinal_principal": "COMPRA_MODERADA", "confianca_score": 88}}

    def opinioes(self, db, data_pregao):
        return {"PETR4": "SINAL_POSITIVO"}

    def posicoes(self, db, versao):
        return {}

    def eventos(self, db, data_pregao, versao):
        return {"PETR4": [{"event_id": "b1", "tipo": "BLOQUEIO_DADO", "simbolo": "PETR4",
                           "data_pregao": data_pregao, "payload": {"motivos": [{"codigo": "SEM_DADO"}]}}]}

    def amostras_confianca(self, db, versao):
        return []

    def salvar_snapshot(self, db, snapshot):
        self.snapshots.append(snapshot)

    def salvar_timeline(self, db, simbolo, versao, itens):
        self.timelines.append((simbolo, itens))


def test_operabilidade_v2_gera_snapshot_e_timeline_com_repo_disponivel():
    repo = RepoFake()
    total = OperabilidadeV2(repo).atualizar_pregao(None, date(2026, 10, 9), "OPR-2026.10.10-1")

    assert total == 1
    assert repo.snapshots[0]["simbolo"] == "PETR4"
    assert repo.snapshots[0]["statusSistema"] == "EM_OBSERVACAO"
    assert repo.snapshots[0]["statusOperacional"] == "EM_OBSERVACAO"
    assert repo.snapshots[0]["faixaLiquidez"] == "MEDIA"
    assert repo.snapshots[0]["elegibilidadeTicker"]["ressalvas"][0]["codigo"] == "SPREAD_AUSENTE"
    assert repo.snapshots[0]["confiancaFaixa"] == "NAO_CALIBRADA"
    assert repo.timelines[0][0] == "PETR4"


def test_operabilidade_v2_noop_sem_tabelas_v2():
    repo = RepoFake(disponivel=False)
    total = OperabilidadeV2(repo).atualizar_pregao(None, date(2026, 10, 9), "OPR-2026.10.10-1")

    assert total == 0
    assert repo.snapshots == []


class DbCapture:
    def __init__(self):
        self.execucoes = []

    def execute(self, comando, parametros):
        self.execucoes.append((str(comando), parametros))


def test_persistencia_snapshot_usa_colunas_da_migration_v25_v26():
    db = DbCapture()
    snapshot = montar_snapshot(EntradaSnapshot(
        simbolo="PETR4",
        data_pregao=date(2026, 10, 9),
        versao_regra="OPR-2026.10.10-1",
        status_sistema="EM_OBSERVACAO",
        status_operacional=None,
        faixa_liquidez="MEDIA",
        setor_grupo="PETROLEO",
    ))

    RepositorioOperabilidadeV2().salvar_snapshot(db, snapshot)

    sql, parametros = db.execucoes[0]
    assert "status_sistema" in sql
    assert "status_operacional" in sql
    assert "consenso_json" in sql and "tese_json" in sql
    assert "setor_grupo" in sql
    assert parametros["status"] == "EM_OBSERVACAO"
    assert parametros["setor"] == "PETROLEO"
    assert parametros["status_operacional"] is None


def test_persistencia_timeline_normaliza_alerta_e_prepara_colunas_da_migration():
    db = DbCapture()
    item = montar_timeline([{
        "tipo": "BLOQUEIO_DADO",
        "simbolo": "PETR4",
        "data_pregao": date(2026, 10, 9),
        "payload": {"motivos": [{"codigo": "SEM_DADO"}]},
    }])[0]

    RepositorioOperabilidadeV2().salvar_timeline(db, "PETR4", "OPR-2026.10.10-1", [item])

    sql, parametros = db.execucoes[0]
    assert "data_pregao" in sql and "data_evento" in sql and "ocorrido_em" in sql
    assert "tipo_evento" in sql and "categoria" in sql and "codigo" in sql
    assert len(parametros["event_id"]) == 36
    assert parametros["tipo"] == "BLOQUEIO_DADO"
    assert parametros["categoria"] == "DADO"
    assert parametros["severidade"] == "ATENCAO"
    assert '"versaoRegra": "OPR-2026.10.10-1"' in parametros["payload"]
