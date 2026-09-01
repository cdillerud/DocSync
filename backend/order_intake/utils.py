"""Utility helpers for order intake parsers."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Optional


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def excel_serial_to_datetime(value: Any) -> Optional[datetime]:
    """Convert an Excel serial date to datetime when necessary.

    openpyxl normally converts formatted date cells for us. This helper makes the
    parser resilient to files where dates are stored as plain numeric values.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, (int, float)):
        return datetime(1899, 12, 30) + timedelta(days=float(value))
    return None


def clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def numeric_reference(value: Any) -> Optional[str]:
    """Return a normalized numeric-like reference, otherwise None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return text
    return None
