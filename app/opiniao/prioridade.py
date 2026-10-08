"""Fila de prioridade do lote Gemini (TASK-GEM-L2)."""

from __future__ import annotations

from datetime import date


def priorizar(repositorio, db, data_pregao: date, simbolos: list[str], limite: int | None = None) -> list[str]:
    """Ordena sem repetir: favoritos, monitorados, mudança de opinião/risco, variação incomum e liquidez."""
    universo = [s.upper() for s in simbolos]
    permitido = set(universo)
    ordenados: list[str] = []

    def adiciona(candidatos):
        for simbolo in candidatos or []:
            s = str(simbolo).upper()
            if s in permitido and s not in ordenados:
                ordenados.append(s)

    adiciona(repositorio.favoritos_para_gemini(db))
    adiciona(repositorio.monitorados_ativos(db))
    adiciona(repositorio.com_mudanca_de_opiniao(db, data_pregao, universo))
    adiciona(repositorio.com_variacao_incomum(db, data_pregao, universo))
    adiciona(repositorio.por_liquidez(db, universo))
    adiciona(universo)
    return ordenados if limite is None else ordenados[:limite]
