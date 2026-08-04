"""GPI Document Hub vendor resolution services.

Provides LLM candidate ranking plus the established resolution status,
negative-feedback, guardrail, analytics, and admin interfaces.
"""

import json
import logging
from datetime import datetime, timezone
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from services.llm_router import get_provider
from services.providers.base_provider import LLMProviderError
from deps import get_db
from services.vendor_name_helpers import normalize_vendor_name

logger = logging.getLogger(__name__)

MAX_CANDIDATES = 10


@dataclass
class VendorRankingResult:
    selected_vendor_id: Optional[str]
    selected_vendor_name: Optional[str]
    confidence: float
    reason: str
    candidates_evaluated: int
    model_used: str
    generated_at: str
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def rank_vendor_candidates(
    vendor_raw: str,
    candidates: List[Dict[str, Any]],
    document_context: Optional[Dict[str, Any]] = None,
) -> VendorRankingResult:
    generated_at = datetime.now(timezone.utc).isoformat()

    # --- trivial early returns ---
    if not candidates:
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="No candidates provided",
            candidates_evaluated=0,
            model_used="none",
            generated_at=generated_at,
            error="No candidates provided",
        )

    if len(candidates) == 1:
        c = candidates[0]
        return VendorRankingResult(
            selected_vendor_id=c.get("vendor_id"),
            selected_vendor_name=c.get("vendor_name"),
            confidence=1.0,
            reason="Only one candidate",
            candidates_evaluated=1,
            model_used="none",
            generated_at=generated_at,
        )

    # --- cap at top-10 by match_score ---
    ranked = sorted(candidates, key=lambda x: float(x.get("match_score", 0)), reverse=True)[:MAX_CANDIDATES]

    # --- obtain provider ---
    try:
        provider = get_provider("classification")
    except LLMProviderError as e:
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used="none",
            generated_at=generated_at,
            error=str(e),
        )

    model_used = type(provider).__name__

    # --- build prompt ---
    candidate_lines = []
    valid_ids = set()
    for i, c in enumerate(ranked, 1):
        vid = c.get("vendor_id", "")
        vname = c.get("vendor_name", "")
        aliases = c.get("aliases", [])
        score = c.get("match_score", "")
        valid_ids.add(vid)
        alias_str = f', aliases: {", ".join(aliases)}' if aliases else ""
        score_str = f", match_score: {score}" if score else ""
        candidate_lines.append(f"  {i}. vendor_id=\"{vid}\", vendor_name=\"{vname}\"{alias_str}{score_str}")

    doc_ctx = ""
    if document_context:
        parts = []
        for k in ("doc_type", "invoice_number_clean", "amount_float"):
            v = document_context.get(k)
            if v is not None:
                parts.append(f"{k}: {v}")
        if parts:
            doc_ctx = "\nDocument context: " + ", ".join(parts)

    system_prompt = (
        "You are a vendor-name disambiguation expert for a business document hub. "
        "Given a raw vendor string from a document and a shortlist of candidate vendors "
        "from the master database, select the single best match. "
        "Respond ONLY with a JSON object in this exact schema:\n"
        '{\n'
        '  "selected_vendor_id": "string or null",\n'
        '  "confidence": 0.0,\n'
        '  "reason": "one sentence explaining the match"\n'
        '}\n'
        "If none of the candidates is a reasonable match, set selected_vendor_id to null "
        "and confidence below 0.3. Do not include any text outside the JSON object."
    )

    user_prompt = (
        f'Raw vendor string from document: "{vendor_raw}"\n'
        f"{doc_ctx}\n\n"
        f"Candidate vendors:\n"
        + "\n".join(candidate_lines)
    )

    try:
        raw = await provider.complete(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            session_id=f"vendor_rank_{vendor_raw[:30]}",
            expect_json=True,
        )
        logger.info("Vendor ranking raw response: %s", raw)

        # parse JSON
        text = raw.strip()
        if text.startswith("{"):
            json_str = text
        elif "{" in text:
            json_str = text[text.find("{"):text.rfind("}") + 1]
        else:
            raise ValueError(f"No JSON found in response: {text[:200]}")

        data = json.loads(json_str)
        sel_id = data.get("selected_vendor_id")
        conf = float(data.get("confidence", 0.0))
        reason = data.get("reason", "")

        # --- safety check ---
        if sel_id is not None and sel_id not in valid_ids:
            return VendorRankingResult(
                selected_vendor_id=None,
                selected_vendor_name=None,
                confidence=0.0,
                reason=reason,
                candidates_evaluated=len(ranked),
                model_used=model_used,
                generated_at=generated_at,
                error="Model selected vendor not in candidate list",
            )

        sel_name = None
        if sel_id is not None:
            for c in ranked:
                if c.get("vendor_id") == sel_id:
                    sel_name = c.get("vendor_name")
                    break

        return VendorRankingResult(
            selected_vendor_id=sel_id,
            selected_vendor_name=sel_name,
            confidence=max(0.0, min(1.0, conf)),
            reason=reason,
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
        )

    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse vendor ranking response: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error="Failed to parse model response",
        )

    except LLMProviderError as e:
        logger.error("LLM provider error during vendor ranking: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )

    except Exception as e:
        logger.error("Vendor ranking failed: %s", e)
        return VendorRankingResult(
            selected_vendor_id=None,
            selected_vendor_name=None,
            confidence=0.0,
            reason="",
            candidates_evaluated=len(ranked),
            model_used=model_used,
            generated_at=generated_at,
            error=str(e),
        )

# =============================================================================
# VENDOR RESOLUTION OBSERVABILITY
# Restored from audited commit 6c2bc390bf6709b241354cf4fdcaa2d60c35bc99.
# Ranking surfaces above remain unchanged.
# =============================================================================

# ---------------------------------------------------------------------------
# Resolution statuses
# ---------------------------------------------------------------------------

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# 1. Build per-document vendor_resolution object
# ---------------------------------------------------------------------------

def build_resolution_object(
    vendor_raw: str,
    match_result: Dict[str, Any],
    status: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured vendor_resolution object for a document.

    Args:
        vendor_raw: The raw vendor string from the document.
        match_result: The result dict from lookup_vendor_alias or match_vendor_in_bc.
        status: Override status (resolved/unresolved/ambiguous/needs_review).
        reason: Human-readable reason for the resolution outcome.

    Returns:
        A dict suitable for storing as doc["vendor_resolution"].
    """
    method = match_result.get("vendor_match_method", "none")
    vendor_canonical = match_result.get("vendor_canonical")
    score = match_result.get("match_score") or match_result.get("score")

    if not status:
        if vendor_canonical and method in ("alias_match", "bc_exact_match", "bc_search"):
            status = STATUS_RESOLVED
        elif vendor_canonical and method == "fuzzy_match":
            score_val = float(score) if score else 0
            status = STATUS_RESOLVED if score_val >= 0.95 else STATUS_NEEDS_REVIEW
        elif vendor_canonical:
            status = STATUS_RESOLVED
        else:
            status = STATUS_UNRESOLVED

    if not reason:
        if status == STATUS_RESOLVED:
            reason = f"Auto-resolved via {method}"
        elif status == STATUS_NEEDS_REVIEW:
            reason = f"Fuzzy match ({method}) below high-confidence threshold"
        elif status == STATUS_AMBIGUOUS:
            reason = "Multiple possible vendor matches"
        else:
            reason = "No vendor match found"

    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""

    return {
        "status": status,
        "method": method,
        "raw": vendor_raw or "",
        "normalized": normalized,
        "matched_vendor_name": match_result.get("vendor_name"),
        "matched_vendor_no": match_result.get("vendor_no") or vendor_canonical,
        "score": float(score) if score else None,
        "reason": reason,
        "reviewed_override": False,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. Negative feedback capture
# ---------------------------------------------------------------------------

async def capture_rejection(
    doc_id: str,
    vendor_raw: str,
    proposed_vendor_id: str,
    proposed_vendor_name: str,
    proposed_method: str,
    proposed_score: float,
    corrected_vendor_id: str,
    corrected_vendor_name: str,
    actor: str = "reviewer",
) -> Dict[str, Any]:
    """Record a rejected auto-match for the negative feedback loop.

    Called when a reviewer overrides an auto-matched vendor.
    """
    db = get_db()
    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""
    now = datetime.now(timezone.utc).isoformat()

    # Check if this pairing already has a rejection
    existing = await db.vendor_match_rejections.find_one({
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
    }, {"_id": 0})

    if existing:
        # Increment rejection count
        await db.vendor_match_rejections.update_one(
            {
                "normalized_raw": normalized,
                "proposed_vendor_id": proposed_vendor_id,
            },
            {
                "$inc": {"rejection_count": 1},
                "$set": {
                    "last_rejected_at": now,
                    "last_corrected_vendor_id": corrected_vendor_id,
                    "last_corrected_vendor_name": corrected_vendor_name,
                    "last_actor": actor,
                },
                "$push": {
                    "rejection_history": {
                        "doc_id": doc_id,
                        "corrected_vendor_id": corrected_vendor_id,
                        "corrected_vendor_name": corrected_vendor_name,
                        "actor": actor,
                        "timestamp": now,
                    }
                },
            },
        )
        logger.info(
            '[VendorRejection] Reinforced rejection: raw="%s" proposed=%s (count=%d)',
            normalized, proposed_vendor_id, existing.get("rejection_count", 0) + 1,
        )
        return {**existing, "rejection_count": existing.get("rejection_count", 0) + 1}

    # Create new rejection record
    rejection = {
        "vendor_raw": vendor_raw,
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
        "proposed_vendor_name": proposed_vendor_name,
        "proposed_method": proposed_method,
        "proposed_score": proposed_score,
        "corrected_vendor_id": corrected_vendor_id,
        "corrected_vendor_name": corrected_vendor_name,
        "rejection_count": 1,
        "first_rejected_at": now,
        "last_rejected_at": now,
        "last_corrected_vendor_id": corrected_vendor_id,
        "last_corrected_vendor_name": corrected_vendor_name,
        "last_actor": actor,
        "rejection_history": [{
            "doc_id": doc_id,
            "corrected_vendor_id": corrected_vendor_id,
            "corrected_vendor_name": corrected_vendor_name,
            "actor": actor,
            "timestamp": now,
        }],
    }
    await db.vendor_match_rejections.insert_one(rejection)
    rejection.pop("_id", None)

    logger.info(
        '[VendorRejection] New rejection: raw="%s" proposed=%s corrected=%s',
        normalized, proposed_vendor_id, corrected_vendor_id,
    )
    return rejection


# ---------------------------------------------------------------------------
# 3. Guardrail check — block repeat bad matches
# ---------------------------------------------------------------------------

async def check_rejection_guardrail(
    vendor_raw: str,
    proposed_vendor_id: str,
) -> Optional[Dict[str, Any]]:
    """Check if a proposed vendor match was previously rejected.

    Returns the rejection record if found, None if the match is safe.
    """
    db = get_db()
    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""
    if not normalized or not proposed_vendor_id:
        return None

    rejection = await db.vendor_match_rejections.find_one({
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
    }, {"_id": 0})

    if rejection:
        logger.info(
            '[VendorGuardrail] Blocked repeat match: raw="%s" vendor=%s (rejected %d times)',
            normalized, proposed_vendor_id, rejection.get("rejection_count", 0),
        )
    return rejection


# ---------------------------------------------------------------------------
# 4. Resolution analytics
# ---------------------------------------------------------------------------

async def get_resolution_metrics() -> Dict[str, Any]:
    """Compute vendor resolution analytics."""
    db = get_db()

    total = await db.hub_documents.count_documents({})

    # Vendor-applicable documents are the population where resolution is
    # expected or has already been attempted.
    vendor_applicable_types = [
        "AP_Invoice",
        "AP_INVOICE",
        "PurchaseInvoice",
        "PurchaseOrder",
        "Remittance",
        "REMITTANCE",
        "Credit_Memo",
        "CREDIT_MEMO",
        "Purchase_Invoice",
        "PURCHASE_INVOICE",
    ]
    vendor_applicable_filter = {
        "$or": [
            {"doc_type": {"$in": vendor_applicable_types}},
            {"suggested_job_type": {"$in": vendor_applicable_types}},
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }
    vendor_applicable_total = await db.hub_documents.count_documents(
        vendor_applicable_filter
    )

    status_pipeline = [
        {"$group": {
            "_id": "$vendor_resolution.status",
            "count": {"$sum": 1},
        }},
    ]
    status_raw = await db.hub_documents.aggregate(
        status_pipeline
    ).to_list(10)
    status_counts = {
        row["_id"]: row["count"]
        for row in status_raw
        if row["_id"]
    }

    resolved = status_counts.get(STATUS_RESOLVED, 0)
    unresolved = status_counts.get(STATUS_UNRESOLVED, 0)
    ambiguous = status_counts.get(STATUS_AMBIGUOUS, 0)
    needs_review = status_counts.get(STATUS_NEEDS_REVIEW, 0)
    no_resolution = (
        total
        - resolved
        - unresolved
        - ambiguous
        - needs_review
    )

    # Preserve the historical all-document rate for compatibility.
    resolution_rate = (
        round((resolved / total * 100), 1)
        if total > 0
        else 0
    )

    vendor_resolved_total = await db.hub_documents.count_documents({
        "$and": [
            vendor_applicable_filter,
            {"vendor_resolution.status": STATUS_RESOLVED},
        ]
    })
    vendor_resolution_rate = (
        round(
            (
                vendor_resolved_total
                / vendor_applicable_total
                * 100
            ),
            1,
        )
        if vendor_applicable_total > 0
        else 0
    )

    method_pipeline = [
        {"$match": {
            "vendor_resolution.method": {
                "$exists": True,
                "$ne": None,
            }
        }},
        {"$group": {
            "_id": "$vendor_resolution.method",
            "count": {"$sum": 1},
        }},
    ]
    method_raw = await db.hub_documents.aggregate(
        method_pipeline
    ).to_list(20)
    by_method = {
        row["_id"]: row["count"]
        for row in method_raw
        if row["_id"]
    }

    buckets = {
        "60-79": 0,
        "80-89": 0,
        "90-94": 0,
        "95-97": 0,
        "98-100": 0,
    }
    fuzzy_methods = [
        "fuzzy_candidate",
        "fuzzy_match",
        "fuzzy",
        "fuzzy_bc",
        "fuzzy_candidates",
    ]
    fuzzy_pipeline = [
        {"$match": {
            "vendor_resolution.method": {
                "$in": fuzzy_methods,
            },
            "vendor_resolution.score": {
                "$exists": True,
                "$ne": None,
            },
        }},
        {"$project": {
            "score": "$vendor_resolution.score",
        }},
    ]
    fuzzy_docs = await db.hub_documents.aggregate(
        fuzzy_pipeline
    ).to_list(5000)

    for fuzzy_doc in fuzzy_docs:
        score = fuzzy_doc.get("score", 0)
        if score is None:
            continue

        percent = score * 100 if score <= 1 else score

        if 60 <= percent < 80:
            buckets["60-79"] += 1
        elif 80 <= percent < 90:
            buckets["80-89"] += 1
        elif 90 <= percent < 95:
            buckets["90-94"] += 1
        elif 95 <= percent < 98:
            buckets["95-97"] += 1
        elif percent >= 98:
            buckets["98-100"] += 1

    unresolved_pipeline = [
        {"$match": {
            "vendor_resolution.status": STATUS_UNRESOLVED,
        }},
        {"$group": {
            "_id": "$vendor_resolution.raw",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]
    unresolved_raw = await db.hub_documents.aggregate(
        unresolved_pipeline
    ).to_list(25)
    top_unresolved = [
        {
            "raw": row["_id"],
            "count": row["count"],
        }
        for row in unresolved_raw
        if row["_id"]
    ]

    corrected_pipeline = [
        {"$match": {
            "vendor_resolution.reviewed_override": True,
        }},
        {"$group": {
            "_id": "$vendor_resolution.raw",
            "count": {"$sum": 1},
            "vendor_name": {
                "$first": "$vendor_canonical",
            },
            "vendor_no": {
                "$first": (
                    "$vendor_resolution.matched_vendor_no"
                ),
            },
        }},
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]
    corrected_raw = await db.hub_documents.aggregate(
        corrected_pipeline
    ).to_list(25)
    top_corrected = [
        {
            "raw": row["_id"],
            "count": row["count"],
            "vendor_name": row.get("vendor_name"),
            "vendor_no": row.get("vendor_no"),
        }
        for row in corrected_raw
        if row["_id"]
    ]

    total_rejections = (
        await db.vendor_match_rejections.count_documents({})
    )

    return {
        "total_documents": total,
        "vendor_applicable_total": vendor_applicable_total,
        "vendor_resolved_total": vendor_resolved_total,
        "vendor_resolution_rate": vendor_resolution_rate,
        "resolved_count": resolved,
        "unresolved_count": unresolved,
        "ambiguous_count": ambiguous,
        "needs_review_count": needs_review,
        "no_resolution_data": no_resolution,
        "resolution_rate": resolution_rate,
        "by_method": by_method,
        "fuzzy_score_buckets": buckets,
        "top_unresolved": top_unresolved,
        "top_corrected": top_corrected,
        "total_rejections": total_rejections,
    }


# ---------------------------------------------------------------------------
# 5. Get rejection history (admin)
# ---------------------------------------------------------------------------

async def get_rejections(limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
    """Get vendor match rejection history for admin review."""
    db = get_db()
    cursor = db.vendor_match_rejections.find(
        {}, {"_id": 0}
    ).sort("last_rejected_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


# ---------------------------------------------------------------------------
# 6. Ensure indexes
# ---------------------------------------------------------------------------

async def ensure_resolution_indexes():
    """Create indexes for vendor resolution collections."""
    db = get_db()
    try:
        await db.vendor_match_rejections.create_index(
            [("normalized_raw", 1), ("proposed_vendor_id", 1)],
            unique=True,
        )
        await db.vendor_match_rejections.create_index("last_rejected_at")
        await db.hub_documents.create_index("vendor_resolution.status")
        await db.hub_documents.create_index("vendor_resolution.method")
        logger.info("[VendorResolution] Indexes ensured")
    except Exception as e:
        logger.warning("[VendorResolution] Index creation note: %s", e)
