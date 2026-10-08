"""TASK-IA-03: o worker chama o servico de IA por HTTP (CTR-IA-01) e grava a resposta.

Servidor HTTP local de verdade (thread) para o cliente; repositorio e banco falsos para a
orquestracao. Aceite: com o servico fora do ar a linha REGRA sai igual a do `--sem-llm`.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app.opiniao import gerar
from app.opiniao.cliente_ia import (
    ErroDoServicoIA,
    Identidade,
    RotaNaoEncontrada,
    ServicoIA,
    pedido_do_ativo,
    pedido_do_dossie,
)
from app.opiniao.regras import CURTO, MEDIO, NEGATIVO, montar_dossie
from app.opiniao.reserva import resposta_de_regra

HOJE = date(2026, 10, 6)
LOG = logging.getLogger("teste")


def _detalhes():
    return {
        "versao_regra": "2026.09.27-3",
        "resumo": {"recomendacao": "VENDA_VALUATION", "nivel_risco": "ALTO"},
        "valuation": {"cenarios_graham": {"base": {"margem_seguranca_percent": -458.0}},
                      "classificacao_earnings_yield": "MUITO_BAIXO", "classificacao_pl": "EXIGENTE"},
        "contexto_tecnico_serie": {"sinal_momentum": "NEUTRO_TECNICO", "sinal_reversao": "NEUTRO_TECNICO"},
    }


def _dossie():
    dossie, ausentes = montar_dossie(_detalhes(), [], 0, HOJE)
    return dossie, ausentes


# ---------------------------------------------------------------- servidor de teste

class _Estado:
    def __init__(self):
        self.recebidos: list[dict] = []
        self.status_opiniao = 200
        self.status_ativo = 200
        self.resposta: dict | None = None
        self.resposta_ativo: dict | None = None


def _servidor(estado: _Estado):
    class Manipulador(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencia o stderr do teste
            pass

        def _json(self, codigo: int, corpo: dict):
            dados = json.dumps(corpo).encode()
            self.send_response(codigo)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            if self.path == "/saude":
                self._json(200, {"status": "OK", "modelo": "qwen2.5:1.5b-instruct", "skills_versao": "skills@abc"})
            else:
                self._json(404, {})

        def do_POST(self):
            corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            estado.recebidos.append(corpo)
            if self.path == "/opiniao/ativo":
                if estado.status_ativo != 200:
                    self._json(estado.status_ativo, {"detail": "erro de teste"})
                    return
                self._json(200, estado.resposta_ativo)
                return
            if estado.status_opiniao != 200:
                self._json(estado.status_opiniao, {"detail": "erro de teste"})
                return
            self._json(200, estado.resposta)

    servidor = HTTPServer(("127.0.0.1", 0), Manipulador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor


@pytest.fixture()
def servico():
    estado = _Estado()
    servidor = _servidor(estado)
    yield ServicoIA(f"http://127.0.0.1:{servidor.server_port}", timeout_s=5), estado
    servidor.shutdown()


# ---------------------------------------------------------------- cliente

class TestCliente:
    def test_pedido_leva_evidencias_permitidas_e_risco_do_dossie(self):
        dossie, ausentes = _dossie()
        d = dossie[MEDIO]
        pedido = pedido_do_dossie("PETR4", HOJE, d, ausentes, "2026.09.27-3")
        assert pedido["permitidas"] == list(d.permitidas) and pedido["permitidas"][0] == NEGATIVO
        assert pedido["risco_calculado"] == d.risco
        assert pedido["horizonte_pregoes"] == 63 and pedido["data_pregao"] == "2026-10-06"
        assert {e["id"] for e in pedido["evidencias"]} == {e.id for e in d.evidencias}
        assert set(pedido["evidencias"][0]) == {"id", "rotulo", "valor", "direcao"}

    def test_identidade_vem_da_saude(self, servico):
        cliente, _ = servico
        assert cliente.identidade() == Identidade("qwen2.5:1.5b-instruct", "skills@abc")

    def test_opinar_envia_o_pedido_e_devolve_a_resposta(self, servico):
        cliente, estado = servico
        dossie, ausentes = _dossie()
        estado.resposta = {**resposta_de_regra(dossie[MEDIO]), "dados_ausentes": [], "fontes": [],
                           "modelo": "qwen2.5:1.5b-instruct", "skills_versao": "skills@abc", "origem": "MODELO"}
        resposta = cliente.opinar(pedido_do_dossie("PETR4", HOJE, dossie[MEDIO], ausentes, "v"))
        assert resposta["origem"] == "MODELO"
        assert estado.recebidos[0]["simbolo"] == "PETR4"

    def test_opinar_ativo_envia_tres_horizontes_em_uma_requisicao(self, servico):
        cliente, estado = servico
        dossie, ausentes = _dossie()
        estado.resposta_ativo = {
            "skills_versao": "skills@abc",
            "cota": {"gemini_disponivel": True},
            "itens": [
                {**resposta_de_regra(d), "horizonte_pregoes": h, "modelo": "gemini", "origem": "MODELO"}
                for h, d in dossie.items()
            ],
        }
        resposta = cliente.opinar_ativo(pedido_do_ativo("PETR4", HOJE, dossie, ausentes, "v"))
        assert len(estado.recebidos) == 1
        assert [h["horizonte_pregoes"] for h in estado.recebidos[0]["horizontes"]] == [21, 63, 126]
        assert len(resposta["itens"]) == 3 and resposta["cota"]["gemini_disponivel"] is True

    def test_opinar_ativo_404_sinaliza_fallback_v1(self, servico):
        cliente, estado = servico
        estado.status_ativo = 404
        dossie, ausentes = _dossie()
        with pytest.raises(RotaNaoEncontrada):
            cliente.opinar_ativo(pedido_do_ativo("PETR4", HOJE, dossie, ausentes, "v"))

    def test_erro_http_vira_erro_do_servico(self, servico):
        cliente, estado = servico
        estado.status_opiniao = 422
        dossie, ausentes = _dossie()
        with pytest.raises(ErroDoServicoIA, match="HTTP 422"):
            cliente.opinar(pedido_do_dossie("PETR4", HOJE, dossie[MEDIO], ausentes, "v"))

    def test_servico_fora_do_ar_vira_erro_do_servico(self):
        with pytest.raises(ErroDoServicoIA, match="indisponivel"):
            ServicoIA("http://127.0.0.1:9", timeout_s=1).identidade()


# ---------------------------------------------------------------- orquestracao

class _Banco:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


class _Repo:
    def __init__(self, existentes=()):
        self.gravados: list[dict] = []
        self._existentes = set(existentes)

    def ultimo_insight(self, db, simbolo, data_pregao):
        return {"id": 1792, "detalhes": _detalhes()}

    def fatores_recentes(self, db, simbolo):
        return []

    def fatos_relevantes_30d(self, db, simbolo, data_pregao):
        return 0

    def ja_existe(self, db, simbolo, data_pregao, horizonte, modelo, versao):
        return (horizonte, modelo, versao) in self._existentes

    def gravar(self, db, registro):
        self.gravados.append(registro)
        return True


class _ServicoFalso:
    """Responde MODELO no medio e REGRA (reserva do proprio servico) nos demais; ou cai."""

    def __init__(self, cair=False):
        self.cair = cair
        self.pedidos: list[dict] = []

    def opinar(self, pedido):
        self.pedidos.append(pedido)
        if self.cair:
            raise ErroDoServicoIA("fora do ar")
        dossie, _ = _dossie()
        d = dossie[pedido["horizonte_pregoes"]]
        corpo = resposta_de_regra(d)
        origem = "MODELO" if pedido["horizonte_pregoes"] == MEDIO else "REGRA"
        return {**corpo, "dados_ausentes": [], "fontes": [], "modelo": "qwen", "skills_versao": "skills@abc",
                "origem": origem, "tentativas": 1 if origem == "MODELO" else 0}


IDENTIDADE = Identidade("qwen", "skills@abc")


class TestOrquestracao:
    def test_grava_o_que_o_servico_devolve_com_a_identidade_do_lote(self):
        repo, resumo = _Repo(), gerar.Resumo()
        gerar.gerar_do_ativo(_Banco(), repo, "PETR4", HOJE, _ServicoFalso(), IDENTIDADE, LOG, resumo)
        assert len(repo.gravados) == 3 and resumo.do_modelo == 1 and resumo.de_regra == 2
        medio = next(r for r in repo.gravados if r["horizonte_pregoes"] == MEDIO)
        assert medio["origem"] == "MODELO" and medio["tentativas"] == 1
        assert all(r["modelo"] == "qwen" and r["versao_prompt"] == "skills@abc" for r in repo.gravados)

    def test_servico_fora_do_ar_grava_regra_igual_a_do_sem_llm(self):
        # Aceite da TASK-IA-03: a linha REGRA nao muda por existir (ou nao) o servico.
        com_falha, sem_llm = _Repo(), _Repo()
        resumo = gerar.Resumo()
        gerar.gerar_do_ativo(_Banco(), com_falha, "PETR4", HOJE, _ServicoFalso(cair=True), IDENTIDADE, LOG, resumo)
        gerar.gerar_do_ativo(_Banco(), sem_llm, "PETR4", HOJE, None, gerar.IDENTIDADE_LOCAL, LOG, gerar.Resumo())
        assert resumo.falhas_do_servico == 3
        campos = ("opiniao", "risco", "justificativa_json", "invalida_json", "dados_ausentes_json", "evidencias_json")
        for a, b in zip(com_falha.gravados, sem_llm.gravados):
            assert all(a[c] == b[c] for c in campos)
            assert a["origem"] == b["origem"] == "REGRA"

    def test_reserva_do_servico_e_identica_a_regra_local(self):
        repo_servico, repo_local = _Repo(), _Repo()
        gerar.gerar_do_ativo(_Banco(), repo_servico, "PETR4", HOJE, _ServicoFalso(), IDENTIDADE, LOG, gerar.Resumo())
        gerar.gerar_do_ativo(_Banco(), repo_local, "PETR4", HOJE, None, gerar.IDENTIDADE_LOCAL, LOG, gerar.Resumo())
        curto_s = next(r for r in repo_servico.gravados if r["horizonte_pregoes"] == CURTO)
        curto_l = next(r for r in repo_local.gravados if r["horizonte_pregoes"] == CURTO)
        assert curto_s["justificativa_json"] == curto_l["justificativa_json"]

    def test_idempotencia_pela_identidade(self):
        repo = _Repo(existentes={(h, "qwen", "skills@abc") for h in (21, 63, 126)})
        servico, resumo = _ServicoFalso(), gerar.Resumo()
        gerar.gerar_do_ativo(_Banco(), repo, "PETR4", HOJE, servico, IDENTIDADE, LOG, resumo)
        assert resumo.ja_existiam == 3 and not repo.gravados and not servico.pedidos

    def test_item_de_trecho_e_gravado_inteiro(self):
        class ComTrecho(_ServicoFalso):
            def opinar(self, pedido):
                r = super().opinar(pedido)
                r["justificativa"] = [{"evidencia_id": None, "trecho_id": "evidencia/momentum#2016-2026",
                                       "leitura": "Momentum bateu o mercado em 49% das semanas.",
                                       "fonte": "conhecimento/evidencia/momentum.md#resultado",
                                       "trecho": "Quintil de maior momentum: 49,1% das semanas."}]
                return r
        repo = _Repo()
        gerar.gerar_do_ativo(_Banco(), repo, "PETR4", HOJE, ComTrecho(), IDENTIDADE, LOG, gerar.Resumo())
        item = json.loads(repo.gravados[0]["justificativa_json"])[0]
        assert item == {"evidencia_id": None, "trecho_id": "evidencia/momentum#2016-2026",
                        "leitura": "Momentum bateu o mercado em 49% das semanas.",
                        "fonte": "conhecimento/evidencia/momentum.md#resultado",
                        "trecho": "Quintil de maior momentum: 49,1% das semanas."}

    def test_identidade_cai_para_local_quando_saude_falha(self):
        servico, identidade = gerar.resolver_identidade(ServicoIA("http://127.0.0.1:9", timeout_s=1), LOG)
        assert servico is None and identidade == gerar.IDENTIDADE_LOCAL
