"""
Deep Learning Engine — 5 advanced intelligence layers.

1. EXTRACTION PATTERN LEARNING  — Remember what works per vendor per field
2. DOCUMENT SIMILARITY ENGINE   — Match unknown docs to mastered templates
3. CONFIDENCE SELF-CORRECTION   — Audit own decisions, detect drift
4. VENDOR MATURITY SCORING      — Multi-dimensional vendor mastery rating
5. PREDICTIVE READINESS         — Predict human review need before validation
"""

import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("deep_learning")

# Collections
EXTRACTION_PATTERNS_COL = "extraction_patterns"
DOC_FINGERPRINTS_COL = "document_fingerprints"
SELF_CORRECTION_COL = "self_correction_audits"
VENDOR_MATURITY_COL = "vendor_maturity_scores"
READINESS_PREDICTIONS_COL = "readiness_predictions"


def _now():
    return datetime.now(timezone.utc).isoformat()


# =============================================================================
# 1. EXTRACTION PATTERN LEARNING
# =============================================================================

async def learn_extraction_patterns(db, doc: Dict):
    """
    After every successful extraction, record WHICH fields were found
    and their characteristics per vendor. Over time, this builds a
    per-vendor extraction playbook.
    """
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
    if not vendor_no:
        return

    extracted = doc.get("extracted_fields") or {}
    if not extracted:
        return

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    # Build field presence map with value characteristics
    field_patterns = {}
    for field_name, value in extracted.items():
        if not value or field_name.startswith("_") or field_name == "line_items":
            continue

        val_str = str(value).strip()
        if not val_str:
            continue

        pattern = {
            "present": True,
            "value_length": len(val_str),
            "is_numeric": val_str.replace(".", "").replace(",", "").replace("-", "").isdigit(),
            "has_prefix": bool(any(val_str.startswith(p) for p in ["INV", "PO", "SO", "BOL", "#"])),
        }
        field_patterns[field_name] = pattern

    # Line items pattern
    line_items = extracted.get("line_items") or []
    line_pattern = {
        "count": len(line_items),
        "has_amounts": sum(1 for li in line_items if li.get("amount") or li.get("unit_price") or li.get("total")),
        "has_descriptions": sum(1 for li in line_items if li.get("description") or li.get("item")),
        "has_quantities": sum(1 for li in line_items if li.get("quantity")),
    }

    # Upsert — merge with existing patterns
    existing = await db[EXTRACTION_PATTERNS_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )

    if existing:
        # Merge field presence counts
        existing_fields = existing.get("field_presence", {})
        for fname, pat in field_patterns.items():
            safe = fname.replace(".", "_").replace("$", "_")
            if safe in existing_fields:
                existing_fields[safe]["seen_count"] = existing_fields[safe].get("seen_count", 0) + 1
                existing_fields[safe]["last_seen"] = _now()
            else:
                existing_fields[safe] = {
                    "seen_count": 1,
                    "first_seen": _now(),
                    "last_seen": _now(),
                    **pat,
                }
        field_presence = existing_fields
    else:
        field_presence = {}
        for fname, pat in field_patterns.items():
            safe = fname.replace(".", "_").replace("$", "_")
            field_presence[safe] = {
                "seen_count": 1,
                "first_seen": _now(),
                "last_seen": _now(),
                **pat,
            }

    total_docs = (existing or {}).get("total_documents", 0) + 1

    # Compute field reliability scores
    field_reliability = {}
    for fname, fdata in field_presence.items():
        seen = fdata.get("seen_count", 0)
        reliability = round(seen / max(total_docs, 1), 4)
        field_reliability[fname] = reliability

    await db[EXTRACTION_PATTERNS_COL].update_one(
        {"vendor_no": vendor_no},
        {"$set": {
            "vendor_no": vendor_no,
            "vendor_name": doc.get("vendor_canonical") or extracted.get("vendor", ""),
            "doc_type": doc_type,
            "field_presence": field_presence,
            "field_reliability": field_reliability,
            "line_item_pattern": line_pattern,
            "total_documents": total_docs,
            "updated_at": _now(),
        }},
        upsert=True,
    )

    logger.debug("[DeepLearn:ExtractionPatterns] vendor=%s fields=%d total=%d",
                 vendor_no, len(field_patterns), total_docs)


async def get_extraction_hints_for_vendor(db, vendor_no: str) -> Dict:
    """
    Get learned extraction hints for a vendor — used by the classification
    pipeline to tell the AI what fields to expect and their characteristics.
    """
    pattern = await db[EXTRACTION_PATTERNS_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if not pattern or pattern.get("total_documents", 0) < 2:
        return {}

    hints = {
        "expected_fields": [],
        "reliable_fields": [],
        "line_item_expectations": {},
    }

    for fname, reliability in (pattern.get("field_reliability") or {}).items():
        if reliability >= 0.8:
            hints["reliable_fields"].append(fname)
        elif reliability >= 0.3:
            hints["expected_fields"].append(fname)

    lp = pattern.get("line_item_pattern") or {}
    if lp.get("count", 0) > 0:
        hints["line_item_expectations"] = {
            "typical_count": lp["count"],
            "usually_has_amounts": lp.get("has_amounts", 0) > 0,
            "usually_has_descriptions": lp.get("has_descriptions", 0) > 0,
        }

    return hints


# =============================================================================
# 2. DOCUMENT SIMILARITY ENGINE
# =============================================================================

def _compute_fingerprint(doc: Dict) -> Dict:
    """Build a feature vector from a document's characteristics."""
    extracted = doc.get("extracted_fields") or {}
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    line_items = extracted.get("line_items") or []

    # Extract numerical features
    amount_str = str(extracted.get("amount") or extracted.get("invoice_amount") or extracted.get("total_amount") or "0")
    amount_clean = amount_str.replace("$", "").replace(",", "").strip()
    try:
        amount = float(amount_clean)
    except (ValueError, TypeError):
        amount = 0.0

    # Amount bucket
    if amount == 0:
        amount_bucket = "zero"
    elif amount < 100:
        amount_bucket = "tiny"
    elif amount < 1000:
        amount_bucket = "small"
    elif amount < 10000:
        amount_bucket = "medium"
    elif amount < 100000:
        amount_bucket = "large"
    else:
        amount_bucket = "xlarge"

    # Field presence signature
    field_names = sorted([k for k, v in extracted.items()
                          if v and k != "line_items" and not k.startswith("_")])
    field_sig = hashlib.md5(",".join(field_names).encode()).hexdigest()[:8]

    return {
        "doc_type": doc_type,
        "field_count": len(field_names),
        "field_names": field_names,
        "field_signature": field_sig,
        "line_item_count": len(line_items),
        "amount_bucket": amount_bucket,
        "has_po": bool(extracted.get("po_number")),
        "has_invoice_number": bool(extracted.get("invoice_number")),
        "has_vendor": bool(extracted.get("vendor")),
        "has_date": bool(extracted.get("invoice_date") or extracted.get("date")),
    }


def _similarity_score(fp1: Dict, fp2: Dict) -> float:
    """Compute similarity between two document fingerprints (0-1)."""
    score = 0.0
    weights_total = 0.0

    # Doc type match (weight: 3)
    if fp1.get("doc_type") and fp1["doc_type"] == fp2.get("doc_type"):
        score += 3.0
    weights_total += 3.0

    # Field signature match (weight: 2)
    if fp1.get("field_signature") == fp2.get("field_signature"):
        score += 2.0
    else:
        # Partial field overlap
        f1 = set(fp1.get("field_names", []))
        f2 = set(fp2.get("field_names", []))
        if f1 and f2:
            overlap = len(f1 & f2) / max(len(f1 | f2), 1)
            score += 2.0 * overlap
    weights_total += 2.0

    # Amount bucket (weight: 1.5)
    if fp1.get("amount_bucket") == fp2.get("amount_bucket"):
        score += 1.5
    weights_total += 1.5

    # Line item count similarity (weight: 1)
    lc1 = fp1.get("line_item_count", 0)
    lc2 = fp2.get("line_item_count", 0)
    if lc1 == lc2:
        score += 1.0
    elif abs(lc1 - lc2) <= 2:
        score += 0.5
    weights_total += 1.0

    # Boolean field matches (weight: 0.5 each)
    for field in ["has_po", "has_invoice_number", "has_vendor", "has_date"]:
        if fp1.get(field) == fp2.get(field):
            score += 0.5
        weights_total += 0.5

    return round(score / max(weights_total, 1), 4)


async def store_document_fingerprint(db, doc: Dict, outcome: str):
    """Store a document's fingerprint for future similarity matching."""
    doc_id = doc.get("id", "")
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""

    fp = _compute_fingerprint(doc)

    await db[DOC_FINGERPRINTS_COL].update_one(
        {"doc_id": doc_id},
        {"$set": {
            "doc_id": doc_id,
            "vendor_no": vendor_no,
            "vendor_name": doc.get("vendor_canonical") or (doc.get("extracted_fields") or {}).get("vendor", ""),
            "outcome": outcome,
            "fingerprint": fp,
            "ai_confidence": doc.get("ai_confidence") or 0.0,
            "automation_decision": doc.get("automation_decision") or "",
            "stored_at": _now(),
        }},
        upsert=True,
    )


async def find_similar_documents(db, doc: Dict, limit: int = 5) -> List[Dict]:
    """
    Find the most similar documents to a given document.
    Used for unknown vendors — find what worked for similar docs.
    """
    target_fp = _compute_fingerprint(doc)

    # Pre-filter: same doc type, successful outcomes
    query = {"outcome": {"$in": ["auto_validated", "auto_filed", "approved", "posted_to_bc", "linked"]}}
    if target_fp.get("doc_type"):
        query["fingerprint.doc_type"] = target_fp["doc_type"]

    candidates = await db[DOC_FINGERPRINTS_COL].find(
        query, {"_id": 0}
    ).limit(200).to_list(200)

    if not candidates:
        return []

    # Score each candidate
    scored = []
    for c in candidates:
        cfp = c.get("fingerprint", {})
        sim = _similarity_score(target_fp, cfp)
        scored.append({
            "doc_id": c.get("doc_id", ""),
            "vendor_no": c.get("vendor_no", ""),
            "vendor_name": c.get("vendor_name", ""),
            "outcome": c.get("outcome", ""),
            "similarity": sim,
            "ai_confidence": c.get("ai_confidence", 0),
        })

    scored.sort(key=lambda x: x["similarity"], reverse=True)
    return scored[:limit]


# =============================================================================
# 3. CONFIDENCE SELF-CORRECTION
# =============================================================================

async def run_self_correction_audit(db, sample_size: int = 50) -> Dict:
    """
    Sample auto-filed documents and re-evaluate them with current knowledge.
    Detect drift — cases where today's smarter system would decide differently.
    """
    from services.document_readiness_service import evaluate_readiness

    # Sample random auto-filed/auto-validated docs
    pipeline = [
        {"$match": {
            "$or": [
                {"auto_cleared": True},
                {"automation_decision": "auto_link"},
            ],
            "extracted_fields": {"$exists": True},
        }},
        {"$sample": {"size": sample_size}},
        {"$project": {"_id": 0}},
    ]

    docs = await db.hub_documents.aggregate(pipeline).to_list(sample_size)
    if not docs:
        return {"audited": 0, "drifts": 0, "message": "No auto-filed docs to audit"}

    audited = 0
    drifts = []
    confirmations = 0

    for doc in docs:
        doc_id = doc.get("id", "")
        original_decision = doc.get("automation_decision") or "auto_file"

        # Re-evaluate with current readiness logic
        readiness = evaluate_readiness(doc)
        new_decision = readiness.get("recommended_action", "")
        new_status = readiness.get("status", "")

        # Check for drift
        is_drift = False
        drift_reason = ""

        # If we originally auto-filed but now we'd say it needs review
        if original_decision in ("auto_file", "auto_link", "auto_clear"):
            if new_status in ("NeedsReview", "Blocked", "Exception"):
                is_drift = True
                drift_reason = f"Originally {original_decision}, now would be {new_status}"

        # Check for signal contradictions
        blockers = readiness.get("blockers") or []
        if blockers and original_decision in ("auto_file", "auto_link", "auto_clear"):
            is_drift = True
            drift_reason = f"Active blockers found: {', '.join(blockers)}"

        if is_drift:
            drift_record = {
                "doc_id": doc_id,
                "original_decision": original_decision,
                "current_evaluation": new_status,
                "current_action": new_decision,
                "drift_reason": drift_reason,
                "blockers": blockers,
                "vendor_no": doc.get("bc_vendor_number") or doc.get("vendor_no") or "",
                "doc_type": doc.get("document_type") or "",
                "ai_confidence": doc.get("ai_confidence") or 0.0,
                "audited_at": _now(),
            }
            drifts.append(drift_record)
        else:
            confirmations += 1

        audited += 1

    # Store audit results
    audit_record = {
        "audit_id": f"audit_{_now().replace(':', '-').replace('.', '-')}",
        "sample_size": sample_size,
        "audited": audited,
        "confirmations": confirmations,
        "drift_count": len(drifts),
        "drift_rate": round(len(drifts) / max(audited, 1), 4),
        "drifts": drifts[:20],  # Store top 20 drifts
        "run_at": _now(),
    }

    await db[SELF_CORRECTION_COL].insert_one(audit_record)

    # If drift rate is significant, log a warning
    drift_rate = audit_record["drift_rate"]
    if drift_rate > 0.1:
        logger.warning("[DeepLearn:SelfCorrection] HIGH drift rate: %.1f%% (%d/%d)",
                       drift_rate * 100, len(drifts), audited)
    else:
        logger.info("[DeepLearn:SelfCorrection] Audit complete: %d audited, %d drifts (%.1f%%)",
                    audited, len(drifts), drift_rate * 100)

    return {
        "audited": audited,
        "confirmations": confirmations,
        "drifts": len(drifts),
        "drift_rate": drift_rate,
        "drift_details": drifts[:10],
        "message": f"Audited {audited} docs, found {len(drifts)} decision drifts ({drift_rate * 100:.1f}%)",
    }


async def get_self_correction_history(db, limit: int = 10) -> List[Dict]:
    """Get recent self-correction audit results."""
    return await db[SELF_CORRECTION_COL].find(
        {}, {"_id": 0}
    ).sort("run_at", -1).limit(limit).to_list(limit)


# =============================================================================
# 4. VENDOR MATURITY SCORING
# =============================================================================

async def compute_vendor_maturity(db, vendor_no: str) -> Dict:
    """
    Compute a multi-dimensional maturity score for a vendor.
    Dimensions: volume, accuracy, consistency, recency, field_coverage, error_rate
    Each dimension 0-100, composite 0-100.
    """
    # Gather all data sources
    intel = await db.vendor_realtime_intelligence.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    patterns = await db[EXTRACTION_PATTERNS_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    posting = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"}, {"_id": 0}
    )

    if not intel:
        return {
            "vendor_no": vendor_no,
            "maturity_level": "unknown",
            "composite_score": 0,
            "dimensions": {},
            "message": "No learning data for this vendor",
        }

    total = intel.get("total_documents", 0)
    success = intel.get("success_count", 0)
    corrections = intel.get("correction_count", 0)
    failures = intel.get("failure_count", 0)

    # DIMENSION 1: Volume (0-100) — more docs = more mature
    if total >= 200:
        volume_score = 100
    elif total >= 100:
        volume_score = 90
    elif total >= 50:
        volume_score = 75
    elif total >= 20:
        volume_score = 60
    elif total >= 10:
        volume_score = 40
    elif total >= 3:
        volume_score = 20
    else:
        volume_score = 5

    # DIMENSION 2: Accuracy (0-100) — success rate
    accuracy_score = round((success / max(total, 1)) * 100) if total > 0 else 0

    # DIMENSION 3: Consistency (0-100) — low correction rate = high consistency
    correction_rate = corrections / max(total, 1)
    consistency_score = max(0, round((1 - correction_rate * 2) * 100))

    # DIMENSION 4: Recency (0-100) — recent activity = higher score
    last_doc = intel.get("last_document_at", "")
    recency_score = 50  # default
    if last_doc:
        try:
            last_dt = datetime.fromisoformat(last_doc.replace("Z", "+00:00"))
            days_ago = (datetime.now(timezone.utc) - last_dt).days
            if days_ago <= 1:
                recency_score = 100
            elif days_ago <= 7:
                recency_score = 80
            elif days_ago <= 30:
                recency_score = 60
            elif days_ago <= 90:
                recency_score = 40
            else:
                recency_score = 20
        except (ValueError, TypeError):
            pass

    # DIMENSION 5: Field Coverage (0-100) — how many fields reliably extracted
    field_coverage_score = 50  # Default to moderate when no extraction patterns exist
    if patterns:
        reliability = patterns.get("field_reliability") or {}
        if reliability:
            reliable_count = sum(1 for v in reliability.values() if v >= 0.7)
            total_fields = len(reliability)
            field_coverage_score = round((reliable_count / max(total_fields, 1)) * 100)
        else:
            # Patterns exist but no reliability data — infer from doc count
            field_coverage_score = 60 if total >= 20 else 40

    # DIMENSION 6: Error Rate (0-100) — low error = high score
    error_rate = failures / max(total, 1)
    error_score = max(0, round((1 - error_rate * 5) * 100))

    # Composite Score (weighted)
    weights = {
        "volume": 0.15,
        "accuracy": 0.30,
        "consistency": 0.15,
        "recency": 0.10,
        "field_coverage": 0.15,
        "error_rate": 0.15,
    }

    dimensions = {
        "volume": {"score": volume_score, "weight": weights["volume"],
                   "detail": f"{total} documents processed"},
        "accuracy": {"score": accuracy_score, "weight": weights["accuracy"],
                     "detail": f"{success}/{total} successful"},
        "consistency": {"score": consistency_score, "weight": weights["consistency"],
                        "detail": f"{corrections} corrections ({correction_rate:.0%} rate)"},
        "recency": {"score": recency_score, "weight": weights["recency"],
                    "detail": f"Last activity: {last_doc[:10] if last_doc else 'unknown'}"},
        "field_coverage": {"score": field_coverage_score, "weight": weights["field_coverage"],
                           "detail": f"{sum(1 for v in (patterns or {}).get('field_reliability', {}).values() if v >= 0.7)} reliable fields"},
        "error_rate": {"score": error_score, "weight": weights["error_rate"],
                       "detail": f"{failures} failures ({error_rate:.0%} rate)"},
    }

    composite = round(sum(d["score"] * d["weight"] for d in dimensions.values()))

    # Maturity level — aligned with UI labels
    if composite >= 75:
        level = "mastered"
    elif composite >= 60:
        level = "proficient"
    elif composite >= 40:
        level = "developing"
    elif composite >= 20:
        level = "learning"
    else:
        level = "novice"

    # Has posting template?
    has_template = bool(posting)
    template_confidence = (posting or {}).get("posting_template", {}).get("confidence", "none") if posting else "none"

    result = {
        "vendor_no": vendor_no,
        "vendor_name": intel.get("vendor_name", ""),
        "maturity_level": level,
        "composite_score": composite,
        "dimensions": dimensions,
        "total_documents": total,
        "has_posting_template": has_template,
        "template_confidence": template_confidence,
        "computed_at": _now(),
    }

    # Store the maturity score
    await db[VENDOR_MATURITY_COL].update_one(
        {"vendor_no": vendor_no},
        {"$set": result},
        upsert=True,
    )

    return result


async def compute_all_vendor_maturity(db) -> Dict:
    """Compute maturity scores for all known vendors."""
    vendors = await db.vendor_realtime_intelligence.find(
        {}, {"_id": 0, "vendor_no": 1}
    ).to_list(1000)

    results = {"computed": 0, "levels": {}, "vendors": []}
    for v in vendors:
        vno = v.get("vendor_no", "")
        if not vno:
            continue
        maturity = await compute_vendor_maturity(db, vno)
        results["computed"] += 1
        level = maturity.get("maturity_level", "unknown")
        results["levels"][level] = results["levels"].get(level, 0) + 1
        results["vendors"].append({
            "vendor_no": vno,
            "vendor_name": maturity.get("vendor_name", ""),
            "level": level,
            "score": maturity.get("composite_score", 0),
            "total_docs": maturity.get("total_documents", 0),
        })

    results["vendors"].sort(key=lambda x: x["score"], reverse=True)
    return results


# =============================================================================
# 5. PREDICTIVE READINESS
# =============================================================================

async def predict_readiness(db, doc: Dict) -> Dict:
    """
    Predict whether a document will need human review BEFORE validation.
    Uses vendor history, doc type patterns, and field quality signals.
    """
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    extracted = doc.get("extracted_fields") or {}
    confidence = doc.get("ai_confidence") or 0.0

    prediction = {
        "will_need_review": False,
        "review_probability": 0.0,
        "risk_factors": [],
        "positive_signals": [],
        "recommendation": "auto_process",
    }

    risk_score = 0.0

    # Factor 1: Vendor history
    if vendor_no:
        intel = await db.vendor_realtime_intelligence.find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )
        if intel:
            auto_rate = intel.get("auto_validation_rate", 0)
            total = intel.get("total_documents", 0)
            correction_rate = intel.get("correction_rate", 0)

            if total >= 5 and auto_rate >= 0.9:
                prediction["positive_signals"].append(
                    f"Vendor {vendor_no} has {auto_rate:.0%} auto rate over {total} docs"
                )
                risk_score -= 0.3
            elif total >= 5 and auto_rate < 0.5:
                prediction["risk_factors"].append(
                    f"Vendor {vendor_no} only {auto_rate:.0%} auto rate"
                )
                risk_score += 0.3

            if correction_rate > 0.2:
                prediction["risk_factors"].append(
                    f"Vendor has high correction rate ({correction_rate:.0%})"
                )
                risk_score += 0.2
        else:
            prediction["risk_factors"].append("Unknown vendor — no learning history")
            risk_score += 0.25
    else:
        prediction["risk_factors"].append("No vendor identified")
        risk_score += 0.3

    # Factor 2: AI confidence
    if confidence >= 0.95:
        prediction["positive_signals"].append(f"High AI confidence ({confidence:.0%})")
        risk_score -= 0.2
    elif confidence >= 0.80:
        risk_score -= 0.1
    elif confidence < 0.60:
        prediction["risk_factors"].append(f"Low AI confidence ({confidence:.0%})")
        risk_score += 0.3

    # Factor 3: Field completeness
    required = ["vendor", "invoice_number"]
    amount_fields = ["amount", "invoice_amount", "total_amount"]
    missing = [f for f in required if not extracted.get(f)]
    has_amount = any(extracted.get(f) for f in amount_fields)

    if missing:
        prediction["risk_factors"].append(f"Missing fields: {', '.join(missing)}")
        risk_score += 0.15 * len(missing)
    if not has_amount and doc_type not in ("Shipment", "BOL", "Packing_Slip"):
        prediction["risk_factors"].append("No amount extracted")
        risk_score += 0.15

    # Factor 4: Doc type history
    if doc_type:
        type_stats = await db.document_outcomes.aggregate([
            {"$match": {"doc_type": doc_type}},
            {"$group": {
                "_id": "$outcome",
                "count": {"$sum": 1},
            }},
        ]).to_list(20)

        if type_stats:
            total_typed = sum(s["count"] for s in type_stats)
            auto_typed = sum(s["count"] for s in type_stats
                             if s["_id"] in ("auto_validated", "auto_filed", "approved", "posted_to_bc", "linked"))
            if total_typed >= 5:
                type_auto_rate = auto_typed / total_typed
                if type_auto_rate >= 0.9:
                    prediction["positive_signals"].append(
                        f"Doc type '{doc_type}' has {type_auto_rate:.0%} success rate"
                    )
                    risk_score -= 0.15
                elif type_auto_rate < 0.5:
                    prediction["risk_factors"].append(
                        f"Doc type '{doc_type}' only {type_auto_rate:.0%} success rate"
                    )
                    risk_score += 0.15

    # Factor 5: Extraction pattern match
    if vendor_no:
        patterns = await db[EXTRACTION_PATTERNS_COL].find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )
        if patterns:
            expected = [f for f, r in (patterns.get("field_reliability") or {}).items() if r >= 0.7]
            if expected:
                found = [f for f in expected if extracted.get(f)]
                coverage = len(found) / len(expected)
                if coverage >= 0.9:
                    prediction["positive_signals"].append(
                        f"All expected fields present ({len(found)}/{len(expected)})"
                    )
                    risk_score -= 0.15
                elif coverage < 0.5:
                    prediction["risk_factors"].append(
                        f"Missing expected fields ({len(found)}/{len(expected)})"
                    )
                    risk_score += 0.15

    # Compute final probability
    review_probability = max(0.0, min(1.0, 0.5 + risk_score))

    prediction["review_probability"] = round(review_probability, 4)
    prediction["will_need_review"] = review_probability > 0.5
    prediction["recommendation"] = (
        "route_to_review" if review_probability > 0.7
        else "monitor" if review_probability > 0.4
        else "auto_process"
    )

    return prediction


async def predict_and_store(db, doc_id: str) -> Dict:
    """Predict readiness and store the prediction."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "doc_not_found"}

    prediction = await predict_readiness(db, doc)
    prediction["doc_id"] = doc_id
    prediction["predicted_at"] = _now()

    await db[READINESS_PREDICTIONS_COL].update_one(
        {"doc_id": doc_id},
        {"$set": prediction},
        upsert=True,
    )

    return prediction


# =============================================================================
# MASTER HOOK — Called from per_document_learning_service
# =============================================================================

async def run_deep_learning(db, doc_id: str, trigger: str = "ingestion"):
    """
    Run all deep learning engines on a document.
    Called alongside the per-document learning service.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"learned": False}

    outcome = trigger
    results = {}

    # 1. Extraction patterns (always)
    try:
        await learn_extraction_patterns(db, doc)
        results["extraction_patterns"] = "ok"
    except Exception as e:
        results["extraction_patterns"] = f"error: {e}"

    # 2. Document fingerprint (always)
    try:
        await store_document_fingerprint(db, doc, outcome)
        results["fingerprint"] = "ok"
    except Exception as e:
        results["fingerprint"] = f"error: {e}"

    # 3. Predictive readiness (on ingestion/classification only)
    if trigger in ("ingestion", "classification", "pipeline"):
        try:
            pred = await predict_readiness(db, doc)
            results["prediction"] = pred.get("recommendation", "unknown")
        except Exception as e:
            results["prediction"] = f"error: {e}"

    return results


# =============================================================================
# QUERY APIs
# =============================================================================

async def get_deep_learning_summary(db) -> Dict:
    """Summary of all deep learning engines."""
    # Extraction patterns
    pattern_count = await db[EXTRACTION_PATTERNS_COL].count_documents({})
    top_patterns = await db[EXTRACTION_PATTERNS_COL].find(
        {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1, "total_documents": 1,
             "field_reliability": 1, "updated_at": 1}
    ).sort("total_documents", -1).limit(10).to_list(10)

    # Document fingerprints
    fp_count = await db[DOC_FINGERPRINTS_COL].count_documents({})

    # Self-correction audits
    latest_audit = await db[SELF_CORRECTION_COL].find_one(
        {}, {"_id": 0}, sort=[("run_at", -1)]
    )

    # Vendor maturity
    maturity_levels = {}
    maturity_pipeline = [
        {"$group": {"_id": "$maturity_level", "count": {"$sum": 1}}},
    ]
    for r in await db[VENDOR_MATURITY_COL].aggregate(maturity_pipeline).to_list(10):
        maturity_levels[r["_id"]] = r["count"]

    top_mature = await db[VENDOR_MATURITY_COL].find(
        {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1, "maturity_level": 1,
             "composite_score": 1, "total_documents": 1}
    ).sort("composite_score", -1).limit(10).to_list(10)

    # Predictions
    prediction_count = await db[READINESS_PREDICTIONS_COL].count_documents({})
    pred_pipeline = [
        {"$group": {"_id": "$recommendation", "count": {"$sum": 1}}},
    ]
    pred_breakdown = {r["_id"]: r["count"]
                      for r in await db[READINESS_PREDICTIONS_COL].aggregate(pred_pipeline).to_list(10)}

    return {
        "extraction_patterns": {
            "vendors_tracked": pattern_count,
            "top_vendors": [{
                "vendor_no": p.get("vendor_no", ""),
                "vendor_name": p.get("vendor_name", ""),
                "documents": p.get("total_documents", 0),
                "reliable_fields": sum(1 for v in (p.get("field_reliability") or {}).values() if v >= 0.7),
                "total_fields": len(p.get("field_reliability") or {}),
            } for p in top_patterns],
        },
        "document_similarity": {
            "fingerprints_stored": fp_count,
        },
        "self_correction": {
            "latest_audit": {
                "audited": (latest_audit or {}).get("audited", 0),
                "drifts": (latest_audit or {}).get("drift_count", 0),
                "drift_rate": (latest_audit or {}).get("drift_rate", 0),
                "run_at": (latest_audit or {}).get("run_at", "never"),
            } if latest_audit else None,
        },
        "vendor_maturity": {
            "levels": maturity_levels,
            "top_vendors": [{
                "vendor_no": m.get("vendor_no", ""),
                "vendor_name": m.get("vendor_name", ""),
                "level": m.get("maturity_level", "unknown"),
                "score": m.get("composite_score", 0),
                "total_docs": m.get("total_documents", 0),
            } for m in top_mature],
        },
        "predictive_readiness": {
            "predictions_made": prediction_count,
            "breakdown": pred_breakdown,
        },
        "generated_at": _now(),
    }
