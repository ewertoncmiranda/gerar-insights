import logging
from datetime import date

from app.opiniao import gerar
from app.opiniao.cliente_ia import Identidade
from app.opiniao.regras import HORIZONTES, montar_dossie
from app.opiniao.reserva import resposta_de_regra
from tests.opiniao.test_cliente_ia import _detalhes


HOJE = date(2026, 10, 8)
LOG = logging.getLogger("teste")


class BancoFake:
    def commit(self):
        pass


class RepoLoteFake:
    def __init__(self, simbolos):
        self.simbolos = simbolos
        self.gravados = []
        self.reaproveitar = {}

    def ultimo_pregao_com_insight(self, db):
        return HOJE

    def simbolos_do_pregao(self, db, data_pregao):
        return self.simbolos

    def favoritos_para_gemini(self, db):
        return self.simbolos

    def monitorados_ativos(self, db):
        return []

    def com_mudanca_de_opiniao(self, db, data_pregao, simbolos):
        return []

    def com_variacao_incomum(self, db, data_pregao, simbolos):
        return []

    def por_liquidez(self, db, simbolos):
        return []

    def ultimo_insight(self, db, simbolo, data_pregao):
        return {"id": len(simbolo), "detalhes": _detalhes()}

    def fatores_recentes(self, db, simbolo):
        return []

    def fatos_relevantes_30d(self, db, simbolo, data_pregao):
        return 0

    def ja_existe(self, db, simbolo, data_pregao, horizonte, modelo, versao):
        return False

    def gravar(self, db, registro):
        self.gravados.append(registro)
        return True

    def opinioes_modelo_por_hash(self, db, simbolo, data_pregao, dossie_hash):
        return self.reaproveitar.get(simbolo, [])


class ServicoAtivoFake:
    def __init__(self, cota_falsa_no_ativo=None):
        self.pedidos = []
        self.cota_falsa_no_ativo = cota_falsa_no_ativo

    def opinar_ativo(self, pedido):
        self.pedidos.append(pedido)
        dossie, _ = montar_dossie(_detalhes(), [], 0, HOJE)
        return {
            "cota": {"gemini_disponivel": len(self.pedidos) != self.cota_falsa_no_ativo},
            "itens": [
                {**resposta_de_regra(dossie[h]), "horizonte_pregoes": h, "modelo": "gemini", "origem": "MODELO"}
                for h in HORIZONTES
            ],
        }


def test_lote_limita_chamadas_e_restante_vai_por_regra(monkeypatch):
    repo = RepoLoteFake(["AAA3", "BBB4", "CCC3"])
    monkeypatch.setattr(gerar, "RepositorioOpiniao", lambda: repo)
    resumo = gerar.executar(
        BancoFake(), LOG, HOJE, None, ServicoAtivoFake(), lote_max_gemini=2, sem_limite=False
    )
    assert resumo.priorizados == 2 and resumo.chamadas == 2
    assert [r["modelo"] for r in repo.gravados].count("regra") == 3


def test_sem_limite_envia_todos(monkeypatch):
    repo = RepoLoteFake(["AAA3", "BBB4", "CCC3"])
    servico = ServicoAtivoFake()
    monkeypatch.setattr(gerar, "RepositorioOpiniao", lambda: repo)
    resumo = gerar.executar(
        BancoFake(), LOG, HOJE, None, servico, lote_max_gemini=1, sem_limite=True
    )
    assert resumo.priorizados == 3 and resumo.chamadas == 3 and len(servico.pedidos) == 3


def test_cota_indisponivel_para_chamadas_seguintes(monkeypatch):
    repo = RepoLoteFake(["AAA3", "BBB4", "CCC3"])
    servico = ServicoAtivoFake(cota_falsa_no_ativo=2)
    monkeypatch.setattr(gerar, "RepositorioOpiniao", lambda: repo)
    resumo = gerar.executar(
        BancoFake(), LOG, HOJE, None, servico, lote_max_gemini=3, sem_limite=False
    )
    assert resumo.chamadas == 2 and resumo.sem_cota == 1


def test_hash_reaproveitado_nao_chama_servico(monkeypatch):
    repo = RepoLoteFake(["AAA3"])
    repo.reaproveitar["AAA3"] = [
        {
            "simbolo": "AAA3", "data_pregao": HOJE, "horizonte_pregoes": h,
            "opiniao": "SINAL_NEUTRO", "risco": "RISCO_MEDIO", "justificativa_json": "[]",
            "invalida_json": "[]", "dados_ausentes_json": "[]", "evidencias_json": "[]",
            "modelo": "gemini", "versao_prompt": "skills@abc", "versao_regra": "v",
            "origem": "MODELO", "tentativas": 0, "dossie_hash": "x", "insight_id": 1,
        }
        for h in HORIZONTES
    ]
    servico = ServicoAtivoFake()
    gerar.gerar_do_ativo(
        BancoFake(), repo, "AAA3", HOJE, servico, Identidade("gemini", "skills@abc"), LOG, gerar.Resumo()
    )
    assert not servico.pedidos and len(repo.gravados) == 3
