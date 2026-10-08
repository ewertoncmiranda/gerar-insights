"""Curva de calibracao do score de confianca.

Modulo puro: recebe pares (score, acerto) ja avaliados pelo diario/backtest e
devolve uma leitura por faixa. Nao decide nova regra; so mede se um score alto
historicamente acertou mais do que um score baixo.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class AmostraConfianca:
    score: float | int | None
    acerto: bool | None


@dataclass(frozen=True)
class FaixaConfianca:
    faixa: str
    minimo: int
    maximo: int
    total: int
    direcionais: int
    acertos: int
    taxa_acerto: float | None


def curva_por_faixa(
    amostras: Iterable[AmostraConfianca | tuple[float | int | None, bool | None]],
    tamanho_faixa: int = 20,
) -> list[FaixaConfianca]:
    """Agrupa score de 0 a 100 em faixas e calcula acerto direcional.

    `acerto=None` entra no total da faixa, mas nao entra na taxa de acerto:
    sinais sem direcao (`NEUTRO`, `SEM_MARGEM`) nao devem inventar acerto.
    """

    if tamanho_faixa <= 0 or tamanho_faixa > 100:
        raise ValueError("tamanho_faixa deve estar entre 1 e 100")

    grupos = {
        (minimo, min(100, minimo + tamanho_faixa - 1)): {
            "total": 0,
            "direcionais": 0,
            "acertos": 0,
        }
        for minimo in range(0, 101, tamanho_faixa)
    }

    for amostra in amostras:
        score, acerto = _valores(amostra)
        if score is None:
            continue
        minimo, maximo = _faixa(score, tamanho_faixa)
        grupo = grupos[minimo, maximo]
        grupo["total"] += 1
        if acerto is not None:
            grupo["direcionais"] += 1
            grupo["acertos"] += int(bool(acerto))

    return [
        FaixaConfianca(
            faixa=f"{minimo}-{maximo}",
            minimo=minimo,
            maximo=maximo,
            total=grupo["total"],
            direcionais=grupo["direcionais"],
            acertos=grupo["acertos"],
            taxa_acerto=(
                None
                if grupo["direcionais"] == 0
                else round(grupo["acertos"] / grupo["direcionais"], 6)
            ),
        )
        for (minimo, maximo), grupo in sorted(grupos.items())
    ]


def _valores(
    amostra: AmostraConfianca | tuple[float | int | None, bool | None],
) -> tuple[float | int | None, bool | None]:
    if isinstance(amostra, AmostraConfianca):
        return amostra.score, amostra.acerto
    return amostra


def _faixa(score: float | int, tamanho_faixa: int) -> tuple[int, int]:
    normalizado = min(100, max(0, int(score)))
    minimo = (normalizado // tamanho_faixa) * tamanho_faixa
    if minimo > 100:
        minimo = 100
    maximo = min(100, minimo + tamanho_faixa - 1)
    return minimo, maximo
