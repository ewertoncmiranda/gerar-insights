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


def carteira_com(*variacoes, inicio=INICIO):
    """Um ativo por variacao: preco 100 no sinal e na entrada, 100*(1+v) na saida."""
    return {
        f"A{i}": serie([100, 100, 100 * (1 + v)], inicio=inicio) for i, v in enumerate(variacoes)
    }


def test_excesso_sobre_a_media_simples_da_carteira_no_mesmo_periodo():
    ativo = serie([10, 10, 12])  # +20%
    carteira = carteira_com(0.0, 0.05, 0.10, 0.0, 0.10)  # media +5%
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, carteira=carteira, custo_ida_e_volta=D(0))
    assert resultado.retorno_carteira == D("0.05")
    assert resultado.excesso_carteira == D("0.15")
    assert resultado.ativos_na_carteira == 5


def test_custo_sai_dos_dois_lados_comparando_liquido_com_liquido():
    """Comprar a carteira inteira tambem paga custo."""
    ativo = serie([10, 10, 12])
    carteira = carteira_com(0.05, 0.05, 0.05, 0.05, 0.05)
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, carteira=carteira, custo_ida_e_volta=D("0.001"))
    assert resultado.retorno_carteira == D("0.049000")
    assert resultado.excesso_carteira == D("0.150000")  # 0,199 - 0,049


def test_carteira_fina_demais_nao_vira_regua():
    ativo = serie([10, 10, 12])
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, carteira=carteira_com(0.05, 0.05))
    assert resultado.retorno_carteira is None
    assert resultado.excesso_carteira is None
    assert resultado.ativos_na_carteira == 2


def test_ativo_sem_preco_nas_duas_datas_fica_fora_da_media():
    """Comparar periodos diferentes nao e comparacao."""
    ativo = serie([10, 10, 12])
    carteira = carteira_com(0.10, 0.10, 0.10, 0.10, 0.10)
    carteira["DESENCONTRADO"] = serie([100, 100, 500], inicio=date(2025, 1, 6))
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, carteira=carteira, custo_ida_e_volta=D(0))
    assert resultado.ativos_na_carteira == 5
    assert resultado.retorno_carteira == D("0.1")


def test_desdobramento_de_outro_ativo_nao_contamina_a_media():
    ativo = serie([10, 10, 12])
    carteira = carteira_com(0.10, 0.10, 0.10, 0.10, 0.10)
    carteira["DESDOBROU"] = serie([100, 100, 50])  # 2:1 em preco bruto
    resultado = avaliar(ativo[0].data, "COMPRA_FORTE", ativo, 2, carteira=carteira, custo_ida_e_volta=D(0))
    assert resultado.ativos_na_carteira == 5
    assert resultado.retorno_carteira == D("0.1")


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
    assert VERSAO_REGRA == "2026.09.27-2"


# --- proventos (Item 3, 27/09/2026) --------------------------------------


def test_provento_na_janela_soma_ao_retorno():
    pregoes = serie(fechamentos=[10, 10, 10, 10], aberturas=[10, 10, 10, 10])
    proventos = {pregoes[2].data: D("0.50")}  # data-com dentro da janela [entrada, saida)

    resultado = avaliar(
        pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=3,
        custo_ida_e_volta=D(0), proventos=proventos,
    )

    # (10 + 0.50) / 10 - 1 = 0.05, nao 0 como seria so com o preco
    assert resultado.retorno_bruto == D("0.05")
    assert resultado.proventos_periodo == D("0.500000")


def test_provento_fora_da_janela_nao_conta():
    pregoes = serie(fechamentos=[10, 10, 10, 10], aberturas=[10, 10, 10, 10])
    proventos = {pregoes[0].data: D("0.50")}  # data-com ANTES da entrada

    resultado = avaliar(
        pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=3,
        custo_ida_e_volta=D(0), proventos=proventos,
    )

    assert resultado.retorno_bruto == D("0")
    assert resultado.proventos_periodo == D("0")


def test_sem_proventos_retorno_e_so_de_preco():
    pregoes = serie(fechamentos=[10, 11, 12, 13], aberturas=[10, 10.5, 11.5, 12.5])
    resultado = avaliar(pregoes[0].data, "COMPRA_FORTE", pregoes, horizonte=3, custo_ida_e_volta=D(0))
    assert resultado.proventos_periodo == D("0")
