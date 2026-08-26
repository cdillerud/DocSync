from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

from ai_provider import ai_provider_configured, evaluate_with_ai
from bc_client import BusinessCentralClient, BusinessCentralSettings
from commercial_agent_service import (
    build_cost_change_request,
    build_incorrect_item_request,
    build_low_margin_request,
)
from commercial_persistence import persist_evaluation


READ_GROUP = "commercialAgents"
WRITE_GROUP = "commercialAgentWrite"


class QueueWorkerError(RuntimeError):
    pass


def _client() -> BusinessCentralClient:
    return BusinessCentralClient(BusinessCentralSettings.from_environment())


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _persistence_enabled() -> bool:
    return os.getenv("GPI_ENABLE_COMMERCIAL_PERSISTENCE", "0").strip() == "1"


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("value", [])
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _decode_odata_identifier(value: Any) -> str:
    text = str(value or "").strip()

    def replace_match(match: re.Match[str]) -> str:
        return chr(int(match.group(1), 16))

    return re.sub(r"_x([0-9A-Fa-f]{4})_", replace_match, text)


def get_next_pending_queue(
    *,
    client: BusinessCentralClient | None = None,
) -> dict[str, Any] | None:
    bc = client or _client()
    payload = bc.get_api_json(
        READ_GROUP,
        "commercialAgentQueueEntries?"
        "$filter=status eq 'Pending'&"
        "$orderby=priority desc,requestedAt asc&$top=1",
    )
    rows = _rows(payload)
    return rows[0] if rows else None


def _historical_invoice_line(
    queue: dict[str, Any],
    *,
    client: BusinessCentralClient,
) -> dict[str, Any]:
    document_no = str(queue.get("documentNo") or "").strip()
    source_key = str(queue.get("sourceKey") or "").strip()
    try:
        line_no = int(source_key.rsplit(":", 1)[1])
    except (IndexError, ValueError) as exc:
        raise QueueWorkerError(
            "Low Margin queue sourceKey does not contain a valid line number."
        ) from exc

    escaped_document = document_no.replace("'", "''")
    filter_text = (
        f"invoiceNo eq '{escaped_document}' and lineNo eq {line_no}"
    )
    encoded_filter = quote(filter_text, safe="()$=,' ")
    payload = client.get_api_json(
        "commercialGuardrails",
        f"historicalSalesLines?$filter={encoded_filter}&$top=2",
    )
    rows = _rows(payload)
    if len(rows) != 1:
        raise QueueWorkerError(
            "Expected exactly one posted sales invoice line for Low Margin queue work."
        )
    return rows[0]


def build_request_from_queue(
    queue: dict[str, Any],
    *,
    client: BusinessCentralClient | None = None,
):
    bc = client or _client()
    agent_type = _decode_odata_identifier(queue.get("agentType"))
    customer_no = str(queue.get("customerNo") or "").strip()
    item_no = str(queue.get("itemNo") or "").strip()
    document_no = str(queue.get("documentNo") or "").strip()
    source_system_id = queue.get("sourceSystemId") or None
    correlation_id = queue.get("correlationId") or None

    if agent_type == "Cost Change":
        return build_cost_change_request(
            item_no=item_no,
            previous_unit_cost=float(queue.get("previousValue") or 0),
            current_unit_cost=float(queue.get("currentValue") or 0),
            source_key=str(queue.get("sourceKey") or item_no),
            source_system_id=source_system_id,
            correlation_id=correlation_id,
        )

    if agent_type == "Incorrect Item":
        return build_incorrect_item_request(
            customer_no=customer_no,
            item_no=item_no,
            document_no=document_no,
            source_system_id=source_system_id,
            correlation_id=correlation_id,
        )

    if agent_type == "Low Margin":
        line = _historical_invoice_line(queue, client=bc)
        return build_low_margin_request(
            customer_no=customer_no,
            item_no=item_no,
            document_no=document_no,
            unit_price=float(queue.get("currentValue") or 0),
            unit_cost=float(queue.get("previousValue") or 0),
            quantity=float(line.get("quantity") or 0),
            line_amount=float(line.get("lineAmount") or 0),
            source_system_id=source_system_id,
            correlation_id=correlation_id,
        )

    raise QueueWorkerError(f"Unsupported queue agent type: {agent_type!r}")


def prepare_next_queue(
    *,
    client: BusinessCentralClient | None = None,
) -> dict[str, Any]:
    bc = client or _client()
    queue = get_next_pending_queue(client=bc)
    if queue is None:
        return {"status": "empty"}

    request = build_request_from_queue(queue, client=bc)
    screening = request.context.get("screening", {})
    return {
        "status": "prepared",
        "queue": queue,
        "screening": screening,
        "evaluationRequest": request.model_dump(mode="json"),
        "aiProviderConfigured": ai_provider_configured(),
        "persistenceEnabled": _persistence_enabled(),
    }


def _write_queue_snapshot(
    queue: dict[str, Any],
    *,
    client: BusinessCentralClient,
) -> dict[str, Any]:
    queue_id = str(queue.get("id") or "").strip()
    if not queue_id:
        raise QueueWorkerError("Queue record is missing id.")

    snapshot = client.get_api_json(
        WRITE_GROUP,
        f"commercialAgentQueueWrites({queue_id})",
    )
    if not isinstance(snapshot, dict):
        raise QueueWorkerError("Queue write API returned an invalid record.")

    snapshot_id = str(snapshot.get("id") or "").strip()
    if snapshot_id != queue_id:
        raise QueueWorkerError("Queue write API returned a different record id.")

    expected_entry = int(queue.get("entryNo") or 0)
    snapshot_entry = int(snapshot.get("entryNo") or 0)
    if expected_entry and snapshot_entry != expected_entry:
        raise QueueWorkerError("Queue write API returned a different queue entry.")

    expected_status = _decode_odata_identifier(queue.get("status"))
    snapshot_status = _decode_odata_identifier(snapshot.get("status"))
    if expected_status and snapshot_status != expected_status:
        raise QueueWorkerError(
            "Queue state changed before write: "
            f"expected {expected_status!r}, found {snapshot_status!r}."
        )

    etag = str(snapshot.get("@odata.etag") or "").strip()
    if not etag:
        raise QueueWorkerError("Queue write API record is missing @odata.etag.")

    return snapshot


def _patch_queue(
    queue: dict[str, Any],
    body: dict[str, Any],
    *,
    client: BusinessCentralClient,
) -> dict[str, Any] | None:
    snapshot = _write_queue_snapshot(queue, client=client)
    queue_id = str(snapshot.get("id") or "").strip()
    etag = str(snapshot.get("@odata.etag") or "").strip()
    return client.patch_api_json(
        WRITE_GROUP,
        f"commercialAgentQueueWrites({queue_id})",
        body=body,
        etag=etag,
    )


def execute_next_queue(
    *,
    client: BusinessCentralClient | None = None,
) -> dict[str, Any]:
    bc = client or _client()
    queue = get_next_pending_queue(client=bc)
    if queue is None:
        return {"status": "empty"}

    request = build_request_from_queue(queue, client=bc)
    screening = request.context.get("screening", {})
    should_evaluate = bool(screening.get("shouldEvaluate"))

    # Deterministically screened-out work does not need an AI provider or
    # exception/evidence persistence. Only candidates that actually require
    # AI evaluation are gated on those runtime controls.
    if should_evaluate:
        if not ai_provider_configured():
            raise QueueWorkerError(
                "AI provider is not configured; candidate queue execution is refused."
            )
        if not _persistence_enabled():
            raise QueueWorkerError(
                "GPI_ENABLE_COMMERCIAL_PERSISTENCE is not 1; candidate queue execution is refused."
            )

    claimed = _patch_queue(
        queue,
        {
            "status": "Processing",
            "startedAt": _utc_now_text(),
            "attemptCount": int(queue.get("attemptCount") or 0) + 1,
            "lastError": "",
        },
        client=bc,
    )
    if not claimed:
        raise QueueWorkerError("BC did not return the claimed queue record.")

    claimed_queue = {**queue, **claimed}

    try:
        if not should_evaluate:
            completed = _patch_queue(
                claimed_queue,
                {
                    "status": "Completed",
                    "completedAt": _utc_now_text(),
                    "exceptionEntryNo": 0,
                    "lastError": "",
                },
                client=bc,
            )
            return {
                "status": "completed_no_candidate",
                "queueEntryNo": queue.get("entryNo"),
                "screening": screening,
                "queue": completed,
            }

        result = evaluate_with_ai(request)
        persisted = persist_evaluation(
            request,
            result,
            queue_entry_no=int(queue.get("entryNo") or 0),
            client=bc,
        )
        exception_entry_no = int(persisted.get("exceptionEntryNo") or 0)
        completed = _patch_queue(
            claimed_queue,
            {
                "status": "Completed",
                "completedAt": _utc_now_text(),
                "exceptionEntryNo": exception_entry_no,
                "lastError": "",
            },
            client=bc,
        )
        return {
            "status": "completed",
            "queueEntryNo": queue.get("entryNo"),
            "screening": screening,
            "evaluationResult": result.model_dump(mode="json"),
            "persistence": persisted,
            "queue": completed,
        }
    except Exception as exc:
        latest = claimed_queue
        try:
            _patch_queue(
                latest,
                {
                    "status": "Failed",
                    "completedAt": _utc_now_text(),
                    "lastError": str(exc)[:2048],
                },
                client=bc,
            )
        except Exception:
            pass
        raise
