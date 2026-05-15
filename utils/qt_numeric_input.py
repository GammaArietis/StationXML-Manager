"""PyQt6 numeric validators and safe parsing (locale C, decimal point)."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt6.QtCore import QLocale
from PyQt6.QtGui import QDoubleValidator, QIntValidator
from PyQt6.QtWidgets import QLineEdit, QTableWidget

_C_LOCALE = QLocale(QLocale.Language.C)


def c_double_validator(
    parent=None,
    bottom: float = -1e18,
    top: float = 1e18,
    decimals: int = 12,
) -> QDoubleValidator:
    validator = QDoubleValidator(bottom, top, decimals, parent)
    validator.setLocale(_C_LOCALE)
    validator.setNotation(QDoubleValidator.Notation.StandardNotation)
    return validator


def c_int_validator(
    parent=None,
    bottom: int = -2_000_000_000,
    top: int = 2_000_000_000,
) -> QIntValidator:
    validator = QIntValidator(bottom, top, parent)
    validator.setLocale(_C_LOCALE)
    return validator


def apply_c_double_validator(line_edit: QLineEdit, **kwargs) -> None:
    line_edit.setValidator(c_double_validator(line_edit, **kwargs))


def apply_c_int_validator(line_edit: QLineEdit, **kwargs) -> None:
    line_edit.setValidator(c_int_validator(line_edit, **kwargs))


def parse_float_text(
    text: str,
    field_label: str,
    *,
    allow_empty: bool = False,
    default_if_empty: float = 0.0,
) -> Tuple[Optional[float], Optional[str]]:
    stripped = (text or "").strip()
    if not stripped:
        if allow_empty:
            return default_if_empty, None
        return None, f"Il campo «{field_label}» è vuoto."
    try:
        return float(stripped), None
    except ValueError:
        return (
            None,
            f"Valore non valido in «{field_label}»: usa solo numeri con il punto decimale (es. 1.23).",
        )


def parse_table_float(
    table: QTableWidget,
    row: int,
    col: int,
    field_label: str,
    *,
    allow_empty: bool = False,
    default_if_empty: float = 0.0,
) -> Tuple[Optional[float], Optional[str]]:
    item = table.item(row, col)
    if item is None:
        if allow_empty:
            return default_if_empty, None
        return None, f"Cella mancante in «{field_label}» (riga {row + 1})."
    return parse_float_text(
        item.text(),
        field_label,
        allow_empty=allow_empty,
        default_if_empty=default_if_empty,
    )


def parse_pz_table_pairs(
    table: QTableWidget,
    table_name: str,
) -> Tuple[Optional[List[Tuple[float, float]]], Optional[str]]:
    pairs: List[Tuple[float, float]] = []
    for row in range(table.rowCount()):
        real_val, err = parse_table_float(
            table, row, 0, f"{table_name} — riga {row + 1}, Real"
        )
        if err:
            return None, err
        imag_val, err = parse_table_float(
            table, row, 1, f"{table_name} — riga {row + 1}, Imaginary"
        )
        if err:
            return None, err
        pairs.append((real_val, imag_val))
    return pairs, None
