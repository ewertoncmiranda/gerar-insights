import pytest

from app.core.analysis.regra_v2 import (
    EntradaV2,
    juros_anual_de_cdi_diario,
    posicao_no_range,
    recomendar_v2,
)


@pytest.mark.parametrize(
    ("entrada", "esperada"),
    [
        (EntradaV2(10.0, 2.0, 4.4), "COMPRA_FORTE"),
        (EntradaV2(30.0, 3.0, 4.4), "COMPRA_MODERADA"),
        (EntradaV2(100.0, 1.0, 4.4), "VENDA_VALUATION"),
        (EntradaV2(21.0, 1.0, 4.4, posicao_52w=95.0), "ALERTA_RISCO"),
        (EntradaV2(15.0, 1.0, 4.4), "MANTER"),
    ],
)
def test_recomendar_v2_cobre_todas_as_classes(entrada, esperada):
    assert recomendar_v2(entrada).recomendacao == esperada


@pytest.mark.parametrize(
    "entrada",
    [
        EntradaV2(0.0, 2.0, 4.4),
        EntradaV2(10.0, None, 4.4),
        EntradaV2(10.0, -1.0, 4.4),
        EntradaV2(10.0, 2.0, None),
    ],
)
def test_recomendar_v2_sem_dados_incompletos(entrada):
    saida = recomendar_v2(entrada)
    assert saida.recomendacao == "SEM_DADOS"
    assert saida.como_dict()["preco_justo_base"] is None


def test_recomendar_v2_aplica_piso_de_juros_e_preserva_metadados():
    saida = recomendar_v2(
        EntradaV2(10.0, 2.0, 0.5, ipca_12m_percent=5.0, fonte_lpa="CVM_TTM")
    )
    payload = saida.como_dict()

    assert saida.juros_usado == 2.0
    assert payload["ipca_usado_percent"] == 5.0
    assert payload["fonte_lpa"] == "CVM_TTM"
    assert payload["margem_base_percent"] == round(saida.margem_base, 4)


def test_funcoes_auxiliares_da_regra_v2():
    assert juros_anual_de_cdi_diario(None) is None
    assert juros_anual_de_cdi_diario(0.1) > 0.1
    assert posicao_no_range(15.0, 10.0, 20.0) == 50.0
    assert posicao_no_range(15.0, None, 20.0) is None
    assert posicao_no_range(15.0, 20.0, 20.0) is None
