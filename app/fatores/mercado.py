"""Fatores de referencia proprios, no lugar do NEFIN (LAC-INS-7). Puro.

Todo mes, com a caracteristica de cada papel no primeiro pregao do mes e o
retorno dele ate o primeiro pregao do mes seguinte:

    MKT  media do universo (igual peso) menos o CDI do mes
    SMB  tercil de MENOR valor de mercado menos o de maior
    HML  maior book-to-market menos o menor
    WML  maior momento 12-1 menos o menor
    IML  MENOR liquidez menos a maior (premio de iliquidez)
    QMJ  maior qualidade (Piotroski) menos a menor

A regressao do retorno mensal de uma carteira contra esses fatores da o alfa
(intercepto): o que a regra traz alem de ja apostar em valor, tamanho,
momento, liquidez ou qualidade.
"""

from __future__ import annotations

from dataclasses import dataclass

TERCIL = 1 / 3
MINIMO_POR_PERNA = 5

# fator -> (caracteristica, True se a perna comprada e a de MAIOR valor)
LONG_SHORT = {
    "SMB": ("VALOR_MERCADO", False),
    "HML": ("BOOK_TO_MARKET", True),
    "WML": ("MOMENTO_12_1", True),
    "IML": ("LIQUIDEZ_63D", False),
    "QMJ": ("PIOTROSKI", True),
}


@dataclass(frozen=True)
class RetornoFator:
    codigo: str
    retorno: float
    n_long: int | None
    n_short: int | None


def fatores_do_mes(
    retorno_seguinte: dict[str, float],
    caracteristicas: dict[str, dict[str, float]],
    cdi_do_mes: float | None,
) -> list[RetornoFator]:
    """retorno_seguinte: papel -> retorno ate o proximo mes; caracteristicas:
    papel -> {codigo: valor} no dia de referencia."""
    saida: list[RetornoFator] = []
    if len(retorno_seguinte) >= MINIMO_POR_PERNA and cdi_do_mes is not None:
        media = sum(retorno_seguinte.values()) / len(retorno_seguinte)
        saida.append(RetornoFator("MKT", media - cdi_do_mes, len(retorno_seguinte), None))
    for codigo, (caracteristica, maior_compra) in LONG_SHORT.items():
        valores = {
            s: c[caracteristica] for s, c in caracteristicas.items()
            if caracteristica in c and s in retorno_seguinte
        }
        pernas = _tercis(valores)
        if pernas is None:
            continue
        baixo, alto = pernas
        comprada, vendida = (alto, baixo) if maior_compra else (baixo, alto)
        retorno = _media(retorno_seguinte, comprada) - _media(retorno_seguinte, vendida)
        saida.append(RetornoFator(codigo, retorno, len(comprada), len(vendida)))
    return saida


def _tercis(valores: dict[str, float]) -> tuple[list[str], list[str]] | None:
    ordenados = [s for s, _ in sorted(valores.items(), key=lambda kv: kv[1])]
    tamanho = int(len(ordenados) * TERCIL)
    if tamanho < MINIMO_POR_PERNA:
        return None
    return ordenados[:tamanho], ordenados[-tamanho:]


def _media(retornos: dict[str, float], simbolos: list[str]) -> float:
    return sum(retornos[s] for s in simbolos) / len(simbolos)


def regressao(y: list[float], x: list[list[float]]) -> tuple[list[float], list[float]] | None:
    """Minimos quadrados de y contra [1, x1, ..., xk]: (coeficientes, erros-padrao).
    O primeiro coeficiente e o alfa. None se faltar observacao ou a matriz for singular."""
    n, k = len(y), (len(x[0]) + 1 if x else 1)
    if n <= k + 1:
        return None
    linhas = [[1.0, *xi] for xi in x]
    xtx = [[sum(lin[i] * lin[j] for lin in linhas) for j in range(k)] for i in range(k)]
    xty = [sum(lin[i] * yi for lin, yi in zip(linhas, y)) for i in range(k)]
    inversa = _inverter(xtx)
    if inversa is None:
        return None
    beta = [sum(inversa[i][j] * xty[j] for j in range(k)) for i in range(k)]
    residuos = [yi - sum(b * v for b, v in zip(beta, lin)) for lin, yi in zip(linhas, y)]
    s2 = sum(r * r for r in residuos) / (n - k)
    erros = [max(inversa[i][i] * s2, 0.0) ** 0.5 for i in range(k)]
    return beta, erros


def _inverter(m: list[list[float]]) -> list[list[float]] | None:
    """Gauss-Jordan com pivotamento parcial (matriz pequena: fatores + 1)."""
    n = len(m)
    a = [linha[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, linha in enumerate(m)]
    for col in range(n):
        pivo = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivo][col]) < 1e-12:
            return None
        a[col], a[pivo] = a[pivo], a[col]
        fator = a[col][col]
        a[col] = [v / fator for v in a[col]]
        for r in range(n):
            if r != col and a[r][col]:
                mult = a[r][col]
                a[r] = [vr - mult * vc for vr, vc in zip(a[r], a[col])]
    return [linha[n:] for linha in a]
