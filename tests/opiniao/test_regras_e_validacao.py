"""Opiniao por horizonte no worker: regras puras e reserva por regra (sem rede).

Validacao da resposta do modelo e prompt sao do servico de IA (insider-ia-b3-ecossytem, TASK-IA-03),
testados la em tests/test_validador_e_regras.py.
"""

from __future__ import annotations

from datetime import date

from app.opiniao.reserva import resposta_de_regra
from app.opiniao.regras import (
    CURTO,
    LONGO,
    MEDIO,
    NEGATIVO,
    NEUTRO,
    POSITIVO,
    RISCO_ALTO,
    RISCO_MEDIO,
    SEM_BASE,
    montar_dossie,
)

HOJE = date(2026, 10, 7)


def _insight(recomendacao="VENDA_VALUATION", margem=-458.0, ey="MUITO_BAIXO", pl="EXIGENTE",
             momentum="NEUTRO_TECNICO", nivel="ALTO"):
    return {
        "versao_regra": "2026.09.27-3",
        "resumo": {"recomendacao": recomendacao, "nivel_risco": nivel},
        "valuation": {
            "cenarios_graham": {"base": {"margem_seguranca_percent": margem}},
            "classificacao_earnings_yield": ey,
            "classificacao_pl": pl,
        },
        "contexto_tecnico_serie": {"sinal_momentum": momentum, "sinal_reversao": "NEUTRO_TECNICO"},
    }


def _fator(codigo, familia, percentil, direcao=1, dia=date(2026, 9, 30)):
    return {"codigo": codigo, "familia": familia, "descricao": codigo, "direcao_esperada": direcao,
            "data_referencia": dia, "valor": 1, "percentil_universo": percentil}


class TestRegras:
    def test_valuation_desfavoravel_permite_negativo_no_medio_e_longo(self):
        dossie, _ = montar_dossie(_insight(), [], 0, HOJE)
        assert dossie[MEDIO].permitidas == (NEGATIVO, NEUTRO)
        assert dossie[LONGO].permitidas == (NEGATIVO, NEUTRO)

    def test_curto_prazo_sem_evidencia_direcional_fica_sem_base(self):
        dossie, _ = montar_dossie(_insight(), [], 0, HOJE)
        assert dossie[CURTO].permitidas == (SEM_BASE,)
        assert dossie[CURTO].motivo_sem_base

    def test_sinais_mistos_nao_permitem_direcao(self):
        detalhes = _insight(recomendacao="COMPRA_MODERADA", margem=40.0, ey="MUITO_BAIXO", pl="EXIGENTE")
        dossie, _ = montar_dossie(detalhes, [], 0, HOJE)
        assert POSITIVO not in dossie[MEDIO].permitidas
        assert NEGATIVO not in dossie[MEDIO].permitidas

    def test_fator_parado_e_ignorado_e_declarado(self):
        velho = _fator("ROIC", "QUALIDADE", 0.9, dia=date(2020, 5, 4))
        dossie, ausentes = montar_dossie(_insight(), [velho], 0, HOJE)
        assert all(e.id != "fator_roic" for e in dossie[LONGO].evidencias)
        assert any("ROIC" in a for a in ausentes)

    def test_fator_recente_entra_com_direcao_pela_posicao(self):
        fatores = [_fator("ROIC", "QUALIDADE", 0.9), _fator("ALAVANCAGEM", "QUALIDADE", 0.9, direcao=-1)]
        dossie, _ = montar_dossie(_insight(), fatores, 0, HOJE)
        por_id = {e.id: e for e in dossie[LONGO].evidencias}
        assert por_id["fator_roic"].direcao == 1
        assert por_id["fator_alavancagem"].direcao == -1  # alavancagem alta e ruim

    def test_dados_criticos_atrasados_forcam_sem_base(self):
        dossie, _ = montar_dossie(_insight(), [], 0, HOJE, dados_criticos_atrasados=True)
        assert all(d.permitidas == (SEM_BASE,) for d in dossie.values())

    def test_risco_sobe_com_fato_relevante_no_curto_e_medio(self):
        sem, _ = montar_dossie(_insight(nivel="MEDIO"), [], 0, HOJE)
        com, _ = montar_dossie(_insight(nivel="MEDIO"), [], 2, HOJE)
        assert sem[CURTO].risco == RISCO_MEDIO
        assert com[CURTO].risco == RISCO_ALTO
        assert com[LONGO].risco == RISCO_MEDIO


def _dossie_medio():
    dossie, _ = montar_dossie(_insight(), [], 0, HOJE)
    return dossie[MEDIO]


class TestRespostaDeRegra:
    def test_regra_usa_a_opiniao_mais_forte_permitida_e_valida(self):
        d = _dossie_medio()
        resposta = resposta_de_regra(d)
        assert resposta["opiniao"] == NEGATIVO and resposta["risco"] == d.risco
        ids = {e.id for e in d.evidencias}
        assert resposta["justificativa"] and all(j["evidencia_id"] in ids for j in resposta["justificativa"])

    def test_sem_base_nao_inventa_direcao(self):
        dossie, _ = montar_dossie(_insight(), [], 0, HOJE)
        assert resposta_de_regra(dossie[CURTO])["opiniao"] == SEM_BASE


class TestPontosApontadosNaRevisao:
    def test_regra_positiva_nao_justifica_com_evidencia_contraria(self):
        # PETR4 em 2026-10-06: opiniao positiva no curto prazo com a reversao a media tecnica negativa.
        detalhes = _insight(momentum="COMPRA_TECNICA")
        detalhes["contexto_tecnico_serie"]["sinal_reversao"] = "VENDA_TECNICA"
        fatores = [_fator("MOMENTO_12_1", "PRECO", 0.95), _fator("DRAWDOWN_12M", "PRECO", 0.9),
                   _fator("BETA_12M", "PRECO", 0.1, direcao=-1)]
        dossie, _ = montar_dossie(detalhes, fatores, 0, HOJE)
        d = dossie[CURTO]
        assert d.permitidas[0] == POSITIVO
        resposta = resposta_de_regra(d)
        por_id = {e.id: e for e in d.evidencias}
        assert all(por_id[j["evidencia_id"]].direcao > 0 for j in resposta["justificativa"])
        assert any("sentido contrário" in i and "reversão" in i.lower() for i in resposta["o_que_invalida"])

    def test_regra_nunca_passa_de_cinco_justificativas(self):
        d = _dossie_medio()
        assert len(resposta_de_regra(d)["justificativa"]) <= 5
