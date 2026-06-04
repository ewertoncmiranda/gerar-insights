import sys

from app.config.config_logger import setup_logger
from app.config.settings import Settings
from app.core.core_processor import CoreProcessor

logger = setup_logger()


def main():
    try:

        settings = Settings()
        core = CoreProcessor.instanciar(logger=logger)

        queue_url = core.ensure_queue(settings.queue_name)
        logger.info("Iniciando processamento ...")
        core.consume_messages(queue_url)
    except Exception as e:
        logger.critical(f"Erro Critico durante processamento: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
