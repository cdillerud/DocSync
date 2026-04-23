"""Deterministic Coloplast-style forecast-sheet parser.

No LLM. No fuzzy side channels. No "best effort" inference that
mutates meaning. Ambiguity surfaces as structured
``PlanningRowError`` entries, never as silently invented intent.

Shape assumption (Coloplast-specific):
  * One row per item (horizontal layout).
  * Required canonical columns: ``item_no`` (one of: Item, SKU, Item
    Number, Item No, Part Number, Part No).
  * Optional canonical columns: ``description`` (Description, Item
    Description), ``uom`` (UOM, UM, Unit, Unit of Measure).
  * Forecast columns: one column per period, labeled either weekly
    (``W15``, ``Week 15``, ``2026-W15``) or monthly (``2026-04``,
    ``Apr 2026``, ``April 2026``). The parser emits one
    ``PlanningRow`` per (item_row × period_column) cell.
  * Footer / total rows whose item_no cell is one of
    ``{"total", "grand total", "sum", "totals"}`` (case-insensitive)
    are skipped and recorded in ``skipped_rows``.
  * Blank rows (every cell empty/whitespace) are skipped.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .types import (
    PlanningParseResult,
    PlanningRow,
    PlanningRowError,
    PlanningSheet,
)


# ── Canonical column aliases (case-insensitive, whitespace-normalized) ────

_CANONICAL_ALIASES: Dict[str, Tuple[str, ...]] = {
    "item_no": (
        "item", "item no", "item number", "item_no",
        "sku", "part no", "part number",
    ),
    "description": (
        "description", "item description", "desc",
    ),
    "uom": (
        "uom", "um", "unit", "unit of measure",
    ),
}

_FOOTER_ITEM_MARKERS = frozenset({"total", "grand total", "sum", "totals"})


# ── Period-column recognizers ──────────────────────────────────────────────

# Weekly: W15, Week 15, 2026-W15, 2026 W15  (week number 1..53)
_WEEKLY_PATTERNS: Tuple[re.Pattern, ...] = (
    re.compile(r"^\s*(?:week\s*|w)\s*(?P<week>\d{1,2})\s*$", re.IGNORECASE),
    re.compile(
        r"^\s*(?P<year>\d{4})\s*[-/\s]?\s*w\s*(?P<week>\d{1,2})\s*$",
        re.IGNORECASE,
    ),
)

# Monthly: 2026-04, 04/2026, April 2026, Apr 2026
_MONTHLY_PATTERN_NUMERIC = re.compile(
    r"^\s*(?:(?P<year1>\d{4})\s*[-/\s]\s*(?P<m1>\d{1,2})"
    r"|(?P<m2>\d{1,2})\s*[-/\s]\s*(?P<year2>\d{4}))\s*$"
)
_MONTH_NAMES = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)
_MONTHLY_PATTERN_NAME = re.compile(
    r"^\s*(?P<name>jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may"
    r"|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember|t)?|oct(?:ober)?"
    r"|nov(?:ember)?|dec(?:ember)?)"
    r"\s*[-/\s]?\s*(?P<year>\d{4})\s*$",
    re.IGNORECASE,
)


def _norm_header(cell: Any) -> str:
    return re.sub(r"\s+", " ", str(cell or "").strip().lower())


def _iso_week_to_date(year: int, week: int) -> Optional[date]:
    """Return the Monday of the given ISO year-week, or None if invalid."""
    try:
        return date.fromisocalendar(year, week, 1)
    except (ValueError, TypeError):
        return None


def _parse_period_header(
    header_cell: Any, default_year: int,
) -> Optional[Tuple[str, date, str]]:
    """Return ``(label, period_start, kind)`` if header is a recognized
    period column, else ``None``.

    ``default_year`` is used for weekly labels that omit the year
    (e.g. ``"W15"``). Monthly labels always carry the year explicitly;
    nothing is silently invented.
    """
    raw = str(header_cell or "").strip()
    if not raw:
        return None

    # Weekly patterns first (so "W15" doesn't ever match month-name logic).
    for pat in _WEEKLY_PATTERNS:
        m = pat.match(raw)
        if not m:
            continue
        year = int(m.groupdict().get("year") or default_year)
        week = int(m.group("week"))
        if not (1 <= week <= 53):
            return None
        d = _iso_week_to_date(year, week)
        if d is None:
            return None
        return (f"{year}-W{week:02d}", d, "weekly")

    # Numeric monthly (YYYY-MM / MM-YYYY variants).
    m = _MONTHLY_PATTERN_NUMERIC.match(raw)
    if m:
        if m.group("year1"):
            year = int(m.group("year1"))
            month = int(m.group("m1"))
        else:
            year = int(m.group("year2"))
            month = int(m.group("m2"))
        if not (1 <= month <= 12):
            return None
        return (f"{year}-{month:02d}", date(year, month, 1), "monthly")

    # Named monthly (Apr 2026 / April 2026).
    m = _MONTHLY_PATTERN_NAME.match(raw)
    if m:
        name = m.group("name").lower()
        year = int(m.group("year"))
        # Match first month whose name starts with the captured prefix.
        for idx, full in enumerate(_MONTH_NAMES, start=1):
            if full.startswith(name) or name.startswith(full[:3]):
                return (f"{year}-{idx:02d}", date(year, idx, 1), "monthly")
        return None

    return None


# ── Column-map builder ─────────────────────────────────────────────────────

def _build_column_map(header_row: List[Any]) -> Dict[str, int]:
    mapping: Dict[str, int] = {}
    for idx, cell in enumerate(header_row):
        norm = _norm_header(cell)
        if not norm:
            continue
        for canonical, aliases in _CANONICAL_ALIASES.items():
            if canonical in mapping:
                continue
            if norm in aliases:
                mapping[canonical] = idx
                break
    return mapping


def _build_period_columns(
    header_row: List[Any], default_year: int,
) -> Tuple[Tuple[int, str, date, str], ...]:
    out: List[Tuple[int, str, date, str]] = []
    for idx, cell in enumerate(header_row):
        parsed = _parse_period_header(cell, default_year)
        if parsed is None:
            continue
        label, start, kind = parsed
        out.append((idx, label, start, kind))
    return tuple(out)


# ── Cell helpers ───────────────────────────────────────────────────────────

def _is_blank_row(row: List[Any]) -> bool:
    for cell in row:
        if cell is None:
            continue
        if isinstance(cell, str) and not cell.strip():
            continue
        return False
    return True


def _read_str(row: List[Any], idx: Optional[int]) -> str:
    if idx is None or idx < 0 or idx >= len(row):
        return ""
    v = row[idx]
    if v is None:
        return ""
    return str(v).strip()


def _parse_qty_cell(cell: Any) -> Tuple[Optional[float], Optional[str]]:
    """Return ``(qty, error_code)``. A blank cell returns ``(None, None)``
    and the parser silently skips it — forecasts legitimately have holes.
    """
    if cell is None:
        return None, None
    if isinstance(cell, bool):
        return None, "qty_not_numeric"
    if isinstance(cell, (int, float)):
        return float(cell), None
    s = str(cell).strip()
    if not s:
        return None, None
    # Strip commas and whitespace only — never currency symbols, never
    # best-effort coercion. If it doesn't parse cleanly, it's an error.
    cleaned = s.replace(",", "")
    try:
        return float(cleaned), None
    except ValueError:
        return None, "qty_not_numeric"


# ── Public parser ──────────────────────────────────────────────────────────

def parse_coloplast_sheet(sheet: PlanningSheet) -> PlanningParseResult:
    """Parse a Coloplast-shaped forecast sheet into a typed result.

    Strictly deterministic: same input always produces the same output.
    """
    # Default year for bare "W15"-style week labels. We pick the year
    # of today's UTC date — this is the ONE non-pure input, and it
    # affects only weekly labels that omit the year explicitly.
    # Callers that need determinism across calendar days should pass
    # year-qualified labels ("2026-W15").
    default_year = date.today().year

    header_row = list(sheet.header_row or [])
    data_rows = list(sheet.data_rows or [])

    errors: List[PlanningRowError] = []

    column_map = _build_column_map(header_row)
    period_columns = _build_period_columns(header_row, default_year)

    if "item_no" not in column_map:
        errors.append(PlanningRowError(
            source_row_index=-1,
            source_column_index=None,
            severity="error",
            code="missing_required_column_item_no",
            message=(
                "No 'item_no' column recognized in header row. Expected one "
                f"of: {sorted(_CANONICAL_ALIASES['item_no'])}."
            ),
        ))
    if not period_columns:
        errors.append(PlanningRowError(
            source_row_index=-1,
            source_column_index=None,
            severity="error",
            code="no_period_columns_recognized",
            message=(
                "No period columns recognized in header row. Weekly "
                "(W15 / Week 15 / 2026-W15) and monthly (2026-04 / "
                "Apr 2026) formats are supported."
            ),
        ))

    rows: List[PlanningRow] = []
    skipped: List[int] = []

    if "item_no" not in column_map or not period_columns:
        # Cannot parse data rows without structural anchors. Return
        # header errors only — do NOT attempt to guess.
        return PlanningParseResult(
            rows=tuple(rows),
            errors=tuple(errors),
            column_map=column_map,
            period_columns=period_columns,
            skipped_rows=tuple(skipped),
        )

    item_col = column_map["item_no"]
    uom_col = column_map.get("uom")

    for row_idx, raw_row in enumerate(data_rows):
        row = list(raw_row or [])

        if _is_blank_row(row):
            skipped.append(row_idx)
            continue

        item_no_raw = _read_str(row, item_col)
        if item_no_raw.lower() in _FOOTER_ITEM_MARKERS:
            skipped.append(row_idx)
            continue

        if not item_no_raw:
            errors.append(PlanningRowError(
                source_row_index=row_idx,
                source_column_index=item_col,
                severity="error",
                code="missing_item_no",
                message="Row has no item_no value.",
                raw_value=None,
            ))
            continue

        uom = _read_str(row, uom_col) or None

        for col_idx, period_label, period_start, period_kind in period_columns:
            cell = row[col_idx] if col_idx < len(row) else None
            qty, err_code = _parse_qty_cell(cell)

            if err_code is not None:
                errors.append(PlanningRowError(
                    source_row_index=row_idx,
                    source_column_index=col_idx,
                    severity="error",
                    code=err_code,
                    message=(
                        f"Quantity cell at period {period_label!r} did not "
                        "parse as a number."
                    ),
                    raw_value=cell,
                ))
                continue

            if qty is None:
                # Legitimately empty cell — forecasts have holes.
                continue

            if qty < 0:
                errors.append(PlanningRowError(
                    source_row_index=row_idx,
                    source_column_index=col_idx,
                    severity="error",
                    code="negative_qty",
                    message=(
                        f"Negative quantity {qty} at period {period_label!r}."
                    ),
                    raw_value=cell,
                ))
                continue

            rows.append(PlanningRow(
                customer_no=sheet.customer_no.strip(),
                item_no=item_no_raw,
                period_label=period_label,
                period_start=period_start,
                period_kind=period_kind,
                target_qty=qty,
                uom=uom,
                source_row_index=row_idx,
                source_column_index=col_idx,
            ))

    return PlanningParseResult(
        rows=tuple(rows),
        errors=tuple(errors),
        column_map=column_map,
        period_columns=period_columns,
        skipped_rows=tuple(skipped),
    )


__all__ = ["parse_coloplast_sheet"]
