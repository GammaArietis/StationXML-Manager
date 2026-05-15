"""Sanitize phone numbers for FDSN StationXML / ObsPy (pattern: [0-9]+-[0-9]+)."""

from __future__ import annotations

import re
from typing import Optional

# ObsPy / FDSN StationXML: PhoneNumber text must match this pattern.
_FDSN_PHONE_PATTERN = re.compile(r"^[0-9]+-[0-9]+$")
_INVALID_LITERALS = frozenset({"", "none", "null", "n/a"})


def _is_valid_fdsn_phone(value: str) -> bool:
    if not _FDSN_PHONE_PATTERN.fullmatch(value):
        return False
    _country, subscriber = value.split("-", 1)
    return len(_country) >= 1 and len(subscriber) >= 3


def sanitize_fdsn_phone_string(
    raw: object,
    *,
    default_country_code: int = 39,
) -> Optional[str]:
    """
    Normalize a phone string to FDSN form ``country-subscriber`` (e.g. ``39-3331234567``).

    Returns None if the value cannot be represented safely (caller must omit Phone in XML).
    """
    if raw is None:
        return None

    text = str(raw).strip()
    if not text or text.lower() in _INVALID_LITERALS:
        return None

    # Keep only digits, '+' and '-'.
    cleaned = re.sub(r"[^\d+\-]", "", text)
    if not cleaned or cleaned in ("+", "-"):
        return None

    default_cc = str(int(default_country_code)) if default_country_code is not None else "39"
    if not default_cc.isdigit():
        default_cc = "39"

    # ``39-333...`` with country code and subscriber (not e.g. ``091-123456``).
    if cleaned.count("-") == 1 and not cleaned.startswith("+"):
        country, subscriber = cleaned.split("-", 1)
        if (
            country.isdigit()
            and subscriber.isdigit()
            and country == default_cc
            and _is_valid_fdsn_phone(cleaned)
        ):
            return cleaned
        # Treat other dash placements as noise; continue with digits only.
        cleaned = cleaned.replace("-", "")

    # International prefix ``+39...`` → strip '+', split country / subscriber.
    if cleaned.startswith("+"):
        digits = cleaned[1:].replace("-", "")
        if not digits.isdigit():
            return None
        if digits.startswith(default_cc) and len(digits) > len(default_cc):
            result = f"{default_cc}-{digits[len(default_cc):]}"
        else:
            result = None
            for cc_len in (3, 2, 1):
                if len(digits) <= cc_len:
                    continue
                candidate = f"{digits[:cc_len]}-{digits[cc_len:]}"
                if _is_valid_fdsn_phone(candidate):
                    result = candidate
                    break
        return result if result and _is_valid_fdsn_phone(result) else None

    # No '+': digits only, or malformed multiple dashes.
    if "-" in cleaned:
        return None

    digits = cleaned
    if not digits.isdigit():
        return None

    if digits.startswith(default_cc) and len(digits) > len(default_cc):
        result = f"{default_cc}-{digits[len(default_cc):]}"
    else:
        result = f"{default_cc}-{digits}"

    return result if _is_valid_fdsn_phone(result) else None
