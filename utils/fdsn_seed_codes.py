"""FDSN SEED Appendix A channel code helpers."""

from __future__ import annotations

import math
import re
from typing import Iterable, Optional


def get_fdsn_band_code(
    sample_rate: float,
    is_broadband: bool = True,
    *,
    instrument_code: str | None = None,
) -> str:
    """Return the SEED band code for a sample rate in samples/second."""
    try:
        sr = float(sample_rate or 0.0)
    except (TypeError, ValueError):
        sr = 0.0

    # Accelerometers (instrument code N) are DC-capable: use the broadband branch
    # for the first letter proposal (e.g. 100 Hz -> H, not E).
    if str(instrument_code or "").strip().upper()[:1] == "N":
        is_broadband = True

    if sr >= 5000:
        return "G"
    if sr >= 1000:
        return "F"
    if sr >= 250:
        return "C"
    if sr >= 80:
        return "H" if is_broadband else "E"
    if sr >= 10:
        return "B" if is_broadband else "S"
    if sr > 1:
        return "M"
    if sr >= 0.1:
        return "L"
    if sr >= 0.01:
        return "V"
    if sr >= 0.001:
        return "U"
    return "R"


def _normalize_units(input_units: str) -> str:
    return re.sub(r"\s+", "", str(input_units or "").upper())


def get_instrument_code(input_units: str) -> str:
    """
    Return the FDSN instrument code from physical input units.

    Appendix A convention used here:
    - ``N`` for acceleration sensors (m/s**2 and common variants)
    - ``H`` for velocity sensors (m/s and common variants)

    Unknown or ambiguous units default to ``H`` because seismometer velocity
    channels are the common StationXML case and this avoids raising in UI flows.
    """
    units = _normalize_units(input_units)
    accel_markers = (
        "M/S**2",
        "M/S^2",
        "M/S/S",
        "M/SEC**2",
        "M/SEC^2",
        "M/SEC/SEC",
        "MPS2",
        "M/S2",
        "ACCEL",
        "ACCELERATION",
    )
    if any(marker in units for marker in accel_markers):
        return "N"

    velocity_markers = (
        "M/S",
        "M/SEC",
        "MPS",
        "M*S-1",
        "M/S**1",
        "VELOCITY",
        "VEL",
    )
    if any(marker in units for marker in velocity_markers):
        return "H"

    return "H"


def _pole_components(pole) -> tuple[float, float]:
    if isinstance(pole, complex):
        return float(pole.real), float(pole.imag)
    real_val = getattr(pole, "real_val", getattr(pole, "real", 0.0))
    imag_val = getattr(pole, "imag_val", getattr(pole, "imag", 0.0))
    return float(real_val or 0.0), float(imag_val or 0.0)


def get_corner_frequency_from_poles(
    poles: Iterable,
    *,
    pz_transfer_function_type: str = "LAPLACE (RADIANS/SECOND)",
) -> Optional[float]:
    """
    Estimate low corner frequency from the smallest non-zero pole magnitude.

    Poles in ``LAPLACE (HERTZ)`` are already in Hz; poles in radians/second are
    converted to Hz by dividing by ``2*pi``.
    """
    magnitudes = []
    for pole in poles or []:
        try:
            real_val, imag_val = _pole_components(pole)
            magnitude = math.hypot(real_val, imag_val)
        except (TypeError, ValueError):
            continue
        if magnitude > 1e-9:
            magnitudes.append(magnitude)

    if not magnitudes:
        return None

    min_mag = min(magnitudes)
    is_hertz = "HERTZ" in str(pz_transfer_function_type or "").upper()
    return min_mag if is_hertz else min_mag / (2 * math.pi)


def is_broadband_from_poles(
    poles: Iterable,
    *,
    pz_transfer_function_type: str = "LAPLACE (RADIANS/SECOND)",
    threshold_hz: float = 0.1,
) -> bool:
    """Return True when estimated corner frequency is <= 0.1 Hz."""
    corner_frequency = get_corner_frequency_from_poles(
        poles,
        pz_transfer_function_type=pz_transfer_function_type,
    )
    if corner_frequency is None:
        return False
    return corner_frequency <= threshold_hz
