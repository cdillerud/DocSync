# GPI Square9 Parity Engine - fail-closed shadow classifier.
# Classification/evidence only. Routing, BC resolution, dedupe, and delivery stay deterministic.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.parity_engine.contracts import (
    assert_valid_result,
    canonical_classification_schema,
    fail_closed_result,
)
from services.parity_engine.function_gateway_provider import (
    FunctionGatewayProvider,
)


SYSTEM_PROMPT = """You are the GPI Square9 parity-engine SHADOW document classifier.

Your output is evidence only. You are NOT authoritative for routing, Business Central
resolution, SharePoint destinations, posting, delivery, deduplication, or any write.

Rules:
1. Use only the supplied document evidence.
2. Select document_type only from the provided JSON Schema enum.
3. Extract references only when supported by the supplied evidence.
4. Never invent a Business Central record, destination folder, or delivery action.
5. If evidence is insufficient or contradictory, choose Unknown_Document when appropriate,
   set needs_review=true, and explain the ambiguity.
6. Unknown_Document must always set needs_review=true.
7. Any non-empty ambiguities list must set needs_review=true.
8. Evidence.source_text must be a short verbatim span from the supplied input.
9. Confidence must reflect the evidence, not a desire to auto-route.
10. Return only the strict structured object requested by the schema.
"""


@dataclass(frozen=True)
class ShadowClassification:
    result: Dict[str, Any]
    gateway_request_id: str
    model_response_id: str
    deployment: str
    latency_ms: Optional[float]
    fail_closed: bool
    error: Optional[str]


class ShadowClassifier:
    def __init__(
        self,
        provider: Optional[FunctionGatewayProvider] = None,
    ):
        self._provider = provider or FunctionGatewayProvider()

    async def classify(
        self,
        *,
        document_evidence: str,
        session_id: str,
    ) -> ShadowClassification:
        evidence = str(document_evidence or "").strip()

        if not evidence:
            result = fail_closed_result(
                "empty document evidence"
            )
            return ShadowClassification(
                result=result,
                gateway_request_id="",
                model_response_id="",
                deployment="",
                latency_ms=None,
                fail_closed=True,
                error="empty document evidence",
            )

        try:
            gateway = await self._provider.complete_json(
                system_prompt=SYSTEM_PROMPT,
                user_prompt=(
                    "DOCUMENT EVIDENCE\n"
                    "=================\n"
                    + evidence[:80000]
                ),
                json_schema=canonical_classification_schema(),
                session_id=session_id,
            )

            assert_valid_result(gateway.result)

            return ShadowClassification(
                result=gateway.result,
                gateway_request_id=gateway.request_id,
                model_response_id=gateway.response_id,
                deployment=gateway.deployment,
                latency_ms=gateway.latency_ms,
                fail_closed=False,
                error=None,
            )

        except Exception as exc:
            safe_error = (
                f"{type(exc).__name__}: {str(exc)}"
            )[:500]

            result = fail_closed_result(safe_error)

            return ShadowClassification(
                result=result,
                gateway_request_id="",
                model_response_id="",
                deployment="",
                latency_ms=None,
                fail_closed=True,
                error=safe_error,
            )
