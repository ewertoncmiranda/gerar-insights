import logging

from app.config.settings import Settings

NOME_LOGGER = "sqs-consumer"
FORMATO = '%(asctime)s %(levelname)s %(name)s - %(message)s'


def setup_logger(nivel: str | None = None) -> logging.Logger:
    """Logger unico do worker.

    O nivel vem de LOG_LEVEL (Settings) - antes era INFO fixo (ISS-08). Chamar
    mais de uma vez nao duplica o handler: cada evento aparece uma vez so.
    """
    logger = logging.getLogger(NOME_LOGGER)
    nome_nivel = (nivel or Settings().log_level or "INFO").upper()
    logger.setLevel(getattr(logging, nome_nivel, logging.INFO))
    if not any(getattr(h, "_b3_handler", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(FORMATO))
        handler._b3_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False
    return logger
