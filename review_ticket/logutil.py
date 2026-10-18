"""Logging setup for review-ticket (progress to stderr; receipts stay on stdout)."""

from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

LOG = logging.getLogger("review_ticket")

_LEVELS = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}


def parse_log_level(name: str) -> int:
    key = (name or "warning").strip().casefold()
    if key not in _LEVELS:
        raise ValueError(f"Unknown log_level '{name}'. Use one of: {', '.join(sorted(set(_LEVELS)))}.")
    return _LEVELS[key]


def configure_logging(level: str, *, stream: TextIO | None = None) -> None:
    numeric = parse_log_level(level)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s review-ticket: %(message)s", datefmt="%H:%M:%S")
    )
    root = logging.getLogger("review_ticket")
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(numeric)
    root.propagate = False


def configure_logging_from_env() -> None:
    configure_logging(os.environ.get("REVIEW_TICKET_LOG_LEVEL", "warning"))
