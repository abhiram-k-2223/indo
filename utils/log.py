import logging
import sys
from typing import Optional


_LOG_CONFIGURED = False


def setup_logger(name: str = "indo", level: Optional[str] = None) -> logging.Logger:
    global _LOG_CONFIGURED

    logger = logging.getLogger(name)

    if _LOG_CONFIGURED:
        return logger

    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    log_level = level_map.get((level or "").upper(), logging.INFO)
    logger.setLevel(log_level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%d %b %H:%M:%S",
    ))
    logger.handlers.clear()
    logger.addHandler(handler)

    _LOG_CONFIGURED = True
    return logger
