"""Motor de avaliacao de sinais (app/validacao/avaliador.py), com series sinteticas."""

from datetime import date, timedelta
from decimal import Decimal

from app.core.analysis.versao_regra import VERSAO_REGRA
from app.validacao.avaliador import (
    COMPRA,
    SEM_DIRECAO,
    VENDA,
    Pregao,
    avaliar,
    direcao,
)

D = Decimal
INICIO = date(2026, 1, 5)  # segunda


def serie(fechamentos, aberturas=None, inicio=INICIO):
    """Um pregao por dia util a partir de `inicio`."""
    aberturas = aberturas or fechamentos
    dias = []
    dia = inicio
    while len(dias) < len(fechamentos):
        if dia.weekday() < 5:
            dias.append(dia)
        dia += timedelta(days=1)
    return [Pregao(d, D(str(a)), D(str(f))) for d, a, f in zip(dias, aberturas, fechamentos)]


def test_entra_na_abertura_seguinte_e_sai_no_fechamento_do_horizonte():
    """Entrar no fechamento do proprio dia do sinal seria vies de futuro."""
    pregoes = serie(fechamentos=[10, 11, 12, 13], aberturas=[10, 10.5, 11.5, 12.5])

    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=3, custo_ida_e_volta=D(0))

    assert resultado.data_entrada == pregoes[1].data
    assert resultado.preco_entrada == D("10.5")
    assert resultado.data_saida == pregoes[3].data
    assert resultado.preco_saida == D("13")
    assert resultado.retorno_bruto == D("0.238095")  # 13 / 10.5 - 1


def test_sem_pregoes_suficientes_o_sinal_fica_pendente():
    pregoes = serie([10, 11, 12])
    assert avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=21) is None


def test_dia_do_sinal_fora_da_serie_nao_e_avaliado():
    pregoes = serie([10, 11, 12, 13])
    assert avaliar(date(2020, 1, 1), "COMPRA_FORTE", pregoes, horizonte=2) is None


def test_custo_de_ida_e_volta_e_descontado():
    pregoes = serie([10, 10, 11])
    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=2, custo_ida_e_volta=D("0.001"))
    assert resultado.retorno_liquido == resultado.retorno_bruto - D("0.001")


def test_acerto_depende_da_direcao_da_recomendacao():
    alta = serie([10, 10, 12])
    queda = serie([10, 10, 8])

    assert avaliar(alta[0].data, "COMPRA_MODERADA", alta, 2).acerto is True
    assert avaliar(queda[0].data, "COMPRA_MODERADA", queda, 2).acerto is False
    assert avaliar(queda[0].data, "VENDA_VALUATION", queda, 2).acerto is True
    assert avaliar(alta[0].data, "VENDA_VALUATION", alta, 2).acerto is False


def test_manter_nao_tem_acerto_mas_tem_retorno():
    """MANTER nao aposta em direcao nenhuma: inventar acerto seria mentir."""
    pregoes = serie([10, 10, 12])
    resultado = avaliar(pregoes[0].data, "MANTER", pregoes, 2)
    assert resultado.acerto is None
    assert resultado.retorno_bruto > 0


def test_ganho_menor_que_o_custo_nao_conta_como_acerto():
    pregoes = serie([10, 10, D("10.005")])
    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, 2, custo_ida_e_volta=D("0.001"))
    assert resultado.retorno_bruto > 0
    assert resultado.acerto is False


def test_excesso_sobre_bova11_no_mesmo_periodo():
    ativo = serie([10, 10, 12])  # +20%
    bova11 = serie([100, 100, 105])  # +5%
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, benchmark=bova11, custo_ida_e_volta=D(0))
    assert resultado.retorno_bova11 == D("0.05")
    assert resultado.excesso_bova11 == D("0.15")


def test_benchmark_sem_as_datas_deixa_excesso_nulo_em_vez_de_comparar_periodos_diferentes():
    ativo = serie([10, 10, 12])
    bova11 = serie([100, 100, 105], inicio=date(2025, 1, 6))
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, benchmark=bova11)
    assert resultado.retorno_bova11 is None
    assert resultado.excesso_bova11 is None


def test_cdi_acumulado_da_entrada_ate_a_vespera_da_saida():
    pregoes = serie([10, 10, 10, 10])
    entrada, meio, saida = pregoes[1].data, pregoes[2].data, pregoes[3].data
    cdi = {pregoes[0].data: D("9"), entrada: D("1"), meio: D("1"), saida: D("9")}

    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, 3, cdi_diario=cdi, custo_ida_e_volta=D(0))

    # So entrada e meio contam: 1,01 x 1,01 - 1
    assert resultado.retorno_cdi == D("0.020100")
    assert resultado.excesso_cdi == D("-0.020100")


def test_salto_de_desdobramento_marca_a_janela_como_suspeita():
    """Preco bruto do COTAHIST: desdobramento 2:1 parece queda de 50%."""
    pregoes = serie(fechamentos=[20, 20, 10, 10], aberturas=[20, 20, 10, 10])
    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, 3)
    assert resultado.evento_suspeito is True


def test_oscilacao_normal_nao_e_suspeita():
    pregoes = serie([10, D("10.5"), D("9.8"), D("10.2")])
    assert avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, 3).evento_suspeito is False


def test_direcao_das_familias_de_recomendacao():
    assert direcao("COMPRA_FORTE") == COMPRA
    assert direcao("COMPRA_TECNICA") == COMPRA
    assert direcao("VENDA_VALUATION") == VENDA
    assert direcao("ALERTA_RISCO") == SEM_DIRECAO
    assert direcao(None) == SEM_DIRECAO


def test_versao_da_regra_esta_fixada():
    """Mudou limiar ou formula? Incremente VERSAO_REGRA e atualize este teste.

    Este teste existe para a mudanca de regra nao passar despercebida: sinais
    de regras diferentes nao podem cair no mesmo placar.
    """
    assert VERSAO_REGRA == "2026.09.26-1"
