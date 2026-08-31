"""Resilient read-only AP routing context for held-out/corpus evaluation.

The production resolver prefers the local BC reference cache in Mongo, then
falls back to live Business Central. During V117 targeted corpus expansion the
source container intermittently lost DNS resolution for `mongodb:27017`, causing
30-second ServerSelectionTimeout failures for most selected labels.

For evaluation only, this wrapper uses the full resolver while Mongo is healthy.
After the first Mongo/DNS failure it switches subsequent calls to a live-BC-only
resolver built from extracted/filename PO candidates. This preserves read-only
Business Central context without discarding Accounting labels or repeatedly
waiting on an unavailable local cache.

No SharePoint, Mongo, or Business Central writes occur here.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from services.ap_bc_routing_context_service import (
    _fetch_live_purchase_order_context,
    enrich_document_with_bundle_refs,
    resolve_ap_routing_context as _base_resolve_ap_routing_context,
)
from services.po_resolution_service import extract_po_candidates

_MONGO_UNAVAILABLE = False


def _is_mongo_unavailable_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__}:{exc}".lower()
    return (
        "serverselectiontimeouterror" in text
        or "mongodb:27017" in text
        or ("temporary failure in name resolution" in text and "mongo" in text)
    )


async def _live_bc_only_context(
    document: Dict[str, Any],
    *,
    bundle_refs: Optional[Dict[str, Any]],
    fallback_reason: str,
) -> Dict[str, Any]:
    candidate_doc = enrich_document_with_bundle_refs(document, bundle_refs)
    fields = candidate_doc.get("extracted_fields") or {}
    candidates = extract_po_candidates(
        str(candidate_doc.get("raw_text") or ""),
        fields,
        file_name=str(candidate_doc.get("file_name") or ""),
    )
    valid = [
        row
        for row in candidates
        if row.get("valid_format") and not row.get("is_non_po") and row.get("normalized")
    ]

    trace: List[Dict[str, Any]] = []
    for candidate in valid[:8]:
        po_number = str(candidate.get("normalized") or "")
        try:
            live = await _fetch_live_purchase_order_context(po_number)
        except Exception as exc:
            trace.append({
                "candidate": po_number,
                "status": "error",
                "error": f"{type(exc).__name__}:{exc}"[:300],
            })
            continue
        if not live:
            trace.append({"candidate": po_number, "status": "not_found"})
            continue

        resolved = {
            "status": "resolved",
            "po_number": live.get("bc_document_no") or po_number,
            "bc_record_id": live.get("bc_record_id", ""),
            "bc_vendor_no": live.get("bc_vendor_no", ""),
            "bc_vendor_name": live.get("bc_vendor_name", ""),
            "bc_status": live.get("bc_status", ""),
            "location_code": live.get("location_code", ""),
            "verified_order_numbers": [live.get("bc_document_no") or po_number],
            "live_bc_context": live,
            "lookup_source": "evaluation_live_bc_only",
            "context_fallback_reason": fallback_reason,
            "lookup_trace": trace + [{"candidate": po_number, "status": "resolved"}],
        }
        for key in (
            "ship_to_name",
            "ship_to_address",
            "ship_to_city",
            "ship_to_state",
            "ship_to_country",
        ):
            if live.get(key):
                resolved[key] = live[key]
        return resolved

    return {
        "status": "not_found",
        "miss_reason": "evaluation_live_bc_no_match",
        "verified_order_numbers": [],
        "candidates_tried": [str(row.get("normalized") or "") for row in valid[:8]],
        "lookup_source": "evaluation_live_bc_only",
        "context_fallback_reason": fallback_reason,
        "lookup_trace": trace,
    }


async def resolve_ap_routing_context_resilient(
    document: Dict[str, Any],
    *,
    bundle_refs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Use normal resolver until Mongo fails, then fail over to live BC only."""
    global _MONGO_UNAVAILABLE

    if _MONGO_UNAVAILABLE:
        return await _live_bc_only_context(
            document,
            bundle_refs=bundle_refs,
            fallback_reason="mongo_unavailable_latched",
        )

    try:
        return await _base_resolve_ap_routing_context(document, bundle_refs=bundle_refs)
    except Exception as exc:
        if not _is_mongo_unavailable_error(exc):
            raise
        _MONGO_UNAVAILABLE = True
        return await _live_bc_only_context(
            document,
            bundle_refs=bundle_refs,
            fallback_reason=f"{type(exc).__name__}:{exc}"[:300],
        )


def mongo_fallback_latched() -> bool:
    return bool(_MONGO_UNAVAILABLE)
