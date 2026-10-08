import logging

from pythonjsonlogger.json import JsonFormatter

from app.config.settings import Settings

NOME_LOGGER = "sqs-consumer"
FORMATO_JSON = "%(asctime)s %(levelname)s %(name)s %(message)s"


def setup_logger(nivel: str | None = None) -> logging.Logger:
    """Logger unico do worker.

    O nivel vem de LOG_LEVEL (Settings), o formato e JSON e chamar mais de uma
    vez nao duplica o handler: cada evento aparece uma vez so.
    """
    logger = logging.getLogger(NOME_LOGGER)
    nome_nivel = (nivel or Settings().log_level or "INFO").upper()
    logger.setLevel(getattr(logging, nome_nivel, logging.INFO))
    if not any(getattr(h, "_b3_handler", False) for h in logger.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(JsonFormatter(FORMATO_JSON))
        handler._b3_handler = True  # type: ignore[attr-defined]
        logger.addHandler(handler)
        logger.propagate = False
    for handler in logger.handlers:
        if getattr(handler, "_b3_handler", False) and not isinstance(
            handler.formatter, JsonFormatter
        ):
            handler.setFormatter(JsonFormatter(FORMATO_JSON))
    return logger
