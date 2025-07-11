# common/logger.py
import logging
import os
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

def get_logger(name: str):
    log_dir = Path(os.getenv("LOCALAPPDATA", ".")) / "Botflows"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file_prefix = log_dir / f"botflows_{datetime.now().strftime('%Y-%m-%d')}.log"

    file_handler = TimedRotatingFileHandler(
        filename=log_file_prefix,
        when="midnight",
        backupCount=7,
        encoding="utf-8",
        utc=False
    )
    file_handler.suffix = "%Y-%m-%d"
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    if not logger.handlers:
        logger.addHandler(file_handler)
        logger.addHandler(console_handler)

    return logger
