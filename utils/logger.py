from __future__ import annotations
import logging
import colorlog

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

def get_logger(
    name: str,
    level: int | str = 'INFO',
) -> logging.Logger:

    logger = logging.getLogger(name)

    if logger.handlers:
        return logger 
    
    logger.setLevel(level)

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
    logger.addHandler(handler)
    logger.propagate = False
    
    return logger