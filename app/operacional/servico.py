"""Elegibilidade de um pregao inteiro (OPR-INS-1). Sem comando proprio (AGENTS.md, start unico):
quem chama e o diario operacional (OPR-INS-4), dentro da rotina diaria."""

from __future__ import annotations

import os
from datetime import date

from app.operacional.elegibilidade import Elegibilidade, FatosDoAtivo, LimitesLiquidez, avaliar
from app.operacional.repositorio import RepositorioOperacional

VERSAO_REGRA_PADRAO = "OPR-2026.10.10-1"


def versao_regra() -> str:
    return os.getenv("OPERACIONAL_VERSAO_REGRA", VERSAO_REGRA_PADRAO)


def avaliar_pregao(db, data_pregao: date | None = None, simbolos: list[str] | None = None,
                   versao: str | None = None, repositorio: RepositorioOperacional | None = None
                   ) -> tuple[date | None, list[Elegibilidade]]:
    """Elegibilidade de todos os ativos com liquidez calculada no pregao (padrao: o ultimo)."""
    repo = repositorio or RepositorioOperacional()
    limites = LimitesLiquidez.de_parametros(repo.parametros_da_regra(db, versao or versao_regra()))
    data_pregao = data_pregao or repo.ultimo_pregao_com_liquidez(db)
    if data_pregao is None:
        return None, []
    liquidez = repo.liquidez_do_pregao(db, data_pregao)
    fatos = repo.fatos_do_pregao(db, data_pregao)
    alvo = [s.upper() for s in simbolos] if simbolos else sorted(liquidez)
    return data_pregao, [avaliar(s, data_pregao, liquidez.get(s), fatos.get(s, FatosDoAtivo()), limites) for s in alvo]