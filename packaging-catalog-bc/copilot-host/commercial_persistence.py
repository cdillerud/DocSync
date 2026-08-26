from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from bc_client import BusinessCentralClient, BusinessCentralSettings
from commercial_agent_contract import (
    CommercialEvaluationRequest,
    CommercialEvaluationResult,
)


WRITE_API_GROUP = "commercialAgentWrite"

AGENT_TYPE_TO_BC = {
    "lowMargin": "Low Margin",
    "costChange": "Cost Change",
    "incorrectItem": "Incorrect Item",
}


def _utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _client() -> BusinessCentralClient:
    return BusinessCentralClient(BusinessCentralSettings.from_environment())


def _clean_optional(value: Any) -> Any:
    return None if value in (None, "") else value


def build_exception_body(
    request: CommercialEvaluationRequest,
    result: CommercialEvaluationResult,
    *,
    queue_entry_no: int = 0,
) -> dict[str, Any]:
    now = _utc_now_text()
    return {
        "agentType": AGENT_TYPE_TO_BC[result.agentType],
        "detectedAt": now,
        "sourceType": request.sourceType,
        "sourceSystemId": (
            None if request.sourceSystemId is None else str(request.sourceSystemId)
        ),
        "sourceKey": request.sourceKey,
        "customerNo": _clean_optional(request.customerNo),
        "itemNo": _clean_optional(request.itemNo),
        "documentType": _clean_optional(request.documentType),
        "documentNo": _clean_optional(request.documentNo),
        "severity": result.severity,
        "riskScore": result.riskScore,
        "confidenceScore": result.confidenceScore,
        "status": "New",
        "summary": result.summary,
        "finding": result.finding,
        "recommendedAction": result.recommendedAction,
        "aiModel": result.model,
        "evaluationVersion": result.evaluationVersion,
        "correlationId": str(result.correlationId),
        "queueEntryNo": queue_entry_no,
        "createdAt": now,
        "updatedAt": now,
    }


def build_evidence_body(
    evidence: Any,
    *,
    exception_entry_no: int,
) -> dict[str, Any]:
    return {
        "exceptionEntryNo": exception_entry_no,
        "evidenceType": evidence.evidenceType,
        "sourceSystem": evidence.sourceSystem,
        "sourceRecordType": evidence.sourceRecordType,
        "sourceSystemId": (
            None if evidence.sourceSystemId is None else str(evidence.sourceSystemId)
        ),
        "metric": evidence.metric,
        "currentValue": evidence.currentValue,
        "comparisonValue": _clean_optional(evidence.comparisonValue),
        "variance": evidence.variance or 0,
        "unit": _clean_optional(evidence.unit),
        "weight": evidence.weight,
        "explanation": evidence.explanation,
        "provenance": evidence.provenance,
        "capturedAt": _utc_now_text(),
    }


def persist_evaluation(
    request: CommercialEvaluationRequest,
    result: CommercialEvaluationResult,
    *,
    queue_entry_no: int = 0,
    client: BusinessCentralClient | None = None,
) -> dict[str, Any]:
    if result.correlationId != request.correlationId:
        raise ValueError("Correlation ID mismatch; persistence refused.")
    if result.agentType != request.agentType:
        raise ValueError("Agent type mismatch; persistence refused.")
    if not result.shouldSurface:
        return {
            "persisted": False,
            "reason": "not_surfaceable",
            "correlationId": str(result.correlationId),
        }

    bc = client or _client()
    exception = bc.post_api_json(
        WRITE_API_GROUP,
        "commercialAgentExceptionWrites",
        body=build_exception_body(
            request,
            result,
            queue_entry_no=queue_entry_no,
        ),
    )
    if not exception:
        raise RuntimeError("BC did not return the created commercial exception.")

    exception_entry_no = int(exception.get("entryNo") or 0)
    if exception_entry_no <= 0:
        raise RuntimeError("BC created exception without a valid entry number.")

    evidence_ids: list[str] = []
    for evidence in request.evidence:
        created = bc.post_api_json(
            WRITE_API_GROUP,
            "commercialAgentEvidenceWrites",
            body=build_evidence_body(
                evidence,
                exception_entry_no=exception_entry_no,
            ),
        )
        if created and created.get("id"):
            evidence_ids.append(str(created["id"]))

    return {
        "persisted": True,
        "exceptionId": str(exception.get("id") or ""),
        "exceptionEntryNo": exception_entry_no,
        "evidenceCount": len(evidence_ids),
        "evidenceIds": evidence_ids,
        "correlationId": str(result.correlationId),
    }
