from __future__ import annotations

import hashlib
from typing import Literal
from urllib.parse import quote

from bc_client import (
    BusinessCentralClient,
    BusinessCentralSettings,
)


ActionName = Literal[
    "evaluate",
    "readyForReview",
    "approve",
    "reject",
    "reopen",
]


SUMMARY_FIELDS = (
    "id",
    "entryNo",
    "status",
    "customerNo",
    "customerName",
    "description",
    "lineCount",
    "approvalLineCount",
    "hasPricingExceptions",
    "decisionNoteRequired",
    "primaryPricingExceptionStatus",
    "primaryPricingExceptionMessage",
    "primaryApprover",
    "decisionNote",
    "readyForCustomerPresentation",
    "customerEmailReady",
    "actionContractVersion",
    "actionResource",
    "fullQuoteExpandName",
    "canEvaluate",
    "canMoveToReadyForReview",
    "canApprove",
    "canReject",
    "canReopen",
    "rejectDecisionNoteRequired",
    "allowedWriteActions",
    "writeConfirmationRequired",
    "actionContractNote",
    "recommendedNextAction",
)


def _allowed_actions(summary: dict) -> list[str]:
    raw = str(summary.get("allowedWriteActions") or "")

    return [
        value.strip()
        for value in raw.split(",")
        if value.strip()
    ]


def _expected_status(
    action: ActionName,
    current_status: str,
) -> str:
    values = {
        "evaluate": current_status,
        "readyForReview": "Ready",
        "approve": "Approved",
        "reject": "Rejected",
        "reopen": "Draft",
    }

    return values[action]


def _confirmation_text(
    quote_no: int,
    action: ActionName,
) -> str:
    values = {
        "evaluate": (
            f"Evaluate Packaging Quote {quote_no} using the current "
            "Business Central pricing and guardrail rules?"
        ),
        "readyForReview": (
            f"Move Packaging Quote {quote_no} to Ready for Review?"
        ),
        "approve": (
            f"Approve Packaging Quote {quote_no}?"
        ),
        "reject": (
            f"Reject Packaging Quote {quote_no}?"
        ),
        "reopen": (
            f"Reopen Packaging Quote {quote_no} and return it to Draft?"
        ),
    }

    return values[action]


def _confirmation_token(
    *,
    quote_id: str,
    quote_no: int,
    current_status: str,
    action: ActionName,
    contract_version: str,
    decision_note: str,
) -> str:
    material = "|".join(
        (
            "gpi-packaging-quote-action",
            quote_id,
            str(quote_no),
            current_status,
            action,
            contract_version,
            decision_note,
        )
    )

    digest = hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()

    return (
        f"GPI-Q{quote_no}-"
        f"{action.upper()}-"
        f"{digest[:24]}"
    )


def _single_summary(
    client: BusinessCentralClient,
    quote_no: int,
) -> dict:
    filter_value = quote(
        f"entryNo eq {quote_no}",
        safe="",
    )

    select_value = ",".join(SUMMARY_FIELDS)

    payload = client.get_json(
        "packagingQuoteSummaries"
        f"?$filter={filter_value}"
        f"&$select={select_value}"
    )

    rows = payload.get("value")

    if not isinstance(rows, list):
        raise RuntimeError(
            "Business Central summary response did not contain "
            "a value array."
        )

    if len(rows) != 1:
        raise RuntimeError(
            f"Expected one summary row for Quote {quote_no}; "
            f"received {len(rows)}."
        )

    row = rows[0]

    if not isinstance(row, dict):
        raise RuntimeError(
            "Business Central summary row was not an object."
        )

    return row


def prepare_native(
    *,
    quote_no: int,
    action: ActionName,
    decision_note: str | None = None,
) -> dict:
    if quote_no == 67:
        raise RuntimeError(
            "STOP: Packaging Quote 67 is protected and may not "
            "be used by the native Prepare flow."
        )

    settings = BusinessCentralSettings.from_environment()
    client = BusinessCentralClient(settings)

    summary = _single_summary(
        client,
        quote_no,
    )

    contract_version = str(
        summary.get("actionContractVersion") or ""
    )

    if contract_version != "1.0":
        raise RuntimeError(
            "STOP: unsupported action contract version: "
            f"{contract_version}"
        )

    if str(summary.get("actionResource") or "") != "packagingQuotes":
        raise RuntimeError(
            "STOP: unexpected action resource: "
            f"{summary.get('actionResource')}"
        )

    allowed_actions = _allowed_actions(summary)

    is_allowed = action in allowed_actions

    reason: str | None = None

    if not is_allowed:
        if not allowed_actions:
            reason = (
                f"Action '{action}' is not currently permitted. "
                "Business Central exposes no write actions for the "
                "quote in its current state."
            )
        else:
            reason = (
                f"Action '{action}' is not currently permitted. "
                "Allowed actions: "
                + ", ".join(allowed_actions)
                + "."
            )

    elif summary.get("writeConfirmationRequired") is not True:
        reason = (
            f"Action '{action}' is advertised as available, but the "
            "Business Central contract does not require write "
            "confirmation. Execution is therefore blocked by the "
            "orchestrator safety policy."
        )
        is_allowed = False

    decision_note_provided = decision_note is not None

    normalized_note = (
        decision_note.strip()
        if decision_note_provided
        else ""
    )

    if decision_note_provided and action not in {
        "approve",
        "reject",
    }:
        raise RuntimeError(
            "STOP: DecisionNote may only be supplied with "
            "approve or reject."
        )

    if (
        decision_note_provided
        and not normalized_note
    ):
        raise RuntimeError(
            "STOP: supplied DecisionNote may not be blank."
        )

    if "\r" in normalized_note or "\n" in normalized_note:
        raise RuntimeError(
            "STOP: DecisionNote must be a single line."
        )

    if action == "approve":
        note_required = bool(
            summary.get("decisionNoteRequired")
        )
    elif action == "reject":
        note_required = bool(
            summary.get("rejectDecisionNoteRequired")
        )
    else:
        note_required = False

    note_enables_action = (
        not is_allowed
        and str(summary.get("status") or "") == "Ready"
        and action in {"approve", "reject"}
        and note_required
        and decision_note_provided
    )

    effective_allowed = (
        is_allowed
        or note_enables_action
    )

    effective_confirmation_required = (
        effective_allowed
    )

    effective_reason = (
        None
        if note_enables_action
        else reason
    )

    note_will_be_written = (
        decision_note_provided
        and action in {"approve", "reject"}
    )

    current_status = str(
        summary.get("status") or ""
    )

    quote_id = str(
        summary.get("id") or ""
    )

    quote_number = int(
        summary.get("entryNo")
    )

    expected_status = (
        _expected_status(
            action,
            current_status,
        )
        if effective_allowed
        else None
    )

    confirmation_text = (
        _confirmation_text(
            quote_number,
            action,
        )
        if effective_confirmation_required
        else None
    )

    token = _confirmation_token(
        quote_id=quote_id,
        quote_no=quote_number,
        current_status=current_status,
        action=action,
        contract_version=contract_version,
        decision_note=normalized_note,
    )

    return {
        "schemaVersion": "1.0",
        "mode": "Prepare",
        "quoteNo": quote_number,
        "quoteId": quote_id,
        "customerNo": str(
            summary.get("customerNo") or ""
        ),
        "customerName": str(
            summary.get("customerName") or ""
        ),
        "currentStatus": current_status,
        "requestedAction": action,
        "isAllowed": effective_allowed,
        "confirmationRequired":
            effective_confirmation_required,
        "confirmationText": confirmation_text,
        "expectedResultStatus": expected_status,
        "reason": effective_reason,
        "confirmationToken": (
            token
            if (
                effective_allowed
                and effective_confirmation_required
            )
            else None
        ),
        "allowedWriteActions": allowed_actions,
        "contractVersion": contract_version,
        "recommendedNextAction": str(
            summary.get("recommendedNextAction") or ""
        ),
        "hasPricingExceptions": bool(
            summary.get("hasPricingExceptions")
        ),
        "primaryPricingExceptionStatus": str(
            summary.get("primaryPricingExceptionStatus") or ""
        ),
        "primaryPricingExceptionMessage": str(
            summary.get("primaryPricingExceptionMessage") or ""
        ),
        "primaryApprover": str(
            summary.get("primaryApprover") or ""
        ),
        "decisionNoteRequired": note_required,
        "decisionNoteProvided": decision_note_provided,
        "decisionNote": (
            normalized_note
            if decision_note_provided
            else None
        ),
        "decisionNoteWillBeWritten":
            note_will_be_written,
        "decisionNoteEnablesAction":
            note_enables_action,
        "writeExecution": {
            "permitted": (
                effective_allowed
                and effective_confirmation_required
            ),
            "executeMode": "Execute",
            "confirmationTokenRequired": (
                effective_allowed
                and effective_confirmation_required
            ),
        },
    }