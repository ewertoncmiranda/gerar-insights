"""python -m app.fatores calcular --desde AAAA-MM [--ate AAAA-MM]

Calcula os fatores do Plano LAC no primeiro pregao de cada mes do periodo e
os fatores de referencia (MKT, SMB, HML, WML, IML, QMJ). Idempotente: rodar
de novo o mesmo mes sobrescreve as mesmas linhas. Exige a V16.
"""

from __future__ import annotations

import argparse
import calendar
import sys
from datetime import date, datetime


def _mes(texto: str, fim: bool = False) -> date:
    ano, mes = (int(p) for p in texto.split("-")[:2])
    return date(ano, mes, calendar.monthrange(ano, mes)[1] if fim else 1)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.fatores", description="Fatores do Plano LAC")
    sub = parser.add_subparsers(dest="comando", required=True)
    calcular = sub.add_parser("calcular", help="calcula e grava fator_valor e fator_mercado_mensal")
    calcular.add_argument("--desde", required=True, help="AAAA-MM (primeiro mes)")
    calcular.add_argument("--ate", help="AAAA-MM (ultimo mes; padrao: ate o ultimo pregao carregado)")
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.fatores.repositorio import TabelaAusente
    from app.fatores.servico import CalculoDeFatores

    logger = setup_logger()
    inicio = datetime.now()
    try:
        resumo = CalculoDeFatores(ConfigDatabase().session, logger).calcular(
            _mes(argumentos.desde), _mes(argumentos.ate, fim=True) if argumentos.ate else None
        )
    except TabelaAusente as erro:
        logger.error("%s", erro)
        return 2
    logger.info("Fatores concluidos: %s meses, %s linhas em fator_valor, %s em fator_mercado_mensal (%.1fs)",
                resumo.meses, resumo.linhas_fator, resumo.linhas_mercado, (datetime.now() - inicio).total_seconds())
    return 0


if __name__ == "__main__":
    sys.exit(main())
