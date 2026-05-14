"""
Centralized logging: console + app.log for debugging API clients and validation.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from core.config import get_settings

_CONFIGURED = False


def configure_application_logging(
    log_file: Optional[Path] = None,
    *,
    console_level: int = logging.DEBUG,
    file_level: int = logging.DEBUG,
) -> None:
    """
    Attach console + file handler to the root logger.
    Default log path comes from AppSettings.log_file_path (LOG_FILE_PATH / .env).
    Safe to call multiple times (no duplicate handlers).
    """
    global _CONFIGURED
    if log_file is not None:
        log_path = Path(log_file).resolve()
    else:
        log_path = Path(get_settings().log_file_path).expanduser().resolve()

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    if not _CONFIGURED:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(file_level)
        fh.setFormatter(fmt)
        root.addHandler(fh)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(console_level)
        ch.setFormatter(fmt)
        root.addHandler(ch)

        _CONFIGURED = True


def log_pydantic_validation(logger: logging.Logger, exc: ValidationError, context: str = "") -> None:
    """Log Pydantic errors in a structured way (file + console via logger)."""
    prefix = f"{context}: " if context else ""
    logger.error("%sPydantic validation failed: %s", prefix, exc.errors())
    for err in exc.errors():
        logger.error("  loc=%s type=%s msg=%s", err.get("loc"), err.get("type"), err.get("msg"))


def log_network_error(
    logger: logging.Logger,
    service: str,
    exc: BaseException,
    detail: str = "",
) -> None:
    """Log external HTTP / connectivity failures with traceback to app.log."""
    msg = f"[{service}] {detail}: {exc}" if detail else f"[{service}]: {exc}"
    logger.exception(msg)
