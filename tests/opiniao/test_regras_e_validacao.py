"""Opiniao por horizonte: regras puras, validacao da resposta do modelo e orquestracao (sem rede)."""

from __future__ import annotations

import json
import logging
from datetime import date

from app.opiniao import gerar
from app.opiniao.modelo_llm import ErroDoProvedor, resposta_de_regra, validar
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


def _resposta(**extra):
    base = {"opiniao": NEGATIVO, "risco": RISCO_ALTO,
            "justificativa": [{"evidencia_id": "regra_v1", "leitura": "O sinal determinístico aponta VENDA_VALUATION."}],
            "o_que_invalida": ["Revisão forte do lucro projetado."]}
    base.update(extra)
    return base


class TestValidacao:
    def test_resposta_correta_passa(self):
        ok, erros = validar(_resposta(), _dossie_medio())
        assert erros == [] and ok["opiniao"] == NEGATIVO

    def test_opiniao_fora_das_permitidas_e_rejeitada(self):
        _, erros = validar(_resposta(opiniao=POSITIVO), _dossie_medio())
        assert any("fora das permitidas" in e for e in erros)

    def test_risco_diferente_do_calculado_e_rejeitado(self):
        _, erros = validar(_resposta(risco="RISCO_BAIXO"), _dossie_medio())
        assert any("difere do calculado" in e for e in erros)

    def test_evidencia_inexistente_e_rejeitada(self):
        r = _resposta(justificativa=[{"evidencia_id": "inventada", "leitura": "x"}])
        _, erros = validar(r, _dossie_medio())
        assert any("inexistente" in e for e in erros)

    def test_numero_que_nao_esta_no_dossie_e_rejeitado(self):
        r = _resposta(justificativa=[{"evidencia_id": "margem_graham_base",
                                      "leitura": "A margem é de 73,2% segundo o modelo."}])
        _, erros = validar(r, _dossie_medio())
        assert any("número fora do dossiê" in e for e in erros)

    def test_numero_do_dossie_e_aceito(self):
        r = _resposta(justificativa=[{"evidencia_id": "margem_graham_base",
                                      "leitura": "A margem de segurança está em -458.0%, bem negativa."}])
        ok, erros = validar(r, _dossie_medio())
        assert erros == [] and ok

    def test_vocabulario_proibido_e_rejeitado(self):
        r = _resposta(o_que_invalida=["Garantido que cai."])
        _, erros = validar(r, _dossie_medio())
        assert any("vocabulário" in e for e in erros)

    def test_negativo_exige_citar_evidencia_desfavoravel(self):
        r = _resposta(justificativa=[{"evidencia_id": "sinal_momentum", "leitura": "Momentum neutro."}])
        _, erros = validar(r, _dossie_medio())
        assert any("sem citar evidência desfavorável" in e for e in erros)

    def test_nao_objeto_e_rejeitado(self):
        assert validar([], _dossie_medio())[0] is None


class _Provedor:
    nome = "modelo-teste"

    def __init__(self, respostas):
        self._respostas = list(respostas)
        self.chamadas = 0

    def gerar(self, sistema, usuario, schema):
        self.chamadas += 1
        item = self._respostas.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item)


LOG = logging.getLogger("teste")


class TestConsultaAoModelo:
    def test_segunda_tentativa_corrige_a_primeira(self):
        provedor = _Provedor([_resposta(opiniao=POSITIVO), _resposta()])
        resposta, tentativas = gerar.consultar_modelo(provedor, "WEGE3", _dossie_medio(), LOG)
        assert resposta["opiniao"] == NEGATIVO and tentativas == 2

    def test_duas_rejeicoes_devolvem_none(self):
        provedor = _Provedor(["isto nao e json", _resposta(opiniao=POSITIVO)])
        resposta, tentativas = gerar.consultar_modelo(provedor, "WEGE3", _dossie_medio(), LOG)
        assert resposta is None and tentativas == 2

    def test_provedor_fora_do_ar_nao_derruba(self):
        provedor = _Provedor([ErroDoProvedor("fora")])
        resposta, _ = gerar.consultar_modelo(provedor, "WEGE3", _dossie_medio(), LOG)
        assert resposta is None and provedor.chamadas == 1


class TestRespostaDeRegra:
    def test_regra_usa_a_opiniao_mais_forte_permitida_e_valida(self):
        d = _dossie_medio()
        resposta = resposta_de_regra(d)
        assert resposta["opiniao"] == NEGATIVO and resposta["risco"] == d.risco
        ok, erros = validar(resposta, d)
        assert erros == [], erros

    def test_sem_base_nao_inventa_direcao(self):
        dossie, _ = montar_dossie(_insight(), [], 0, HOJE)
        assert resposta_de_regra(dossie[CURTO])["opiniao"] == SEM_BASE
