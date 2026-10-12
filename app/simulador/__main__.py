"""Etapa diária das estratégias MOMENTO_PURO e BAIXO_SPREAD.

Roda exclusivamente pela rotina da manhã (infra/scripts/cargas-etl.ps1).
Calcula scores diários das estratégias exclusivas do simulador e grava em
simulador_resultado.
"""

from __future__ import annotations

import sys

from app.config.config_logger import setup_logger
from app.config.database_config import ConfigDatabase
from app.simulador.baixo_spread import BaixoSpreadService
from app.simulador.momento_puro import MomentoPuroService


def main() -> int:
    logger = setup_logger()
    with ConfigDatabase().session() as db:
        resultados_momento = MomentoPuroService(logger).executar(db)
        resultados_spread = BaixoSpreadService(logger).executar(db)

    logger.info(
        "Estratégias do simulador concluídas: %d resultados",
        len(resultados_momento) + len(resultados_spread),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
