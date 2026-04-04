"""
Advanced Learning Engine — 7 engines that learn EVERYTHING.

1. LINE ITEM INTELLIGENCE      — Memorize vendor line patterns + GL mappings
2. DOCUMENT FLOW SEQUENCING    — Learn arrival order per vendor, predict next doc
3. AMOUNT PATTERN LEARNING     — Per-vendor amount ranges + anomaly detection
4. CORRECTION REPLAY ENGINE    — Replay corrections across all similar docs
5. FIELD CORRELATION LEARNING  — Learn field→field prediction rules
6. TEMPORAL INTELLIGENCE       — Day/hour patterns, volume prediction
7. ERROR PATTERN RECOGNITION   — Categorize failures, learn how to handle each
"""

import logging
import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from collections import Counter, defaultdict

logger = logging.getLogger("advanced_learning")

# Collections
LINE_INTEL_COL = "line_item_intelligence"
DOC_FLOW_COL = "document_flow_sequences"
AMOUNT_PATTERNS_COL = "amount_patterns"
CORRECTION_REPLAY_COL = "correction_replays"
FIELD_CORRELATIONS_COL = "field_correlations"
TEMPORAL_INTEL_COL = "temporal_intelligence"
ERROR_PATTERNS_COL = "error_patterns"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _utcnow():
    return datetime.now(timezone.utc)


# =============================================================================
# 1. LINE ITEM INTELLIGENCE
# =============================================================================

async def learn_line_items(db, doc: Dict):
    """
    Memorize line item patterns per vendor: descriptions, GL accounts,
    item numbers, typical amounts, quantities. Used to auto-map future lines.
    """
    vendor_no = (doc.get("bc_vendor_number") or doc.get("vendor_no")
                 or doc.get("matched_vendor_no") or "")
    if not vendor_no:
        return

    extracted = doc.get("extracted_fields") or {}
    line_items = extracted.get("line_items") or []
    if not line_items:
        return

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    for li in line_items:
        desc = (li.get("description") or li.get("item") or "").strip()
        if not desc:
            continue

        # Normalize description for pattern matching
        desc_lower = desc.lower().strip()
        desc_key = desc_lower.replace(" ", "_").replace(",", "")[:60]

        amount = 0.0
        for af in ["amount", "total", "unit_price", "line_amount"]:
            val = li.get(af)
            if val:
                try:
                    amount = float(str(val).replace("$", "").replace(",", "").strip())
                    break
                except (ValueError, TypeError):
                    pass

        gl_account = li.get("gl_account") or li.get("account") or li.get("account_no") or ""
        item_no = li.get("item_number") or li.get("item_no") or li.get("no") or ""
        quantity = li.get("quantity") or 1

        safe_key = desc_key.replace(".", "_").replace("$", "_")

        await db[LINE_INTEL_COL].update_one(
            {"vendor_no": vendor_no, "line_key": safe_key},
            {
                "$set": {
                    "vendor_no": vendor_no,
                    "line_key": safe_key,
                    "description_canonical": desc,
                    "doc_type": doc_type,
                    "last_gl_account": gl_account,
                    "last_item_no": item_no,
                    "updated_at": _now(),
                },
                "$inc": {"seen_count": 1, "total_amount": amount, "total_quantity": float(quantity)},
                "$min": {"min_amount": amount} if amount > 0 else {},
                "$max": {"max_amount": amount} if amount > 0 else {},
                "$addToSet": {
                    "gl_accounts_seen": gl_account,
                    "item_numbers_seen": item_no,
                } if gl_account or item_no else {},
            },
            upsert=True,
        )

    # Update vendor line item summary
    line_count = await db[LINE_INTEL_COL].count_documents({"vendor_no": vendor_no})
    await db[LINE_INTEL_COL].update_one(
        {"vendor_no": vendor_no, "line_key": "__summary__"},
        {"$set": {
            "vendor_no": vendor_no,
            "line_key": "__summary__",
            "unique_line_types": line_count,
            "updated_at": _now(),
        }, "$inc": {"total_invoices_with_lines": 1}},
        upsert=True,
    )


async def get_line_item_suggestions(db, vendor_no: str) -> List[Dict]:
    """Get learned line item patterns for a vendor — suggest GL mappings."""
    patterns = await db[LINE_INTEL_COL].find(
        {"vendor_no": vendor_no, "line_key": {"$ne": "__summary__"}},
        {"_id": 0}
    ).sort("seen_count", -1).limit(20).to_list(20)

    suggestions = []
    for p in patterns:
        seen = p.get("seen_count", 0)
        avg_amount = p.get("total_amount", 0) / max(seen, 1)
        suggestions.append({
            "description": p.get("description_canonical", ""),
            "seen_count": seen,
            "avg_amount": round(avg_amount, 2),
            "min_amount": p.get("min_amount", 0),
            "max_amount": p.get("max_amount", 0),
            "suggested_gl": p.get("last_gl_account", ""),
            "suggested_item": p.get("last_item_no", ""),
            "gl_accounts_seen": p.get("gl_accounts_seen", []),
        })
    return suggestions


# =============================================================================
# 2. DOCUMENT FLOW SEQUENCING
# =============================================================================

async def learn_document_flow(db, doc: Dict):
    """
    Track document arrival sequences per vendor.
    E.g., BOL → PO → Invoice always arrives in that order for TUMALOC.
    """
    vendor_no = (doc.get("bc_vendor_number") or doc.get("vendor_no")
                 or doc.get("matched_vendor_no") or "")
    if not vendor_no:
        return

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    if not doc_type or doc_type in ("Unknown", "Unknown_Document"):
        return

    po_number = (doc.get("extracted_fields") or {}).get("po_number") or ""
    ref_number = (doc.get("extracted_fields") or {}).get("reference_number") or ""
    group_key = po_number or ref_number or ""

    created = doc.get("created_utc") or doc.get("ingested_at") or _now()

    await db[DOC_FLOW_COL].insert_one({
        "vendor_no": vendor_no,
        "doc_type": doc_type,
        "group_key": group_key,
        "doc_id": doc.get("id", ""),
        "arrived_at": created,
        "recorded_at": _now(),
    })

    # Update vendor flow pattern: track doc type transitions
    recent = await db[DOC_FLOW_COL].find(
        {"vendor_no": vendor_no},
        {"_id": 0, "doc_type": 1, "arrived_at": 1}
    ).sort("arrived_at", -1).limit(50).to_list(50)

    if len(recent) >= 2:
        # Count transitions (type A → type B)
        transitions = Counter()
        for i in range(len(recent) - 1):
            from_type = recent[i + 1].get("doc_type", "")
            to_type = recent[i].get("doc_type", "")
            if from_type and to_type:
                transitions[f"{from_type}→{to_type}"] += 1

        if transitions:
            top_transitions = dict(transitions.most_common(10))
            await db[DOC_FLOW_COL].update_one(
                {"vendor_no": vendor_no, "_summary": True},
                {"$set": {
                    "vendor_no": vendor_no,
                    "_summary": True,
                    "transitions": top_transitions,
                    "total_docs": len(recent),
                    "last_doc_type": recent[0].get("doc_type", ""),
                    "updated_at": _now(),
                }},
                upsert=True,
            )


async def predict_next_document(db, vendor_no: str) -> Dict:
    """Predict what document type will arrive next from a vendor."""
    summary = await db[DOC_FLOW_COL].find_one(
        {"vendor_no": vendor_no, "_summary": True}, {"_id": 0}
    )
    if not summary:
        return {"vendor_no": vendor_no, "prediction": "unknown", "confidence": 0}

    last_type = summary.get("last_doc_type", "")
    transitions = summary.get("transitions") or {}

    # Find all transitions FROM the last doc type
    candidates = {}
    for t_key, count in transitions.items():
        parts = t_key.split("→")
        if len(parts) == 2 and parts[0] == last_type:
            candidates[parts[1]] = count

    if not candidates:
        return {"vendor_no": vendor_no, "last_type": last_type,
                "prediction": "unknown", "confidence": 0}

    total = sum(candidates.values())
    best = max(candidates, key=candidates.get)
    conf = candidates[best] / total

    return {
        "vendor_no": vendor_no,
        "last_type": last_type,
        "predicted_next": best,
        "confidence": round(conf, 3),
        "alternatives": {k: round(v / total, 3) for k, v in candidates.items()},
    }


# =============================================================================
# 3. AMOUNT PATTERN LEARNING
# =============================================================================

async def learn_amount_pattern(db, doc: Dict):
    """
    Learn typical invoice amounts per vendor. Detect anomalies.
    """
    vendor_no = (doc.get("bc_vendor_number") or doc.get("vendor_no")
                 or doc.get("matched_vendor_no") or "")
    if not vendor_no:
        return

    extracted = doc.get("extracted_fields") or {}
    amount = 0.0
    for af in ["amount", "invoice_amount", "total_amount"]:
        val = extracted.get(af)
        if val:
            try:
                amount = float(str(val).replace("$", "").replace(",", "").strip())
                break
            except (ValueError, TypeError):
                pass

    if amount <= 0:
        return

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    # Store individual amount
    await db[AMOUNT_PATTERNS_COL].update_one(
        {"vendor_no": vendor_no},
        {
            "$push": {"amounts": {"$each": [amount], "$slice": -200}},
            "$inc": {"count": 1, "sum": amount},
            "$min": {"min_amount": amount},
            "$max": {"max_amount": amount},
            "$set": {
                "vendor_no": vendor_no,
                "doc_type": doc_type,
                "last_amount": amount,
                "updated_at": _now(),
            },
        },
        upsert=True,
    )

    # Recompute stats
    record = await db[AMOUNT_PATTERNS_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if record:
        amounts = record.get("amounts", [])
        count = len(amounts)
        if count >= 3:
            avg = sum(amounts) / count
            variance = sum((a - avg) ** 2 for a in amounts) / count
            stddev = math.sqrt(variance) if variance > 0 else 0

            # Detect if current amount is anomalous (>2 stddev from mean)
            is_anomaly = abs(amount - avg) > (2 * stddev) if stddev > 0 else False

            await db[AMOUNT_PATTERNS_COL].update_one(
                {"vendor_no": vendor_no},
                {"$set": {
                    "avg_amount": round(avg, 2),
                    "stddev": round(stddev, 2),
                    "latest_is_anomaly": is_anomaly,
                }},
            )

            if is_anomaly:
                logger.warning(
                    "[AmountAnomaly] vendor=%s amount=%.2f avg=%.2f stddev=%.2f — ANOMALY DETECTED",
                    vendor_no, amount, avg, stddev,
                )


async def check_amount_anomaly(db, vendor_no: str, amount: float) -> Dict:
    """Check if an amount is anomalous for a vendor."""
    record = await db[AMOUNT_PATTERNS_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if not record or record.get("count", 0) < 3:
        return {"is_anomaly": False, "reason": "insufficient_data"}

    avg = record.get("avg_amount", 0)
    stddev = record.get("stddev", 0)

    if stddev == 0:
        return {"is_anomaly": amount != avg, "reason": "zero_variance",
                "avg": avg, "amount": amount}

    z_score = abs(amount - avg) / stddev
    is_anomaly = z_score > 2.0

    return {
        "is_anomaly": is_anomaly,
        "z_score": round(z_score, 2),
        "avg_amount": avg,
        "stddev": stddev,
        "min_seen": record.get("min_amount", 0),
        "max_seen": record.get("max_amount", 0),
        "typical_range": [round(avg - 2 * stddev, 2), round(avg + 2 * stddev, 2)],
        "amount": amount,
        "severity": "high" if z_score > 3 else "medium" if z_score > 2 else "normal",
    }


# =============================================================================
# 4. CORRECTION REPLAY ENGINE
# =============================================================================

async def replay_correction(db, vendor_no: str, field_name: str,
                            old_value: str, new_value: str, source_doc_id: str) -> Dict:
    """
    When a human corrects a field, replay that correction across all
    similar documents from the same vendor that have the old value.
    """
    query = {
        "id": {"$ne": source_doc_id},
        "$or": [
            {"bc_vendor_number": vendor_no},
            {"vendor_no": vendor_no},
            {"matched_vendor_no": vendor_no},
        ],
        f"extracted_fields.{field_name}": old_value,
        "status": {"$nin": ["Completed", "Posted", "Archived"]},
    }

    candidates = await db.hub_documents.find(
        query, {"_id": 0, "id": 1, f"extracted_fields.{field_name}": 1, "status": 1}
    ).limit(50).to_list(50)

    replayed = 0
    skipped = 0

    for c in candidates:
        doc_id = c.get("id", "")
        try:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    f"extracted_fields.{field_name}": new_value,
                    f"correction_replay.{field_name}": {
                        "from": old_value,
                        "to": new_value,
                        "replayed_from": source_doc_id,
                        "replayed_at": _now(),
                    },
                }},
            )
            replayed += 1
        except Exception:
            skipped += 1

    # Record the replay
    replay_record = {
        "vendor_no": vendor_no,
        "field_name": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "source_doc_id": source_doc_id,
        "candidates_found": len(candidates),
        "replayed": replayed,
        "skipped": skipped,
        "replayed_at": _now(),
    }
    await db[CORRECTION_REPLAY_COL].insert_one(replay_record)

    if replayed > 0:
        logger.info(
            "[CorrectionReplay] vendor=%s field=%s: replayed %d/%d docs (%s→%s)",
            vendor_no, field_name, replayed, len(candidates), old_value[:20], new_value[:20],
        )

    return replay_record


async def get_replay_history(db, limit: int = 20) -> List[Dict]:
    """Get recent correction replays."""
    return await db[CORRECTION_REPLAY_COL].find(
        {}, {"_id": 0}
    ).sort("replayed_at", -1).limit(limit).to_list(limit)


# =============================================================================
# 5. FIELD CORRELATION LEARNING
# =============================================================================

async def learn_field_correlations(db, doc: Dict):
    """
    Learn which fields predict other fields.
    E.g., PO prefix "GPI-" → always freight. Vendor contains "LOGISTICS" → AP_Invoice.
    """
    extracted = doc.get("extracted_fields") or {}
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    if not doc_type or not extracted:
        return

    # Build field features
    features = {}
    po = extracted.get("po_number") or ""
    if po:
        # PO prefix patterns
        prefix = po[:3].upper() if len(po) >= 3 else po.upper()
        features["po_prefix"] = prefix

    vendor_name = extracted.get("vendor") or ""
    if vendor_name:
        vn_lower = vendor_name.lower()
        for keyword in ["freight", "logistics", "shipping", "transport", "carrier",
                        "supply", "material", "tool", "chemical", "electric"]:
            if keyword in vn_lower:
                features["vendor_keyword"] = keyword
                break

    amount = 0.0
    for af in ["amount", "invoice_amount", "total_amount"]:
        val = extracted.get(af)
        if val:
            try:
                amount = float(str(val).replace("$", "").replace(",", "").strip())
                break
            except (ValueError, TypeError):
                pass

    if amount > 0:
        if amount < 500:
            features["amount_range"] = "small"
        elif amount < 5000:
            features["amount_range"] = "medium"
        elif amount < 50000:
            features["amount_range"] = "large"
        else:
            features["amount_range"] = "xlarge"

    line_items = extracted.get("line_items") or []
    features["line_count_bucket"] = "0" if not line_items else "1" if len(line_items) == 1 else "2-5" if len(line_items) <= 5 else "many"

    has_date = bool(extracted.get("invoice_date") or extracted.get("date"))
    features["has_date"] = str(has_date)

    # Store correlations: feature → doc_type
    for feat_name, feat_val in features.items():
        safe_name = feat_name.replace(".", "_").replace("$", "_")
        safe_val = str(feat_val).replace(".", "_").replace("$", "_")
        corr_key = f"{safe_name}={safe_val}"

        await db[FIELD_CORRELATIONS_COL].update_one(
            {"correlation_key": corr_key},
            {
                "$inc": {
                    "total": 1,
                    f"doc_types.{doc_type.replace('.', '_').replace('$', '_')}": 1,
                },
                "$set": {
                    "correlation_key": corr_key,
                    "feature_name": feat_name,
                    "feature_value": str(feat_val),
                    "updated_at": _now(),
                },
            },
            upsert=True,
        )


async def get_field_predictions(db, doc: Dict) -> List[Dict]:
    """Use learned correlations to predict doc type from field values."""
    extracted = doc.get("extracted_fields") or {}

    # Build same features
    features = {}
    po = extracted.get("po_number") or ""
    if po and len(po) >= 3:
        features["po_prefix"] = po[:3].upper()

    vendor_name = extracted.get("vendor") or ""
    if vendor_name:
        vn_lower = vendor_name.lower()
        for kw in ["freight", "logistics", "shipping", "transport", "carrier",
                    "supply", "material", "tool", "chemical", "electric"]:
            if kw in vn_lower:
                features["vendor_keyword"] = kw
                break

    predictions = []
    for feat_name, feat_val in features.items():
        safe_name = feat_name.replace(".", "_").replace("$", "_")
        safe_val = str(feat_val).replace(".", "_").replace("$", "_")
        corr_key = f"{safe_name}={safe_val}"

        corr = await db[FIELD_CORRELATIONS_COL].find_one(
            {"correlation_key": corr_key}, {"_id": 0}
        )
        if corr and corr.get("total", 0) >= 3:
            doc_types = corr.get("doc_types", {})
            total = corr["total"]
            best_type = max(doc_types, key=doc_types.get) if doc_types else ""
            if best_type:
                confidence = doc_types[best_type] / total
                predictions.append({
                    "feature": f"{feat_name}={feat_val}",
                    "predicted_type": best_type.replace("_", " "),
                    "confidence": round(confidence, 3),
                    "samples": total,
                })

    return sorted(predictions, key=lambda x: x["confidence"], reverse=True)


# =============================================================================
# 6. TEMPORAL INTELLIGENCE
# =============================================================================

async def learn_temporal_pattern(db, doc: Dict):
    """
    Learn time-based patterns: day-of-week volume, hour-of-day,
    processing speed per vendor.
    """
    created = doc.get("created_utc") or doc.get("ingested_at") or ""
    if not created:
        return

    try:
        if isinstance(created, str):
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        else:
            dt = created
    except (ValueError, TypeError):
        return

    dow = dt.strftime("%A")  # Monday, Tuesday, etc.
    hour = dt.hour
    month = dt.strftime("%Y-%m")
    date_str = dt.strftime("%Y-%m-%d")

    vendor_no = (doc.get("bc_vendor_number") or doc.get("vendor_no")
                 or doc.get("matched_vendor_no") or "")
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    # Global temporal patterns
    await db[TEMPORAL_INTEL_COL].update_one(
        {"temporal_id": "global"},
        {
            "$inc": {
                f"by_dow.{dow}": 1,
                f"by_hour.h{hour:02d}": 1,
                f"by_month.{month}": 1,
                f"by_date.{date_str}": 1,
            },
            "$set": {"temporal_id": "global", "updated_at": _now()},
        },
        upsert=True,
    )

    # Per-vendor temporal
    if vendor_no:
        await db[TEMPORAL_INTEL_COL].update_one(
            {"temporal_id": f"vendor_{vendor_no}"},
            {
                "$inc": {
                    f"by_dow.{dow}": 1,
                    f"by_hour.h{hour:02d}": 1,
                    "total": 1,
                },
                "$set": {
                    "temporal_id": f"vendor_{vendor_no}",
                    "vendor_no": vendor_no,
                    "last_seen": _now(),
                    "updated_at": _now(),
                },
            },
            upsert=True,
        )

    # Per-doc-type temporal
    if doc_type:
        safe_type = doc_type.replace(".", "_").replace("$", "_")
        await db[TEMPORAL_INTEL_COL].update_one(
            {"temporal_id": f"type_{safe_type}"},
            {
                "$inc": {
                    f"by_dow.{dow}": 1,
                    f"by_hour.h{hour:02d}": 1,
                    "total": 1,
                },
                "$set": {
                    "temporal_id": f"type_{safe_type}",
                    "doc_type": doc_type,
                    "updated_at": _now(),
                },
            },
            upsert=True,
        )


async def predict_volume(db) -> Dict:
    """Predict tomorrow's inbox volume based on learned patterns."""
    global_data = await db[TEMPORAL_INTEL_COL].find_one(
        {"temporal_id": "global"}, {"_id": 0}
    )
    if not global_data:
        return {"prediction": "no_data"}

    by_dow = global_data.get("by_dow", {})
    by_date = global_data.get("by_date", {})

    # Tomorrow's day of week
    tomorrow = _utcnow() + timedelta(days=1)
    tomorrow_dow = tomorrow.strftime("%A")

    # Average for that day of week
    dow_avg = by_dow.get(tomorrow_dow, 0)
    total_weeks = max(len(by_date) / 7, 1)
    predicted = round(dow_avg / total_weeks) if total_weeks > 0 else 0

    # Recent daily average (last 7 days)
    recent_total = 0
    recent_days = 0
    for i in range(1, 8):
        d = (_utcnow() - timedelta(days=i)).strftime("%Y-%m-%d")
        v = by_date.get(d, 0)
        if v > 0:
            recent_total += v
            recent_days += 1

    recent_avg = round(recent_total / max(recent_days, 1))

    # Blend prediction
    blended = round((predicted + recent_avg) / 2) if predicted > 0 else recent_avg

    # Peak day detection
    peak_day = max(by_dow, key=by_dow.get) if by_dow else "unknown"
    quiet_day = min(by_dow, key=by_dow.get) if by_dow else "unknown"

    return {
        "tomorrow": tomorrow.strftime("%A %Y-%m-%d"),
        "predicted_volume": blended,
        "dow_historical": dow_avg,
        "recent_7day_avg": recent_avg,
        "peak_day": peak_day,
        "quiet_day": quiet_day,
        "by_day_of_week": by_dow,
    }


# =============================================================================
# 7. ERROR PATTERN RECOGNITION
# =============================================================================

async def learn_error_pattern(db, doc: Dict, error_type: str, error_detail: str):
    """
    When extraction or processing fails, categorize WHY.
    Scan quality? Wrong page? New layout? Missing fields?
    """
    vendor_no = (doc.get("bc_vendor_number") or doc.get("vendor_no")
                 or doc.get("matched_vendor_no") or "")
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    doc_id = doc.get("id", "")

    # Categorize the error
    error_category = "unknown"
    detail_lower = error_detail.lower() if error_detail else ""

    if any(k in detail_lower for k in ["scan", "ocr", "unreadable", "blurry", "image quality"]):
        error_category = "scan_quality"
    elif any(k in detail_lower for k in ["no text", "empty", "blank"]):
        error_category = "empty_document"
    elif any(k in detail_lower for k in ["timeout", "rate limit", "api error"]):
        error_category = "api_failure"
    elif any(k in detail_lower for k in ["not found", "missing", "no match"]):
        error_category = "missing_data"
    elif any(k in detail_lower for k in ["duplicate", "already exists"]):
        error_category = "duplicate"
    elif any(k in detail_lower for k in ["format", "parse", "invalid", "unexpected"]):
        error_category = "format_error"
    elif any(k in detail_lower for k in ["new layout", "changed", "different"]):
        error_category = "layout_change"
    else:
        error_category = "other"

    await db[ERROR_PATTERNS_COL].insert_one({
        "doc_id": doc_id,
        "vendor_no": vendor_no,
        "doc_type": doc_type,
        "error_type": error_type,
        "error_category": error_category,
        "error_detail": error_detail[:500],
        "recorded_at": _now(),
    })

    # Update category counters
    await db[ERROR_PATTERNS_COL].update_one(
        {"_summary": True, "type": "category_counts"},
        {
            "$inc": {
                f"categories.{error_category}": 1,
                "total_errors": 1,
            },
            "$set": {"_summary": True, "type": "category_counts", "updated_at": _now()},
        },
        upsert=True,
    )

    # Per-vendor error tracking
    if vendor_no:
        await db[ERROR_PATTERNS_COL].update_one(
            {"_summary": True, "type": "vendor_errors", "vendor_no": vendor_no},
            {
                "$inc": {f"categories.{error_category}": 1, "total": 1},
                "$set": {
                    "_summary": True, "type": "vendor_errors",
                    "vendor_no": vendor_no, "updated_at": _now(),
                },
            },
            upsert=True,
        )


async def learn_from_validation_failure(db, doc: Dict):
    """Learn from validation failures on a document."""
    vr = doc.get("validation_results") or {}
    checks = vr.get("checks") or []

    for check in checks:
        if isinstance(check, dict) and not check.get("passed", True):
            error_type = check.get("check_name", "validation")
            error_detail = check.get("message", check.get("details", ""))
            await learn_error_pattern(db, doc, error_type, error_detail)


# =============================================================================
# MASTER HOOK — Called from per_document_learning_service
# =============================================================================

async def run_advanced_learning(db, doc_id: str, trigger: str = "ingestion"):
    """Run all 7 advanced learning engines on a document."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"learned": False}

    results = {}

    # 1. Line Item Intelligence
    try:
        await learn_line_items(db, doc)
        results["line_items"] = "ok"
    except Exception as e:
        results["line_items"] = f"error: {e}"

    # 2. Document Flow Sequencing
    try:
        await learn_document_flow(db, doc)
        results["doc_flow"] = "ok"
    except Exception as e:
        results["doc_flow"] = f"error: {e}"

    # 3. Amount Pattern Learning
    try:
        await learn_amount_pattern(db, doc)
        results["amount_pattern"] = "ok"
    except Exception as e:
        results["amount_pattern"] = f"error: {e}"

    # 5. Field Correlations
    try:
        await learn_field_correlations(db, doc)
        results["field_correlations"] = "ok"
    except Exception as e:
        results["field_correlations"] = f"error: {e}"

    # 6. Temporal Intelligence
    try:
        await learn_temporal_pattern(db, doc)
        results["temporal"] = "ok"
    except Exception as e:
        results["temporal"] = f"error: {e}"

    # 7. Error Pattern Recognition (from validation failures)
    try:
        await learn_from_validation_failure(db, doc)
        results["error_patterns"] = "ok"
    except Exception as e:
        results["error_patterns"] = f"error: {e}"

    return results


# =============================================================================
# QUERY APIs
# =============================================================================

async def get_advanced_learning_summary(db) -> Dict:
    """Summary of all 7 advanced learning engines."""

    # 1. Line Item Intelligence
    line_vendors = await db[LINE_INTEL_COL].count_documents({"line_key": "__summary__"})
    line_patterns = await db[LINE_INTEL_COL].count_documents({"line_key": {"$ne": "__summary__"}})
    top_line_vendors = await db[LINE_INTEL_COL].find(
        {"line_key": "__summary__"},
        {"_id": 0, "vendor_no": 1, "unique_line_types": 1, "total_invoices_with_lines": 1}
    ).sort("total_invoices_with_lines", -1).limit(5).to_list(5)

    # 2. Document Flow
    flow_vendors = await db[DOC_FLOW_COL].count_documents({"_summary": True})
    total_flow_events = await db[DOC_FLOW_COL].count_documents({"_summary": {"$ne": True}})

    # 3. Amount Patterns
    amount_vendors = await db[AMOUNT_PATTERNS_COL].count_documents({})
    anomalies = await db[AMOUNT_PATTERNS_COL].count_documents({"latest_is_anomaly": True})
    top_amount_vendors = await db[AMOUNT_PATTERNS_COL].find(
        {}, {"_id": 0, "vendor_no": 1, "count": 1, "avg_amount": 1, "min_amount": 1,
             "max_amount": 1, "latest_is_anomaly": 1}
    ).sort("count", -1).limit(5).to_list(5)

    # 4. Correction Replays
    total_replays = await db[CORRECTION_REPLAY_COL].count_documents({})
    total_replayed_docs = 0
    replay_pipeline = [{"$group": {"_id": None, "total": {"$sum": "$replayed"}}}]
    rp_agg = await db[CORRECTION_REPLAY_COL].aggregate(replay_pipeline).to_list(1)
    if rp_agg:
        total_replayed_docs = rp_agg[0].get("total", 0)

    # 5. Field Correlations
    total_correlations = await db[FIELD_CORRELATIONS_COL].count_documents({})
    strong_correlations = await db[FIELD_CORRELATIONS_COL].find(
        {"total": {"$gte": 5}}, {"_id": 0}
    ).sort("total", -1).limit(10).to_list(10)

    # Compute top predictions
    top_predictions = []
    for corr in strong_correlations:
        doc_types = corr.get("doc_types", {})
        total = corr.get("total", 1)
        if doc_types:
            best_type = max(doc_types, key=doc_types.get)
            confidence = doc_types[best_type] / total
            if confidence >= 0.7:
                top_predictions.append({
                    "rule": f"{corr.get('feature_name')}={corr.get('feature_value')}",
                    "predicts": best_type,
                    "confidence": round(confidence, 3),
                    "samples": total,
                })

    # 6. Temporal Intelligence
    temporal = await db[TEMPORAL_INTEL_COL].find_one(
        {"temporal_id": "global"}, {"_id": 0}
    )
    volume_prediction = await predict_volume(db)

    # 7. Error Patterns
    error_summary = await db[ERROR_PATTERNS_COL].find_one(
        {"_summary": True, "type": "category_counts"}, {"_id": 0}
    )

    return {
        "line_item_intelligence": {
            "vendors_tracked": line_vendors,
            "unique_patterns": line_patterns,
            "top_vendors": top_line_vendors,
        },
        "document_flow": {
            "vendors_with_sequences": flow_vendors,
            "total_flow_events": total_flow_events,
        },
        "amount_patterns": {
            "vendors_tracked": amount_vendors,
            "active_anomalies": anomalies,
            "top_vendors": top_amount_vendors,
        },
        "correction_replay": {
            "total_replays": total_replays,
            "total_docs_corrected": total_replayed_docs,
        },
        "field_correlations": {
            "total_correlations": total_correlations,
            "strong_rules": top_predictions[:5],
        },
        "temporal_intelligence": {
            "by_day_of_week": (temporal or {}).get("by_dow", {}),
            "volume_prediction": volume_prediction,
        },
        "error_patterns": {
            "categories": (error_summary or {}).get("categories", {}),
            "total_errors": (error_summary or {}).get("total_errors", 0),
        },
        "generated_at": _now(),
    }
