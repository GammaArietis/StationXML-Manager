"""
Centralized SQLite bootstrap for all application entry points (Desktop, Web, API).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from core.config import AppSettings, get_settings
from database.db_manager import DatabaseManager

logger = logging.getLogger(__name__)

# Repository root (…/StationXML-Manager-V1)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

_db_manager: Optional[DatabaseManager] = None


def resolve_project_path(path: Path | str) -> Path:
    """Resolve relative paths against the project root (stable on headless servers)."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (PROJECT_ROOT / p).resolve()


def init_database(
    *,
    settings: AppSettings | None = None,
    db_path: Path | str | None = None,
    schema_path: Path | str | None = None,
) -> DatabaseManager:
    """
    Create the SQLite file and apply schema.sql (CREATE TABLE IF NOT EXISTS).

    Safe to call multiple times and from any entry point.
    """
    global _db_manager

    cfg = settings or get_settings()
    resolved_db = resolve_project_path(db_path if db_path is not None else cfg.database_path)
    resolved_schema = resolve_project_path(
        schema_path if schema_path is not None else cfg.schema_path
    )

    manager = DatabaseManager(resolved_db)
    manager.initialize_database(resolved_schema)

    _db_manager = manager
    logger.info("Database ready at %s", resolved_db)
    return manager


def get_database_manager() -> DatabaseManager:
    """Return the singleton manager, initializing the DB on first use."""
    if _db_manager is None:
        return init_database()
    return _db_manager
