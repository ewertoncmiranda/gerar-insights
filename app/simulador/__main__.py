"""Etapa diária das estratégias MOMENTO_PURO e BAIXO_SPREAD.

Roda exclusivamente pela rotina da manhã (infra/scripts/cargas-etl.ps1).
Calcula scores diários das estratégias exclusivas do simulador e grava em
simulador_resultado.

Na primeira execução após registro de um ativo sem histórico, preenche
automaticamente os últimos 5 anos de pregões antes de rodar o dia atual.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.config.config_logger import setup_logger
from app.config.database_config import ConfigDatabase
from app.external.database.cotahist_repository import RepositorioCotahist
from app.simulador.baixo_spread import BaixoSpreadService
from app.simulador.momento_puro import MomentoPuroService


def main() -> int:
    logger = setup_logger()
    with ConfigDatabase().session() as db:
        cotahist = RepositorioCotahist()
        momento = MomentoPuroService(logger, cotahist)
        spread = BaixoSpreadService(logger, cotahist)

        _backfill_se_necessario(db, cotahist, logger, momento, spread)

        resultados_momento = momento.executar(db)
        resultados_spread = spread.executar(db)

    logger.info(
        "Estratégias do simulador concluídas: %d resultados",
        len(resultados_momento) + len(resultados_spread),
    )
    return 0


def _backfill_se_necessario(db, cotahist, logger, momento, spread) -> None:
    """Preenche simulador_resultado retroativamente quando algum ativo não tem
    histórico (primeira execução após registro). Idempotente: dias já gravados
    são ignorados por cada serviço."""
    ontem = date.today() - timedelta(days=1)
    ativos_sem_historico = db.execute(
        text(
            "SELECT COUNT(*) FROM simulador_ativo a WHERE a.ativo = TRUE "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM simulador_resultado r "
            "  WHERE r.ativo_id = a.id AND r.data_pregao < :ontem"
            ")"
        ),
        {"ontem": ontem},
    ).scalar() or 0

    if not ativos_sem_historico:
        return

    cinco_anos_atras = date.today() - timedelta(days=5 * 365)
    pregoes = cotahist.pregoes_entre(db, cinco_anos_atras, ontem)
    if not pregoes:
        logger.info(
            "Backfill simulador: sem pregões no COTAHIST para %s..%s",
            cinco_anos_atras, ontem,
        )
        return

    logger.info(
        "Backfill simulador: %d ativo(s) sem histórico — %d pregões a processar (%s..%s)",
        ativos_sem_historico, len(pregoes), pregoes[0], pregoes[-1],
    )
    for i, dia in enumerate(pregoes, start=1):
        momento.executar(db, dia)
        spread.executar(db, dia)
        if i % 63 == 0:
            logger.info("Backfill simulador: %d/%d pregões (%s)", i, len(pregoes), dia)
    logger.info("Backfill simulador: concluído — %d pregões processados", len(pregoes))


if __name__ == "__main__":
    sys.exit(main())
