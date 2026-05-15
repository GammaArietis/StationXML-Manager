"""Global Qt exception hook — show critical dialog instead of silent exit."""

from __future__ import annotations

import logging
import sys
import traceback
from types import TracebackType
from typing import Callable, Optional, Type

from PyQt6.QtWidgets import QApplication, QMessageBox

logger = logging.getLogger("App")

_MAX_TRACE_CHARS = 4000
_original_excepthook: Optional[Callable] = None


def install_qt_exception_hook() -> None:
    global _original_excepthook
    if _original_excepthook is not None:
        return
    _original_excepthook = sys.excepthook
    sys.excepthook = _qt_exception_hook


def _qt_exception_hook(
    exc_type: Type[BaseException],
    exc_value: BaseException,
    exc_tb: Optional[TracebackType],
) -> None:
    if issubclass(exc_type, KeyboardInterrupt):
        if _original_excepthook:
            _original_excepthook(exc_type, exc_value, exc_tb)
        return

    tb_text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    logger.critical("Unhandled exception:\n%s", tb_text)

    if len(tb_text) > _MAX_TRACE_CHARS:
        condensed = "…\n" + tb_text[-_MAX_TRACE_CHARS:]
    else:
        condensed = tb_text

    message = f"{exc_type.__name__}: {exc_value}\n\n{condensed}"

    app = QApplication.instance()
    if app is not None:
        try:
            QMessageBox.critical(None, "Errore Imprevisto", message)
        except Exception as dialog_err:
            logger.error("Could not show error dialog: %s", dialog_err)
            print(f"Errore Imprevisto:\n{message}", file=sys.stderr)
    else:
        print(f"Errore Imprevisto:\n{message}", file=sys.stderr)
