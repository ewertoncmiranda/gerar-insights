"""Intervalo de confianca por bootstrap em blocos de meses (infra#TASK-31).

O intervalo analitico (Wilson; media +- 1,96 erro-padrao) supoe janelas
independentes. No backtest elas nao sao:
  - no mesmo mes, dezenas de ativos reagem ao mesmo mercado;
  - com horizonte de 63 pregoes (~3 meses), a janela de marco se sobrepoe as
    de abril e maio.
Reamostrar janelas soltas ignora as duas coisas e da um intervalo estreito
demais. Aqui a unidade reamostrada e o MES inteiro, em blocos de meses
consecutivos do tamanho do horizonte (moving block bootstrap): o que esta
correlacionado vai junto para a reamostra.

Deterministico (semente fixa): rodar o backtest duas vezes da o mesmo numero.
"""

from __future__ import annotations

import math
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import date

REAMOSTRAS = 400
SEMENTE = 20260927
PREGOES_POR_MES = 21


def _percentis(valores: list[float]) -> tuple[float, float] | None:
    if len(valores) < 20:
        return None
    ordenados = sorted(valores)
    return ordenados[int(0.025 * len(ordenados))], ordenados[int(0.975 * len(ordenados)) - 1]


def intervalo_em_blocos(
    janelas: Sequence[tuple[date, bool | None, float | None]], horizonte: int
) -> dict:
    """janelas: (data_entrada, acerto ou None, excesso sobre a carteira ou None).

    Devolve {"acerto": (inf, sup) | None, "excesso": (inf, sup) | None, "meses": n}.
    """
    por_mes: dict[int, list[tuple[bool | None, float | None]]] = defaultdict(list)
    for entrada, acerto, excesso in janelas:
        por_mes[entrada.year * 12 + entrada.month].append((acerto, excesso))
    meses = sorted(por_mes)
    if len(meses) < 2:
        return {"acerto": None, "excesso": None, "meses": len(meses)}

    bloco = max(1, min(len(meses), math.ceil(horizonte / PREGOES_POR_MES)))
    blocos_por_reamostra = math.ceil(len(meses) / bloco)
    inicios = range(len(meses) - bloco + 1)
    gerador = random.Random(SEMENTE)

    taxas, medias = [], []
    for _ in range(REAMOSTRAS):
        acertos = direcionais = 0
        soma = 0.0
        n_excesso = 0
        for _ in range(blocos_por_reamostra):
            inicio = gerador.choice(inicios)
            for mes in meses[inicio : inicio + bloco]:
                for acerto, excesso in por_mes[mes]:
                    if acerto is not None:
                        direcionais += 1
                        acertos += acerto
                    if excesso is not None:
                        soma += excesso
                        n_excesso += 1
        if direcionais:
            taxas.append(acertos / direcionais)
        if n_excesso:
            medias.append(soma / n_excesso)
    return {"acerto": _percentis(taxas), "excesso": _percentis(medias), "meses": len(meses)}
