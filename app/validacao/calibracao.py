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
from app.core.analysis.valuation import ValuationAnalyzer
from app.validacao.avaliador import direcao
from app.validacao.backtest import CORTE_PADRAO, INICIO_PADRAO, Amostra, montar_amostras, regra_v1_antiga

AMOSTRA_MINIMA = 60
# Criterio da ISS-F3: regra que chama a maior parte do mercado de "venda" nao
# discrimina nada - na primeira passada o objetivo sem esta trava escolheu
# 92% de venda no teste. Restricao, nao objetivo: medida na calibracao.
FRACAO_VENDA_MAXIMA = 0.5

GRADE = {
    "multiplo_base": [8.5, 10.0, 12.0, 15.0],
    "margem_compra_forte": [0.0, 10.0, 20.0],
    "ey_compra_forte": [8.0, 12.0],
    "margem_compra_moderada": [-30.0, -10.0, 0.0, 10.0, 20.0],
    "ey_compra_moderada": [6.0, 8.0],
    "margem_venda": [-15.0, -30.0, -50.0, -70.0, -100.0, -150.0],
}


def _valuations(amostras: list[Amostra], multiplo: float) -> list[tuple[dict, float | None] | None]:
    """Valuation de cada amostra para um multiplo base: a parte que depende
    so do multiplo; os demais limiares so mudam a leitura dela."""
    analisador = ValuationAnalyzer(limiares=replace(LIMIARES_ATUAIS, multiplo_base=multiplo))
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
        valuation = analisador.analyze(snapshot, taxa, "CALIBRACAO", a.lpas_anuais, a.vpa)
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


def recomendar(valuations, limiares: Limiares) -> list[str | None]:
    politica = RecommendationPolicy(limiares)
    return [None if v is None else politica.define_recommendation(v[0], v[1]) for v in valuations]


def calibrar(amostras: list[Amostra], horizonte: int) -> dict:
    por_multiplo = {m: _valuations(amostras, m) for m in GRADE["multiplo_base"]}
    candidatos = []
    chaves = list(GRADE)
    for combinacao in itertools.product(*(GRADE[c] for c in chaves)):
        parametros = dict(zip(chaves, combinacao))
        if parametros["margem_venda"] >= parametros["margem_compra_moderada"]:
            continue
        limiares = replace(LIMIARES_ATUAIS, **parametros)
        medida = medir(recomendar(por_multiplo[limiares.multiplo_base], limiares), amostras, "CALIBRACAO", horizonte)
        if (medida["separacao"] is None or medida["compra"]["n"] < AMOSTRA_MINIMA
                or medida["venda"]["n"] < AMOSTRA_MINIMA or medida["fracao_venda"] > FRACAO_VENDA_MAXIMA):
            continue
        candidatos.append((medida["separacao"], parametros, medida))
    if not candidatos:
        raise RuntimeError("Nenhuma combinacao com amostra minima nos dois lados e venda <= 50%")
    candidatos.sort(key=lambda c: c[0], reverse=True)
    melhor_sep, melhor, medida_cal = candidatos[0]
    melhor_limiares = replace(LIMIARES_ATUAIS, **melhor)

    atuais_val = por_multiplo.get(LIMIARES_ATUAIS.multiplo_base) or _valuations(amostras, LIMIARES_ATUAIS.multiplo_base)
    antiga = [regra_v1_antiga(a) for a in amostras]
    recs_melhor = recomendar(por_multiplo[melhor_limiares.multiplo_base], melhor_limiares)
    recs_atuais = recomendar(atuais_val, LIMIARES_ATUAIS)

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
        "melhor": {"parametros": melhor, "calibracao": medida_cal,
                   "teste": medir(recs_melhor, amostras, "TESTE", horizonte)},
        "top5_calibracao": [{"separacao": s, "parametros": p} for s, p, _ in candidatos[:5]],
        "limiares_atuais": {"parametros": {c: getattr(LIMIARES_ATUAIS, c) for c in chaves},
                            "calibracao": medir(recs_atuais, amostras, "CALIBRACAO", horizonte),
                            "teste": medir(recs_atuais, amostras, "TESTE", horizonte)},
        "v1_antiga": {"calibracao": medir(antiga, amostras, "CALIBRACAO", horizonte),
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
