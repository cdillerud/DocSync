"""
PO Format Learning Engine — Learn vendor-specific PO number transformations.

The gap: The extraction system pulls "po_number" from vendor invoices, but
different vendors use wildly different PO formats:
  - "PO-778245-GPI" (vendor adds their own suffix)
  - "3456" (just a short number — could be a PO, BOL, or trip ID)
  - "MAR26-FTL-3" (freight trip reference, not a PO at all)
  - "W117448" (matches BC exactly)

This service learns from every PO validation attempt:
  1. Records: (vendor, extracted_po, matched_bc_po, transformation_used)
  2. Builds per-vendor transformation rules
  3. Applies learned transformations BEFORE BC validation on future docs

The learning loop:
  - Doc ingested → PO extracted → Transformations applied → BC validation
  - If matched: record which transformation worked
  - If failed: record all transformations tried
  - Over time: vendor-specific rules emerge (e.g., "TUMALOC: strip suffix after last dash")
"""

import re
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("po_format_learning")

PO_FORMAT_COL = "po_format_intelligence"
PO_MATCH_LOG_COL = "po_match_log"


def _now():
    return datetime.now(timezone.utc).isoformat()


# =========================================================================
# 1. BUILT-IN TRANSFORMATIONS
# =========================================================================

TRANSFORMATIONS = [
    ("original", lambda po: po),
    ("strip_vendor_suffix", lambda po: re.sub(r'-[A-Z]{2,5}$', '', po)),  # PO-778245-GPI → PO-778245
    ("strip_prefix_po", lambda po: re.sub(r'^PO[-#\s]*', '', po, flags=re.I)),  # PO-778245 → 778245
    ("strip_prefix_p0", lambda po: re.sub(r'^P0[-#\s]*', '', po, flags=re.I)),  # P0024310-3 → 24310-3
    ("numeric_only", lambda po: re.sub(r'[^0-9]', '', po)),  # any → digits only
    ("strip_leading_zeros", lambda po: po.lstrip('0')),
    ("last_segment", lambda po: po.rsplit('-', 1)[-1] if '-' in po else po),  # PO-778245-GPI → GPI; or 3456 → 3456
    ("first_segment", lambda po: po.split('-')[0] if '-' in po else po),  # PO-778245-GPI → PO
    ("middle_segment", lambda po: po.split('-')[1] if po.count('-') >= 2 else po),  # PO-778245-GPI → 778245
    ("strip_all_dashes", lambda po: po.replace('-', '')),  # P0024310-3 → P00243103
    ("first_6_digits", lambda po: re.sub(r'[^0-9]', '', po)[:6]),  # Extract first 6 digits
    ("prefix_W", lambda po: f"W{po}" if not po.startswith('W') else po),  # 117448 → W117448
    ("strip_prefix_W", lambda po: po[1:] if po.startswith('W') else po),  # W117448 → 117448
    ("add_po_prefix", lambda po: f"PO{po}" if not po.upper().startswith('PO') else po),
    ("strip_trailing_dash_num", lambda po: re.sub(r'-\d{1,2}$', '', po)),  # P0024310-3 → P0024310
    ("combined_strip_then_numeric", lambda po: re.sub(r'[^0-9]', '', re.sub(r'-[A-Z]{2,5}$', '', po))),
]


def apply_all_transformations(po: str) -> List[Tuple[str, str]]:
    """Apply all known transformations to a PO number, return (name, result) pairs."""
    results = []
    seen = set()
    for name, fn in TRANSFORMATIONS:
        try:
            result = fn(po).strip()
            if result and len(result) >= 3 and result not in seen:
                results.append((name, result))
                seen.add(result)
        except Exception:
            continue
    return results


# =========================================================================
# 2. LEARN FROM PO MATCH OUTCOMES
# =========================================================================

async def record_po_match(
    db,
    vendor_no: str,
    extracted_po: str,
    matched: bool,
    matched_bc_po: str = "",
    transformation_used: str = "",
    doc_id: str = "",
):
    """Record a PO match attempt and update vendor PO format intelligence."""
    log_entry = {
        "vendor_no": vendor_no,
        "extracted_po": extracted_po,
        "matched": matched,
        "matched_bc_po": matched_bc_po,
        "transformation_used": transformation_used if matched else "",
        "doc_id": doc_id,
        "recorded_at": _now(),
    }

    await db[PO_MATCH_LOG_COL].insert_one(log_entry)

    # Update vendor-level PO format intelligence
    if vendor_no:
        await _update_vendor_po_intelligence(db, vendor_no)


async def _update_vendor_po_intelligence(db, vendor_no: str):
    """Recompute vendor-level PO format intelligence from match history."""

    pipeline = [
        {"$match": {"vendor_no": vendor_no}},
        {"$group": {
            "_id": "$vendor_no",
            "total_attempts": {"$sum": 1},
            "total_matched": {"$sum": {"$cond": ["$matched", 1, 0]}},
            "total_failed": {"$sum": {"$cond": ["$matched", 0, 1]}},
        }},
    ]
    global_stats = await db[PO_MATCH_LOG_COL].aggregate(pipeline).to_list(1)

    # Count which transformations succeed most
    transform_pipe = [
        {"$match": {"vendor_no": vendor_no, "matched": True, "transformation_used": {"$ne": ""}}},
        {"$group": {
            "_id": "$transformation_used",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    transform_stats = await db[PO_MATCH_LOG_COL].aggregate(transform_pipe).to_list(20)

    # Build transformation priority (most successful first)
    transform_priority = [
        {"name": t["_id"], "success_count": t["count"]}
        for t in transform_stats
    ]

    # Detect common PO format patterns from successful matches
    format_patterns = []
    successful_matches = await db[PO_MATCH_LOG_COL].find(
        {"vendor_no": vendor_no, "matched": True},
        {"_id": 0, "extracted_po": 1, "matched_bc_po": 1, "transformation_used": 1}
    ).limit(50).to_list(50)

    if successful_matches:
        # Analyze what the successful BC PO numbers look like
        bc_pos = [m["matched_bc_po"] for m in successful_matches if m.get("matched_bc_po")]
        if bc_pos:
            # Check if BC POs have a common prefix
            prefixes = [re.match(r'^([A-Z]+)', p) for p in bc_pos]
            prefix_counts = {}
            for p in prefixes:
                if p:
                    prefix = p.group(1)
                    prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1
            if prefix_counts:
                top_prefix = max(prefix_counts, key=prefix_counts.get)
                format_patterns.append({
                    "type": "bc_po_prefix",
                    "value": top_prefix,
                    "frequency": prefix_counts[top_prefix] / len(bc_pos),
                })

            # Check average PO length
            avg_len = sum(len(p) for p in bc_pos) / len(bc_pos)
            format_patterns.append({
                "type": "bc_po_avg_length",
                "value": round(avg_len, 1),
            })

    # Detect failed POs that are likely NOT PO numbers (trip IDs, BOL refs, etc.)
    failed_pos = await db[PO_MATCH_LOG_COL].find(
        {"vendor_no": vendor_no, "matched": False},
        {"_id": 0, "extracted_po": 1}
    ).limit(50).to_list(50)

    non_po_patterns = []
    if failed_pos:
        failed_vals = [f["extracted_po"] for f in failed_pos if f.get("extracted_po")]
        # Check for common patterns in failed POs
        date_like = sum(1 for v in failed_vals if re.match(r'^[A-Z]{3}\d{2}', v))
        if date_like > len(failed_vals) * 0.3:
            non_po_patterns.append("date_prefix_reference")  # MAR26-FTL-3 etc.

        very_short = sum(1 for v in failed_vals if len(v) <= 4)
        if very_short > len(failed_vals) * 0.3:
            non_po_patterns.append("short_reference")  # 3456 etc.

    g = global_stats[0] if global_stats else {}
    total = g.get("total_attempts", 0)
    matched_count = g.get("total_matched", 0)

    intel = {
        "vendor_no": vendor_no,
        "total_po_attempts": total,
        "matched_count": matched_count,
        "failed_count": g.get("total_failed", 0),
        "match_rate": round(matched_count / max(total, 1), 4),
        "transform_priority": transform_priority,
        "format_patterns": format_patterns,
        "non_po_patterns": non_po_patterns,
        "updated_at": _now(),
    }

    await db[PO_FORMAT_COL].update_one(
        {"vendor_no": vendor_no},
        {"$set": intel},
        upsert=True,
    )


# =========================================================================
# 3. APPLY LEARNED TRANSFORMATIONS
# =========================================================================

async def get_smart_po_candidates(db, vendor_no: str, extracted_po: str) -> List[str]:
    """
    Given a vendor and an extracted PO, return a prioritized list of
    PO candidates based on learned transformation rules.

    The returned list is ordered: most-likely-to-match first.
    """
    if not extracted_po or not extracted_po.strip():
        return []

    candidates = []
    seen = set()

    # 1. Always include the original
    clean = extracted_po.strip()
    candidates.append(clean)
    seen.add(clean)

    # 2. Apply vendor-specific learned transformations (if available)
    if vendor_no:
        intel = await db[PO_FORMAT_COL].find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )

        if intel and intel.get("transform_priority"):
            # Apply transformations in learned priority order
            priority = intel["transform_priority"]
            transform_map = {name: fn for name, fn in TRANSFORMATIONS}

            for tp in priority:
                t_name = tp["name"]
                if t_name in transform_map:
                    try:
                        result = transform_map[t_name](clean).strip()
                        if result and len(result) >= 3 and result not in seen:
                            candidates.append(result)
                            seen.add(result)
                    except Exception:
                        continue

            # If we know the BC PO prefix pattern, try adding it
            for fp in (intel.get("format_patterns") or []):
                if fp.get("type") == "bc_po_prefix" and fp.get("frequency", 0) > 0.5:
                    prefix = fp["value"]
                    numeric = re.sub(r'[^0-9]', '', clean)
                    if numeric and not clean.startswith(prefix):
                        prefixed = f"{prefix}{numeric}"
                        if prefixed not in seen:
                            candidates.append(prefixed)
                            seen.add(prefixed)

    # 3. Apply all generic transformations (lower priority)
    for name, fn in TRANSFORMATIONS:
        try:
            result = fn(clean).strip()
            if result and len(result) >= 3 and result not in seen:
                candidates.append(result)
                seen.add(result)
        except Exception:
            continue

    return candidates


# =========================================================================
# 4. QUERY APIs
# =========================================================================

async def get_po_format_summary(db) -> Dict:
    """Summary of PO format intelligence."""
    total_vendors = await db[PO_FORMAT_COL].count_documents({})
    total_logs = await db[PO_MATCH_LOG_COL].count_documents({})

    # Vendors with worst PO match rates
    worst = await db[PO_FORMAT_COL].find(
        {"total_po_attempts": {"$gte": 3}},
        {"_id": 0}
    ).sort("match_rate", 1).limit(10).to_list(10)

    # Most effective transformations globally
    global_transform_pipe = [
        {"$match": {"matched": True, "transformation_used": {"$ne": ""}}},
        {"$group": {"_id": "$transformation_used", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_transforms = [
        {"name": t["_id"], "count": t["count"]}
        for t in await db[PO_MATCH_LOG_COL].aggregate(global_transform_pipe).to_list(10)
    ]

    return {
        "vendors_tracked": total_vendors,
        "total_match_attempts": total_logs,
        "top_transformations": top_transforms,
        "worst_match_vendors": worst,
        "generated_at": _now(),
    }
