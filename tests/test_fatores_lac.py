"""Modulos puros do Plano LAC: aceite da LAC-INS (proventos sem dupla contagem,
ajuste de preco por evento, fatores sem olhar o futuro, ranking em serie conhecida)."""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.fatores import ajuste_preco, evento, mercado, percentis, preco, proventos_contabeis, qualidade
from app.validacao import ranking


@dataclass(frozen=True)
class Vela:
    data: date
    abertura: Decimal
    fechamento: Decimal


# --- LAC-INS-2: ajuste por evento -------------------------------------------


def test_desdobramento_2_para_1_ajusta_so_o_passado():
    serie = [Vela(date(2026, 3, 9), Decimal(20), Decimal(20)), Vela(date(2026, 3, 10), Decimal(10), Decimal(10))]
    evento_ = ajuste_preco.EventoCorporativo("X", date(2026, 3, 10), Decimal("0.5"))
    ajustada = ajuste_preco.ajustar(serie, [evento_])
    assert ajustada[0].fechamento == Decimal(10)
    assert ajustada[1].fechamento == Decimal(10)


def test_evento_sem_confianca_nao_ajusta():
    serie = [Vela(date(2026, 3, 9), Decimal(20), Decimal(20))]
    duvidoso = ajuste_preco.EventoCorporativo("X", date(2026, 3, 10), Decimal("0.5"), Decimal("0.5"))
    assert ajuste_preco.ajustar(serie, [duvidoso]) is serie


# --- LAC-INS-1: proventos da DVA ---------------------------------------------


def _pc(tipo, ini, fim, valor, entrega=None):
    return proventos_contabeis.ProventoContabil(tipo, ini, fim, entrega, Decimal(valor))


def test_dfp_vira_quarto_trimestre_sem_dupla_contagem():
    registros = [
        _pc("ITR", date(2025, 1, 1), date(2025, 3, 31), "0.10"),
        _pc("ITR", date(2025, 4, 1), date(2025, 6, 30), "0.10"),
        _pc("ITR", date(2025, 7, 1), date(2025, 9, 30), "0.10"),
        _pc("DFP", date(2025, 1, 1), date(2025, 12, 31), "0.50", date(2026, 2, 20)),
    ]
    periodos = proventos_contabeis.periodos_sem_dupla_contagem(registros)
    assert sum(p.por_acao for p in periodos) == Decimal("0.50")


def test_valor_do_periodo_repartido_entre_as_datas_ex():
    registros = [_pc("ITR", date(2025, 1, 1), date(2025, 3, 31), "0.30", date(2025, 5, 10))]
    eventos = proventos_contabeis.eventos_por_data(registros, [date(2025, 2, 10), date(2025, 3, 10)])
    assert eventos == {date(2025, 2, 10): Decimal("0.15"), date(2025, 3, 10): Decimal("0.15")}


def test_sem_marca_ex_vale_a_entrega_e_b3_prevalece():
    registros = [_pc("ITR", date(2025, 1, 1), date(2025, 3, 31), "0.30", date(2025, 5, 10))]
    assert proventos_contabeis.eventos_por_data(registros, []) == {date(2025, 5, 10): Decimal("0.30")}
    assert proventos_contabeis.eventos_por_data(registros, [], inicio_fonte_b3=date(2025, 1, 1)) == {}
    combinado = proventos_contabeis.combinar({date(2025, 5, 10): Decimal("0.30")}, {date(2025, 5, 10): Decimal("0.31")})
    assert combinado[date(2025, 5, 10)] == Decimal("0.31")


# --- LAC-INS-3: fatores de preco sem olhar o futuro ---------------------------


def _serie(n, inicio=date(2024, 1, 1), passo=1.001):
    return [preco.PregaoFator(inicio + timedelta(days=i), 10 * passo ** i, 1_000_000.0) for i in range(n)]


def test_fator_do_mes_nao_usa_o_proprio_dia_nem_o_futuro():
    serie = _serie(400)
    referencia = serie[300].data
    base = preco.calcular(serie, referencia)
    futuro_alterado = serie[:300] + [preco.PregaoFator(p.data, p.fechamento * 5, 1.0) for p in serie[300:]]
    assert preco.calcular(futuro_alterado, referencia) == base
    assert base["MOMENTO_12_1"] > 0
    assert base["DRAWDOWN_12M"] == pytest.approx(0.0)


def test_spread_mediano_precisa_de_metade_dos_pregoes():
    com = [preco.PregaoFator(date(2026, 1, i), 10.0, None, 10.0, 9.9, 10.1) for i in range(1, 11)]
    assert preco.spread_mediano(com) == pytest.approx(0.02)
    assert preco.spread_mediano([preco.PregaoFator(date(2026, 1, 1), 10.0)] * 4) is None


# --- LAC-INS-4: qualidade e valor ponto no tempo ------------------------------


def _balanco(ano, entrega, lucro=100.0, **extra):
    campos = dict(lucro_liquido=lucro, patrimonio_liquido=1000.0, receita_liquida=2000.0, ebit=150.0,
                  divida_bruta=300.0, caixa=100.0, fluxo_caixa_operacional=lucro + 20, acoes=100.0, lpa=lucro / 100,
                  vpa=10.0, ativo_total=2000.0, ativo_circulante=500.0, passivo_circulante=400.0, lucro_bruto=600.0)
    campos.update(extra)
    return qualidade.Balanco(date(ano, 12, 31), "ANUAL", entrega, **campos)


def test_balanco_ainda_nao_entregue_nao_existe_na_data():
    balancos = [_balanco(2024, date(2025, 3, 1)), _balanco(2025, date(2026, 3, 1), lucro=200.0)]
    antes = qualidade.calcular(balancos, date(2026, 2, 1), preco_bruto=10.0)
    depois = qualidade.calcular(balancos, date(2026, 3, 2), preco_bruto=10.0)
    assert antes["EARNINGS_YIELD"] == pytest.approx(0.1)
    assert depois["EARNINGS_YIELD"] == pytest.approx(0.2)
    assert depois["CRESCIMENTO_LPA"] == pytest.approx(1.0)


def test_piotroski_completo_e_sem_valor_parcial():
    atual = _balanco(2025, date(2026, 3, 1), lucro=200.0)
    anterior = _balanco(2024, date(2025, 3, 1))
    assert 0 <= qualidade.piotroski(atual, anterior) <= 9
    incompleto = _balanco(2025, date(2026, 3, 1), lucro_bruto=None)
    assert qualidade.piotroski(incompleto, anterior) is None


# --- LAC-INS-5 e 6 --------------------------------------------------------------


def test_percentis_com_empate_e_grupo_pequeno():
    assert percentis.percentis({"A": 1, "B": 2, "C": 2, "D": 3}) == {"A": 0.0, "B": 0.5, "C": 0.5, "D": 1.0}
    grupos = {s: "G1" for s in "ABCDE"} | {"F": "G2"}
    no_setor = percentis.percentis_por_grupo({s: i for i, s in enumerate("ABCDEF")}, grupos)
    assert set(no_setor) == set("ABCDE")


def test_evento_conta_por_entrega_e_exclui_o_proprio_dia():
    ref = date(2026, 6, 1)
    comunicados = [("FATO_RELEVANTE", ref), ("FATO_RELEVANTE", ref - timedelta(days=10)),
                   ("FATO_RELEVANTE", ref - timedelta(days=100)), ("PROVENTOS", ref - timedelta(days=170))]
    fatores = evento.calcular(comunicados, ref)
    assert fatores == {"FATOS_RELEVANTES_90D": 1.0, "AVISOS_PROVENTOS_180D": 1.0}


# --- LAC-INS-7: fatores de referencia e alfa ----------------------------------


def test_regressao_recupera_alfa_e_beta_conhecidos():
    x = [[float(i % 7) - 3] for i in range(40)]
    y = [0.01 + 2.0 * xi[0] for xi in x]
    coeficientes, _ = mercado.regressao(y, x)
    assert coeficientes[0] == pytest.approx(0.01)
    assert coeficientes[1] == pytest.approx(2.0)


def test_smb_compra_os_menores():
    retornos = {f"S{i}": (0.05 if i < 10 else -0.05) for i in range(30)}
    caracteristicas = {f"S{i}": {"VALOR_MERCADO": float(i)} for i in range(30)}
    smb = next(f for f in mercado.fatores_do_mes(retornos, caracteristicas, 0.01) if f.codigo == "SMB")
    assert smb.retorno == pytest.approx(0.10)


# --- LAC-INS-8 e 9: ranking --------------------------------------------------------


def test_spearman_e_quintis_em_serie_conhecida():
    scores = [float(i) for i in range(50)]
    assert ranking.spearman(scores, [s * 2 for s in scores]) == pytest.approx(1.0)
    assert ranking.spearman(scores, [-s for s in scores]) == pytest.approx(-1.0)
    q = ranking.quintis(scores, scores)
    assert [n for _, _, n in q] == [10] * 5 and q[0][1] < q[-1][1]


def test_janelas_sucessivas_e_promocao():
    janelas = ranking.janelas_sucessivas(2011, 2016, 2018)
    assert [j.nome for j in janelas] == ["T2016", "T2017", "T2018"]
    assert janelas[0].treino_fim == date(2015, 12, 31)
    bons = [ranking.MesRanking(date(2016 + i // 12, i % 12 + 1, 1), 63, 0.10, [(1, 0.0, 10), (5, 0.03, 10)], 50)
            for i in range(24)]
    assert ranking.decidir_promocao(bons, 63, 1, 0.001, None).promover
    ruins = [ranking.MesRanking(m.data_referencia, 63, -0.05, [(1, 0.02, 10), (5, 0.0, 10)], 50) for m in bons]
    decisao = ranking.decidir_promocao(ruins, 63, 3, -0.01, None)
    assert not decisao.promover and len(decisao.motivos) >= 2
