import sys

from app.config.config_logger import setup_logger
from app.config.observability import ObservabilityMetrics, iniciar_servidor_observabilidade
from app.config.settings import Settings
from app.core.core_processor import CoreProcessor

logger = setup_logger()


def main():
    try:

        settings = Settings()
        metricas = ObservabilityMetrics()
        iniciar_servidor_observabilidade(
            settings.metrics_port,
            logger,
            metricas,
            settings.metrics_enabled,
        )
        core = CoreProcessor.instanciar(logger=logger, metricas=metricas)

        queue_url = core.ensure_queue(settings.queue_name)
        historical_series_queue_url = core.ensure_queue(settings.historical_series_queue_name)
        logger.info("Iniciando processamento ...")
        core.consume_queues({
            "ativos": (queue_url, core.processar_mensagem_ativo),
            "series_historicas": (historical_series_queue_url, core.processar_mensagem_serie_historica),
        })
    except Exception as e:
        logger.critical(f"Erro Critico durante processamento: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
