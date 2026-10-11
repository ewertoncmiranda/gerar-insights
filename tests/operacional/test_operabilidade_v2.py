from datetime import date

from app.operacional.consenso import montar_consenso
from app.operacional.snapshot import EntradaSnapshot, faixa_confianca, montar_snapshot
from app.operacional.timeline import montar_timeline
from app.operacional.v2 import OperabilidadeV2


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
            status_operacional="EM_OBSERVACAO",
            faixa_liquidez="ALTA",
            sinal_principal="COMPRA_MODERADA",
            confianca_score=92,
            confianca_tem_evidencia=False,
        )
    )

    assert snapshot["confiancaFaixa"] == "NAO_CALIBRADA"
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
    assert timeline[0]["severidade"] == "ALERTA"
    assert timeline[1]["titulo"] == "Posicao simulada fechada (STOP)"


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
    assert repo.snapshots[0]["faixaLiquidez"] == "ALTA"
    assert repo.snapshots[0]["confiancaFaixa"] == "NAO_CALIBRADA"
    assert repo.timelines[0][0] == "PETR4"


def test_operabilidade_v2_noop_sem_tabelas_v2():
    repo = RepoFake(disponivel=False)
    total = OperabilidadeV2(repo).atualizar_pregao(None, date(2026, 10, 9), "OPR-2026.10.10-1")

    assert total == 0
    assert repo.snapshots == []
