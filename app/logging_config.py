"""Configura logs locais com rotação, sem registrar nomes de sessões."""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging(log_file: Path) -> None:
    """Configura o logger da aplicação em arquivo UTF-8.

    Args:
        log_file: Arquivo em um diretório previamente criado.
    """
    logger = logging.getLogger("studytimer")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for existing_handler in logger.handlers[:]:
        existing_handler.close()
        logger.removeHandler(existing_handler)
    handler = RotatingFileHandler(log_file, maxBytes=1_048_576, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(handler)
