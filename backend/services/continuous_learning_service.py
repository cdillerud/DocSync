"""
Continuous Learning Service — Makes the AI smarter with every interaction.

Four learning engines:
A. Auto-learn from BC-posted invoices (Draft→Posted detection)
B. Cross-vendor pattern learning (propagate corrections to similar vendors)
C. Confidence auto-promotion (low→medium→high based on approval ratio)
D. Extraction learning from field corrections (vendor-specific extraction profiles)
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# A. Auto-learn from BC-posted invoices
# =============================================================================

async def detect_posted_drafts(db, limit: int = 100) -> Dict:
    """
    Find auto-drafted PIs that have been posted in BC (Draft → Open/Posted).
    Compare the final posted version with the original draft.
    Every difference becomes a correction that adjusts the template.
    """
    from services.draft_feedback_service import sync_draft_from_bc

    # Find drafts that haven't been fully synced yet
    docs = await db.hub_documents.find(
        {
            "auto_draft_created": True,
            "draft_review_status": {"$nin": ["feedback_synced"]},
            "bc_purchase_invoice.bc_system_id": {"$exists": True, "$ne": ""},
        },
        {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1,
         "auto_draft_bc_record_no": 1, "draft_bc_sync.bc_status": 1}
    ).limit(limit).to_list(limit)

    results = {"checked": 0, "posted_found": 0, "changes_learned": 0, "errors": 0}

    for doc in docs:
        doc_id = doc.get("id", "")
        if not doc_id:
            continue
        results["checked"] += 1

        try:
            sync_result = await sync_draft_from_bc(doc_id, db)
            if not sync_result.get("success"):
                continue

            bc_status = sync_result.get("bc_status", "")

            # If the draft has been posted (Open or Posted), mark as fully learned
            if bc_status.lower() in ("open", "posted"):
                results["posted_found"] += 1
                if sync_result.get("changes_detected"):
                    results["changes_learned"] += sync_result.get("corrections", 0) if isinstance(sync_result.get("corrections"), int) else len(sync_result.get("corrections", []))

                # Mark as fully synced so we don't re-process
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "draft_review_status": "feedback_synced",
                        "draft_posted_in_bc": True,
                        "draft_posted_detected_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )

                # Record the positive completion event
                vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
                await db.posting_learning_events.insert_one({
                    "vendor_no": vendor_no,
                    "doc_id": doc_id,
                    "event_type": "draft_posted_in_bc",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "feedback": "positive_completion",
                    "bc_status": bc_status,
                    "had_corrections": sync_result.get("changes_detected", False),
                })

        except Exception as e:
            results["errors"] += 1
            logger.warning("[ContinuousLearning] Error checking posted draft %s: %s", doc_id[:8], e)

    logger.info(
        "[ContinuousLearning] Posted draft detection: checked=%d, posted=%d, changes_learned=%d",
        results["checked"], results["posted_found"], results["changes_learned"]
    )
    return results


# =============================================================================
# B. Cross-vendor pattern learning
# =============================================================================

async def propagate_cross_vendor_learning(db, limit: int = 20) -> Dict:
    """
    When a vendor's template gets corrected, find vendors with similar profiles
    and apply compatible corrections with reduced weight.

    Similarity is based on: same variability profile type, similar line counts,
    similar item distributions.
    """
    # Find recent corrections that haven't been propagated yet
    recent_corrections = await db.posting_learning_events.find(
        {
            "event_type": {"$in": ["draft_corrected", "draft_bc_feedback"]},
            "cross_vendor_propagated": {"$ne": True},
        },
        {"_id": 0}
    ).sort("posted_at", -1).limit(limit).to_list(limit)

    results = {"corrections_checked": 0, "propagated_to_vendors": 0, "propagations_applied": 0}

    for correction in recent_corrections:
        source_vendor = correction.get("vendor_no", "")
        if not source_vendor:
            continue
        results["corrections_checked"] += 1

        # Get the source vendor's profile
        source_profile = await db.posting_pattern_analysis.find_one(
            {"vendor_no": source_vendor, "status": "analyzed"},
            {"_id": 0, "variability_profile": 1, "posting_template": 1,
             "line_patterns": 1, "vendor_no": 1}
        )
        if not source_profile:
            continue

        source_var = source_profile.get("variability_profile", {})
        source_type = source_var.get("type", "")
        source_line_count = source_profile.get("posting_template", {}).get("typical_line_count", 0)

        # Find similar vendors (same variability type, similar line count)
        similar_query = {
            "vendor_no": {"$ne": source_vendor},
            "status": "analyzed",
            "variability_profile.type": source_type,
        }
        if source_line_count > 0:
            similar_query["posting_template.typical_line_count"] = {
                "$gte": max(1, source_line_count - 2),
                "$lte": source_line_count + 2,
            }

        similar_vendors = await db.posting_pattern_analysis.find(
            similar_query,
            {"_id": 0, "vendor_no": 1}
        ).limit(10).to_list(10)

        corrections_list = correction.get("corrections", [])
        if not corrections_list:
            continue

        for sim in similar_vendors:
            sim_vendor = sim.get("vendor_no", "")
            if not sim_vendor:
                continue

            # Apply corrections with reduced weight (1 instead of 3)
            inc_ops = {}
            for c in corrections_list:
                ctype = c.get("type", "")
                if ctype == "item_change":
                    corrected = c.get("corrected", "")
                    if corrected:
                        inc_ops[f"line_patterns.top_items.{corrected}"] = 1
                elif ctype == "tax_change":
                    corrected = c.get("corrected", "")
                    if corrected:
                        inc_ops[f"line_patterns.tax_code_distribution.{corrected}"] = 1

            if inc_ops:
                inc_ops["cross_vendor_learning_count"] = 1
                await db.posting_pattern_analysis.update_one(
                    {"vendor_no": sim_vendor, "status": "analyzed"},
                    {
                        "$inc": inc_ops,
                        "$set": {"last_cross_vendor_learn_at": datetime.now(timezone.utc).isoformat()},
                    }
                )
                results["propagated_to_vendors"] += 1
                results["propagations_applied"] += len(inc_ops) - 1  # minus the count increment

        # Mark as propagated
        await db.posting_learning_events.update_one(
            {"vendor_no": source_vendor, "doc_id": correction.get("doc_id"), "event_type": correction.get("event_type")},
            {"$set": {"cross_vendor_propagated": True}}
        )

    logger.info(
        "[ContinuousLearning] Cross-vendor: checked=%d, propagated_to=%d, adjustments=%d",
        results["corrections_checked"], results["propagated_to_vendors"], results["propagations_applied"]
    )
    return results


# =============================================================================
# C. Confidence auto-promotion
# =============================================================================

async def auto_promote_confidence(db) -> Dict:
    """
    Automatically promote vendor template confidence based on approval ratio.

    Rules:
    - low → medium: 5+ approved drafts with <20% correction rate
    - medium → high: 15+ approved drafts with <10% correction rate
    - Demotion: >40% correction rate drops confidence one level
    """
    results = {"promoted": [], "demoted": [], "unchanged": 0}

    # Get all analyzed vendors
    vendors = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "posting_template.confidence": 1}
    ).to_list(1000)

    for v in vendors:
        vendor_no = v.get("vendor_no", "")
        if not vendor_no:
            continue

        current_confidence = v.get("posting_template", {}).get("confidence", "low")

        # Count approvals and corrections for this vendor
        total_approved = await db.posting_learning_events.count_documents({
            "vendor_no": vendor_no,
            "event_type": "draft_approved",
        })
        total_corrected = await db.posting_learning_events.count_documents({
            "vendor_no": vendor_no,
            "event_type": {"$in": ["draft_corrected", "draft_bc_feedback"]},
        })
        total_posted = await db.posting_learning_events.count_documents({
            "vendor_no": vendor_no,
            "event_type": "draft_posted_in_bc",
            "had_corrections": False,
        })

        # Total positive = approved + posted without corrections
        total_positive = total_approved + total_posted
        total_reviews = total_positive + total_corrected

        if total_reviews == 0:
            results["unchanged"] += 1
            continue

        correction_rate = total_corrected / total_reviews
        new_confidence = current_confidence

        # Promotion logic
        if current_confidence == "low" and total_positive >= 5 and correction_rate < 0.20:
            new_confidence = "medium"
        elif current_confidence == "medium" and total_positive >= 15 and correction_rate < 0.10:
            new_confidence = "high"

        # Demotion logic
        if total_reviews >= 5 and correction_rate > 0.40:
            if current_confidence == "high":
                new_confidence = "medium"
            elif current_confidence == "medium":
                new_confidence = "low"

        if new_confidence != current_confidence:
            await db.posting_pattern_analysis.update_one(
                {"vendor_no": vendor_no, "status": "analyzed"},
                {"$set": {
                    "posting_template.confidence": new_confidence,
                    "confidence_auto_promoted_at": datetime.now(timezone.utc).isoformat(),
                    "confidence_promotion_reason": {
                        "from": current_confidence,
                        "to": new_confidence,
                        "total_positive": total_positive,
                        "total_corrected": total_corrected,
                        "correction_rate": round(correction_rate, 3),
                    },
                }}
            )

            # Record learning event
            await db.posting_learning_events.insert_one({
                "vendor_no": vendor_no,
                "event_type": "confidence_auto_promotion",
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "feedback": "promotion" if new_confidence > current_confidence else "demotion",
                "from_confidence": current_confidence,
                "to_confidence": new_confidence,
                "total_positive": total_positive,
                "total_corrected": total_corrected,
                "correction_rate": round(correction_rate, 3),
            })

            if new_confidence > current_confidence:
                results["promoted"].append({"vendor": vendor_no, "from": current_confidence, "to": new_confidence})
            else:
                results["demoted"].append({"vendor": vendor_no, "from": current_confidence, "to": new_confidence})

            logger.info(
                "[ContinuousLearning] Confidence %s: %s %s→%s (positive=%d, corrected=%d, rate=%.1f%%)",
                "promoted" if new_confidence > current_confidence else "demoted",
                vendor_no, current_confidence, new_confidence,
                total_positive, total_corrected, correction_rate * 100,
            )
        else:
            results["unchanged"] += 1

    logger.info(
        "[ContinuousLearning] Confidence check: %d promoted, %d demoted, %d unchanged",
        len(results["promoted"]), len(results["demoted"]), results["unchanged"]
    )
    return results


# =============================================================================
# D. Extraction learning from field corrections
# =============================================================================

async def learn_from_field_correction(
    db, doc_id: str, vendor_no: str, field_name: str,
    original_value: str, corrected_value: str
):
    """
    Called when a user manually corrects an extracted field on a document.
    Records the correction and builds a vendor-specific extraction profile.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Record the correction event
    await db.posting_learning_events.insert_one({
        "vendor_no": vendor_no,
        "doc_id": doc_id,
        "event_type": "extraction_field_correction",
        "posted_at": now,
        "feedback": "corrective",
        "field": field_name,
        "original": original_value,
        "corrected": corrected_value,
    })

    await db.classification_corrections.insert_one({
        "doc_id": doc_id,
        "vendor_id": vendor_no,
        "correction_type": f"extraction_{field_name}",
        "original_type": original_value,
        "corrected_type": corrected_value,
        "source": "manual_field_correction",
        "confirmed_at": now,
        "applied": True,
    })

    # Update vendor extraction profile
    # This tracks which fields tend to be wrong for each vendor
    await db.vendor_extraction_profiles.update_one(
        {"vendor_no": vendor_no},
        {
            "$inc": {
                f"field_corrections.{field_name}.total": 1,
                "total_corrections": 1,
            },
            "$set": {
                f"field_corrections.{field_name}.last_corrected_at": now,
                "last_correction_at": now,
            },
            "$push": {
                f"field_corrections.{field_name}.recent_corrections": {
                    "$each": [{"original": original_value, "corrected": corrected_value, "at": now}],
                    "$slice": -10,  # keep last 10
                }
            },
        },
        upsert=True,
    )

    logger.info(
        "[ContinuousLearning] Extraction correction: vendor=%s field=%s '%s'→'%s'",
        vendor_no, field_name, original_value[:30], corrected_value[:30],
    )


async def get_vendor_extraction_profile(db, vendor_no: str) -> Optional[Dict]:
    """Get the extraction profile for a vendor — shows which fields tend to be wrong."""
    profile = await db.vendor_extraction_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    return profile


# =============================================================================
# Master orchestrator — runs all learning engines
# =============================================================================

async def run_all_learning_engines(db) -> Dict:
    """
    Run all continuous learning engines. Called by the background scheduler.
    Returns combined results from all engines.
    """
    results = {
        "posted_draft_detection": {},
        "cross_vendor_learning": {},
        "confidence_auto_promotion": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    try:
        results["posted_draft_detection"] = await detect_posted_drafts(db)
    except Exception as e:
        results["posted_draft_detection"] = {"error": str(e)}
        logger.warning("[ContinuousLearning] Posted draft detection failed: %s", e)

    try:
        results["cross_vendor_learning"] = await propagate_cross_vendor_learning(db)
    except Exception as e:
        results["cross_vendor_learning"] = {"error": str(e)}
        logger.warning("[ContinuousLearning] Cross-vendor learning failed: %s", e)

    try:
        results["confidence_auto_promotion"] = await auto_promote_confidence(db)
    except Exception as e:
        results["confidence_auto_promotion"] = {"error": str(e)}
        logger.warning("[ContinuousLearning] Confidence promotion failed: %s", e)

    try:
        from services.sales_order_learning_service import detect_posted_sales_drafts
        results["posted_so_detection"] = await detect_posted_sales_drafts(db)
    except Exception as e:
        results["posted_so_detection"] = {"error": str(e)}
        logger.warning("[ContinuousLearning] SO draft detection failed: %s", e)

    logger.info("[ContinuousLearning] All engines complete: %s", {
        k: "ok" if "error" not in v else "error" for k, v in results.items() if isinstance(v, dict)
    })
    return results
