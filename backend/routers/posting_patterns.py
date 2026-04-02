"""
GPI Document Hub — Posting Pattern Analysis API

Endpoints to analyze BC posting patterns and build vendor posting profiles.
"""
import logging
from fastapi import APIRouter, Query

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posting-patterns", tags=["posting-patterns"])


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


@router.post("/analyze-top")
async def analyze_top_vendors(top_n: int = Query(default=20, le=100)):
    """
    Analyze posting patterns for the top N vendors by invoice volume.
    This is the main "learn from humans" endpoint — it queries BC production,
    studies how invoices were posted, and builds posting templates.
    """
    db = get_db()
    bc = get_bc_service()

    from services.posting_pattern_analyzer import build_all_vendor_posting_profiles
    result = await build_all_vendor_posting_profiles(db, bc, top_n=top_n)
    return result


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

    proof = {
        "vendor_no": vendor_no,
        "vendor_names": profile.get("vendor_names_seen", []),
        "invoices_studied": profile.get("invoices_analyzed", 0),
        "lines_studied": profile.get("lines_analyzed", 0),
        "what_the_system_learned": {
            "typical_invoice_amount": f"${amount.get('mean', 0):,.2f} (range ${amount.get('min', 0):,.2f}-${amount.get('max', 0):,.2f})",
            "typical_line_count": lines.get("lines_per_invoice", {}).get("median", "?"),
            "primary_gl_accounts": list(lines.get("top_gl_accounts", {}).keys())[:5],
            "primary_items": list(lines.get("top_items", {}).keys())[:5],
            "common_descriptions": list(lines.get("top_descriptions", {}).keys())[:5],
            "tax_handling": f"{tax.get('tax_rate_typical', 0)}% tax" if tax.get("invoices_with_tax", 0) > 0 else "Tax-free",
            "currency": profile.get("currency_distribution", {}),
            "vendor_invoice_number_usage": f"{profile.get('vendor_invoice_number_rate', 0)*100:.0f}%",
        },
        "auto_post_template": {
            "confidence": template.get("confidence", "?"),
            "would_create": {
                "currency": template.get("recommended_currency", "USD"),
                "line_count": template.get("typical_line_count", 1),
                "tax_handling": template.get("tax_handling", "?"),
                "line_templates": template.get("line_templates", []),
            },
        },
        "verdict": f"LEARNED ({template.get('confidence', '?').upper()} confidence)" if profile.get("invoices_analyzed", 0) >= 3 else "INSUFFICIENT DATA",
    }

    return proof
