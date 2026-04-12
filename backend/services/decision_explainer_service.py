"""
GPI Document Hub - Decision Explainer Service

Takes a document's current state and returns a plain-English explanation
of why it is in its current workflow status.
Read-only — never writes to the database.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Dict, Any, Optional

from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError

logger = logging.getLogger(__name__)


@dataclass
class ExplainerResult:
    document_id: str
    explanation: str
    blocking_reason: Optional[str]
    next_action: Optional[str]
    model_used: str
    generated_at: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def explain_document_status(document: Dict[str, Any]) -> ExplainerResult:
    """
    Build context from the document dict and ask the LLM to explain
    why this document is in its current workflow status.
    """
    doc_id = document.get("id", "unknown")
    generated_at = datetime.now(timezone.utc).isoformat()

    # ---- obtain provider ----
    try:
        provider = get_provider("explanation")
    except LLMProviderError as e:
        return ExplainerResult(
            document_id=doc_id,
            explanation="",
            blocking_reason=None,
            next_action=None,
            model_used="none",
            generated_at=generated_at,
            error=str(e),
        )

    model_used = f"{provider.__class__.__name__}"

    # ---- build context ----
    parts = []

    workflow_status = document.get("workflow_status")
    if workflow_status:
        parts.append(f"workflow_status: {workflow_status}")

    doc_type = document.get("doc_type")
    if doc_type:
        parts.append(f"doc_type: {doc_type}")

    # workflow_events — last 10 summarised
    events = document.get("workflow_events") or []
    if events:
        recent = events[-10:]
        event_lines = []
        for ev in recent:
            name = ev.get("event") or ev.get("name") or ev.get("type") or "unknown"
            ts = ev.get("timestamp") or ev.get("created_utc") or ""
            event_lines.append(f"  - {name} @ {ts}")
        parts.append("workflow_events (last 10):\n" + "\n".join(event_lines))

    # ai_extraction
    ai_ext = document.get("ai_extraction") or {}
    if ai_ext:
        confidence = ai_ext.get("confidence")
        fields = [k for k, v in ai_ext.get("fields", {}).items() if v] if isinstance(ai_ext.get("fields"), dict) else []
        ext_summary = f"ai_extraction confidence={confidence}"
        if fields:
            ext_summary += f", extracted_fields=[{', '.join(fields)}]"
        parts.append(ext_summary)

    # ai_classification
    ai_cls = document.get("ai_classification") or {}
    if ai_cls:
        proposed = ai_cls.get("proposed_doc_type") or ai_cls.get("proposed_type")
        conf = ai_cls.get("confidence")
        if proposed:
            parts.append(f"ai_classification: proposed={proposed}, confidence={conf}")

    # bc_validation
    bc_val = document.get("bc_validation") or {}
    if bc_val:
        status = bc_val.get("status")
        err = bc_val.get("error") or bc_val.get("error_message")
        line = f"bc_validation: status={status}"
        if err:
            line += f", error={err}"
        parts.append(line)

    # vendor info
    vendor_raw = document.get("vendor_raw")
    vendor_resolved = document.get("vendor_resolved")
    if vendor_raw:
        parts.append(f"vendor_raw: {vendor_raw}")
    if vendor_resolved:
        parts.append(f"vendor_resolved: {vendor_resolved}")

    # invoice / amount
    inv = document.get("invoice_number_clean")
    amt = document.get("amount_float")
    if inv:
        parts.append(f"invoice_number_clean: {inv}")
    if amt is not None:
        parts.append(f"amount_float: {amt}")

    context_str = "\n".join(parts) if parts else "(no context fields available)"

    system_prompt = (
        "You are a workflow-status explainer for a document processing hub. "
        "Given the current state of a document, respond ONLY with a JSON object "
        "using this exact schema:\n"
        '{\n'
        '  "explanation": "2-3 sentence plain English summary of the document\'s current state",\n'
        '  "blocking_reason": "What specifically is preventing progress, or null if not blocked",\n'
        '  "next_action": "The single most useful thing a user could do right now, or null if no action needed"\n'
        '}\n'
        "Do not include any text outside the JSON object."
    )

    user_prompt = f"Explain the current state of this document:\n\n{context_str}"

    try:
        raw = await provider.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            session_id=f"explain_{doc_id}",
            expect_json=True,
        )
        logger.info("Explainer raw response for %s: %s", doc_id, raw)

        # extract JSON
        if raw.startswith("{"):
            json_str = raw
        elif "{" in raw:
            json_str = raw[raw.find("{"):raw.rfind("}") + 1]
        else:
            raise ValueError(f"No JSON found in response: {raw}")

        data = json.loads(json_str)

        return ExplainerResult(
            document_id=doc_id,
            explanation=data.get("explanation", ""),
            blocking_reason=data.get("blocking_reason"),
            next_action=data.get("next_action"),
            model_used=model_used,
            generated_at=generated_at,
        )

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse model response for %s: %s", doc_id, e)
        return ExplainerResult(
            document_id=doc_id,
            explanation="",
            blocking_reason=None,
            next_action=None,
            model_used=model_used,
            generated_at=generated_at,
            error="Failed to parse model response",
        )

    except LLMProviderError as e:
        logger.error("LLM provider error for %s: %s", doc_id, e)
        return ExplainerResult(
            document_id=doc_id,
            explanation="",
            blocking_reason=None,
            next_action=None,
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )

    except Exception as e:
        logger.error("Explainer failed for %s: %s", doc_id, e)
        return ExplainerResult(
            document_id=doc_id,
            explanation="",
            blocking_reason=None,
            next_action=None,
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )
