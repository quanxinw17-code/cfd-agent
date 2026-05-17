from __future__ import annotations

import logging
from pathlib import Path


def configure_task_logger(name: str, output_dir: str | Path, filename: str) -> logging.Logger:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    log_path = Path(output_dir) / filename
    existing = [h for h in logger.handlers if isinstance(h, logging.FileHandler) and h.baseFilename == str(log_path)]
    if not existing:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)
    return logger

