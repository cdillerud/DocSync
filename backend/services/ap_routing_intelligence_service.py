"""AI-first AP routing intelligence orchestration.

Pipeline:
    primary classification
      -> supporting-page reference extraction
      -> Business Central context resolution
      -> supervised few-shot route prediction
      -> deterministic safety governor

This service returns a routing decision. It does NOT move SharePoint files or
post to Business Central. Runtime integration may act on `auto_route` only after
held-out promotion gates are met for the relevant vendor/pattern cohort.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

from services.ap_bc_routing_context_service import resolve_ap_routing_context
from services.ap_primary_document_service import classify_primary_document
from services.ap_routing_decision_service import (
    DECISION_AUTO_ROUTE,
    DECISION_NEEDS_REVIEW,
    decide_ap_route,
)
from services.document_bundle_reference_service import extract_supporting_references

logger = logging.getLogger(__name__)

DEFAULT_CONTRACT_PATH = Path(__file__).resolve().parents[1] / "config" / "ap_routing_contract.v1.json"


def load_routing_contract(path: Optional[str] = None) -> Dict[str, Any]:
    contract_path = Path(path) if path else DEFAULT_CONTRACT_PATH
    data = json.loads(contract_path.read_text(encoding="utf-8"))
    if not data.get("version"):
        raise ValueError("AP routing contract has no version")
    if "static_routes" not in data:
        raise ValueError("AP routing contract has no static_routes")
    return data


def _text_excerpt(file_path: str, max_pages: int = 5, max_chars: int = 12000) -> str:
    if Path(file_path).suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        chunks = []
        for page in reader.pages[:max_pages]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(chunks)[:max_chars]
    except Exception:
        return ""


async def _vendor_threshold(db, vendor_name: str) -> Optional[float]:
    if db is None or not vendor_name:
        return None
    try:
        row = await db.ap_routing_vendor_thresholds.find_one(
            {"normalized_vendor": vendor_name}, {"_id": 0}
        )
        if row and row.get("enabled") and row.get("auto_route_threshold") is not None:
            return float(row["auto_route_threshold"])
    except Exception:
        logger.debug("Vendor AP routing threshold lookup unavailable", exc_info=True)
    return None


async def analyze_ap_routing(
    db,
    *,
    file_path: str,
    file_name: str,
    document_id: Optional[str] = None,
    contract: Optional[Dict[str, Any]] = None,
    persist_decision: bool = False,
    llm_send: Optional[Callable[[str, str], Awaitable[Any]]] = None,
) -> Dict[str, Any]:
    contract = contract or load_routing_contract()

    primary = await classify_primary_document(file_path, file_name)
    document_type = primary.get("suggested_job_type") or primary.get("document_type") or "Unknown_Document"
    extracted = dict(primary.get("extracted_fields") or {})

    bundle = await extract_supporting_references(
        file_path,
        file_name,
        primary_document_type=document_type,
        primary_fields=extracted,
    )
    document = {
        "id": document_id or "",
        "file_name": file_name,
        "document_type": document_type,
        "suggested_job_type": document_type,
        "confidence": primary.get("confidence"),
        "vendor_canonical": extracted.get("vendor") or extracted.get("vendor_name") or "",
        "extracted_fields": extracted,
        "raw_text": _text_excerpt(file_path),
        "bundle_references": bundle,
    }
    bc_context = await resolve_ap_routing_context(document, bundle_refs=bundle)

    # Resolve vendor again after BC enrichment; BC may know a vendor that the
    # invoice extraction could not identify cleanly.
    if not document["vendor_canonical"]:
        document["vendor_canonical"] = (
            bc_context.get("bc_vendor_name")
            or ((bc_context.get("live_bc_context") or {}).get("bc_vendor_name"))
            or ""
        )

    threshold = await _vendor_threshold(db, document["vendor_canonical"])
    routing = await decide_ap_route(
        db,
        document=document,
        bc_context=bc_context,
        contract=contract,
        vendor_auto_threshold=threshold,
        llm_send=llm_send,
    )

    # Classification uncertainty is independent from routing confidence. A
    # high-confidence route cannot rescue an unknown/weak primary document.
    classification_confidence = float(primary.get("confidence") or 0.0)
    minimum_classification_confidence = float(contract.get("minimum_classification_confidence") or 0.80)
    if classification_confidence < minimum_classification_confidence:
        routing = dict(routing)
        routing["decision"] = DECISION_NEEDS_REVIEW
        routing["route_path"] = str(contract.get("review_route") or "")
        routing["reason"] = (
            f"primary classification confidence {classification_confidence:.1%} below "
            f"{minimum_classification_confidence:.1%}; " + str(routing.get("reason") or "")
        ).strip("; ")
        routing.setdefault("blockers", []).append("primary classification below automation threshold")

    result = {
        "schema_version": "2.0",
        "document_id": document_id,
        "file_name": file_name,
        "primary_classification": primary,
        "document_type": document_type,
        "classification_confidence": classification_confidence,
        "bundle_references": bundle,
        "bc_context": bc_context,
        "routing": routing,
        "manual_validation_required": routing.get("decision") != DECISION_AUTO_ROUTE,
        "auto_route_ready": routing.get("decision") == DECISION_AUTO_ROUTE,
        "proposed_temp_route": routing.get("route_path", ""),
        "contract_version": contract.get("version"),
    }

    if persist_decision:
        if db is None:
            raise ValueError("db is required when persist_decision=True")
        if not document_id:
            raise ValueError("document_id is required when persist_decision=True")
        await db.hub_documents.update_one(
            {"id": document_id},
            {
                "$set": {
                    "ap_routing_intelligence": result,
                    "ap_routing_manual_validation_required": result["manual_validation_required"],
                    "ap_routing_proposed_temp_route": result["proposed_temp_route"],
                    "ap_routing_contract_version": result["contract_version"],
                }
            },
        )

    return result
