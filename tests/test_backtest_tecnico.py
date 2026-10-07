from datetime import date, timedelta
from decimal import Decimal

from app.validacao.avaliador import ResultadoHorizonte
from app.validacao.backtest import (
    Amostra,
    VERSAO_MOMENTUM,
    VERSAO_REVERSAO,
    Vela,
    aplicar,
    regra_momentum,
    regra_reversao,
    sinais_tecnicos_da_janela,
)


def _dia(i: int) -> date:
    return date(2026, 1, 1) + timedelta(days=i)


def _vela(i: int, fechamento: float, volume: int = 1000) -> Vela:
    preco = Decimal(str(fechamento))
    return Vela(_dia(i), preco, preco, preco, preco, Decimal(volume))


def _resultado(retorno: str = "0.10") -> ResultadoHorizonte:
    return ResultadoHorizonte(
        horizonte=21,
        data_entrada=date(2026, 2, 2),
        data_saida=date(2026, 3, 3),
        preco_entrada=Decimal("10"),
        preco_saida=Decimal("11"),
        retorno_bruto=Decimal(retorno),
        retorno_liquido=Decimal(retorno),
        retorno_carteira=None,
        retorno_cdi=None,
        excesso_carteira=None,
        ativos_na_carteira=None,
        excesso_cdi=None,
        acerto=None,
        evento_suspeito=False,
    )


def _amostra(**campos) -> Amostra:
    base = dict(
        simbolo="TEST3",
        dia=date(2026, 2, 1),
        periodo="TESTE",
        preco=10.0,
        minima_52s=7.0,
        maxima_52s=11.0,
        lpa_anual=None,
        lpa_recente=None,
        fonte_lpa_recente="AUSENTE",
        lpas_anuais=[],
        vpa=None,
        selic=None,
        juros_cdi=None,
        ipca_12m=None,
        resultados={21: _resultado()},
    )
    base.update(campos)
    return Amostra(**base)


def test_sinais_tecnicos_usam_apenas_a_janela_entregue():
    janela = [_vela(i, 10.0, 1000) for i in range(19)]
    janela.append(_vela(19, 12.0, 2000))

    sinais = sinais_tecnicos_da_janela(janela)

    assert sinais["sinal_momentum"] == "COMPRA_TECNICA"
    assert sinais["sinal_reversao"] in {"VENDA_TECNICA", "NEUTRO_TECNICO"}


def test_regras_tecnicas_entram_no_backtest_com_versao_propria():
    amostra = _amostra(sinal_momentum="COMPRA_TECNICA", sinal_reversao="VENDA_TECNICA")

    avaliacoes = aplicar(amostras=[amostra], regras={VERSAO_MOMENTUM: regra_momentum, VERSAO_REVERSAO: regra_reversao})

    assert {(a.versao, a.recomendacao) for a in avaliacoes} == {
        (VERSAO_MOMENTUM, "COMPRA_TECNICA"),
        (VERSAO_REVERSAO, "VENDA_TECNICA"),
    }
    assert [a.resultado.acerto for a in avaliacoes] == [True, False]


def test_regra_tecnica_sem_sinal_nao_gera_linha_no_placar():
    amostra = _amostra(sinal_momentum=None, sinal_reversao=None)

    assert aplicar(amostras=[amostra], regras={VERSAO_MOMENTUM: regra_momentum, VERSAO_REVERSAO: regra_reversao}) == []
