"""OPR-INS-5: IR estimado do paper trading (apuracao mensal, isencao, prejuizo, DARF minimo, rateio)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal as D

import pytest

from app.operacional import ir
from app.operacional.ir import OperacaoFechada, apurar, carregar_regras, provisao_em

REGRAS = carregar_regras()  # ir/2026.json do repositorio


def op(i, simbolo, saida, venda, resultado, entrada=None):
    return OperacaoFechada(i, simbolo, entrada or date(saida.year, saida.month, 1), saida, D(str(venda)), D(str(resultado)))


def test_arquivo_de_regras_versionado():
    assert REGRAS.versao == "ir/2026.json"
    comum = REGRAS.vigente(date(2026, 10, 9))["operacao_comum"]
    assert comum["aliquota"] == 0.15 and comum["isencao_vendas_mes"] == 20000
    assert REGRAS.classe("PETR4", date(2026, 10, 9)) == ("ACAO", True)
    assert REGRAS.classe("BPAC11", date(2026, 10, 9)) == ("UNIT_OU_FUNDO", False)
    assert REGRAS.classe("AAPL34", date(2026, 10, 9)) == ("BDR", False)
    assert REGRAS.classe("PETR4F", date(2026, 10, 9)) == ("ACAO", True)  # fracionario


def test_vendas_de_acoes_ate_20_mil_sao_isentas():
    (a,) = apurar([op(1, "PETR4", date(2026, 10, 9), 19_999.99, 1_500)], REGRAS)
    assert a.lucro_isento == D("1500") and a.base == 0 and a.imposto_do_mes == 0 and a.irrf == 0


def test_acima_de_20_mil_tributa_15_por_cento_menos_irrf():
    (a,) = apurar([op(1, "PETR4", date(2026, 10, 9), 15_000, 1_000), op(2, "VALE3", date(2026, 10, 20), 10_000, 1_000)],
                  REGRAS)
    assert a.base == D("2000")
    assert a.irrf == D("1.25")  # 0,005% de 25 mil
    assert a.imposto_do_mes == D("298.75") and a.pago == D("298.75")
    assert sum(a.rateio.values()) == a.imposto_do_mes
    assert abs(a.rateio[1] - a.rateio[2]) <= D("0.01")  # lucros iguais; o centavo vai para uma


def test_unit_ou_bdr_sem_isencao_tributa_mesmo_com_pouca_venda():
    (a,) = apurar([op(1, "BPAC11", date(2026, 10, 9), 5_000, 400)], REGRAS)
    assert a.base == D("400") and a.imposto_do_mes == D("59.75")  # 60 - 0,25 de IRRF


def test_prejuizo_acumulado_compensa_lucro_futuro():
    meses = apurar([op(1, "PETR4", date(2026, 8, 10), 30_000, -800),
                    op(2, "VALE3", date(2026, 9, 10), 30_000, 1_000)], REGRAS)
    agosto, setembro = meses
    assert agosto.imposto_do_mes == 0 and agosto.prejuizo_acumulado == D("800")
    assert setembro.prejuizo_compensado == D("800") and setembro.base == D("200")
    assert setembro.imposto_do_mes == D("28.50")  # 30 - 1,50 de IRRF
    assert setembro.prejuizo_acumulado == 0


def test_prejuizo_de_mes_isento_tambem_compensa():
    agosto, setembro = apurar([op(1, "PETR4", date(2026, 8, 10), 5_000, -300),
                               op(2, "VALE3", date(2026, 9, 10), 30_000, 1_000)], REGRAS)
    assert agosto.prejuizo_acumulado == D("300")
    assert setembro.base == D("700")


def test_darf_abaixo_de_10_reais_acumula_para_o_mes_seguinte():
    agosto, setembro = apurar([op(1, "BPAC11", date(2026, 8, 10), 1_000, 40),   # 6 - 0,05 = 5,95
                               op(2, "BPAC11", date(2026, 9, 10), 1_000, 40)], REGRAS)
    assert agosto.imposto_do_mes == D("5.95") and agosto.pago == 0 and agosto.resto_para_o_seguinte == D("5.95")
    assert setembro.a_pagar == D("11.90") and setembro.pago == D("11.90") and setembro.resto_para_o_seguinte == 0


def test_rateio_so_nas_operacoes_com_lucro():
    (a,) = apurar([op(1, "PETR4", date(2026, 10, 1), 20_000, 3_000), op(2, "VALE3", date(2026, 10, 2), 20_000, -1_000),
                   op(3, "ITUB4", date(2026, 10, 3), 20_000, 1_000)], REGRAS)
    assert a.base == D("3000")
    assert a.rateio[2] == 0  # operacao com prejuizo nao recebe imposto
    assert abs(a.rateio[1] - 3 * a.rateio[3]) <= D("0.03")  # proporcional ao lucro (3 mil x 1 mil)
    assert sum(a.rateio.values()) == a.imposto_do_mes


def test_day_trade_vira_violacao():
    (a,) = apurar([op(1, "PETR4", date(2026, 10, 9), 30_000, 100, entrada=date(2026, 10, 9))], REGRAS)
    assert a.violacoes and a.violacoes[0]["codigo"] == ir.DAY_TRADE


def test_provisao_e_darf_no_mes_seguinte():
    meses = apurar([op(1, "PETR4", date(2026, 9, 10), 30_000, 1_000)], REGRAS)
    imposto = meses[0].pago
    assert provisao_em(meses, date(2026, 9, 30)) == (imposto, D0 := D(0))
    assert provisao_em(meses, date(2026, 10, 1)) == (D0, imposto)          # paga no mes seguinte
    assert provisao_em(meses, date(2026, 11, 3)) == (D0, D0)               # dois meses depois: ja pago


def test_resto_abaixo_do_minimo_continua_provisionado():
    meses = apurar([op(1, "BPAC11", date(2026, 8, 10), 1_000, 40)], REGRAS)
    assert provisao_em(meses, date(2026, 9, 1)) == (D("5.95"), D(0))


def test_regra_sem_vigencia_falha():
    antiga = ir.RegrasIR("teste", ({"vigente_desde": "2030-01-01", "operacao_comum": {}, "classes": {}},))
    with pytest.raises(ValueError):
        antiga.vigente(date(2026, 1, 1))


def test_recalcular_da_o_mesmo_resultado():
    ops = [op(1, "PETR4", date(2026, 9, 10), 30_000, 1_000), op(2, "VALE3", date(2026, 10, 10), 30_000, -50)]
    assert [m.como_json() for m in apurar(ops, REGRAS)] == [m.como_json() for m in apurar(list(reversed(ops)), REGRAS)]
