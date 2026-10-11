from datetime import date, timedelta
from decimal import Decimal

from app.validacao.avaliador import ResultadoHorizonte
from app.validacao.backtest import (
    Amostra,
    REGRAS,
    VERSAO_MOMENTUM,
    VERSAO_REVERSAO,
    Vela,
    agregar,
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


# ---------------------------------------------------------------------------
# REGRAS dict contem as versoes tecnicas (TASK-52 / infra#TASK-32)
# ---------------------------------------------------------------------------

def test_versoes_tecnicas_registradas_em_regras():
    """Os sinais tecnicos entram no placar do backtest com versao propria."""
    assert VERSAO_MOMENTUM in REGRAS
    assert VERSAO_REVERSAO in REGRAS


def test_versoes_tecnicas_sao_funcoes_distintas_das_de_valuation():
    from app.validacao.backtest import VERSAO_REGRA, regra_v1_atual
    assert REGRAS[VERSAO_MOMENTUM] is not REGRAS.get(VERSAO_REGRA)
    assert REGRAS[VERSAO_MOMENTUM] is not REGRAS[VERSAO_REVERSAO]


# ---------------------------------------------------------------------------
# sinais_tecnicos_da_janela — limites de janela
# ---------------------------------------------------------------------------

def test_sinais_nulos_com_janela_abaixo_do_minimo():
    janela = [_vela(i, 10.0) for i in range(19)]  # < 20 (janela_minima padrao)
    sinais = sinais_tecnicos_da_janela(janela)
    assert sinais["sinal_momentum"] is None
    assert sinais["sinal_reversao"] is None


def test_sinais_com_janela_exatamente_no_minimo():
    janela = [_vela(i, 10.0 + i * 0.1, volume=1000) for i in range(20)]
    sinais = sinais_tecnicos_da_janela(janela, janela_minima=20)
    # Nao precisa ter direcao especifica; mas nao pode ser None com 20 velas
    assert sinais["sinal_momentum"] is not None
    assert sinais["sinal_reversao"] is not None


def test_sinais_valores_validos():
    janela = [_vela(i, 10.0 + i * 0.1) for i in range(30)]
    sinais = sinais_tecnicos_da_janela(janela)
    assert sinais["sinal_momentum"] in {"COMPRA_TECNICA", "VENDA_TECNICA", "NEUTRO_TECNICO"}
    assert sinais["sinal_reversao"] in {"COMPRA_TECNICA", "VENDA_TECNICA", "NEUTRO_TECNICO"}


# ---------------------------------------------------------------------------
# Regras tecnicas nao alteram a recomendacao principal (DEC-11)
# ---------------------------------------------------------------------------

def test_sinal_tecnico_nao_sobrescreve_recomendacao_de_valuation():
    """VERSAO_MOMENTUM/REVERSAO sao regras independentes; cada uma produz
    sua propria linha no placar sem fundir com as outras."""
    amostra = _amostra(sinal_momentum="COMPRA_TECNICA", sinal_reversao="VENDA_TECNICA")

    avaliacoes = aplicar(
        amostras=[amostra],
        regras={VERSAO_MOMENTUM: regra_momentum, VERSAO_REVERSAO: regra_reversao},
    )

    versoes = {a.versao for a in avaliacoes}
    assert versoes == {VERSAO_MOMENTUM, VERSAO_REVERSAO}
    # Recomendacoes ficam separadas — a de momentum nao contamina a de reversao
    rec_por_versao = {a.versao: a.recomendacao for a in avaliacoes}
    assert rec_por_versao[VERSAO_MOMENTUM] == "COMPRA_TECNICA"
    assert rec_por_versao[VERSAO_REVERSAO] == "VENDA_TECNICA"


def test_placar_tecnico_separado_do_valuation():
    from app.validacao.backtest import VERSAO_REGRA
    amostra_m = _amostra(sinal_momentum="COMPRA_TECNICA", sinal_reversao="VENDA_TECNICA")

    avaliacoes = aplicar(
        amostras=[amostra_m],
        regras={VERSAO_MOMENTUM: regra_momentum, VERSAO_REVERSAO: regra_reversao},
    )
    placar = agregar(avaliacoes)

    versoes_placar = {l["versao"] for l in placar}
    assert VERSAO_REGRA not in versoes_placar  # valuation nao contamina o placar tecnico
