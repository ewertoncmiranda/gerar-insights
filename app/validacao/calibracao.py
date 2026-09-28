"""Calibracao dos limiares da v1 (TASK-41, ISS-F4).

    python -m app.validacao.calibracao [--horizonte 63] [--corte 2022-12-31]

Protocolo, para o numero nao mentir:
  1. As amostras sao as do backtest (point-in-time, mesmo motor do diario).
  2. A grade de limiares e avaliada SO nas amostras da CALIBRACAO (<= corte).
     Objetivo: separar compra de venda - excesso medio sobre a carteira das
     compras menos o das vendas, no horizonte escolhido - com amostra minima
     nos dois lados (sem isso a "melhor" regra e a que quase nunca fala).
  3. O TESTE (> corte) e olhado uma vez, no fim, para a melhor combinacao, os
     limiares atuais e a v1 antiga. Ele decide se a calibracao GENERALIZOU;
     nao escolhe entre combinacoes (isso seria calibrar no teste).

Saida: relatorio em JSON no stdout (e o que vai para a DEC). Nao grava nada:
adotar os limiares e uma mudanca de codigo (limiares.py + VERSAO_REGRA).
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from dataclasses import replace
from datetime import date

from app.core.analysis.limiares import LIMIARES_ATUAIS, Limiares
from app.core.analysis.market_snapshot import MarketSnapshot
from app.core.analysis.recommendation import RecommendationPolicy
from app.core.analysis.technical_context import TechnicalContextAnalyzer
from app.core.analysis.valuation import MODOS_JUROS, ValuationAnalyzer
from app.validacao.avaliador import direcao
from app.validacao.bootstrap import intervalo_separacao_em_blocos
from app.validacao.backtest import CORTE_PADRAO, INICIO_PADRAO, Amostra, montar_amostras, regra_v1_antiga

AMOSTRA_MINIMA = 60
# Criterio da ISS-F3: regra que chama a maior parte do mercado de "venda" nao
# discrimina nada - na primeira passada o objetivo sem esta trava escolheu
# 92% de venda no teste. Restricao, nao objetivo: medida na calibracao.
FRACAO_VENDA_MAXIMA = 0.5
# TASK-54: a fracao de vendas nao pode depender do regime de juros. Medida
# DENTRO da calibracao, entre 2017-2019 (Selic de 13% caindo a 4,5%) e
# 2020-2022 (2% subindo a 13,75%) - o teste continua sem ser olhado ate o fim.
CORTE_SUBPERIODO = date(2020, 1, 1)
ESTABILIDADE_MAXIMA = 0.10

GRADE = {
    "modo_juros": list(MODOS_JUROS),
    "multiplo_base": [8.5, 10.0, 12.0, 15.0],
    "margem_compra_forte": [0.0, 10.0, 20.0],
    "ey_compra_forte": [8.0, 12.0],
    "margem_compra_moderada": [-30.0, -10.0, 0.0, 10.0, 20.0],
    "ey_compra_moderada": [6.0, 8.0],
    "margem_venda": [-15.0, -30.0, -50.0, -70.0, -100.0, -150.0],
}


def _valuations(
    amostras: list[Amostra], multiplo: float, modo: str = "G_REAL"
) -> list[tuple[dict, float | None] | None]:
    """Valuation de cada amostra para um multiplo base e um modo de juros: a
    parte cara; os demais limiares so mudam a leitura dela."""
    analisador = ValuationAnalyzer(limiares=replace(LIMIARES_ATUAIS, multiplo_base=multiplo, modo_juros=modo))
    saida: list[tuple[dict, float | None] | None] = []
    for a in amostras:
        taxa = a.selic if a.selic is not None else a.juros_cdi
        lpa = a.lpa_recente
        if taxa is None or not lpa or lpa <= 0:
            saida.append(None)
            continue
        snapshot = MarketSnapshot(
            symbol=a.simbolo, price=a.preco, earnings_per_share=lpa, price_earnings=a.preco / lpa,
            open_price=None, previous_close=None, day_high=None, day_low=None, volume=None, market_cap=None,
            fifty_two_week_low=a.minima_52s, fifty_two_week_high=a.maxima_52s,
        )
        valuation = analisador.analyze(snapshot, taxa, "CALIBRACAO", a.lpas_anuais, a.vpa, a.ipca_12m)
        if not valuation["valido"]:
            saida.append(None)
            continue
        posicao = TechnicalContextAnalyzer().analyze(snapshot)["_raw"]["posicao_52w"]
        saida.append((valuation, posicao))
    return saida


def medir(recomendacoes: list[str | None], amostras: list[Amostra], periodo: str, horizonte: int) -> dict:
    """Excesso medio sobre a carteira e acerto por lado, sem janela suspeita."""
    lados: dict[int, list] = {1: [], -1: [], 0: []}
    for rec, a in zip(recomendacoes, amostras):
        if rec is None or rec == "SEM_DADOS" or a.periodo != periodo:
            continue
        r = a.resultados.get(horizonte)
        if r is None or r.evento_suspeito or r.excesso_carteira is None:
            continue
        lados[direcao(rec)].append(r)

    def resumo(rs, sentido):
        if not rs:
            return {"n": 0}
        return {
            "n": len(rs),
            "excesso_carteira": round(float(sum(r.excesso_carteira for r in rs) / len(rs)), 4),
            "acerto": None if sentido == 0 else round(sum((r.retorno_liquido * sentido) > 0 for r in rs) / len(rs), 3),
        }

    total = sum(len(v) for v in lados.values())
    compra, venda, neutro = resumo(lados[1], 1), resumo(lados[-1], -1), resumo(lados[0], 0)
    separacao = (
        round(compra["excesso_carteira"] - venda["excesso_carteira"], 4)
        if compra["n"] and venda["n"] else None
    )
    return {
        "compra": compra, "venda": venda, "sem_direcao": neutro, "separacao": separacao,
        "fracao_venda": round(venda["n"] / total, 3) if total else None,
    }


def fracao_de_vendas(recomendacoes, amostras, horizonte: int, filtro) -> float | None:
    """Fracao de vendas entre as janelas validas das amostras que passam no filtro."""
    total = vendas = 0
    for rec, a in zip(recomendacoes, amostras):
        if rec is None or rec == "SEM_DADOS" or not filtro(a):
            continue
        r = a.resultados.get(horizonte)
        if r is None or r.evento_suspeito or r.excesso_carteira is None:
            continue
        total += 1
        vendas += direcao(rec) < 0
    return vendas / total if total else None


def estabilidade(recomendacoes, amostras, horizonte: int) -> dict:
    """Fracao de vendas nos dois sub-periodos da calibracao e a diferenca."""
    antes = fracao_de_vendas(recomendacoes, amostras, horizonte,
                             lambda a: a.periodo == "CALIBRACAO" and a.dia < CORTE_SUBPERIODO)
    depois = fracao_de_vendas(recomendacoes, amostras, horizonte,
                              lambda a: a.periodo == "CALIBRACAO" and a.dia >= CORTE_SUBPERIODO)
    diferenca = None if antes is None or depois is None else abs(antes - depois)
    return {"venda_2017_2019": _r(antes), "venda_2020_2022": _r(depois), "diferenca": _r(diferenca)}


def _r(valor):
    return None if valor is None else round(valor, 3)


def ic_separacao(recomendacoes, amostras, periodo: str, horizonte: int) -> tuple[float, float] | None:
    """IC 95% da separacao compra x venda por bootstrap em blocos de meses (TASK-37)."""
    janelas = []
    for rec, a in zip(recomendacoes, amostras):
        if rec is None or rec == "SEM_DADOS" or a.periodo != periodo:
            continue
        r = a.resultados.get(horizonte)
        if r is None or r.evento_suspeito or r.excesso_carteira is None:
            continue
        lado = direcao(rec)
        if lado:
            janelas.append((r.data_entrada, lado, float(r.excesso_carteira)))
    ic = intervalo_separacao_em_blocos(janelas, horizonte)
    return None if ic is None else (round(ic[0], 4), round(ic[1], 4))


# Quantos candidatos (os melhores pela separacao pontual) passam pelo bootstrap,
# que e caro; a escolha final e pelo limite inferior do IC (infra#TASK-37).
FINALISTAS = 30


def recomendar(valuations, limiares: Limiares) -> list[str | None]:
    politica = RecommendationPolicy(limiares)
    return [None if v is None else politica.define_recommendation(v[0], v[1]) for v in valuations]


def calibrar(amostras: list[Amostra], horizonte: int) -> dict:
    valuations = {
        (modo, m): _valuations(amostras, m, modo) for modo in GRADE["modo_juros"] for m in GRADE["multiplo_base"]
    }
    candidatos = []
    chaves = list(GRADE)
    for combinacao in itertools.product(*(GRADE[c] for c in chaves)):
        parametros = dict(zip(chaves, combinacao))
        if parametros["margem_venda"] >= parametros["margem_compra_moderada"]:
            continue
        limiares = replace(LIMIARES_ATUAIS, **parametros)
        recs = recomendar(valuations[limiares.modo_juros, limiares.multiplo_base], limiares)
        medida = medir(recs, amostras, "CALIBRACAO", horizonte)
        if (medida["separacao"] is None or medida["compra"]["n"] < AMOSTRA_MINIMA
                or medida["venda"]["n"] < AMOSTRA_MINIMA or medida["fracao_venda"] > FRACAO_VENDA_MAXIMA):
            continue
        estavel = estabilidade(recs, amostras, horizonte)
        if estavel["diferenca"] is None or estavel["diferenca"] > ESTABILIDADE_MAXIMA:
            continue
        candidatos.append((medida["separacao"], parametros, medida, estavel))
    if not candidatos:
        raise RuntimeError("Nenhuma combinacao com amostra minima, venda <= 50% e estavel entre regimes")
    candidatos.sort(key=lambda c: c[0], reverse=True)
    # TASK-37: entre os finalistas pela separacao pontual, vence o maior LIMITE
    # INFERIOR do IC da separacao - robustez, nao o melhor numero de sorte.
    finalistas = []
    for sep, parametros, medida, estavel in candidatos[:FINALISTAS]:
        lim = replace(LIMIARES_ATUAIS, **parametros)
        recs = recomendar(valuations[lim.modo_juros, lim.multiplo_base], lim)
        ic = ic_separacao(recs, amostras, "CALIBRACAO", horizonte)
        finalistas.append((ic[0] if ic else float("-inf"), ic, sep, parametros, medida, estavel))
    finalistas.sort(key=lambda f: f[0], reverse=True)
    _, ic_cal, melhor_sep, melhor, medida_cal, estavel_cal = finalistas[0]
    melhor_limiares = replace(LIMIARES_ATUAIS, **melhor)

    atuais_val = valuations.get((LIMIARES_ATUAIS.modo_juros, LIMIARES_ATUAIS.multiplo_base)) or _valuations(
        amostras, LIMIARES_ATUAIS.multiplo_base, LIMIARES_ATUAIS.modo_juros
    )
    antiga = [regra_v1_antiga(a) for a in amostras]
    recs_melhor = recomendar(valuations[melhor_limiares.modo_juros, melhor_limiares.multiplo_base], melhor_limiares)
    recs_atuais = recomendar(atuais_val, LIMIARES_ATUAIS)

    # O melhor de cada modo, para a DEC comparar os tres com os mesmos criterios.
    por_modo = {}
    for modo in GRADE["modo_juros"]:
        do_modo = [c for c in candidatos if c[1]["modo_juros"] == modo]
        if not do_modo:
            por_modo[modo] = {"combinacoes_validas": 0}
            continue
        sep, parametros, med, est = do_modo[0]
        lim = replace(LIMIARES_ATUAIS, **parametros)
        recs = recomendar(valuations[modo, lim.multiplo_base], lim)
        teste = medir(recs, amostras, "TESTE", horizonte)
        por_modo[modo] = {
            "combinacoes_validas": len(do_modo), "parametros": parametros, "calibracao": med,
            "estabilidade_calibracao": est, "teste": teste,
            "diferenca_venda_calibracao_teste": _r(abs(med["fracao_venda"] - teste["fracao_venda"]))
            if teste["fracao_venda"] is not None else None,
        }

    ultimo_mes = max(a.dia for a in amostras)

    def distribuicao(recs):
        contagem: dict[str, int] = {}
        for rec, a in zip(recs, amostras):
            if a.dia == ultimo_mes and rec:
                contagem[rec] = contagem.get(rec, 0) + 1
        return dict(sorted(contagem.items()))

    return {
        "horizonte": horizonte,
        "combinacoes_validas": len(candidatos),
        "melhor": {"parametros": melhor, "calibracao": medida_cal, "estabilidade_calibracao": estavel_cal,
                   "ic_separacao_calibracao": ic_cal,
                   "teste": medir(recs_melhor, amostras, "TESTE", horizonte),
                   "ic_separacao_teste": ic_separacao(recs_melhor, amostras, "TESTE", horizonte)},
        "finalistas": [{"ic_inferior": f[0], "separacao": f[2], "parametros": f[3]} for f in finalistas[:5]],
        "por_modo": por_modo,
        "top5_calibracao": [{"separacao": c[0], "parametros": c[1]} for c in candidatos[:5]],
        "limiares_atuais": {"parametros": {c: getattr(LIMIARES_ATUAIS, c) for c in chaves},
                            "calibracao": medir(recs_atuais, amostras, "CALIBRACAO", horizonte),
                            "estabilidade_calibracao": estabilidade(recs_atuais, amostras, horizonte),
                            "ic_separacao_calibracao": ic_separacao(recs_atuais, amostras, "CALIBRACAO", horizonte),
                            "ic_separacao_teste": ic_separacao(recs_atuais, amostras, "TESTE", horizonte),
                            "teste": medir(recs_atuais, amostras, "TESTE", horizonte)},
        "v1_antiga": {"ic_separacao_teste": ic_separacao(antiga, amostras, "TESTE", horizonte),
                      "calibracao": medir(antiga, amostras, "CALIBRACAO", horizonte),
                      "teste": medir(antiga, amostras, "TESTE", horizonte)},
        "distribuicao_ultimo_mes": {"data": ultimo_mes.isoformat(), "v1_antiga": distribuicao(antiga),
                                    "limiares_atuais": distribuicao(recs_atuais),
                                    "melhor": distribuicao(recs_melhor)},
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Calibracao dos limiares da v1")
    parser.add_argument("--horizonte", type=int, default=63)
    parser.add_argument("--corte", type=date.fromisoformat, default=CORTE_PADRAO)
    argumentos = parser.parse_args(argv)

    from app.config.database_config import ConfigDatabase

    with ConfigDatabase().session() as db:
        amostras, _, _ = montar_amostras(db, INICIO_PADRAO, argumentos.corte, (argumentos.horizonte,))
    print(json.dumps(calibrar(amostras, argumentos.horizonte), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
