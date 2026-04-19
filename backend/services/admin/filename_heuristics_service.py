"""
Filename Heuristics Classifier (v2.5.8)
────────────────────────────────────────

Pattern-based fallback classifier for docs the main AI couldn't type.
Operates on the 335 stamp-only docs from the v2.5.7 post-process sweep —
those genuinely unclassified filenames the standalone page-level AI
couldn't infer from content.

Rules are (vendor_regex, filename_regex, doc_type, confidence, note):
    • Matched top-down; first match wins.
    • vendor_regex is optional (None = match any vendor).
    • Every match carries an evidence note so reviewers see WHY the AI
      suggested that type. This is critical — heuristic matches must be
      easy for a human to sanity-check and override.

Rule derivation (from real prod sample, iteration_229 preview):
    • TUMALOC — freight broker; filenames like `0305586_doc1.pdf` = invoice
    • CARGOMO — `Invoice-0493680_doc1_...pdf` = invoice
    • Valley Distributing — `Receiving Report (ZRECPOCNFMNLNG)_*.pdf` = BOL
    • Brown Warehouse — `MARCH 2026 ACTIVITY.pdf` = monthly statement
    • Progressive Logistics — `RENEWBIL_HEABRY_*.pdf` = rebill / BOL
    • SMC Worldwide — `Scan2026-04-08_144056 WA2189-2190.pdf` = warehouse activity BOL
    • Crown C / Apex — `Apex 112543 Outbound *.pdf` = BOL
    • Lone Star — `112803.pdf` (numeric-only) = freight invoice
    • GROUPWA — `W117508.pdf` = receiving report
    • GAMMIN — `GAMMIN_AR_*.xls` = AR statement

Safety:
    • Apply is idempotent (writes `filename_heuristic_applied_at` sentinel).
    • Dry-run by default.
    • Preserves the pre-heuristic `doc_type` under
      `doc_type_before_heuristic` for audit.
    • Never touches docs that have classifier output with confidence > 0
      in any type field (we only help the 'Unknown' set).
    • Never touches docs with BC evidence.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from deps import get_db
from services.admin.unknown_doc_reclaim_service import (
    BC_EVIDENCE_FIELDS, UNKNOWN_DOC_TYPES,
)

logger = logging.getLogger(__name__)


# ── Rules ────────────────────────────────────────────────────────
# Keep these tight — false positives silently mis-classify real docs.
# (rule_id, vendor_regex, filename_regex, doc_type, confidence, note)
FILENAME_RULES: List[Tuple[str, Optional[str], str, str, float, str]] = [
    # TUMALOC: freight broker. 6–8 digit prefix + optional _docN/_pN suffix.
    (
        "tumaloc_numeric_freight",
        r"(?i)^TUMALOC$",
        r"^\d{6,8}(_doc\d+|_p\d+|_dragged.*)?\.pdf$",
        "AP_Invoice",
        0.85,
        "TUMALOC numeric filename matches freight-invoice pattern",
    ),
    # CARGOMO: 'Invoice-NNNNNN[_doc1_...]*.pdf' — sometimes with long repeat chains.
    (
        "cargomo_invoice_prefix",
        r"(?i)^CARGOMO",
        r"^Invoice[-_]\d+.*\.pdf$",
        "AP_Invoice",
        0.85,
        "CARGOMO filename starts with 'Invoice-<N>'",
    ),
    # Generic Invoice-prefix fallback (for any vendor)
    (
        "generic_invoice_prefix",
        None,
        r"^Invoice[-_]\d{4,}.*\.(pdf|PDF)$",
        "AP_Invoice",
        0.70,
        "Filename starts with 'Invoice-<digits>'",
    ),
    # Valley Distributing receiving reports
    (
        "valley_receiving_report",
        None,
        r"^Valley Distributing Receiving Report.*\.pdf$",
        "BOL",
        0.85,
        "Valley Distributing 'Receiving Report' filename",
    ),
    # Brown Warehouse — monthly activity statement
    (
        "brown_monthly_activity",
        r"(?i)^Brown Warehouse",
        r"^[A-Z]+ \d{4} ACTIVITY(_doc\d+)?\.pdf$",
        "Monthly_Statement",
        0.80,
        "Brown Warehouse '<MONTH> <YEAR> ACTIVITY' statement",
    ),
    # SMC Worldwide — Scan + 'WA<nums>' batch (Warehouse Activity / BOL)
    (
        "smc_scan_warehouse_activity",
        r"(?i)^SMC",
        r"^Scan\d{4}-\d{2}-\d{2}_\d+ WA\d+.*\.pdf$",
        "BOL",
        0.80,
        "SMC 'Scan...WA<N>' warehouse-activity BOL",
    ),
    # Progressive Logistics — RENEWBIL rebills
    (
        "progressive_renewbil",
        r"(?i)^Progressive",
        r"^RENEWBIL_.*\.pdf$",
        "BOL",
        0.75,
        "Progressive Logistics 'RENEWBIL_' rebill / freight bill",
    ),
    # Crown C — Apex outbound BOLs
    (
        "crown_apex_outbound",
        r"(?i)^CROWN",
        r"^Apex \d+ Outbound.*\.pdf$",
        "BOL",
        0.80,
        "Crown 'Apex <N> Outbound' BOL",
    ),
    # GROUPWA — W-prefix receiving/BOL
    (
        "groupwa_w_prefix",
        r"(?i)^GROUPWA",
        r"^W\d{5,7}(_p\d+|_doc\d+)?\.pdf$",
        "BOL",
        0.80,
        "GROUPWA W-prefixed receiving/BOL",
    ),
    # GAMMIN AR statements (xls)
    (
        "gammin_ar_statement",
        r"(?i)^GAMMIN",
        r"^GAMMIN_AR_\d{8}\.(xls|xlsx)$",
        "AR_Statement",
        0.90,
        "GAMMIN AR aging statement (xls)",
    ),
    # Lone Star — numeric-only freight invoice
    (
        "lonestar_numeric",
        r"(?i)^Lone Star",
        r"^\d{6}\.pdf$",
        "AP_Invoice",
        0.75,
        "Lone Star 6-digit numeric invoice filename",
    ),
    # GamerPackaging from Valley Distributing
    (
        "valley_gamerpackaging",
        r"(?i)^Valley",
        r"^GamerPackaging_\d+\.pdf$",
        "BOL",
        0.75,
        "Valley Distributing 'GamerPackaging_N' BOL",
    ),
]

_COMPILED: List[Tuple[str, Optional[re.Pattern], re.Pattern, str, float, str]] = [
    (rid, re.compile(vr) if vr else None, re.compile(fr), dt, conf, note)
    for (rid, vr, fr, dt, conf, note) in FILENAME_RULES
]


# ── Dynamic/custom rules (auto-proposed, persisted in Mongo) ─────
# Loaded lazily + cached 60s so we don't hit the DB on every classify
# call but still pick up newly-persisted rules without a restart.
_CUSTOM_CACHE: Dict[str, Any] = {"at": 0.0, "rules": []}
_CUSTOM_TTL_SECONDS = 60.0


def _invalidate_custom_rule_cache() -> None:
    """Force the next classify call to refresh from Mongo."""
    _CUSTOM_CACHE["at"] = 0.0
    _CUSTOM_CACHE["rules"] = []


async def _load_custom_rules_from_db() -> List[Tuple[str, Optional[re.Pattern], re.Pattern, str, float, str]]:
    """Pull enabled custom rules from `filename_heuristic_custom_rules`
    and compile them. Bad rows (invalid regex) are logged and skipped."""
    db = get_db()
    rows = await db.filename_heuristic_custom_rules.find(
        {"enabled": True}, {"_id": 0},
    ).to_list(500)
    compiled: List[Tuple[str, Optional[re.Pattern], re.Pattern, str, float, str]] = []
    for r in rows:
        try:
            rid = r.get("rule_id") or f"custom_{len(compiled)}"
            vr = re.compile(r["vendor_regex"]) if r.get("vendor_regex") else None
            fr = re.compile(r["filename_regex"])
            dt = r.get("doc_type") or "Unknown"
            conf = float(r.get("confidence") or 0.70)
            note = r.get("note") or "custom rule"
            compiled.append((rid, vr, fr, dt, conf, note))
        except Exception as e:  # noqa: BLE001 — one bad rule shouldn't break all classification
            logger.warning(
                "Custom filename rule %s skipped (bad regex): %s",
                r.get("rule_id"), e,
            )
    return compiled


async def _get_custom_rules() -> List[Tuple[str, Optional[re.Pattern], re.Pattern, str, float, str]]:
    import time
    now = time.time()
    if now - _CUSTOM_CACHE["at"] < _CUSTOM_TTL_SECONDS and _CUSTOM_CACHE["rules"] is not None:
        return _CUSTOM_CACHE["rules"]
    try:
        rules = await _load_custom_rules_from_db()
    except Exception as e:  # noqa: BLE001 — DB outage shouldn't kill classification
        logger.debug("custom rule load failed: %s", e)
        return _CUSTOM_CACHE.get("rules") or []
    _CUSTOM_CACHE["rules"] = rules
    _CUSTOM_CACHE["at"] = now
    return rules


def _try_match(
    compiled_rules, file_name: str, vendor_str: str, origin: str,
) -> Optional[Dict[str, Any]]:
    for (rid, vr, fr, dt, conf, note) in compiled_rules:
        if vr is not None and not vr.search(vendor_str):
            continue
        if not fr.match(file_name):
            continue
        return {
            "rule_id": rid,
            "doc_type": dt,
            "confidence": conf,
            "note": note,
            "match_on_vendor": bool(vr),
            "match_on_filename": True,
            "origin": origin,
        }
    return None


def classify_filename(
    file_name: Optional[str],
    vendor_canonical: Optional[str] = None,
    vendor_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return the first matching rule as a suggestion, or None.

    Built-in rules are consulted first; custom (auto-proposed) rules
    serve as a fallback. Custom rules are cached for 60 seconds.

    Output:
        {rule_id, doc_type, confidence, note, match_on_vendor,
         match_on_filename, origin}
    """
    if not file_name:
        return None
    fn = file_name.strip()
    vendor_str = (vendor_canonical or vendor_name or "").strip()
    hit = _try_match(_COMPILED, fn, vendor_str, origin="builtin")
    if hit:
        return hit
    # Custom rules: async cache load is only safe when we're in an event
    # loop. Fall back silently if we aren't (e.g. sync pytest context).
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside async code — but we can't await here. Use the
            # cached snapshot if warm, otherwise skip.
            if _CUSTOM_CACHE["rules"]:
                return _try_match(
                    _CUSTOM_CACHE["rules"], fn, vendor_str, origin="custom",
                )
        else:
            rules = loop.run_until_complete(_get_custom_rules())
            return _try_match(rules, fn, vendor_str, origin="custom")
    except RuntimeError:
        # No loop at all. Skip custom rules this time.
        return None
    return None


async def classify_filename_async(
    file_name: Optional[str],
    vendor_canonical: Optional[str] = None,
    vendor_name: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Async variant — consults built-in AND custom rules safely from an
    async context. Prefer this in request handlers + schedulers."""
    if not file_name:
        return None
    fn = file_name.strip()
    vendor_str = (vendor_canonical or vendor_name or "").strip()
    hit = _try_match(_COMPILED, fn, vendor_str, origin="builtin")
    if hit:
        return hit
    custom = await _get_custom_rules()
    return _try_match(custom, fn, vendor_str, origin="custom")


# ── Candidate filter ────────────────────────────────────────────

def _build_candidate_filter() -> Dict[str, Any]:
    """Docs we're willing to *propose* a heuristic for.

    Requirements:
      • All three type fields unclassified (same definition as reclaim)
      • Not already heuristic-classified (idempotent)
      • No BC evidence (defensive)
    """
    bc_not_present = {
        "$and": [{f: {"$in": [None, ""]}} for f in BC_EVIDENCE_FIELDS]
    }
    return {
        "$and": [
            {"doc_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"document_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"suggested_job_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"filename_heuristic_applied_at": {"$in": [None, "", False]}},
            bc_not_present,
        ],
    }


# ── Preview + apply ─────────────────────────────────────────────

async def preview(*, limit: int = 1000, db=None) -> Dict[str, Any]:
    """Scan candidates and count rule matches. No writes."""
    db = db if db is not None else get_db()
    q = _build_candidate_filter()
    total = await db.hub_documents.count_documents(q)

    projection = {"_id": 0, "id": 1, "file_name": 1,
                  "vendor_canonical": 1, "vendor_name": 1}
    docs = await db.hub_documents.find(q, projection).limit(limit).to_list(limit)

    by_rule: Dict[str, int] = {}
    by_target_type: Dict[str, int] = {}
    matches: List[Dict[str, Any]] = []
    unmatched = 0

    for d in docs:
        suggestion = await classify_filename_async(
            d.get("file_name"), d.get("vendor_canonical"), d.get("vendor_name"),
        )
        if not suggestion:
            unmatched += 1
            continue
        by_rule[suggestion["rule_id"]] = by_rule.get(suggestion["rule_id"], 0) + 1
        by_target_type[suggestion["doc_type"]] = by_target_type.get(suggestion["doc_type"], 0) + 1
        matches.append({
            "id": d["id"],
            "file_name": d.get("file_name"),
            "vendor_canonical": d.get("vendor_canonical"),
            **suggestion,
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": total,
        "sample_size": len(docs),
        "matched": len(matches),
        "unmatched": unmatched,
        "by_rule": by_rule,
        "by_target_type": by_target_type,
        "sample_matches": matches[:30],
    }


async def apply(
    *,
    execute: bool = False,
    limit: Optional[int] = None,
    actor: str = "admin",
    min_confidence: float = 0.70,
    keep_in_review: bool = True,
    db=None,
) -> Dict[str, Any]:
    """Apply heuristic classifications. Dry-run by default.

    Args:
        execute: True to mutate.
        limit: cap on docs processed.
        actor: audit label.
        min_confidence: skip rules below this.
        keep_in_review: if True (default), the doc stays at its current
            status (usually NeedsReview) but gets enriched. If False, the
            doc is NOT moved — we only update type fields. (We never
            auto-CLEAR via a heuristic; always require human signoff.)
    """
    db = db if db is not None else get_db()

    if not execute:
        p = await preview(db=db, limit=limit or 1000)
        return {**p, "execute": False, "min_confidence": min_confidence,
                "hint": "Dry-run. Pass execute=true to apply."}

    q = _build_candidate_filter()
    projection = {"_id": 0, "id": 1, "file_name": 1, "doc_type": 1,
                  "document_type": 1, "suggested_job_type": 1,
                  "vendor_canonical": 1, "vendor_name": 1, "status": 1}
    cursor = db.hub_documents.find(q, projection)
    if limit:
        cursor = cursor.limit(int(limit))

    now = datetime.now(timezone.utc).isoformat()
    applied: List[Dict[str, Any]] = []
    below_threshold: List[str] = []
    unmatched_ids: List[str] = []
    errors: List[Dict[str, Any]] = []

    async for doc in cursor:
        doc_id = doc.get("id")
        if not doc_id:
            continue
        try:
            suggestion = await classify_filename_async(
                doc.get("file_name"),
                doc.get("vendor_canonical"),
                doc.get("vendor_name"),
            )
            if not suggestion:
                unmatched_ids.append(doc_id)
                continue
            if suggestion["confidence"] < min_confidence:
                below_threshold.append(doc_id)
                continue

            update = {
                "$set": {
                    "doc_type": suggestion["doc_type"],
                    "document_type": suggestion["doc_type"],
                    "suggested_job_type": suggestion["doc_type"],
                    "doc_type_before_heuristic": doc.get("doc_type"),
                    "filename_heuristic_applied_at": now,
                    "filename_heuristic_applied": True,
                    "filename_heuristic_rule": suggestion["rule_id"],
                    "filename_heuristic_confidence": suggestion["confidence"],
                    "filename_heuristic_note": suggestion["note"],
                    "filename_heuristic_actor": actor,
                    "updated_utc": now,
                },
                "$push": {
                    "workflow_history": {
                        "timestamp": now,
                        "from_status": doc.get("status"),
                        "to_status": doc.get("status"),
                        "event": "filename_heuristic_classified",
                        "actor": actor,
                        "reason": (
                            f"Filename heuristic '{suggestion['rule_id']}' "
                            f"→ doc_type={suggestion['doc_type']} "
                            f"(confidence={suggestion['confidence']}). "
                            f"Evidence: {suggestion['note']}"
                        ),
                    },
                },
            }
            r = await db.hub_documents.update_one({"id": doc_id}, update)
            if r.modified_count:
                applied.append({
                    "id": doc_id,
                    "rule_id": suggestion["rule_id"],
                    "doc_type": suggestion["doc_type"],
                })
        except Exception as e:  # noqa: BLE001
            logger.warning("[FilenameHeuristics] doc %s failed: %s", doc_id, e)
            errors.append({"doc_id": doc_id, "error": str(e)})

    by_rule: Dict[str, int] = {}
    by_target_type: Dict[str, int] = {}
    for row in applied:
        by_rule[row["rule_id"]] = by_rule.get(row["rule_id"], 0) + 1
        by_target_type[row["doc_type"]] = by_target_type.get(row["doc_type"], 0) + 1

    result = {
        "generated_at": now,
        "execute": True,
        "actor": actor,
        "limit_applied": limit,
        "min_confidence": min_confidence,
        "keep_in_review": keep_in_review,
        "applied_count": len(applied),
        "below_threshold_count": len(below_threshold),
        "unmatched_count": len(unmatched_ids),
        "by_rule": by_rule,
        "by_target_type": by_target_type,
        "applied_sample": applied[:50],
        "errors_count": len(errors),
        "errors": errors[:20],
    }
    try:
        await db.filename_heuristic_runs.insert_one({**result, "ran_at": now})
    except Exception as e:  # noqa: BLE001
        logger.debug("[FilenameHeuristics] audit insert failed: %s", e)

    logger.info(
        "[FilenameHeuristics] actor=%s applied=%d below=%d unmatched=%d errors=%d",
        actor, len(applied), len(below_threshold), len(unmatched_ids), len(errors),
    )
    return result


async def recent_runs(limit: int = 20, db=None) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    return await db.filename_heuristic_runs.find(
        {}, {"_id": 0},
    ).sort("ran_at", -1).limit(limit).to_list(limit)


def list_rules() -> List[Dict[str, Any]]:
    """Expose the rule set for UI/admin visibility."""
    return [
        {
            "rule_id": rid,
            "vendor_regex": vr,
            "filename_regex": fr,
            "doc_type": dt,
            "confidence": conf,
            "note": note,
        }
        for (rid, vr, fr, dt, conf, note) in FILENAME_RULES
    ]


__all__ = [
    "classify_filename", "preview", "apply", "recent_runs", "list_rules",
    "FILENAME_RULES",
]
