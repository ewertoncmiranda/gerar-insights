"""Insights diarios da camada Base (COTAHIST + CVM, sem BRAPI).

    python -m app.insights_diarios [--data AAAA-MM-DD]

Roda depois da carga noturna do ETL (scripts/cargas-etl.ps1). Sem --data,
analisa o ultimo pregao que o COTAHIST ja trouxe.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Insights diarios da camada Base")
    parser.add_argument("--data", type=date.fromisoformat, help="pregao a analisar (padrao: o ultimo)")
    argumentos = parser.parse_args(argv)

    from app.config.config_logger import setup_logger
    from app.config.database_config import ConfigDatabase
    from app.core.service.insights_diarios_service import InsightsDiariosService

    logger = setup_logger()
    with ConfigDatabase().session() as db:
        r = InsightsDiariosService(logger).executar(db, argumentos.data)
    logger.info(
        "Insights diarios %s | universo=%d | gravados=%d | ja existiam=%d | sem dados=%d | sem pregao=%s",
        r.data_pregao, r.universo, r.gravados, r.ja_existiam, len(r.sem_dados), r.sem_pregao,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
