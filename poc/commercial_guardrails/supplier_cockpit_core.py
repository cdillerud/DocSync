from __future__ import annotations

import csv
import hashlib
from io import StringIO
from pathlib import Path
from typing import Iterable, Mapping, Sequence


EDITABLE_FIELDS = ("decision", "decision_by", "decision_notes")
DECISION_OPTIONS = ("", "APPROVE", "HOLD", "REJECT")


def load_csv_records(path: str | Path) -> list[dict[str, str]]:
    source = Path(path)
    if not source.exists():
        return []
    with source.open(newline="", encoding="utf-8-sig") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def record_key(record: Mapping[str, object]) -> tuple[str, str, str]:
    """Return a stable queue-item identity for merging local review decisions."""
    return (
        str(record.get("gpi_item_no") or "").strip().casefold(),
        str(record.get("supplier_item_no") or "").strip().casefold(),
        str(record.get("effective_date") or "").strip(),
    )


def decision_widget_scope(
    decision_path: str | Path,
    key: tuple[str, str, str],
) -> str:
    """Return a stable widget scope unique to one review run and one queue item.

    Two separate supplier-review runs can legitimately contain the same GPI item,
    supplier item, and effective date. The decision-log path identifies the run so
    Streamlit widget state cannot leak from one run into another.
    """
    run_identity = str(Path(decision_path).resolve()).casefold()
    payload = "\x1f".join((run_identity, *key))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def merge_saved_decisions(
    queue_records: Sequence[Mapping[str, object]],
    saved_records: Sequence[Mapping[str, object]],
) -> list[dict]:
    """Overlay locally saved decision fields onto a freshly generated approval queue."""
    saved_by_key = {
        record_key(record): record
        for record in saved_records
        if any(record_key(record))
    }
    merged: list[dict] = []
    for record in queue_records:
        row = dict(record)
        saved = saved_by_key.get(record_key(record), {})
        for field in EDITABLE_FIELDS:
            row[field] = str(saved.get(field, row.get(field, "")) or "")
        merged.append(row)
    return merged


def update_decision(
    records: Sequence[Mapping[str, object]],
    key: tuple[str, str, str],
    *,
    decision: str,
    decision_by: str,
    decision_notes: str,
) -> list[dict]:
    """Return queue records with one item's local human decision updated."""
    output: list[dict] = []
    found = False
    for record in records:
        row = dict(record)
        if record_key(row) == key:
            row["decision"] = str(decision or "").strip().upper()
            row["decision_by"] = str(decision_by or "").strip()
            row["decision_notes"] = str(decision_notes or "").strip()
            found = True
        output.append(row)
    if not found:
        raise ValueError("The selected approval item is no longer present in the queue.")
    return output


def summarize_queue(records: Sequence[Mapping[str, object]]) -> dict:
    return {
        "items": len(records),
        "protected_items": sum(
            str(row.get("queue_status") or "").strip().upper() == "PROTECTED_REVIEW"
            for row in records
        ),
        "affected_customers": sum(_float(row.get("affected_customers")) for row in records),
        "protected_customers": sum(_float(row.get("protected_customers")) for row in records),
        "estimated_margin_erosion": sum(
            _float(row.get("estimated_margin_erosion")) for row in records
        ),
    }


def filter_records(
    records: Sequence[Mapping[str, object]],
    *,
    statuses: Iterable[str] = (),
    supplier_text: str = "",
    item_text: str = "",
) -> list[dict]:
    wanted_statuses = {str(value).strip().upper() for value in statuses if str(value).strip()}
    supplier_key = supplier_text.strip().casefold()
    item_key = item_text.strip().casefold()
    output: list[dict] = []
    for record in records:
        status = str(record.get("queue_status") or "").strip().upper()
        supplier = str(record.get("supplier_name") or "").casefold()
        item = str(record.get("gpi_item_no") or "").casefold()
        if wanted_statuses and status not in wanted_statuses:
            continue
        if supplier_key and supplier_key not in supplier:
            continue
        if item_key and item_key not in item:
            continue
        output.append(dict(record))
    return output


def detail_rows_for_item(
    detail_records: Sequence[Mapping[str, object]],
    item_no: str,
) -> list[dict]:
    key = item_no.strip().casefold()
    if not key:
        return []
    rows = [
        dict(row)
        for row in detail_records
        if str(row.get("gpi_item_no") or "").strip().casefold() == key
        and str(row.get("customer_no") or "").strip()
    ]
    rows.sort(
        key=lambda row: (
            -_float(row.get("estimated_margin_erosion")),
            str(row.get("customer_no") or ""),
        )
    )
    return rows


def _float(value: object) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _truthy(value: object) -> bool:
    return str(value or "").strip().casefold() in {"true", "1", "yes", "y"}


def validate_detail_consistency(
    queue_record: Mapping[str, object],
    detail_rows: Sequence[Mapping[str, object]],
    *,
    erosion_tolerance: float = 0.02,
) -> list[str]:
    """Detect a stale or mismatched customer-detail snapshot before a reviewer can act.

    The approval queue and customer detail are generated from the same margin analysis. If
    their customer count, protected-customer count, erosion total, or top exposure disagree,
    the cockpit must treat the detail file as stale rather than silently displaying mixed runs.
    """
    item = str(queue_record.get("gpi_item_no") or "selected item").strip()
    expected_customers = int(round(_float(queue_record.get("affected_customers"))))
    expected_protected = int(round(_float(queue_record.get("protected_customers"))))
    expected_erosion = _float(queue_record.get("estimated_margin_erosion"))
    expected_top = str(queue_record.get("top_customer_no") or "").strip().casefold()

    actual_customers = len(detail_rows)
    actual_protected = sum(_truthy(row.get("special_pricing_protected")) for row in detail_rows)
    actual_erosion = sum(_float(row.get("estimated_margin_erosion")) for row in detail_rows)
    actual_top = ""
    if detail_rows:
        actual_top_row = max(
            detail_rows,
            key=lambda row: _float(row.get("estimated_margin_erosion")),
        )
        actual_top = str(actual_top_row.get("customer_no") or "").strip().casefold()

    errors: list[str] = []
    if actual_customers != expected_customers:
        errors.append(
            f"{item}: customer detail has {actual_customers} row(s), but the approval queue expects {expected_customers}"
        )
    if actual_protected != expected_protected:
        errors.append(
            f"{item}: customer detail has {actual_protected} protected customer(s), but the approval queue expects {expected_protected}"
        )
    if abs(actual_erosion - expected_erosion) > max(erosion_tolerance, abs(expected_erosion) * 0.0001):
        errors.append(
            f"{item}: customer-detail erosion ${actual_erosion:,.2f} does not match queue erosion ${expected_erosion:,.2f}"
        )
    if expected_top and actual_top and actual_top != expected_top:
        errors.append(
            f"{item}: customer detail top exposure does not match the approval queue"
        )
    return errors


def validate_decisions(records: Sequence[Mapping[str, object]]) -> list[str]:
    errors: list[str] = []
    for index, record in enumerate(records, start=1):
        item = str(record.get("gpi_item_no") or f"row {index}").strip()
        status = str(record.get("queue_status") or "").strip().upper()
        decision = str(record.get("decision") or "").strip().upper()
        decision_by = str(record.get("decision_by") or "").strip()

        if decision and decision not in DECISION_OPTIONS:
            errors.append(f"{item}: unsupported decision {decision!r}")
            continue
        if decision and not decision_by:
            errors.append(f"{item}: decision_by is required when a decision is entered")
        if status == "PROTECTED_REVIEW" and decision == "APPROVE":
            errors.append(
                f"{item}: PROTECTED_REVIEW cannot be approved in the generic cockpit; resolve the pricing guardrail first"
            )
    return errors


def records_to_csv(records: Sequence[Mapping[str, object]]) -> str:
    if not records:
        return ""

    fieldnames: list[str] = []
    for record in records:
        for key in record.keys():
            if key not in fieldnames:
                fieldnames.append(str(key))
    for field in EDITABLE_FIELDS:
        if field not in fieldnames:
            fieldnames.append(field)

    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    for record in records:
        row = {key: record.get(key, "") for key in fieldnames}
        writer.writerow(row)
    return buffer.getvalue()


def write_decision_csv(records: Sequence[Mapping[str, object]], path: str | Path) -> None:
    errors = validate_decisions(records)
    if errors:
        raise ValueError("; ".join(errors))
    Path(path).write_text(records_to_csv(records), encoding="utf-8")
