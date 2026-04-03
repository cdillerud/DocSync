"""
GPI Document Hub — Posting Pattern Analysis API

Phase 1: Analyze BC posting patterns and build vendor posting profiles.
Phase 2: Template-driven draft PI creation, auto-post settings, ready document queue.
"""
import asyncio
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Query, BackgroundTasks, Body
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posting-patterns", tags=["posting-patterns"])

# Track background analysis status
_analysis_status = {"running": False, "last_result": None, "progress": "idle"}


def get_db():
    from server import db
    return db


def get_bc_service():
    from services.business_central_service import get_bc_service as _get
    return _get()


@router.get("/status")
async def get_posting_pattern_status():
    """Get overall posting pattern analysis status with totals."""
    db = get_db()

    total_profiles = await db.posting_pattern_analysis.count_documents({"status": "analyzed"})
    high_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "high"
    })
    medium_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "medium"
    })
    low_conf = await db.posting_pattern_analysis.count_documents({
        "status": "analyzed",
        "posting_template.confidence": "low"
    })

    # Aggregate totals across all vendors
    totals_pipeline = [
        {"$match": {"status": "analyzed"}},
        {"$group": {
            "_id": None,
            "total_invoices": {"$sum": "$invoices_analyzed"},
            "total_lines": {"$sum": "$lines_analyzed"},
            "total_learning_events": {"$sum": {"$ifNull": ["$continuous_learning_count", 0]}},
            "total_historical": {"$sum": {"$ifNull": ["$data_sources.historical_posted", 0]}},
            "total_current": {"$sum": {"$ifNull": ["$data_sources.purchase_invoices", 0]}},
        }},
    ]
    totals = {"total_invoices": 0, "total_lines": 0, "total_learning_events": 0,
              "total_historical": 0, "total_current": 0}
    async for row in db.posting_pattern_analysis.aggregate(totals_pipeline):
        totals = {
            "total_invoices": row.get("total_invoices", 0),
            "total_lines": row.get("total_lines", 0),
            "total_learning_events": row.get("total_learning_events", 0),
            "total_historical": row.get("total_historical", 0),
            "total_current": row.get("total_current", 0),
        }

    # Get top 10 vendors by invoice count
    top_vendors = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "vendor_names_seen": 1,
         "invoices_analyzed": 1, "lines_analyzed": 1,
         "posting_template.confidence": 1, "posting_template.consistency_score": 1,
         "amount_stats.mean": 1, "continuous_learning_count": 1, "last_learned_at": 1}
    ).sort("invoices_analyzed", -1).limit(10).to_list(10)

    return {
        "total_profiles": total_profiles,
        "totals": totals,
        "confidence_distribution": {
            "high": high_conf,
            "medium": medium_conf,
            "low": low_conf,
        },
        "top_vendors": [
            {
                "vendor_no": v.get("vendor_no"),
                "vendor_name": (v.get("vendor_names_seen") or ["?"])[0] if v.get("vendor_names_seen") else "?",
                "invoices_analyzed": v.get("invoices_analyzed", 0),
                "lines_analyzed": v.get("lines_analyzed", 0),
                "confidence": v.get("posting_template", {}).get("confidence", "?"),
                "consistency": v.get("posting_template", {}).get("consistency_score", 0),
                "avg_amount": v.get("amount_stats", {}).get("mean", 0),
                "continuous_learns": v.get("continuous_learning_count", 0),
                "last_learned": v.get("last_learned_at", ""),
            }
            for v in top_vendors
        ],
    }


@router.get("/vendor/{vendor_no}")
async def get_vendor_posting_profile(vendor_no: str):
    """Get the full posting profile for a specific vendor."""
    db = get_db()
    from services.posting_pattern_analyzer import get_posting_profile_for_vendor

    profile = await get_posting_profile_for_vendor(db, vendor_no)
    if not profile:
        return {"vendor_no": vendor_no, "status": "not_analyzed",
                "message": "No posting profile found. Run POST /analyze/{vendor_no} first."}
    return profile


@router.post("/analyze/{vendor_no}")
async def analyze_single_vendor(vendor_no: str, limit: int = Query(default=0, le=10000, description="0 = fetch ALL invoices (no cap)")):
    """Analyze posting patterns for a single vendor from BC production data. Default: all invoices."""
    db = get_db()
    bc = get_bc_service()

    from services.posting_pattern_analyzer import analyze_vendor_posting_patterns
    result = await analyze_vendor_posting_patterns(db, bc, vendor_no, limit=limit)
    return result


@router.get("/debug-lines/{vendor_no}")
async def debug_invoice_lines(vendor_no: str):
    """
    Debug endpoint: Get one invoice for a vendor and try to fetch its lines.
    Shows exactly what BC returns so we can fix field mapping.
    """
    db = get_db()
    bc = get_bc_service()

    # Get one invoice
    pi_result = await bc.get_posted_purchase_invoices(vendor_id=vendor_no, limit=1)
    invoices = pi_result.get("invoices", [])

    if not invoices:
        return {"error": "No invoices found", "raw_response": pi_result}

    inv = invoices[0]
    inv_id = inv.get("id", "")

    # Show the invoice fields we got
    result = {
        "invoice_sample": inv,
        "invoice_id": inv_id,
        "line_attempts": {},
    }

    # Try to get lines
    lines = await bc.get_purchase_invoice_lines(inv_id)
    result["lines_found"] = len(lines)
    if lines:
        # Show first line with all its fields
        result["line_sample"] = lines[0]
        result["line_fields"] = list(lines[0].keys())
    else:
        result["line_sample"] = None
        result["line_fields"] = []

    return result


async def _run_top_analysis(top_n: int, force: bool = False):
    """
    Background task: discover ALL vendors from BC posted invoices and analyze each.
    No longer limited to Hub-only vendors — goes straight to BC for the complete picture.
    """
    global _analysis_status
    _analysis_status = {"running": True, "last_result": None, "progress": "discovering vendors from BC..."}
    try:
        db = get_db()
        bc = get_bc_service()
        from services.posting_pattern_analyzer import analyze_vendor_posting_patterns

        # Step 1: Discover ALL unique vendors from BC purchase invoices (ALL statuses)
        # AND from historical posted purchase invoices
        _analysis_status["progress"] = "Discovering vendors from ALL BC invoice sources..."
        discovered_vendors = {}
        skip = 0
        page_size = 500

        # Source 1: purchaseInvoices (all statuses — no filter)
        while True:
            pi_result = await bc.get_posted_purchase_invoices(limit=page_size, skip=skip)
            page = pi_result.get("invoices", [])
            if not page:
                break
            for inv in page:
                vno = inv.get("vendorNumber", "")
                if vno and vno not in discovered_vendors:
                    discovered_vendors[vno] = {
                        "vendor_no": vno,
                        "vendor_name": inv.get("vendorName", ""),
                    }
            logger.info("[PostingPatterns] Discovery (purchaseInvoices): scanned %d invoices, found %d unique vendors so far",
                         skip + len(page), len(discovered_vendors))
            if len(page) < page_size:
                break
            skip += len(page)
            # Safety: if top_n is set and we've found enough vendors, stop discovering
            if top_n > 0 and len(discovered_vendors) >= top_n * 2:
                break

        # Source 2: historical postedPurchaseInvoices
        skip = 0
        while True:
            hist_result = await bc.get_historical_posted_purchase_invoices(limit=page_size, skip=skip)
            page = hist_result.get("invoices", [])
            source = hist_result.get("source", "none_available")
            if not page or source == "none_available":
                break
            for inv in page:
                vno = inv.get("vendorNumber", "")
                if vno and vno not in discovered_vendors:
                    discovered_vendors[vno] = {
                        "vendor_no": vno,
                        "vendor_name": inv.get("vendorName", ""),
                    }
            logger.info("[PostingPatterns] Discovery (historical %s): scanned %d invoices, found %d unique vendors total",
                         source, skip + len(page), len(discovered_vendors))
            if len(page) < page_size:
                break
            skip += len(page)
            if top_n > 0 and len(discovered_vendors) >= top_n * 2:
                break

        # Also include vendors from Hub profiles that might not have BC invoices yet
        hub_vendors = await db.vendor_invoice_profiles.find(
            {"bc_invoice_count": {"$gte": 1}},
            {"_id": 0, "vendor_no": 1, "vendor_name": 1}
        ).to_list(500)
        for v in hub_vendors:
            vno = v.get("vendor_no", "")
            if vno and vno not in discovered_vendors:
                discovered_vendors[vno] = v

        # Sort by name and limit to top_n
        all_vendors = sorted(discovered_vendors.values(), key=lambda x: x.get("vendor_name", ""))
        if top_n > 0:
            all_vendors = all_vendors[:top_n]

        _analysis_status["progress"] = f"Found {len(all_vendors)} vendors. Starting analysis..."
        logger.info("[PostingPatterns] Discovered %d total vendors (%d from BC, %d from Hub). Analyzing %d.",
                     len(discovered_vendors), len(discovered_vendors) - len(hub_vendors), len(hub_vendors), len(all_vendors))

        results = {
            "vendors_discovered": len(discovered_vendors),
            "vendors_queued": len(all_vendors),
            "analyzed": 0, "errors": 0, "skipped": 0,
            "vendor_details": [], "error_details": [], "force": force,
        }

        for i, v in enumerate(all_vendors):
            vendor_no = v.get("vendor_no", "")
            if not vendor_no:
                continue
            _analysis_status["progress"] = f"Analyzing {vendor_no} ({i+1}/{len(all_vendors)})"

            # Check if recent analysis exists (skip if < 7 days old, unless force=True)
            if not force:
                from datetime import datetime, timezone
                existing = await db.posting_pattern_analysis.find_one(
                    {"vendor_no": vendor_no, "status": "analyzed"},
                    {"_id": 0, "analyzed_at": 1}
                )
                if existing and existing.get("analyzed_at"):
                    try:
                        dt = datetime.fromisoformat(existing["analyzed_at"].replace("Z", "+00:00"))
                        if (datetime.now(timezone.utc) - dt).days < 7:
                            results["skipped"] += 1
                            continue
                    except (ValueError, TypeError):
                        pass

            try:
                analysis = await analyze_vendor_posting_patterns(db, bc, vendor_no)
                if analysis.get("status") == "analyzed":
                    results["analyzed"] += 1
                    results["vendor_details"].append({
                        "vendor_no": vendor_no,
                        "vendor_name": v.get("vendor_name", ""),
                        "invoices": analysis.get("invoices_analyzed", 0),
                        "lines": analysis.get("lines_analyzed", 0),
                        "confidence": analysis.get("posting_template", {}).get("confidence", "?"),
                        "consistency": analysis.get("consistency", {}).get("overall", 0),
                    })
                else:
                    results["errors"] += 1
                    results["error_details"].append({
                        "vendor_no": vendor_no,
                        "vendor_name": v.get("vendor_name", ""),
                        "status": analysis.get("status", "unknown"),
                        "error": analysis.get("error", "unknown"),
                    })
                    logger.warning("Vendor %s analysis status: %s, error: %s",
                                   vendor_no, analysis.get("status"), analysis.get("error", ""))
            except Exception as e:
                results["errors"] += 1
                results["error_details"].append({
                    "vendor_no": vendor_no,
                    "vendor_name": v.get("vendor_name", ""),
                    "error": str(e),
                })
                logger.error("Failed to analyze vendor %s: %s", vendor_no, str(e))

            # Brief pause to avoid BC API throttling
            await asyncio.sleep(0.5)

        _analysis_status = {"running": False, "last_result": results, "progress": "complete"}
        logger.info("[PostingPatterns] Background analysis complete: discovered=%d, analyzed=%d, errors=%d, skipped=%d",
                     results["vendors_discovered"], results["analyzed"], results["errors"], results["skipped"])

    except Exception as e:
        _analysis_status = {"running": False, "last_result": {"error": str(e)}, "progress": "failed"}
        logger.error("[PostingPatterns] Background analysis failed: %s", str(e))


@router.post("/analyze-top")
async def analyze_top_vendors(
    background_tasks: BackgroundTasks,
    top_n: int = Query(default=50, le=500, description="Number of top vendors to analyze (0 = all)"),
    force: bool = Query(default=False, description="Force re-analysis even if recent data exists"),
):
    """
    Analyze posting patterns for the top N vendors by invoice volume.
    Runs in background to avoid nginx timeout. Check progress via GET /analyze-top/status.
    Use force=true to re-analyze all vendors (bypasses 7-day freshness check).
    """
    global _analysis_status
    if _analysis_status.get("running"):
        return {
            "status": "already_running",
            "progress": _analysis_status.get("progress", ""),
            "message": "Analysis is already in progress. Check GET /analyze-top/status for progress.",
        }

    background_tasks.add_task(_run_top_analysis, top_n, force)
    return {
        "status": "started",
        "vendors_to_analyze": top_n,
        "force": force,
        "message": f"Background analysis started for top {top_n} vendors{' (FORCE re-analysis)' if force else ''}. Check GET /api/posting-patterns/analyze-top/status for progress.",
    }


@router.get("/analyze-top/status")
async def get_analysis_status():
    """Check the status of a background analyze-top job."""
    return _analysis_status



@router.get("/learning-activity")
async def get_learning_activity(vendor_no: str = Query("", description="Filter by vendor"), limit: int = Query(20, le=100)):
    """
    Show recent continuous learning events — proof that the system
    learns from every single successful BC posting.
    """
    db = get_db()
    query = {}
    if vendor_no:
        query["vendor_no"] = vendor_no

    events = await db.posting_learning_events.find(
        query,
        {"_id": 0, "vendor_no": 1, "doc_id": 1, "posted_at": 1,
         "line_count": 1, "items_used": 1, "item_families": 1,
         "ref_patterns": 1, "amount": 1}
    ).sort("posted_at", -1).limit(limit).to_list(limit)

    # Count total learning events per vendor
    pipeline = [
        {"$group": {"_id": "$vendor_no", "count": {"$sum": 1}, "last": {"$max": "$posted_at"}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    vendor_counts = {}
    async for row in db.posting_learning_events.aggregate(pipeline):
        if row.get("_id"):
            vendor_counts[row["_id"]] = {"events": row["count"], "last_learned": row.get("last", "")}

    return {
        "total_learning_events": await db.posting_learning_events.count_documents({}),
        "recent_events": events,
        "vendors_learning": vendor_counts,
        "description": "Every successful BC posting teaches the system. These events show exactly what was learned.",
    }


@router.get("/learning-proof/{vendor_no}")
async def posting_learning_proof(vendor_no: str):
    """
    Show exactly what the system has learned about how humans post
    invoices for this vendor — and what the auto-post would do.
    """
    db = get_db()

    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    if not profile:
        return {
            "vendor_no": vendor_no,
            "verdict": "NOT LEARNED",
            "message": "No posting analysis exists. Run POST /analyze/{vendor_no} first.",
        }

    template = profile.get("posting_template", {})
    amount = profile.get("amount_stats", {})
    lines = profile.get("line_patterns", {})
    tax = profile.get("tax_pattern", {})
    consistency = profile.get("consistency", {})

    # Build item breakdown with rates
    item_breakdown = {}
    for item, count in lines.get("top_items", {}).items():
        total = sum(lines.get("line_types", {}).values()) or 1
        item_breakdown[item] = f"{round(count / total * 100)}% ({count}/{total} lines)"

    # Describe reference patterns in human terms
    ref_handling = template.get("reference_handling", {})
    ref_patterns_detail = {}
    for pattern, info in (ref_handling.get("all_patterns") or {}).items():
        if isinstance(info, dict):
            ref_patterns_detail[pattern] = f"{info.get('count', 0)} lines ({info.get('rate', 0)*100:.0f}%)"
        else:
            ref_patterns_detail[pattern] = f"{info} lines"

    proof = {
        "vendor_no": vendor_no,
        "vendor_names": profile.get("vendor_names_seen", []),
        "invoices_studied": profile.get("invoices_analyzed", 0),
        "invoices_with_lines_studied": profile.get("invoices_with_lines_analyzed", 0),
        "lines_studied": profile.get("lines_analyzed", 0),
        "data_sources": profile.get("data_sources", {}),
        "status_distribution": profile.get("status_distribution", {}),
        "what_the_system_learned": {
            "typical_invoice_amount": f"${amount.get('mean', 0):,.2f} (range ${amount.get('min', 0):,.2f}-${amount.get('max', 0):,.2f})",
            "typical_line_count": lines.get("lines_per_invoice", {}).get("median", "?"),
            "primary_items": item_breakdown,
            "primary_gl_accounts": list(lines.get("top_gl_accounts", {}).keys())[:5],
            "charge_items": list(lines.get("charge_items", {}).keys())[:5],
            "description_format": ref_handling.get("description", "unknown"),
            "description_pattern_breakdown": ref_patterns_detail,
            "common_descriptions_sample": list(lines.get("top_descriptions", {}).keys())[:5],
            "units_of_measure": list(lines.get("uom_distribution", {}).keys())[:5],
            "line_tax_codes": list(lines.get("tax_code_distribution", {}).keys())[:5],
            "invoice_level_tax": f"{tax.get('tax_rate_typical', 0)}% tax" if tax.get("invoices_with_tax", 0) > 0 else "Tax-free at invoice level",
            "line_tax_code_detail": template.get("line_tax_code", {}),
            "line_amount_stats": lines.get("line_amount_stats", {}),
            "currency": profile.get("currency_distribution", {}),
            "vendor_invoice_number_usage": f"{profile.get('vendor_invoice_number_rate', 0)*100:.0f}%",
        },
        "consistency": {
            "overall_score": f"{consistency.get('overall', 0)*100:.0f}%",
            "dimensions": {
                "line_count": f"{consistency.get('line_count', 0)*100:.0f}% — same # of lines every time",
                "item_family": f"{consistency.get('item_family', 0)*100:.0f}% — always same item FAMILY (e.g., all FREIGHT variants)",
                "item_dominance": f"{consistency.get('item_dominance', 0)*100:.0f}% — one clear primary item within family",
                "line_type": f"{consistency.get('line_type', 0)*100:.0f}% — always same line type (Item/Account/Charge)",
                "ref_pattern_uniformity": f"{consistency.get('ref_pattern_uniformity', 0)*100:.0f}% — same description format every time",
                "ref_coverage": f"{consistency.get('ref_coverage', 0)*100:.0f}% — lines with structured reference #",
                "tax_uniformity": f"{consistency.get('tax_uniformity', 0)*100:.0f}% — always same tax code",
                "uom_uniformity": f"{consistency.get('uom_uniformity', 0)*100:.0f}% — always same unit of measure",
            },
            "item_families_detected": consistency.get("item_families_seen", {}),
            "informational": {
                "exact_item_choice": f"{consistency.get('exact_item_choice', 0)*100:.0f}% — exact same item every time (variants are expected)",
                "amount_tightness": f"{consistency.get('amount_tightness', 0)*100:.0f}% — dollar range tightness (not weighted)",
            },
            "interpretation": (
                "HIGHLY PREDICTABLE — safe for auto-posting"
                if consistency.get("overall", 0) >= 0.8 else
                "MOSTLY PREDICTABLE — good candidate with review"
                if consistency.get("overall", 0) >= 0.6 else
                "VARIABLE — needs human review for each invoice"
                if consistency.get("overall", 0) >= 0.4 else
                "UNPREDICTABLE — not suitable for automation"
            ),
        },
        "auto_post_template": {
            "confidence": template.get("confidence", "?"),
            "consistency_score": template.get("consistency_score", 0),
            "would_create": {
                "currency": template.get("recommended_currency", "USD"),
                "line_count": template.get("typical_line_count", 1),
                "uom": template.get("uom", ""),
                "tax_handling": template.get("tax_handling", "?"),
                "line_tax_code": template.get("line_tax_code", {}),
                "line_templates": template.get("line_templates", []),
                "reference_handling": template.get("reference_handling", {}),
                "description2_usage": template.get("description2_usage", {}),
            },
        },
        "variability_profile": template.get("variability_profile", {}),
        "item_families": consistency.get("item_families_seen", {}),
        "verdict": (
            f"LEARNED ({template.get('confidence', '?').upper()} confidence, "
            f"{consistency.get('overall', 0)*100:.0f}% consistent)"
            if profile.get("invoices_analyzed", 0) >= 3 else "INSUFFICIENT DATA"
        ),
    }

    return proof


# =============================================================================
# Phase 2: Auto-Post Settings, Draft Preview, Ready Queue
# =============================================================================

@router.get("/settings")
async def get_auto_post_settings():
    """Get current auto-post configuration settings."""
    db = get_db()
    settings = await db.auto_post_settings.find_one({"_id": "global"}) or {}
    return {
        "auto_post_enabled": settings.get("auto_post_enabled", False),
        "min_confidence": settings.get("min_confidence", "high"),
        "min_invoices_analyzed": settings.get("min_invoices_analyzed", 10),
        "require_po_match": settings.get("require_po_match", True),
        "allowed_vendors": settings.get("allowed_vendors", []),
        "blocked_vendors": settings.get("blocked_vendors", []),
        "updated_at": settings.get("updated_at", ""),
        "updated_by": settings.get("updated_by", ""),
    }


@router.put("/settings")
async def update_auto_post_settings(
    auto_post_enabled: Optional[bool] = Body(None),
    min_confidence: Optional[str] = Body(None),
    min_invoices_analyzed: Optional[int] = Body(None),
    require_po_match: Optional[bool] = Body(None),
    allowed_vendors: Optional[list] = Body(None),
    blocked_vendors: Optional[list] = Body(None),
):
    """Update auto-post configuration settings."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    update_fields = {"updated_at": now, "updated_by": "admin"}
    if auto_post_enabled is not None:
        update_fields["auto_post_enabled"] = auto_post_enabled
    if min_confidence is not None and min_confidence in ("high", "medium", "low"):
        update_fields["min_confidence"] = min_confidence
    if min_invoices_analyzed is not None:
        update_fields["min_invoices_analyzed"] = max(1, min_invoices_analyzed)
    if require_po_match is not None:
        update_fields["require_po_match"] = require_po_match
    if allowed_vendors is not None:
        update_fields["allowed_vendors"] = allowed_vendors
    if blocked_vendors is not None:
        update_fields["blocked_vendors"] = blocked_vendors

    await db.auto_post_settings.update_one(
        {"_id": "global"},
        {"$set": update_fields},
        upsert=True,
    )

    return {"status": "updated", **update_fields}


@router.get("/ready-queue")
async def get_ready_queue(
    limit: int = Query(50, le=200),
    vendor_no: str = Query("", description="Filter by vendor"),
    confidence: str = Query("", description="Filter by template confidence: high, medium, low"),
):
    """
    List documents that are ReadyForPost with their posting template info.
    This is the queue of invoices ready for auto-posting or manual draft creation.
    """
    db = get_db()

    match_filter = {
        "$or": [
            {"status": "ReadyForPost"},
            {"workflow_status": "ready_for_post"},
        ]
    }
    if vendor_no:
        match_filter["$or"] = [
            {"bc_vendor_number": vendor_no},
            {"vendor_no": vendor_no},
        ]

    docs = await db.hub_documents.find(
        match_filter,
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "doc_type": 1, "suggested_job_type": 1, "document_type": 1,
            "bc_vendor_number": 1, "vendor_no": 1, "vendor_canonical": 1,
            "extracted_fields.invoice_number": 1, "extracted_fields.amount": 1,
            "extracted_fields.invoice_date": 1,
            "normalized_fields.invoice_number": 1, "normalized_fields.amount": 1,
            "suggested_posting_template": 1, "posting_profile_confidence": 1,
            "bc_purchase_invoice": 1, "auto_post_reason": 1,
            "status": 1, "workflow_status": 1, "created_utc": 1,
        }
    ).sort("created_utc", -1).limit(limit).to_list(limit)

    # Enrich with posting profiles
    enriched = []
    for doc in docs:
        v_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        profile = None
        if v_no:
            profile = await db.posting_pattern_analysis.find_one(
                {"vendor_no": v_no, "status": "analyzed"},
                {"_id": 0, "posting_template": 1, "invoices_analyzed": 1}
            )

        template = profile.get("posting_template", {}) if profile else (doc.get("suggested_posting_template") or {})
        template_confidence = template.get("confidence", "none")

        # Apply confidence filter
        if confidence and template_confidence != confidence:
            continue

        ef = doc.get("extracted_fields") or {}
        nf = doc.get("normalized_fields") or {}

        enriched.append({
            "id": doc.get("id", ""),
            "filename": doc.get("filename") or doc.get("file_name", ""),
            "vendor_no": v_no,
            "vendor_name": doc.get("vendor_canonical", ""),
            "invoice_number": ef.get("invoice_number") or nf.get("invoice_number", ""),
            "amount": ef.get("amount") or nf.get("amount", ""),
            "invoice_date": ef.get("invoice_date") or nf.get("invoice_date", ""),
            "template_confidence": template_confidence,
            "template_line_count": template.get("typical_line_count", 0),
            "template_gl_accounts": [lt.get("account_number", "") for lt in template.get("line_templates", []) if lt.get("type") == "Account"],
            "has_draft": bool(doc.get("bc_purchase_invoice")),
            "draft_no": (doc.get("bc_purchase_invoice") or {}).get("bc_record_no", ""),
            "status": doc.get("status") or doc.get("workflow_status", ""),
            "created_utc": doc.get("created_utc", ""),
        })

    return {
        "count": len(enriched),
        "documents": enriched,
    }


@router.post("/draft-preview/{doc_id}")
async def preview_draft_pi(doc_id: str):
    """
    Preview what a Draft Purchase Invoice would look like for this document
    using the vendor's posting template. Does NOT create anything in BC.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}

    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
    if not vendor_no:
        return {"error": "No vendor number resolved", "doc_id": doc_id}

    # Load posting template
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    template = profile.get("posting_template", {}) if profile else {}

    # Build the preview of what would be created
    invoice_number = ef.get("invoice_number") or nf.get("invoice_number") or ""
    invoice_date = ef.get("invoice_date") or nf.get("invoice_date") or ""
    amount = ef.get("amount") or nf.get("amount") or ""
    po_number = ef.get("po_number") or nf.get("po_number") or doc.get("po_number_clean", "")

    # Build preview lines from template
    preview_lines = []
    if template.get("line_templates"):
        for lt in template["line_templates"]:
            line = {
                "lineType": lt.get("type", "Account"),
                "lineObjectNumber": lt.get("account_number") or lt.get("item_number", ""),
                "description": "",
                "quantity": 1,
                "unitCost": 0,
                "usage_rate": lt.get("usage_rate", 0),
            }
            # Construct description based on reference pattern
            ref_handling = template.get("reference_handling", {})
            ref_pattern = ref_handling.get("pattern", "")
            if ref_pattern == "freight_prefix_plus_ref" and po_number:
                line["description"] = f"FREIGHT {po_number}"
            elif ref_pattern == "bol_in_description" and po_number:
                line["description"] = po_number
            else:
                line["description"] = f"Per invoice {invoice_number}" if invoice_number else "Invoice line"

            # Try to compute amount from extracted total
            try:
                total = float(str(amount).replace("$", "").replace(",", "").strip())
                line["unitCost"] = total
            except (ValueError, TypeError):
                pass

            preview_lines.append(line)
    else:
        # Fallback: single line with total amount
        try:
            total = float(str(amount).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            total = 0
        preview_lines.append({
            "lineType": "Account",
            "lineObjectNumber": "",
            "description": f"Per invoice {invoice_number}" if invoice_number else "Invoice line",
            "quantity": 1,
            "unitCost": total,
        })

    return {
        "doc_id": doc_id,
        "vendor_no": vendor_no,
        "vendor_name": doc.get("vendor_canonical", ""),
        "template_confidence": template.get("confidence", "none"),
        "invoices_studied": profile.get("invoices_analyzed", 0) if profile else 0,
        "preview": {
            "vendorNumber": vendor_no,
            "vendorInvoiceNumber": invoice_number,
            "invoiceDate": invoice_date,
            "currency": template.get("recommended_currency", "USD"),
            "taxHandling": template.get("tax_handling", "unknown"),
            "lines": preview_lines,
        },
        "template_details": {
            "line_templates": template.get("line_templates", []),
            "reference_handling": template.get("reference_handling", {}),
            "description2_usage": template.get("description2_usage", {}),
        },
        "already_has_draft": bool(doc.get("bc_purchase_invoice")),
        "existing_draft_no": (doc.get("bc_purchase_invoice") or {}).get("bc_record_no", ""),
    }


@router.post("/create-draft/{doc_id}")
async def create_draft_from_template(doc_id: str, force: bool = Query(False)):
    """
    Create a Draft Purchase Invoice in BC using the vendor's posting template.
    This uses the learned posting patterns to build lines that match human behavior.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found", "success": False}

    # Check if already has a draft
    existing = doc.get("bc_purchase_invoice")
    if existing and not force:
        return {
            "success": True,
            "already_exists": True,
            "bc_record_no": existing.get("bc_record_no", ""),
            "message": "Draft PI already exists. Use force=true to re-create.",
        }

    # Delegate to existing create_purchase_invoice_from_document
    try:
        from routers.gpi_integration import create_purchase_invoice_from_document
        result = await create_purchase_invoice_from_document(doc_id, force=force)
        return result
    except Exception as e:
        logger.error("Failed to create draft PI for %s: %s", doc_id, str(e))
        return {"success": False, "error": str(e)}


@router.get("/vendor-summary")
async def get_vendor_posting_summary(limit: int = Query(50, le=200)):
    """
    Get a summary of all analyzed vendors with their posting profiles,
    document counts, and auto-post readiness.
    """
    db = get_db()

    # All analyzed profiles
    profiles = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "vendor_names_seen": 1, "invoices_analyzed": 1,
         "lines_analyzed": 1, "invoices_with_lines_analyzed": 1,
         "posting_template": 1, "amount_stats": 1, "consistency": 1,
         "analyzed_at": 1, "tax_pattern": 1, "line_patterns": 1}
    ).sort("invoices_analyzed", -1).limit(limit).to_list(limit)

    # Count ready docs per vendor
    pipeline = [
        {"$match": {"$or": [{"status": "ReadyForPost"}, {"workflow_status": "ready_for_post"}]}},
        {"$group": {
            "_id": {"$ifNull": ["$bc_vendor_number", "$vendor_no"]},
            "count": {"$sum": 1},
        }},
    ]
    ready_counts = {}
    async for row in db.hub_documents.aggregate(pipeline):
        if row.get("_id"):
            ready_counts[row["_id"]] = row["count"]

    # Get auto-post settings
    settings = await db.auto_post_settings.find_one({"_id": "global"}) or {}

    vendors = []
    for p in profiles:
        v_no = p.get("vendor_no", "")
        template = p.get("posting_template", {})
        amount_stats = p.get("amount_stats", {})
        line_patterns = p.get("line_patterns", {})
        consistency = p.get("consistency", {})

        vendors.append({
            "vendor_no": v_no,
            "vendor_name": (p.get("vendor_names_seen") or ["?"])[0],
            "invoices_analyzed": p.get("invoices_analyzed", 0),
            "lines_analyzed": p.get("lines_analyzed", 0),
            "invoices_with_lines": p.get("invoices_with_lines_analyzed", 0),
            "confidence": template.get("confidence", "low"),
            "consistency_score": round(consistency.get("overall", 0) * 100),
            "typical_line_count": template.get("typical_line_count", 0),
            "tax_handling": template.get("tax_handling", "unknown"),
            "currency": template.get("recommended_currency", "USD"),
            "avg_amount": amount_stats.get("mean", 0),
            "top_gl_accounts": list(line_patterns.get("top_gl_accounts", {}).keys())[:3],
            "top_items": list(line_patterns.get("top_items", {}).keys())[:3],
            "ready_docs": ready_counts.get(v_no, 0),
            "analyzed_at": p.get("analyzed_at", ""),
            "reference_pattern": template.get("reference_handling", {}).get("pattern", ""),
            "auto_post_eligible": (
                settings.get("auto_post_enabled", False) and
                template.get("confidence", "low") in _confidence_at_or_above(settings.get("min_confidence", "high")) and
                p.get("invoices_analyzed", 0) >= settings.get("min_invoices_analyzed", 10) and
                v_no not in settings.get("blocked_vendors", [])
            ),
        })

    return {
        "count": len(vendors),
        "vendors": vendors,
        "settings": {
            "auto_post_enabled": settings.get("auto_post_enabled", False),
            "min_confidence": settings.get("min_confidence", "high"),
            "min_invoices_analyzed": settings.get("min_invoices_analyzed", 10),
        },
        "ready_total": sum(ready_counts.values()),
    }


def _confidence_at_or_above(min_level: str) -> list:
    """Return confidence levels at or above the given minimum."""
    levels = ["low", "medium", "high"]
    try:
        idx = levels.index(min_level)
        return levels[idx:]
    except ValueError:
        return ["high"]


# =============================================================================
# Invoice Trace: Human vs AI Side-by-Side Comparison
# =============================================================================

@router.get("/trace/{vendor_no}")
async def trace_invoice_comparison(
    vendor_no: str,
    invoice_index: int = Query(0, ge=0, description="Which invoice to trace (0 = most recent)"),
):
    """
    Trace a REAL posted invoice for a vendor from BC Production and compare
    how the human actually posted it vs what our AI template would generate.
    Returns a side-by-side diff with matches, mismatches, and gaps.
    """
    db = get_db()
    bc = get_bc_service()
    import re

    # 1. Load our learned posting template for this vendor
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )

    template = profile.get("posting_template", {}) if profile else {}

    # 2. Fetch real invoices from BC for this vendor
    try:
        pi_result = await bc.get_posted_purchase_invoices(
            vendor_id=vendor_no, limit=invoice_index + 5, skip=0
        )
    except Exception as e:
        return {"error": f"Failed to fetch invoices from BC: {str(e)}", "vendor_no": vendor_no}

    invoices = pi_result.get("invoices", [])

    # Also try historical endpoint
    if not invoices or len(invoices) <= invoice_index:
        try:
            hist_result = await bc.get_historical_posted_purchase_invoices(
                vendor_id=vendor_no, limit=invoice_index + 5, skip=0
            )
            hist_invoices = hist_result.get("invoices", [])
            seen = {inv.get("id") for inv in invoices}
            for inv in hist_invoices:
                if inv.get("id") not in seen:
                    invoices.append(inv)
        except Exception:
            pass

    if not invoices:
        return {
            "error": "No invoices found for this vendor in BC",
            "vendor_no": vendor_no,
            "has_profile": bool(profile),
        }

    if invoice_index >= len(invoices):
        return {
            "error": f"Only {len(invoices)} invoices available. Max index: {len(invoices) - 1}",
            "vendor_no": vendor_no,
            "total_available": len(invoices),
        }

    # 3. Get the target invoice and its lines
    invoice = invoices[invoice_index]
    inv_id = invoice.get("id", "")

    try:
        human_lines = await bc.get_purchase_invoice_lines(inv_id)
    except Exception as e:
        human_lines = []
        logger.warning("Failed to get lines for traced invoice %s: %s", inv_id, str(e))

    # 4. Build the "human posted" summary
    human_summary = _build_line_summary(human_lines)

    # 5. Build what our AI template WOULD generate
    # Extract the BOL/reference from what the human actually typed in descriptions
    # (the BOL is NOT the invoice number — it's embedded in the line descriptions)
    human_ref_info = _extract_reference_from_human_lines(human_lines)

    ef = {
        "invoice_number": invoice.get("vendorInvoiceNumber", ""),
        "amount": invoice.get("totalAmountExcludingTax") or invoice.get("totalAmountIncludingTax", 0),
        "invoice_date": invoice.get("invoiceDate", ""),
        "reference_number": human_ref_info.get("ref", ""),
        "detected_pattern": human_ref_info.get("pattern", ""),
    }
    ai_lines = _simulate_template_lines(template, ef)
    ai_summary = _build_line_summary(ai_lines)

    # 6. Compute the diff
    comparison = _compute_trace_diff(human_lines, human_summary, ai_lines, ai_summary, template)

    return {
        "vendor_no": vendor_no,
        "vendor_name": invoice.get("vendorName", ""),
        "invoice_index": invoice_index,
        "total_invoices_available": len(invoices),
        "invoice": {
            "id": inv_id,
            "number": invoice.get("number", ""),
            "vendor_invoice_number": invoice.get("vendorInvoiceNumber", ""),
            "invoice_date": invoice.get("invoiceDate", ""),
            "due_date": invoice.get("dueDate", ""),
            "status": invoice.get("status", ""),
            "total_excl_tax": invoice.get("totalAmountExcludingTax", 0),
            "total_incl_tax": invoice.get("totalAmountIncludingTax", 0),
            "total_tax": invoice.get("totalTaxAmount", 0),
            "currency": invoice.get("currencyCode", "USD"),
        },
        "human_posted": {
            "line_count": len(human_lines),
            "lines": [
                {
                    "line_type": ln.get("lineType", ""),
                    "item_or_account": ln.get("lineObjectNumber", ""),
                    "description": ln.get("description", ""),
                    "description2": ln.get("description2", ""),
                    "quantity": ln.get("quantity", 0),
                    "unit_cost": ln.get("unitCost", 0),
                    "net_amount": ln.get("netAmount") or ln.get("lineAmount", 0),
                    "tax_code": ln.get("taxCode", ""),
                    "uom": ln.get("unitOfMeasureCode", ""),
                }
                for ln in human_lines
            ],
            "summary": human_summary,
        },
        "ai_would_post": {
            "line_count": len(ai_lines),
            "lines": [
                {
                    "line_type": ln.get("lineType", ""),
                    "item_or_account": ln.get("lineObjectNumber", ""),
                    "description": ln.get("description", ""),
                    "quantity": ln.get("quantity", 0),
                    "unit_cost": ln.get("unitCost", 0),
                    "net_amount": ln.get("netAmount", 0),
                    "tax_code": ln.get("taxCode", ""),
                    "uom": ln.get("uom", ""),
                }
                for ln in ai_lines
            ],
            "summary": ai_summary,
            "template_confidence": template.get("confidence", "none"),
            "template_consistency": template.get("consistency_score", 0),
        },
        "comparison": comparison,
        "has_profile": bool(profile),
        "profile_invoices_studied": profile.get("invoices_analyzed", 0) if profile else 0,
    }


@router.get("/trace/{vendor_no}/list")
async def list_traceable_invoices(vendor_no: str, limit: int = Query(20, le=100)):
    """List available invoices for tracing for a vendor."""
    bc = get_bc_service()

    try:
        pi_result = await bc.get_posted_purchase_invoices(vendor_id=vendor_no, limit=limit)
    except Exception as e:
        return {"error": str(e), "vendor_no": vendor_no, "invoices": []}

    invoices = pi_result.get("invoices", [])
    return {
        "vendor_no": vendor_no,
        "count": len(invoices),
        "invoices": [
            {
                "index": i,
                "number": inv.get("number", ""),
                "vendor_invoice_number": inv.get("vendorInvoiceNumber", ""),
                "invoice_date": inv.get("invoiceDate", ""),
                "status": inv.get("status", ""),
                "total": inv.get("totalAmountExcludingTax") or inv.get("totalAmountIncludingTax", 0),
            }
            for i, inv in enumerate(invoices)
        ],
    }


def _build_line_summary(lines: list) -> dict:
    """Summarize invoice lines into comparable dimensions."""
    if not lines:
        return {"line_count": 0, "line_types": {}, "items": {}, "gl_accounts": {},
                "descriptions": [], "tax_codes": {}, "uoms": {}, "total_amount": 0}

    from collections import Counter
    line_types = Counter()
    items = Counter()
    gl_accounts = Counter()
    descriptions = []
    tax_codes = Counter()
    uoms = Counter()
    total_amount = 0

    for ln in lines:
        lt = ln.get("lineType", "unknown")
        line_types[lt] += 1
        obj = ln.get("lineObjectNumber") or ln.get("item_or_account", "")
        if obj:
            if lt == "Item":
                items[obj] += 1
            elif lt == "Account":
                gl_accounts[obj] += 1
        desc = ln.get("description", "")
        if desc:
            descriptions.append(desc)
        tc = ln.get("taxCode", "")
        if tc:
            tax_codes[tc] += 1
        uom = ln.get("unitOfMeasureCode") or ln.get("uom", "")
        if uom:
            uoms[uom] += 1
        amt = ln.get("netAmount") or ln.get("lineAmount") or ln.get("unitCost", 0) or 0
        try:
            total_amount += float(amt)
        except (ValueError, TypeError):
            pass

    return {
        "line_count": len(lines),
        "line_types": dict(line_types),
        "items": dict(items),
        "gl_accounts": dict(gl_accounts),
        "descriptions": descriptions,
        "tax_codes": dict(tax_codes),
        "uoms": dict(uoms),
        "total_amount": round(total_amount, 2),
    }


def _extract_reference_from_human_lines(human_lines: list) -> dict:
    """
    Extract the BOL/reference number AND the pattern from human-posted line descriptions.
    Returns both the reference and which pattern the human used on THIS invoice.
    """
    import re
    for line in human_lines:
        desc = (line.get("description") or "").strip()
        if not desc:
            continue
        # "FREIGHT 49785" → pattern=freight_prefix_plus_ref, ref="49785"
        m = re.match(r'^(?:FREIGHT|FRT|Freight)\s+(.+)', desc, re.IGNORECASE)
        if m:
            return {"ref": m.group(1).strip(), "pattern": "freight_prefix_plus_ref"}
        # "PO 12345" → pattern=po_prefix_plus_ref, ref="12345"
        m = re.match(r'^PO[#\s]+(.+)', desc, re.IGNORECASE)
        if m:
            return {"ref": m.group(1).strip(), "pattern": "po_prefix_plus_ref"}
        # "W110700" → pattern=order_number_ref
        m = re.match(r'^([A-Z]\d{4,})$', desc.strip(), re.IGNORECASE)
        if m:
            return {"ref": m.group(1), "pattern": "order_number_ref"}
        # Pure number "46133" → pattern=bol_in_description
        m = re.match(r'^(\d{4,7})$', desc.strip())
        if m:
            return {"ref": m.group(1), "pattern": "bol_in_description"}
        # Embedded reference
        m = re.search(r'(\d{4,7})', desc)
        if m:
            return {"ref": m.group(1), "pattern": "embedded_ref"}
    return {"ref": "", "pattern": ""}


def _simulate_template_lines(template: dict, extracted_fields: dict) -> list:
    """
    Simulate what the AI would generate using the posting template.

    Key rules:
    - Respect typical_line_count — emit that many lines
    - Single-line vendors: primary items only (simple freight pattern)
    - Multi-line vendors: emit ALL structural items with proper descriptions,
      quantities, and amounts from the learned metadata
    - Use the BOL/reference number (not invoice number) for freight patterns
    - Add Comment line placeholders where the template shows them
    """
    if not template or not template.get("line_templates"):
        # No template — fallback single line
        try:
            amount = float(str(extracted_fields.get("amount", 0)).replace("$", "").replace(",", "").strip())
        except (ValueError, TypeError):
            amount = 0
        return [{
            "lineType": "Account",
            "lineObjectNumber": "",
            "description": f"Per invoice {extracted_fields.get('invoice_number', '')}",
            "quantity": 1,
            "unitCost": amount,
            "netAmount": amount,
            "taxCode": "",
            "uom": template.get("uom", ""),
        }]

    invoice_number = extracted_fields.get("invoice_number", "")
    reference_number = extracted_fields.get("reference_number", "") or invoice_number
    try:
        total_amount = float(str(extracted_fields.get("amount", 0)).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        total_amount = 0

    ref_handling = template.get("reference_handling", {})
    # Use the pattern detected from the human's actual line if available (trace mode),
    # otherwise fall back to the template's dominant pattern
    ref_pattern = extracted_fields.get("detected_pattern", "") or ref_handling.get("pattern", "")
    line_tax = template.get("line_tax_code", {})
    typical_count = int(template.get("typical_line_count", 1) or 1)
    all_templates = template.get("line_templates", [])

    # --- Single-line vendors: primary only, simple pattern ---
    if typical_count <= 1:
        eligible = [lt for lt in all_templates if lt.get("rank") == "primary"]
        if not eligible:
            eligible = sorted(all_templates, key=lambda x: x.get("usage_rate", 0), reverse=True)[:1]
        eligible = eligible[:1]
        return _build_lines_from_templates(
            eligible, total_amount, ref_pattern, reference_number,
            invoice_number, line_tax, template, single_line=True,
        )

    # --- Multi-line vendors: emit structural skeleton + 1 product slot ---
    # Categorize template items by their structural role
    structural = []  # Always present, always the same (zero-cost or constant)
    surcharges = []  # Always present, small variable cost
    product_candidates = []  # Variable product lines (SKU changes per order)
    other = []  # Everything else

    for lt in all_templates:
        st = lt.get("slot_type", "unknown")
        if st in ("structural_zero", "structural_constant"):
            structural.append(lt)
        elif st == "surcharge":
            surcharges.append(lt)
        elif st in ("variable_product", "structural_variable"):
            product_candidates.append(lt)
        else:
            other.append(lt)

    # Build the line list:
    # 1. All structural items (packaging, tracking — always present)
    # 2. All surcharges (energy, freight surcharges)
    # 3. Exactly 1 variable product slot (the most common product as placeholder)
    # 4. Fill remaining with other frequent items or comments
    selected = []
    selected.extend(structural)
    selected.extend(surcharges)

    # Add exactly 1 product slot — pick the highest usage rate
    if product_candidates:
        selected.append(product_candidates[0])
    elif other:
        # No explicit variable_product — use the highest-usage optional item
        # but only add 1 product slot
        non_zero_others = [o for o in other if not o.get("is_zero_cost", False)]
        zero_others = [o for o in other if o.get("is_zero_cost", False)]
        if non_zero_others:
            selected.append(non_zero_others[0])
        # Add zero-cost others (like Z-POP) as structural
        selected.extend(zero_others)

    # Cap at typical_count
    selected = selected[:typical_count]

    lines = _build_lines_from_templates(
        selected, total_amount, ref_pattern, reference_number,
        invoice_number, line_tax, template, single_line=False,
    )

    # Add Comment line placeholders if the vendor typically uses them
    comment_info = template.get("comment_lines", {})
    typical_comments = comment_info.get("typical_count", 0)
    if typical_comments > 0 and len(lines) < typical_count:
        top_descs = comment_info.get("top_descriptions", [])
        for i in range(min(typical_comments, typical_count - len(lines))):
            lines.append({
                "lineType": "Comment",
                "lineObjectNumber": "",
                "description": top_descs[i] if i < len(top_descs) else "[Comment]",
                "quantity": 0,
                "unitCost": 0,
                "netAmount": 0,
                "taxCode": "",
                "uom": "",
            })

    return lines


def _build_lines_from_templates(
    templates, total_amount, ref_pattern, reference_number,
    invoice_number, line_tax, full_template, single_line=False,
):
    """Build simulated lines from template entries with proper metadata."""
    lines = []

    # Separate value-carrying items from zero-cost structural items
    value_items = [t for t in templates if not t.get("is_zero_cost", False)]

    # Calculate known surcharge amounts (small-value items like ENERGY-DS)
    # The PRIMARY value carrier is the one with the highest typical cost
    if len(value_items) > 1:
        value_items_sorted = sorted(value_items, key=lambda x: x.get("typical_unit_cost", 0) * max(x.get("typical_qty", 1), 1), reverse=True)
        primary_value = value_items_sorted[0]
        surcharge_total = sum(
            (v.get("typical_unit_cost", 0) or 0) * max(v.get("typical_qty", 1), 1)
            for v in value_items_sorted[1:]
        )
    elif value_items:
        primary_value = value_items[0]
        surcharge_total = 0
    else:
        primary_value = None
        surcharge_total = 0

    # Primary product line gets: total_amount - surcharges
    primary_amount = max(total_amount - surcharge_total, 0)

    for lt in templates:
        is_zero = lt.get("is_zero_cost", False)
        is_primary = (lt is primary_value) if primary_value else (lt == templates[0])

        # Use the metadata-enriched description if available
        common_desc = lt.get("common_description", "")
        has_variable_desc = lt.get("unique_descriptions", 0) > 10

        # Determine description
        if has_variable_desc and is_primary:
            # Variable product SKU — this is the slot that changes per order
            # In trace mode, the human's actual product will differ; in auto-post,
            # this comes from the incoming document
            ref = reference_number or invoice_number
            if ref_pattern == "freight_prefix_plus_ref" and ref:
                desc = f"Freight {ref}"
            elif ref_pattern == "bol_in_description" and ref:
                desc = ref
            elif ref_pattern == "po_prefix_plus_ref" and ref:
                desc = f"PO {ref}"
            elif common_desc:
                desc = f"[VARIABLE] {common_desc}"
            else:
                desc = f"Per invoice {invoice_number}" if invoice_number else "[VARIABLE PRODUCT]"
        elif common_desc:
            desc = common_desc
        else:
            ref = reference_number or invoice_number
            if ref_pattern == "freight_prefix_plus_ref" and ref:
                desc = f"Freight {ref}"
            elif ref_pattern == "bol_in_description" and ref:
                desc = ref
            elif ref_pattern == "po_prefix_plus_ref" and ref:
                desc = f"PO {ref}"
            else:
                desc = f"Per invoice {invoice_number}" if invoice_number else "Invoice line"

        # Determine amount
        if is_zero:
            line_amount = 0
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = 0
        elif is_primary:
            # Primary value carrier gets total minus surcharges
            line_amount = round(primary_amount, 2)
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = round(line_amount / max(line_qty, 1), 5) if line_qty else line_amount
        else:
            # Surcharge / secondary value item — use typical cost
            typical_cost = lt.get("typical_unit_cost", 0) or 0
            line_qty = lt.get("typical_qty", 1) or 1
            line_unit_cost = typical_cost
            line_amount = round(line_qty * typical_cost, 2)

        line = {
            "lineType": lt.get("type", "Item"),
            "lineObjectNumber": lt.get("account_number") or lt.get("item_number", ""),
            "description": desc,
            "quantity": line_qty,
            "unitCost": line_unit_cost if not is_zero else 0,
            "netAmount": line_amount,
            "taxCode": lt.get("tax_code", "") or line_tax.get("code", ""),
            "uom": lt.get("uom", "") or full_template.get("uom", ""),
        }
        lines.append(line)

    return lines


def _compute_trace_diff(human_lines, human_summary, ai_lines, ai_summary, template) -> dict:
    """Compute a detailed comparison between human and AI postings."""
    matches = []
    mismatches = []
    gaps = []

    # 1. Line count comparison
    h_count = human_summary.get("line_count", 0)
    a_count = ai_summary.get("line_count", 0)
    if h_count == a_count:
        matches.append({"dimension": "Line Count", "value": str(h_count), "verdict": "MATCH"})
    else:
        mismatches.append({
            "dimension": "Line Count",
            "human": str(h_count),
            "ai": str(a_count),
            "verdict": "MISMATCH",
            "note": f"Human used {h_count} lines, AI template would use {a_count}",
        })

    # 2. Line type comparison
    h_types = human_summary.get("line_types", {})
    a_types = ai_summary.get("line_types", {})
    dominant_h = max(h_types, key=h_types.get) if h_types else "none"
    dominant_a = max(a_types, key=a_types.get) if a_types else "none"
    if dominant_h == dominant_a:
        matches.append({"dimension": "Line Type", "value": dominant_h, "verdict": "MATCH"})
    else:
        mismatches.append({
            "dimension": "Line Type",
            "human": str(h_types),
            "ai": str(a_types),
            "verdict": "MISMATCH",
        })

    # 3. Item/GL account comparison
    h_items = set(human_summary.get("items", {}).keys())
    h_gls = set(human_summary.get("gl_accounts", {}).keys())
    a_items = set(ai_summary.get("items", {}).keys())
    a_gls = set(ai_summary.get("gl_accounts", {}).keys())
    h_all = h_items | h_gls
    a_all = a_items | a_gls
    common = h_all & a_all
    if common:
        matches.append({"dimension": "Items/GL Accounts", "value": ", ".join(sorted(common)), "verdict": "MATCH"})
    h_only = h_all - a_all
    a_only = a_all - h_all
    if h_only:
        mismatches.append({
            "dimension": "Items/GL (Human Only)",
            "human": ", ".join(sorted(h_only)),
            "ai": "—",
            "verdict": "GAP",
            "note": "Human used these but AI template doesn't include them",
        })
    if a_only:
        mismatches.append({
            "dimension": "Items/GL (AI Only)",
            "human": "—",
            "ai": ", ".join(sorted(a_only)),
            "verdict": "GAP",
            "note": "AI template includes these but human didn't use them on this invoice",
        })

    # 4. Description pattern comparison
    h_descs = human_summary.get("descriptions", [])
    a_descs = ai_summary.get("descriptions", [])
    if h_descs and a_descs:
        # Check if same pattern type (e.g., both start with FREIGHT)
        h_first = h_descs[0].strip().upper()[:20] if h_descs else ""
        a_first = a_descs[0].strip().upper()[:20] if a_descs else ""
        # Fuzzy: same prefix?
        h_prefix = h_first.split()[0] if h_first else ""
        a_prefix = a_first.split()[0] if a_first else ""
        if h_prefix == a_prefix and h_prefix:
            matches.append({
                "dimension": "Description Pattern",
                "value": f"Both start with '{h_prefix}'",
                "verdict": "MATCH",
                "human_example": h_descs[0][:60],
                "ai_example": a_descs[0][:60],
            })
        else:
            mismatches.append({
                "dimension": "Description Pattern",
                "human": h_descs[0][:60] if h_descs else "—",
                "ai": a_descs[0][:60] if a_descs else "—",
                "verdict": "MISMATCH",
            })
    elif h_descs and not a_descs:
        gaps.append({"dimension": "Description", "note": "Human has descriptions but AI template doesn't"})

    # 5. Tax code comparison
    h_tax = human_summary.get("tax_codes", {})
    a_tax = ai_summary.get("tax_codes", {})
    if h_tax and a_tax:
        h_top_tax = max(h_tax, key=h_tax.get)
        a_top_tax = max(a_tax, key=a_tax.get)
        if h_top_tax == a_top_tax:
            matches.append({"dimension": "Tax Code", "value": h_top_tax, "verdict": "MATCH"})
        else:
            mismatches.append({
                "dimension": "Tax Code",
                "human": h_top_tax,
                "ai": a_top_tax,
                "verdict": "MISMATCH",
            })
    elif h_tax and not a_tax:
        gaps.append({"dimension": "Tax Code", "note": f"Human used {list(h_tax.keys())} but AI has no tax code"})
    elif not h_tax and not a_tax:
        matches.append({"dimension": "Tax Code", "value": "None (both)", "verdict": "MATCH"})

    # 6. UOM comparison
    h_uom = human_summary.get("uoms", {})
    a_uom = ai_summary.get("uoms", {})
    if h_uom and a_uom:
        h_top_uom = max(h_uom, key=h_uom.get)
        a_top_uom = max(a_uom, key=a_uom.get)
        if h_top_uom == a_top_uom:
            matches.append({"dimension": "UOM", "value": h_top_uom, "verdict": "MATCH"})
        else:
            mismatches.append({"dimension": "UOM", "human": h_top_uom, "ai": a_top_uom, "verdict": "MISMATCH"})

    # 7. Amount comparison
    h_amt = human_summary.get("total_amount", 0)
    a_amt = ai_summary.get("total_amount", 0)
    if h_amt > 0 and a_amt > 0:
        diff_pct = abs(h_amt - a_amt) / max(h_amt, 1) * 100
        if diff_pct < 1:
            matches.append({"dimension": "Total Amount", "value": f"${h_amt:,.2f}", "verdict": "MATCH"})
        else:
            mismatches.append({
                "dimension": "Total Amount",
                "human": f"${h_amt:,.2f}",
                "ai": f"${a_amt:,.2f}",
                "verdict": "CLOSE" if diff_pct < 5 else "MISMATCH",
                "note": f"{diff_pct:.1f}% difference",
            })

    # Overall score
    total_dims = len(matches) + len(mismatches) + len(gaps)
    match_rate = round(len(matches) / max(total_dims, 1) * 100)

    return {
        "match_rate": match_rate,
        "total_dimensions": total_dims,
        "matches": matches,
        "mismatches": mismatches,
        "gaps": gaps,
        "verdict": (
            "EXCELLENT — AI closely replicates human behavior" if match_rate >= 80
            else "GOOD — AI captures most patterns, minor gaps" if match_rate >= 60
            else "NEEDS WORK — Significant differences between human and AI" if match_rate >= 40
            else "POOR — AI template doesn't match human posting behavior"
        ),
    }
