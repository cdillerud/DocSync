from __future__ import annotations

from urllib.parse import quote

from bc_client import (
    BusinessCentralClient,
    BusinessCentralSettings,
)


def _normalize_decision_note(decision_note: str) -> str:
    normalized = decision_note.strip()

    if not normalized:
        raise RuntimeError(
            "STOP: supplied DecisionNote may not be blank."
        )

    if "\r" in normalized or "\n" in normalized:
        raise RuntimeError(
            "STOP: DecisionNote must be a single line."
        )

    return normalized


def _get_quote(
    client: BusinessCentralClient,
    quote_no: int,
) -> dict:
    filter_value = quote(
        f"entryNo eq {quote_no}",
        safe="",
    )

    payload = client.get_json(
        "packagingQuotes"
        f"?$filter={filter_value}"
        "&$select=id,entryNo,status,decisionNote"
    )

    rows = payload.get("value")

    if not isinstance(rows, list):
        raise RuntimeError(
            "STOP: Business Central quote response did not "
            "contain a value array."
        )

    if len(rows) != 1:
        raise RuntimeError(
            f"STOP: expected one Quote {quote_no} row; "
            f"received {len(rows)}."
        )

    row = rows[0]

    if not isinstance(row, dict):
        raise RuntimeError(
            "STOP: Business Central quote row was not an object."
        )

    return row


def write_decision_note_native(
    *,
    quote_no: int,
    decision_note: str,
) -> dict:
    if quote_no == 67:
        raise RuntimeError(
            "STOP: Packaging Quote 67 is protected and may not "
            "be used by the native decision-note writer."
        )

    normalized = _normalize_decision_note(
        decision_note
    )

    settings = (
        BusinessCentralSettings.from_environment()
    )

    client = BusinessCentralClient(settings)

    before = _get_quote(
        client,
        quote_no,
    )

    status_before = str(
        before.get("status") or ""
    )

    if status_before != "Ready":
        raise RuntimeError(
            "STOP: decision notes may only be written by this "
            "utility while the quote is Ready. "
            f"Current status: {status_before}"
        )

    quote_id = str(
        before.get("id") or ""
    )

    if not quote_id:
        raise RuntimeError(
            "STOP: Business Central did not return the quote id."
        )

    etag = str(
        before.get("@odata.etag") or ""
    )

    if not etag:
        raise RuntimeError(
            "STOP: Business Central did not return an OData ETag."
        )

    previous_note = str(
        before.get("decisionNote") or ""
    )

    client.patch_json(
        f"packagingQuotes({quote_id})",
        body={
            "decisionNote": normalized,
        },
        etag=etag,
    )

    after = _get_quote(
        client,
        quote_no,
    )

    status_after = str(
        after.get("status") or ""
    )

    persisted_note = str(
        after.get("decisionNote") or ""
    )

    if status_after != "Ready":
        raise RuntimeError(
            "STOP: decision-note write unexpectedly changed "
            f"quote status to {status_after}."
        )

    if persisted_note != normalized:
        raise RuntimeError(
            "STOP: Business Central decision-note "
            "verification failed."
        )

    return {
        "quoteNo": int(
            after.get("entryNo")
        ),
        "quoteId": str(
            after.get("id") or ""
        ),
        "status": status_after,
        "previousDecisionNote": previous_note,
        "decisionNote": persisted_note,
        "written": True,
    }