"""Best-effort raise of process open-file limits (cross-platform, non-fatal)."""

from __future__ import annotations

import logging
import os
import sys

logger = logging.getLogger(__name__)

_MIN_UNIX_SOFT = 4096
_TARGET_UNIX_SOFT_INF = 8192
_WINDOWS_STDIO_MAX = 8192


def maximize_open_files_limit() -> None:
    """
    Raise open-file / stdio limits where the OS allows.

    Never raises: failures are logged or printed and startup continues.
    """
    if sys.platform == "win32" or os.name == "nt":
        _maximize_windows_stdio()
    else:
        _maximize_unix_nofile()


def _maximize_unix_nofile() -> None:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)

        if hard == resource.RLIM_INFINITY:
            new_soft = max(int(soft), _TARGET_UNIX_SOFT_INF)
        else:
            new_soft = max(_MIN_UNIX_SOFT, int(hard))
            if new_soft > int(hard):
                new_soft = int(hard)

        resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
        logger.info(
            "RLIMIT_NOFILE adjusted: soft=%s (was %s), hard=%s",
            new_soft,
            soft,
            hard,
        )
    except ImportError:
        msg = "resource module not available; skipping open files limit adjustment"
        logger.debug(msg)
    except Exception as exc:
        msg = f"Could not raise open files limit (Unix): {exc}"
        logger.warning(msg)
        print(f"Warning: {msg}")


def _maximize_windows_stdio() -> None:
    try:
        import ctypes

        ctypes.windll.msvcrt._setmaxstdio(_WINDOWS_STDIO_MAX)
        logger.info("Windows C runtime max stdio streams set to %s", _WINDOWS_STDIO_MAX)
    except Exception as exc:
        msg = f"Could not raise Windows stdio limit: {exc}"
        logger.warning(msg)
        print(f"Warning: {msg}")
