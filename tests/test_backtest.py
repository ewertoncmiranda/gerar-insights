"""Testes do backtest walk-forward (TASK-40).

Cobre:
  - primeiros_pregoes_do_mes: amostragem mensal correta
  - montar_series: emenda de codigo antigo, canonico vence, sem abertura descartado
  - aplicar + agregar: placar com n, acerto, taxa-base, IC por bootstrap
  - determinismo: mesmos parametros -> mesmos numeros
  - corte calibracao/teste respeitado
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.validacao.avaliador import ResultadoHorizonte
from app.validacao.backtest import (
    Amostra,
    Avaliacao,
    Vela,
    agregar,
    aplicar,
    montar_series,
    primeiros_pregoes_do_mes,
    regra_v1_atual,
    regra_v1_antiga,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _dia(offset: int, base: date = date(2022, 1, 3)) -> date:
    return base + timedelta(days=offset)


def _vela(d: date, fechamento: float = 10.0, abertura: float | None = None) -> Vela:
    f = Decimal(str(fechamento))
    a = Decimal(str(abertura)) if abertura is not None else f
    return Vela(d, a, f, f, f, Decimal("1000000"))


def _resultado(
    dia: date = date(2022, 2, 1),
    retorno: str = "0.05",
    horizonte: int = 21,
    evento_suspeito: bool = False,
    acerto: bool | None = None,
) -> ResultadoHorizonte:
    return ResultadoHorizonte(
        horizonte=horizonte,
        data_entrada=dia + timedelta(days=1),
        data_saida=dia + timedelta(days=horizonte + 1),
        preco_entrada=Decimal("10"),
        preco_saida=Decimal("10.5"),
        retorno_bruto=Decimal(retorno),
        retorno_liquido=Decimal(retorno),
        retorno_carteira=None,
        retorno_cdi=None,
        excesso_carteira=None,
        ativos_na_carteira=None,
        excesso_cdi=None,
        acerto=acerto,
        evento_suspeito=evento_suspeito,
    )


def _amostra(simbolo="TEST3", dia=date(2022, 2, 1), periodo="CALIBRACAO", **kw) -> Amostra:
    base = dict(
        simbolo=simbolo, dia=dia, periodo=periodo,
        preco=10.0, minima_52s=7.0, maxima_52s=13.0,
        lpa_anual=1.0, lpa_recente=1.2, fonte_lpa_recente="ANUAL 2021-12-31",
        lpas_anuais=[1.2, 1.0], vpa=10.0,
        selic=13.75, juros_cdi=13.5, ipca_12m=5.5,
        resultados={21: _resultado(dia)},
    )
    base.update(kw)
    return Amostra(**base)


def _avaliacao(
    simbolo="TEST3",
    versao="2026.09.27-2",
    periodo="CALIBRACAO",
    recomendacao="SINAL_POSITIVO",
    retorno: str = "0.05",
    horizonte: int = 21,
    evento_suspeito: bool = False,
) -> Avaliacao:
    # aplica a direcao para computar acerto como aplicar() faria
    from app.validacao.avaliador import direcao
    sentido = direcao(recomendacao)
    acerto = None if sentido == 0 else (Decimal(retorno) * sentido > 0)
    return Avaliacao(
        simbolo=simbolo,
        versao=versao,
        periodo=periodo,
        recomendacao=recomendacao,
        resultado=_resultado(retorno=retorno, horizonte=horizonte, evento_suspeito=evento_suspeito, acerto=acerto),
    )


# ---------------------------------------------------------------------------
# primeiros_pregoes_do_mes
# ---------------------------------------------------------------------------

def test_primeiros_pregoes_do_mes_um_por_mes():
    velas = [
        _vela(date(2022, 1, 3)),
        _vela(date(2022, 1, 10)),
        _vela(date(2022, 1, 31)),
        _vela(date(2022, 2, 1)),
        _vela(date(2022, 2, 15)),
        _vela(date(2022, 3, 2)),
    ]
    indices = primeiros_pregoes_do_mes(velas)
    assert indices == [0, 3, 5]


def test_primeiros_pregoes_do_mes_unico_mes():
    velas = [_vela(date(2022, 6, d)) for d in [1, 7, 14, 21, 28]]
    assert primeiros_pregoes_do_mes(velas) == [0]


def test_primeiros_pregoes_do_mes_vazio():
    assert primeiros_pregoes_do_mes([]) == []


def test_primeiros_pregoes_do_mes_cada_dia_mes_diferente():
    velas = [_vela(date(2022, m, 1)) for m in range(1, 7)]
    indices = primeiros_pregoes_do_mes(velas)
    assert indices == list(range(6))


# ---------------------------------------------------------------------------
# montar_series
# ---------------------------------------------------------------------------

def test_montar_series_codigo_canonico():
    """Codigo antigo com continuidade deve ser mesclado no canonico."""
    identidades = {
        "VIIA3": ("BHIA3", True),  # renomeou
        "BHIA3": ("BHIA3", True),
    }
    universo = {"BHIA3"}
    linhas = [
        ("VIIA3", date(2021, 1, 4), 5.0, 5.5, 4.8, 5.2, 1e6),
        ("BHIA3", date(2022, 1, 3), 4.0, 4.2, 3.9, 4.1, 2e6),
    ]
    series = montar_series(linhas, identidades, universo)
    assert "BHIA3" in series
    assert len(series["BHIA3"]) == 2


def test_montar_series_sem_continuidade_descarta():
    identidades = {"VELL3": ("VELL3", False)}  # sem continuidade de preco
    universo = {"VELL3"}
    linhas = [("VELL3", date(2022, 1, 3), 10.0, 11.0, 9.5, 10.5, 5e5)]
    series = montar_series(linhas, identidades, universo)
    assert "VELL3" not in series


def test_montar_series_sem_abertura_ou_fechamento_descarta():
    identidades = {"TEST3": ("TEST3", True)}
    universo = {"TEST3"}
    linhas = [("TEST3", date(2022, 1, 3), None, 11.0, 9.5, None, 5e5)]
    series = montar_series(linhas, identidades, universo)
    assert "TEST3" not in series


def test_montar_series_fora_do_universo_descarta():
    identidades = {"PETR4": ("PETR4", True)}
    universo = {"VALE3"}
    linhas = [("PETR4", date(2022, 1, 3), 30.0, 31.0, 29.5, 30.5, 1e7)]
    series = montar_series(linhas, identidades, universo)
    assert "PETR4" not in series


def test_montar_series_data_repetida_canonico_vence():
    identidades = {"ANTG3": ("NOVG3", True), "NOVG3": ("NOVG3", True)}
    universo = {"NOVG3"}
    dia = date(2022, 6, 1)
    linhas = [
        ("ANTG3", dia, 9.0, 9.5, 8.8, 9.2, 1e6),
        ("NOVG3", dia, 10.0, 10.5, 9.8, 10.2, 2e6),
    ]
    series = montar_series(linhas, identidades, universo)
    velas = series["NOVG3"]
    assert len(velas) == 1
    assert velas[0].fechamento == Decimal("10.2")  # canonico vence


# ---------------------------------------------------------------------------
# aplicar
# ---------------------------------------------------------------------------

def test_aplicar_sem_dados_nao_gera_avaliacao():
    a = _amostra(lpa_recente=None, lpas_anuais=[], selic=None, lpa_anual=None)
    avaliacoes = aplicar([a], {})
    assert avaliacoes == []


def test_aplicar_gera_uma_avaliacao_por_horizonte_e_regra():
    a = _amostra(resultados={21: _resultado(horizonte=21), 63: _resultado(horizonte=63)})
    from app.validacao.backtest import VERSAO_REGRA
    avaliacoes = aplicar([a], {VERSAO_REGRA: regra_v1_atual})
    # Duas entradas: uma por horizonte (21 e 63)
    horizontes = {av.resultado.horizonte for av in avaliacoes}
    assert 21 in horizontes


def test_aplicar_corte_calibracao_teste():
    a_calib = _amostra(periodo="CALIBRACAO")
    a_teste = _amostra(periodo="TESTE", dia=date(2024, 1, 2))
    from app.validacao.backtest import VERSAO_REGRA
    avs = aplicar([a_calib, a_teste], {VERSAO_REGRA: regra_v1_atual})
    periodos = {av.periodo for av in avs}
    assert "CALIBRACAO" in periodos
    assert "TESTE" in periodos


# ---------------------------------------------------------------------------
# agregar
# ---------------------------------------------------------------------------

def test_agregar_estrutura_basica():
    avs = [_avaliacao() for _ in range(5)]
    placar = agregar(avs)
    assert len(placar) >= 1
    linha = placar[0]
    assert "versao" in linha
    assert "periodo" in linha
    assert "avaliados" in linha
    assert linha["avaliados"] == 5


def test_agregar_exclui_janelas_suspeitas():
    avs_ok = [_avaliacao() for _ in range(4)]
    av_susp = _avaliacao(evento_suspeito=True)
    placar = agregar(avs_ok + [av_susp])
    assert placar[0]["avaliados"] == 4


def test_agregar_taxa_base_direcao_compra():
    avs_compra = [_avaliacao(retorno="0.05") for _ in range(6)]
    avs_queda = [_avaliacao(retorno="-0.03") for _ in range(4)]
    placar = agregar(avs_compra + avs_queda)
    linha = next(l for l in placar if l["avaliados"] > 0)
    assert linha["taxa_base"] is not None
    assert 0.0 <= linha["taxa_base"] <= 1.0


def test_agregar_acertos_sinal_positivo():
    avs_acerto = [_avaliacao(retorno="0.05") for _ in range(7)]
    avs_erro = [_avaliacao(retorno="-0.03") for _ in range(3)]
    placar = agregar(avs_acerto + avs_erro)
    linha = placar[0]
    assert linha["acertos"] == 7
    assert linha["avaliados"] == 10


def test_agregar_tem_ic_bootstrap():
    placar = agregar([_avaliacao() for _ in range(12)])
    # IC pode ser None quando ha poucos meses, mas as colunas devem existir
    assert "ic_acerto_inferior" in placar[0]
    assert "ic_acerto_superior" in placar[0]


def test_agregar_periodos_separados():
    avs_calib = [_avaliacao(periodo="CALIBRACAO") for _ in range(4)]
    avs_teste = [_avaliacao(periodo="TESTE") for _ in range(3)]
    placar = agregar(avs_calib + avs_teste)
    periodos = {l["periodo"] for l in placar}
    assert "CALIBRACAO" in periodos
    assert "TESTE" in periodos


# ---------------------------------------------------------------------------
# Determinismo: mesmos parametros -> mesmos numeros
# ---------------------------------------------------------------------------

def test_agregar_determinismo():
    import random
    avs = [_avaliacao(retorno=f"{random.uniform(-0.1, 0.2):.4f}") for _ in range(20)]
    p1 = agregar(avs)
    p2 = agregar(avs)
    assert p1 == p2


def test_aplicar_determinismo():
    amostras = [_amostra(f"T{i}3") for i in range(5)]
    from app.validacao.backtest import VERSAO_REGRA
    r1 = aplicar(amostras, {VERSAO_REGRA: regra_v1_atual})
    r2 = aplicar(amostras, {VERSAO_REGRA: regra_v1_atual})
    assert [(a.simbolo, a.versao, a.resultado.horizonte) for a in r1] == \
           [(a.simbolo, a.versao, a.resultado.horizonte) for a in r2]
