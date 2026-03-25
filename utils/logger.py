from __future__ import annotations

import logging
import os

import colorlog

from config import settings as config

LOG_FORMAT = (
    "%(log_color)s%(levelname)-8s%(reset)s "
    "%(cyan)s%(asctime)s%(reset)s "
    "%(blue)s[%(name)s]%(reset)s "
    "%(message)s"
)

DATEFMT = "%Y-%m-%d %H:%M:%S"

LOG_COLORS = {
    "DEBUG": "cyan",
    "INFO": "green",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "bold_red",
}

# Read MODE early (before config is fully loaded) to avoid circular imports
_MODE = os.getenv("MODE", "dev").lower()


def _make_handler() -> logging.Handler:
    if _MODE == "prod":
        from pythonjsonlogger.json import JsonFormatter

        handler = logging.StreamHandler()
        handler.setFormatter(
            JsonFormatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt=DATEFMT,
                rename_fields={
                    "asctime": "timestamp",
                    "levelname": "level",
                    "name": "logger",
                },
            )
        )
        return handler

    handler = colorlog.StreamHandler()
    handler.setFormatter(
        colorlog.ColoredFormatter(
            LOG_FORMAT,
            datefmt=DATEFMT,
            log_colors=LOG_COLORS,
            reset=True,
            style="%",
        )
    )
    return handler


def get_logger(
    name: str,
    level: int | str = config.LOG_LEVEL,
) -> logging.Logger:

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.addHandler(_make_handler())
    logger.propagate = False

    return logger
