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
    """Get overall posting pattern analysis status."""
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

    # Get top 10 vendors by invoice count
    top_vendors = await db.posting_pattern_analysis.find(
        {"status": "analyzed"},
        {"_id": 0, "vendor_no": 1, "vendor_names_seen": 1,
         "invoices_analyzed": 1, "lines_analyzed": 1,
         "posting_template.confidence": 1, "amount_stats.mean": 1}
    ).sort("invoices_analyzed", -1).limit(10).to_list(10)

    return {
        "total_profiles": total_profiles,
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
                "avg_amount": v.get("amount_stats", {}).get("mean", 0),
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
async def analyze_single_vendor(vendor_no: str, limit: int = Query(default=100, le=500)):
    """Analyze posting patterns for a single vendor from BC production data."""
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


async def _run_top_analysis(top_n: int):
    """Background task: analyze top vendors."""
    global _analysis_status
    _analysis_status = {"running": True, "last_result": None, "progress": "starting"}
    try:
        db = get_db()
        bc = get_bc_service()
        from services.posting_pattern_analyzer import build_all_vendor_posting_profiles

        # Analyze vendors one at a time and update progress
        from services.posting_pattern_analyzer import (
            analyze_vendor_posting_patterns,
            MIN_INVOICES_FOR_PROFILE,
        )
        cursor = db.vendor_invoice_profiles.find(
            {"bc_invoice_count": {"$gte": MIN_INVOICES_FOR_PROFILE}},
            {"_id": 0, "vendor_no": 1, "vendor_name": 1, "bc_invoice_count": 1}
        ).sort("bc_invoice_count", -1).limit(top_n)
        vendors = await cursor.to_list(top_n)

        results = {"vendors_queued": len(vendors), "analyzed": 0, "errors": 0, "skipped": 0, "vendor_details": []}

        for i, v in enumerate(vendors):
            vendor_no = v.get("vendor_no", "")
            if not vendor_no:
                continue
            _analysis_status["progress"] = f"Analyzing {vendor_no} ({i+1}/{len(vendors)})"

            # Check if recent analysis exists
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
                    })
                else:
                    results["errors"] += 1
                    logger.warning("Vendor %s analysis status: %s, error: %s",
                                   vendor_no, analysis.get("status"), analysis.get("error", ""))
            except Exception as e:
                results["errors"] += 1
                logger.error("Failed to analyze vendor %s: %s", vendor_no, str(e))

            # Brief pause to avoid BC API throttling
            await asyncio.sleep(0.5)

        _analysis_status = {"running": False, "last_result": results, "progress": "complete"}
        logger.info("[PostingPatterns] Background analysis complete: analyzed=%d, errors=%d, skipped=%d",
                     results["analyzed"], results["errors"], results["skipped"])

    except Exception as e:
        _analysis_status = {"running": False, "last_result": {"error": str(e)}, "progress": "failed"}
        logger.error("[PostingPatterns] Background analysis failed: %s", str(e))


@router.post("/analyze-top")
async def analyze_top_vendors(background_tasks: BackgroundTasks, top_n: int = Query(default=20, le=100)):
    """
    Analyze posting patterns for the top N vendors by invoice volume.
    Runs in background to avoid nginx timeout. Check progress via GET /analyze-top/status.
    """
    global _analysis_status
    if _analysis_status.get("running"):
        return {
            "status": "already_running",
            "progress": _analysis_status.get("progress", ""),
            "message": "Analysis is already in progress. Check GET /analyze-top/status for progress.",
        }

    background_tasks.add_task(_run_top_analysis, top_n)
    return {
        "status": "started",
        "vendors_to_analyze": top_n,
        "message": f"Background analysis started for top {top_n} vendors. Check GET /api/posting-patterns/analyze-top/status for progress.",
    }


@router.get("/analyze-top/status")
async def get_analysis_status():
    """Check the status of a background analyze-top job."""
    return _analysis_status


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
            "line_count_consistency": f"{consistency.get('line_count', 0)*100:.0f}%",
            "item_choice_consistency": f"{consistency.get('item_choice', 0)*100:.0f}%",
            "line_type_consistency": f"{consistency.get('line_type', 0)*100:.0f}%",
            "item_dominance": f"{consistency.get('item_dominance', 0)*100:.0f}%",
            "interpretation": (
                "HIGHLY PREDICTABLE — safe for auto-posting"
                if consistency.get("overall", 0) >= 0.8 else
                "MOSTLY PREDICTABLE — good candidate with review"
                if consistency.get("overall", 0) >= 0.6 else
                "VARIABLE — needs human review for each invoice"
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
