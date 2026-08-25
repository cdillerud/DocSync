from __future__ import annotations

from urllib.parse import quote

from bc_client import (
    BusinessCentralClient,
    BusinessCentralSettings,
)
from native_decision_note import write_decision_note_native
from native_prepare import (
    ActionName,
    prepare_native,
)


QUOTE_FIELDS = (
    "id",
    "entryNo",
    "status",
    "decisionNote",
    "lastEvaluatedAt",
)


def _single_quote(
    client: BusinessCentralClient,
    quote_no: int,
) -> dict:
    filter_value = quote(
        f"entryNo eq {quote_no}",
        safe="",
    )

    select_value = ",".join(QUOTE_FIELDS)

    payload = client.get_json(
        "packagingQuotes"
        f"?$filter={filter_value}"
        f"&$select={select_value}"
    )

    rows = payload.get("value")

    if not isinstance(rows, list):
        raise RuntimeError(
            "STOP: Business Central quote response did not "
            "contain a value array."
        )

    if len(rows) != 1:
        raise RuntimeError(
            f"STOP: expected one quote row for Quote {quote_no}; "
            f"received {len(rows)}."
        )

    row = rows[0]

    if not isinstance(row, dict):
        raise RuntimeError(
            "STOP: Business Central quote row was not an object."
        )

    return row


def _expected_status(
    action: ActionName,
    status_before: str,
) -> str:
    values = {
        "evaluate": status_before,
        "readyForReview": "Ready",
        "approve": "Approved",
        "reject": "Rejected",
        "reopen": "Draft",
    }

    return values[action]


def execute_native(
    *,
    quote_no: int,
    action: ActionName,
    confirmation_token: str,
    decision_note: str | None = None,
) -> dict:
    if quote_no == 67:
        raise RuntimeError(
            "STOP: Packaging Quote 67 is protected and may not "
            "be used by the native Execute flow."
        )

    # --------------------------------------------------------------
    # LIVE PREPARE + TOKEN VALIDATION BEFORE ANY WRITE
    # --------------------------------------------------------------
    preparation = prepare_native(
        quote_no=quote_no,
        action=action,
        decision_note=decision_note,
    )

    if preparation.get("isAllowed") is not True:
        raise RuntimeError(
            "STOP: action is not currently allowed. "
            f"Reason: {preparation.get('reason')}"
        )

    if preparation.get("confirmationRequired") is not True:
        raise RuntimeError(
            "STOP: live preparation does not require explicit "
            "confirmation. Execution is blocked."
        )

    expected_token = str(
        preparation.get("confirmationToken") or ""
    )

    if not confirmation_token:
        raise RuntimeError(
            "STOP: Execute mode requires the confirmation token "
            "returned by Prepare mode."
        )

    if confirmation_token != expected_token:
        raise RuntimeError(
            "STOP: confirmation token does not match the current "
            "live quote/action state. Prepare the action again "
            "before executing."
        )

    settings = (
        BusinessCentralSettings.from_environment()
    )

    client = BusinessCentralClient(settings)

    before_quote = _single_quote(
        client,
        quote_no,
    )

    status_before = str(
        before_quote.get("status") or ""
    )

    quote_id = str(
        before_quote.get("id") or ""
    )

    if not quote_id:
        raise RuntimeError(
            "STOP: quote SystemId was not returned."
        )

    if status_before != str(
        preparation.get("currentStatus") or ""
    ):
        raise RuntimeError(
            "STOP: quote status changed between Prepare and "
            "Execute validation."
        )

    evaluation_before = str(
        before_quote.get("lastEvaluatedAt") or ""
    )

    decision_note_written = False

    # --------------------------------------------------------------
    # OPTIONAL CONTROLLED NOTE WRITE
    #
    # Token was already validated against this exact note above.
    # --------------------------------------------------------------
    if decision_note is not None:
        if action not in {"approve", "reject"}:
            raise RuntimeError(
                "STOP: DecisionNote may only be supplied with "
                "approve or reject."
            )

        write_decision_note_native(
            quote_no=quote_no,
            decision_note=decision_note,
        )

        decision_note_written = True

        # Re-read the contract after the preliminary write.
        post_note = prepare_native(
            quote_no=quote_no,
            action=action,
            decision_note=None,
        )

        if post_note.get("isAllowed") is not True:
            raise RuntimeError(
                "STOP: decision note was written, but action "
                f"'{action}' is still not permitted. "
                f"Reason: {post_note.get('reason')}"
            )

        post_note_quote = _single_quote(
            client,
            quote_no,
        )

        if str(
            post_note_quote.get("status") or ""
        ) != status_before:
            raise RuntimeError(
                "STOP: quote status changed during decision-note "
                "processing."
            )

    # --------------------------------------------------------------
    # FINAL LIVE CONTRACT REVALIDATION IMMEDIATELY BEFORE POST
    # --------------------------------------------------------------
    live_preparation = prepare_native(
        quote_no=quote_no,
        action=action,
        decision_note=None,
    )

    if live_preparation.get("isAllowed") is not True:
        raise RuntimeError(
            "STOP: action became unavailable before execution. "
            f"Reason: {live_preparation.get('reason')}"
        )

    live_quote = _single_quote(
        client,
        quote_no,
    )

    live_status = str(
        live_quote.get("status") or ""
    )

    if live_status != status_before:
        raise RuntimeError(
            "STOP: quote status changed between initial read "
            f"and execution. Before: {status_before}; "
            f"Current: {live_status}"
        )

    live_quote_id = str(
        live_quote.get("id") or ""
    )

    if live_quote_id != quote_id:
        raise RuntimeError(
            "STOP: quote SystemId changed during execution."
        )

    expected_status = _expected_status(
        action,
        status_before,
    )

    # --------------------------------------------------------------
    # EXECUTE BOUND ACTION
    # Canonical 0.37 path:
    # packagingQuotes(<id>)/Microsoft.NAV.<action>
    # --------------------------------------------------------------
    client.post_json(
        f"packagingQuotes({quote_id})"
        f"/Microsoft.NAV.{action}",
        body={},
    )

    # --------------------------------------------------------------
    # VERIFY FRESH BC STATE
    # --------------------------------------------------------------
    after_quote = _single_quote(
        client,
        quote_no,
    )

    after_preparation = prepare_native(
        quote_no=quote_no,
        action=action,
        decision_note=None,
    )

    status_after = str(
        after_quote.get("status") or ""
    )

    if status_after != expected_status:
        raise RuntimeError(
            "STOP: action executed but resulting status was "
            "unexpected. "
            f"Expected: {expected_status}; "
            f"Actual: {status_after}"
        )

    if action == "evaluate":
        evaluation_after = str(
            after_quote.get("lastEvaluatedAt") or ""
        )

        if not evaluation_after:
            raise RuntimeError(
                "STOP: evaluate returned no Last Evaluated At "
                "value."
            )

        if (
            evaluation_before
            and evaluation_after == evaluation_before
        ):
            raise RuntimeError(
                "STOP: evaluate did not advance "
                "Last Evaluated At."
            )

    normalized_note = (
        decision_note.strip()
        if decision_note is not None
        else None
    )

    return {
        "schemaVersion": "1.0",
        "mode": "Execute",
        "quoteNo": int(
            after_quote.get("entryNo")
        ),
        "quoteId": str(
            after_quote.get("id") or ""
        ),
        "requestedAction": action,
        "executed": True,
        "statusBefore": status_before,
        "statusAfter": status_after,
        "expectedResultStatus": expected_status,
        "decisionNoteWritten": decision_note_written,
        "decisionNote": normalized_note,
        "resultingAllowedWriteActions": (
            after_preparation.get(
                "allowedWriteActions"
            )
            or []
        ),
        "recommendedNextAction": str(
            after_preparation.get(
                "recommendedNextAction"
            )
            or ""
        ),
        "contractVersion": str(
            after_preparation.get(
                "contractVersion"
            )
            or ""
        ),
    }