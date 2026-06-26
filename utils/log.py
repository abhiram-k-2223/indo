import logging
import sys
from typing import Optional


_LOG_CONFIGURED = False


def _setup_handler(log_level: int) -> logging.Handler:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%d %b %H:%M:%S",
    ))
    return handler


def setup_logger(name: str = "indo", level: Optional[str] = None) -> logging.Logger:
    global _LOG_CONFIGURED

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    log_level = level_map.get((level or "").upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(log_level)
    if not _LOG_CONFIGURED:
        root.handlers.clear()
        root.addHandler(_setup_handler(log_level))

    logger = logging.getLogger(name)
    if _LOG_CONFIGURED:
        return logger

    logger.setLevel(log_level)

    _LOG_CONFIGURED = True
    return logger
