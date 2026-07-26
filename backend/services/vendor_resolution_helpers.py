"""
Vendor-resolution helpers used by raw document intake.

These implementations were extracted from server.py to eliminate the final
production reverse import while preserving the existing signatures, control
flow, return shapes, database object and server logger category.
"""

import logging
import os
from datetime import datetime, timezone

from database import db


logger = logging.getLogger("server")

VENDOR_RANKING_CONFIDENCE_THRESHOLD = float(
    os.environ.get(
        "VENDOR_RANKING_CONFIDENCE_THRESHOLD",
        "0.80",
    )
)


def _build_vendor_resolution(vendor_raw: str, match_result: dict) -> dict:
    """Build per-document vendor_resolution object for observability."""
    try:
        from services.vendor_resolution_service import build_resolution_object
        return build_resolution_object(vendor_raw=vendor_raw, match_result=match_result)
    except Exception:
        return {"status": "unresolved", "method": "none", "raw": vendor_raw or ""}

async def _attempt_llm_vendor_ranking(
    doc_id: str,
    vendor_alias_result: dict,
    vendor_raw: str,
    normalized_fields: dict,
) -> tuple:
    """
    LLM-assisted vendor ranking gate.  Runs ONLY when:
      1. ENABLE_LLM_VENDOR_RANKING env var is 'true'
      2. Existing match is not high-confidence

    Returns (updated_vendor_alias_result, llm_ranking_dict, workflow_event_or_None).
    The caller must persist llm_ranking_dict on the document and, if workflow_event
    is not None, append it to workflow_events.
    """
    llm_ranking_dict = None
    workflow_event = None

    if os.environ.get("ENABLE_LLM_VENDOR_RANKING", "false").lower() != "true":
        return vendor_alias_result, llm_ranking_dict, workflow_event

    existing_method = vendor_alias_result.get("vendor_match_method", "none")
    existing_score = float(vendor_alias_result.get("match_score") or 0)

    # High-confidence methods — never override
    HIGH_CONF_METHODS = {"alias", "alias_match", "exact_name", "bc_search"}
    if existing_method in HIGH_CONF_METHODS:
        logger.info("[LLM-VendorRank] Skipped for %s — existing method '%s' is high confidence", doc_id[:8], existing_method)
        return vendor_alias_result, llm_ranking_dict, workflow_event

    if existing_method == "fuzzy_bc" and existing_score >= VENDOR_RANKING_CONFIDENCE_THRESHOLD:
        logger.info("[LLM-VendorRank] Skipped for %s — fuzzy score %.2f >= threshold", doc_id[:8], existing_score)
        return vendor_alias_result, llm_ranking_dict, workflow_event

    # --- Build candidate list from vendor_invoice_profiles ---
    search_term = (vendor_raw or "").strip()
    if not search_term:
        logger.info("[LLM-VendorRank] Skipped for %s — no vendor_raw", doc_id[:8])
        return vendor_alias_result, llm_ranking_dict, workflow_event

    try:
        import re as _re
        first_word = search_term.split()[0] if search_term else ""
        candidates = []

        if first_word and len(first_word) >= 2:
            pattern = _re.compile(_re.escape(first_word), _re.IGNORECASE)
            cursor = db.vendor_invoice_profiles.find(
                {"vendor_name": {"$regex": pattern}},
                {"_id": 0, "vendor_no": 1, "vendor_name": 1}
            ).limit(15)
            async for vip in cursor:
                candidates.append({
                    "vendor_id": vip.get("vendor_no", ""),
                    "vendor_name": vip.get("vendor_name", ""),
                    "match_score": 0.5,
                })

        # Also search aliases
        alias_cursor = db.vendor_aliases.find(
            {"alias_string": {"$regex": _re.compile(_re.escape(first_word), _re.IGNORECASE)}},
            {"_id": 0, "vendor_no": 1, "vendor_name": 1, "canonical_vendor_id": 1}
        ).limit(10)
        seen_ids = {c["vendor_id"] for c in candidates}
        async for alias in alias_cursor:
            vid = alias.get("vendor_no") or alias.get("canonical_vendor_id") or ""
            if vid and vid not in seen_ids:
                candidates.append({
                    "vendor_id": vid,
                    "vendor_name": alias.get("vendor_name", vid),
                    "match_score": 0.4,
                })
                seen_ids.add(vid)

        # Include the existing fuzzy match if any
        if vendor_alias_result.get("vendor_canonical"):
            ex_id = vendor_alias_result["vendor_canonical"]
            if ex_id not in seen_ids:
                candidates.insert(0, {
                    "vendor_id": ex_id,
                    "vendor_name": vendor_alias_result.get("vendor_name") or ex_id,
                    "match_score": existing_score or 0.5,
                })

        if len(candidates) < 2:
            logger.info("[LLM-VendorRank] Skipped for %s — only %d candidate(s)", doc_id[:8], len(candidates))
            return vendor_alias_result, llm_ranking_dict, workflow_event

        # --- Call LLM ranking ---
        from services.vendor_resolution_service import rank_vendor_candidates
        doc_context = {
            "doc_type": normalized_fields.get("doc_type") or "",
            "invoice_number_clean": normalized_fields.get("invoice_number_clean") or "",
            "amount_float": normalized_fields.get("amount_float"),
        }

        ranking_result = await rank_vendor_candidates(
            vendor_raw=search_term,
            candidates=candidates,
            document_context=doc_context,
        )

        # Always store the full ranking result for audit
        llm_ranking_dict = ranking_result.to_dict()

        if ranking_result.error:
            logger.warning("[LLM-VendorRank] Error for %s: %s", doc_id[:8], ranking_result.error)
            return vendor_alias_result, llm_ranking_dict, workflow_event

        if ranking_result.confidence < VENDOR_RANKING_CONFIDENCE_THRESHOLD:
            logger.info("[LLM-VendorRank] Low confidence for %s: %.2f < %.2f — keeping original",
                        doc_id[:8], ranking_result.confidence, VENDOR_RANKING_CONFIDENCE_THRESHOLD)
            return vendor_alias_result, llm_ranking_dict, workflow_event

        # Verify selected vendor is in candidate list
        valid_ids = {c["vendor_id"] for c in candidates}
        if ranking_result.selected_vendor_id not in valid_ids:
            logger.warning("[LLM-VendorRank] Model selected %s not in candidates for %s",
                           ranking_result.selected_vendor_id, doc_id[:8])
            return vendor_alias_result, llm_ranking_dict, workflow_event

        # --- Apply: update vendor_alias_result ---
        logger.info("[LLM-VendorRank] Applied for %s: %s (%s) conf=%.2f — %s",
                    doc_id[:8], ranking_result.selected_vendor_id,
                    ranking_result.selected_vendor_name, ranking_result.confidence,
                    ranking_result.reason)

        vendor_alias_result = {
            **vendor_alias_result,
            "vendor_canonical": ranking_result.selected_vendor_id,
            "vendor_match_method": "llm_ranking",
            "vendor_name": ranking_result.selected_vendor_name,
            "vendor_no": ranking_result.selected_vendor_id,
            "match_score": ranking_result.confidence,
        }

        workflow_event = {
            "event": "llm_vendor_ranking_applied",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "vendor_id": ranking_result.selected_vendor_id,
            "vendor_name": ranking_result.selected_vendor_name,
            "confidence": ranking_result.confidence,
            "reason": ranking_result.reason,
            "model_used": ranking_result.model_used,
        }

    except Exception as exc:
        logger.error("[LLM-VendorRank] Unexpected error for %s: %s", doc_id[:8], exc)
        # Never break the pipeline — fall through with original result

    return vendor_alias_result, llm_ranking_dict, workflow_event

__all__ = [
    "_build_vendor_resolution",
    "_attempt_llm_vendor_ranking",
]
