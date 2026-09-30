"""Percentil no universo e no grupo de setor (LAC-INS-5). Puro.

Percentil de posto medio em [0, 1] (0 = menor valor, 1 = maior), com empate
dividindo a posicao. Grupo com menos de MINIMO_GRUPO papeis nao tem
percentil de setor: a comparacao seria com dois ou tres vizinhos.
"""

from __future__ import annotations

from collections import defaultdict

MINIMO_GRUPO = 5
SEM_GRUPO = "A_CLASSIFICAR"


def percentis(valores: dict[str, float]) -> dict[str, float]:
    if not valores:
        return {}
    if len(valores) == 1:
        return {s: 0.5 for s in valores}
    ordenados = sorted(valores.items(), key=lambda kv: kv[1])
    saida: dict[str, float] = {}
    i = 0
    while i < len(ordenados):
        j = i
        while j + 1 < len(ordenados) and ordenados[j + 1][1] == ordenados[i][1]:
            j += 1
        posto_medio = (i + j) / 2
        for k in range(i, j + 1):
            saida[ordenados[k][0]] = posto_medio / (len(ordenados) - 1)
        i = j + 1
    return saida


def percentis_por_grupo(valores: dict[str, float], grupo_de: dict[str, str]) -> dict[str, float]:
    """Percentil dentro do grupo de setor de cada papel; sem grupo ou grupo
    pequeno, o papel fica de fora."""
    grupos: dict[str, dict[str, float]] = defaultdict(dict)
    for simbolo, valor in valores.items():
        grupo = grupo_de.get(simbolo)
        if grupo and grupo != SEM_GRUPO:
            grupos[grupo][simbolo] = valor
    saida: dict[str, float] = {}
    for membros in grupos.values():
        if len(membros) >= MINIMO_GRUPO:
            saida.update(percentis(membros))
    return saida
