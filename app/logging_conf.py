"""Journalisation structurée (format clé=valeur, lisible et exploitable)."""

from __future__ import annotations

import logging
import sys
from typing import Any


class StructuredFormatter(logging.Formatter):
    """Formateur clé=valeur incluant les champs extra fournis par `logger.info(msg, extra={...})`."""

    def format(self, record: logging.LogRecord) -> str:
        base: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "structured", None)
        if isinstance(extra, dict):
            base.update(extra)
        return " ".join(f"{k}={v!r}" for k, v in base.items())


def setup_logging(level: int = logging.INFO) -> None:
    """Configure la journalisation racine une seule fois."""
    root = logging.getLogger()
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    """Retourne un logger nommé, prêt à l'emploi."""
    setup_logging()
    return logging.getLogger(name)
