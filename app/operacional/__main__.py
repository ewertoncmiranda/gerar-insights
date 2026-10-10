"""Comandos do operacional simulado (Plano OPR).

    python -m app.operacional elegibilidade [--data AAAA-MM-DD] [--simbolo PETR4 ...] [--detalhe]

So leitura nesta etapa (OPR-INS-1): mostra quem pode entrar no pregao, a faixa de liquidez e o
motivo de cada bloqueio. O diario (OPR-INS-4) usa `avaliar_pregao` e grava os bloqueios em
`evento_operacional`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Operacional simulado (paper trading)")
    sub = parser.add_subparsers(dest="comando", required=True)
    ele = sub.add_parser("elegibilidade", help="quem pode entrar no pregao e por que")
    ele.add_argument("--data", type=date.fromisoformat, help="pregao (padrao: o ultimo com liquidez)")
    ele.add_argument("--simbolo", action="append", help="limita a estes ativos (repita)")
    ele.add_argument("--detalhe", action="store_true", help="imprime o JSON de cada ativo")
    argumentos = parser.parse_args(argv)

    from app.config.database_config import ConfigDatabase  # noqa: PLC0415

    with ConfigDatabase().session() as db:
        data_pregao, resultado = avaliar_pregao(db, argumentos.data, argumentos.simbolo)
    if data_pregao is None:
        print("Sem liquidez calculada (rode no ETL: python main.py --liquidez)")
        return 1
    elegiveis = [e for e in resultado if e.elegivel]
    faixas = Counter(e.faixa for e in resultado)
    motivos = Counter(m.codigo for e in resultado for m in e.bloqueios)
    print(f"Elegibilidade {data_pregao} | regra={versao_regra()} | ativos={len(resultado)} | "
          f"elegiveis={len(elegiveis)} | faixas={dict(faixas)}")
    print("Bloqueios por motivo: " + ", ".join(f"{k}={v}" for k, v in motivos.most_common()))
    if argumentos.detalhe:
        for e in resultado:
            print(json.dumps(e.como_json(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
