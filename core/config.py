"""Central application configuration (env + .env)."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

_DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:3000",
    "http://localhost:3000",
)


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    debug: bool = Field(default=False, validation_alias="DEBUG")

    database_path: Path = Field(
        default=Path("data/stationxml.db"),
        validation_alias="DATABASE_PATH",
    )
    schema_path: Path = Field(
        default=Path("database/schema.sql"),
        validation_alias="SCHEMA_PATH",
    )

    yasmine_base_url: str = Field(
        default="http://127.0.0.1:1841",
        validation_alias="YASMINE_BASE_URL",
    )

    log_file_path: Path = Field(
        default=Path("app.log"),
        validation_alias="LOG_FILE_PATH",
    )

    # Comma-separated allowed browser origins (e.g. NiceGUI dev server).
    # CORS_ORIGINS=* is accettato solo con DEBUG=true (sviluppo locale).
    cors_origins: str = Field(
        default="http://127.0.0.1:8080,http://localhost:8080",
        validation_alias="CORS_ORIGINS",
    )

    # Limite richieste/minuto per IP sul prefisso API (0 = disattivato).
    api_rate_limit_per_minute: int = Field(
        default=120,
        validation_alias="API_RATE_LIMIT_PER_MINUTE",
    )


@lru_cache
def get_settings() -> AppSettings:
    return AppSettings()


def cors_allow_origins(settings: AppSettings | None = None) -> List[str]:
    """
    Origini CORS da CORS_ORIGINS (.env), lista separata da virgole.
    In produzione (DEBUG=false) non si usa mai '*': viene ignorato e si applica il default sicuro.
    """
    s = settings or get_settings()
    raw = (s.cors_origins or "").strip()
    if raw == "*":
        if s.debug:
            logger.warning(
                "CORS_ORIGINS=* con DEBUG=true: consentito solo in sviluppo locale attendibile."
            )
            return ["*"]
        logger.warning(
            "CORS_ORIGINS=* ignorato in produzione (DEBUG=false); "
            "uso origini predefinite locali. Imposta CORS_ORIGINS con URL espliciti."
        )
        return list(_DEFAULT_CORS_ORIGINS)
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins:
        return list(_DEFAULT_CORS_ORIGINS)
    return origins


def cors_allow_credentials(origins: List[str]) -> bool:
    """Con Allow-Origin * i browser vietano credenziali: disattiviamo i cookie cross-site."""
    return "*" not in origins


def api_rate_limit_enabled(settings: AppSettings | None = None) -> bool:
    s = settings or get_settings()
    return s.api_rate_limit_per_minute > 0


def api_rate_limit_per_minute(settings: AppSettings | None = None) -> int:
    s = settings or get_settings()
    return max(1, int(s.api_rate_limit_per_minute))
