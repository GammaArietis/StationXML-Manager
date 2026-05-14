import logging

from utils.logging_config import configure_application_logging


def setup_logger() -> None:
    """Backward-compatible entry point: delegates to centralized logging."""
    configure_application_logging()
