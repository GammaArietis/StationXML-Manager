"""Helpers for optional datetime-local fields in the NiceGUI web views."""

from __future__ import annotations


def iso_to_datetime_local_field(iso: str | None) -> str:
    """Map stored ISO string to value for HTML datetime-local (minute precision)."""
    if not iso:
        return ""
    s = str(iso).strip()
    if len(s) >= 16 and s[10] == "T":
        return s[:16]
    return s


def datetime_local_to_db(set_enabled: bool, raw_value: str | None) -> str | None:
    """If editing is not enabled, always None. Otherwise None for empty/invalid input."""
    if not set_enabled:
        return None
    if raw_value is None:
        return None
    v = str(raw_value).strip()
    if not v:
        return None
    if len(v) == 16 and v[10] == "T":
        return v + ":00"
    return v
