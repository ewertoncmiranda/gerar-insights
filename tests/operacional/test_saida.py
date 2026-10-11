"""OPR-INS-3: regra de saida da posicao simulada (cada motivo, prioridade, stop movel, dado ausente)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.operacional import saida
from app.operacional.saida import (EVENTO, LIQUIDEZ, PRAZO, SINAL, STOP, ParametrosSaida, Posicao,
                                   PosicaoNaoAberta, PregaoDaPosicao, avaliar)

# Parametros da versao OPR-2026.10.10-1 (V23), no formato de regra_operacional.parametros_json.
PARAMETROS_V23 = {
    "liquidez": {"dias_iliquido_saida": 5},
    "saida": {"execucao": "ABERTURA_D_MAIS_1", "stop_atr": 2, "trailing_atr": 3, "trailing_armado_apos_atr": 1,
              "prioridade": ["EVENTO", "STOP", "LIQUIDEZ", "SINAL", "PRAZO"]},
}
P = ParametrosSaida.de_parametros(PARAMETROS_V23)
ENTRADA = date(2026, 10, 1)


def posicao(**extra) -> Posicao:
    base = dict(simbolo="PETR4", horizonte_pregoes=21, data_entrada=ENTRADA, preco_entrada=D("50"),
                atr_entrada=D("1"))
    return Posicao(**{**base, **extra})


def pregao(**extra) -> PregaoDaPosicao:
    base = dict(data_pregao=date(2026, 10, 9), fechamento=D("50.5"), maxima=D("50.8"), pregoes_em_posicao=7,
                opiniao="SINAL_POSITIVO", dias_insuficiente_seguidos=0)
    return PregaoDaPosicao(**{**base, **extra})


def test_parametros_da_v23_e_padrao_iguais():
    assert P == ParametrosSaida()
    assert saida.stop_inicial(D("50"), D("1"), P) == D("48")


def test_sem_motivo_a_posicao_fica_e_o_estado_e_atualizado():
    r = avaliar(posicao(), pregao(), P)
    assert not r.sai and r.motivo_saida is None and r.data_decisao is None
    assert r.posicao.maxima_desde_entrada == D("50.8") and r.posicao.stop_atual == D("48")
    assert r.trailing_armado is False and r.ressalvas == []


def test_evento_fato_relevante_desde_a_entrada():
    r = avaliar(posicao(), pregao(fatos_relevantes=(date(2026, 9, 20), date(2026, 10, 8))), P)
    assert r.motivo_saida == EVENTO and r.data_decisao == date(2026, 10, 9)
    assert r.gatilhos[EVENTO][0].codigo == saida.FATO_RELEVANTE and r.gatilhos[EVENTO][0].valor == "2026-10-08"


def test_fato_relevante_antes_da_entrada_nao_conta():
    assert not avaliar(posicao(), pregao(fatos_relevantes=(date(2026, 9, 30),)), P).sai


def test_evento_salto_sem_ajuste():
    r = avaliar(posicao(), pregao(ajuste_serie="AJUSTE_INDISPONIVEL"), P)
    assert r.motivo_saida == EVENTO and r.gatilhos[EVENTO][0].codigo == saida.SALTO_SEM_EVENTO


def test_stop_inicial_pelo_fechamento():
    r = avaliar(posicao(), pregao(fechamento=D("47.9"), maxima=D("49")), P)
    assert r.motivo_saida == STOP
    assert r.gatilhos[STOP][0] == saida.Motivo(saida.STOP_INICIAL, "fechamento abaixo do stop inicial", "47.9", "48.000000")


def test_fechamento_no_stop_nao_sai():
    assert not avaliar(posicao(), pregao(fechamento=D("48")), P).sai


def test_stop_movel_arma_depois_de_um_atr_e_so_sobe():
    # maxima 54 (+4 ATR): trailing = 54 - 3 = 51; armou porque passou de 50 + 1
    r1 = avaliar(posicao(), pregao(maxima=D("54"), fechamento=D("53.5")), P)
    assert r1.trailing_armado and r1.posicao.stop_atual == D("51") and not r1.sai
    # dia seguinte: maxima menor nao baixa o stop; fechamento 50.9 < 51 sai por stop movel
    r2 = avaliar(r1.posicao, pregao(data_pregao=date(2026, 10, 13), maxima=D("52"), fechamento=D("50.9"),
                                    pregoes_em_posicao=8), P)
    assert r2.posicao.stop_atual == D("51") and r2.posicao.maxima_desde_entrada == D("54")
    assert r2.motivo_saida == STOP and r2.gatilhos[STOP][0].codigo == saida.STOP_MOVEL


def test_ganho_menor_que_um_atr_nao_arma_o_trailing():
    r = avaliar(posicao(), pregao(maxima=D("50.99"), fechamento=D("49")), P)
    assert not r.trailing_armado and r.posicao.stop_atual == D("48") and not r.sai


def test_liquidez_depois_de_cinco_pregoes_insuficiente():
    assert not avaliar(posicao(), pregao(dias_insuficiente_seguidos=4), P).sai
    r = avaliar(posicao(), pregao(dias_insuficiente_seguidos=5), P)
    assert r.motivo_saida == LIQUIDEZ and r.gatilhos[LIQUIDEZ][0].valor == "5"


@pytest.mark.parametrize("opiniao", ["SINAL_NEGATIVO", "SEM_BASE"])
def test_sinal_que_deixa_de_sustentar_a_tese(opiniao):
    r = avaliar(posicao(), pregao(opiniao=opiniao), P)
    assert r.motivo_saida == SINAL and r.gatilhos[SINAL][0].valor == opiniao


def test_sinal_neutro_nao_sai():
    assert not avaliar(posicao(), pregao(opiniao="SINAL_NEUTRO"), P).sai


def test_prazo_no_fim_do_horizonte():
    assert not avaliar(posicao(), pregao(pregoes_em_posicao=20), P).sai
    r = avaliar(posicao(), pregao(pregoes_em_posicao=21), P)
    assert r.motivo_saida == PRAZO and r.gatilhos[PRAZO][0].limite == "21"


def test_prioridade_quando_varios_motivos_no_mesmo_pregao():
    todos = pregao(fatos_relevantes=(date(2026, 10, 9),), fechamento=D("47"), dias_insuficiente_seguidos=6,
                   opiniao="SEM_BASE", pregoes_em_posicao=30)
    r = avaliar(posicao(), todos, P)
    assert r.motivo_saida == EVENTO
    assert list(r.gatilhos) == [EVENTO, STOP, LIQUIDEZ, SINAL, PRAZO]  # o resto fica registrado
    sem_evento = pregao(fechamento=D("47"), dias_insuficiente_seguidos=6, opiniao="SEM_BASE", pregoes_em_posicao=30)
    assert avaliar(posicao(), sem_evento, P).motivo_saida == STOP
    assert avaliar(posicao(), pregao(dias_insuficiente_seguidos=6, opiniao="SEM_BASE", pregoes_em_posicao=30),
                   P).motivo_saida == LIQUIDEZ
    assert avaliar(posicao(), pregao(opiniao="SEM_BASE", pregoes_em_posicao=30), P).motivo_saida == SINAL


def test_prioridade_vem_da_regra():
    outra = ParametrosSaida.de_parametros({"saida": {"prioridade": ["PRAZO", "SINAL", "LIQUIDEZ", "STOP", "EVENTO"]}})
    r = avaliar(posicao(), pregao(opiniao="SEM_BASE", pregoes_em_posicao=30), outra)
    assert r.motivo_saida == PRAZO
    with pytest.raises(ValueError):
        ParametrosSaida.de_parametros({"saida": {"prioridade": ["STOP", "STOP"]}})


def test_dado_ausente_vira_ressalva_e_nao_dispara():
    r = avaliar(posicao(), pregao(opiniao=None, dias_insuficiente_seguidos=None), P)
    assert not r.sai
    assert {m.codigo for m in r.ressalvas} == {saida.SEM_OPINIAO, saida.SEM_CONTAGEM_LIQUIDEZ}


def test_posicao_pendente_ou_pregao_anterior_a_entrada():
    with pytest.raises(PosicaoNaoAberta):
        avaliar(posicao(data_entrada=None, preco_entrada=None), pregao(), P)
    with pytest.raises(ValueError):
        avaliar(posicao(), pregao(data_pregao=date(2026, 9, 30)), P)


def test_motivo_saida_json_cabe_no_contrato_posicao_fechada():
    r = avaliar(posicao(), pregao(fechamento=D("47.5"), opiniao="SEM_BASE"), P)
    j = r.motivo_saida_json()
    assert j["motivo"] == STOP and j["execucao"] == "ABERTURA_D_MAIS_1" and j["data_decisao"] == "2026-10-09"
    assert set(j["gatilhos"]) == {STOP, SINAL} and j["stop_atual"] == "48.000000"
    assert j  # motivo_saida_detalhe exige objeto nao vazio (minProperties 1)
