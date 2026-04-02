"""
GPI Document Hub — BC Posting Pattern Analyzer

"Work backwards from BC": Query how humans have posted invoices to BC,
extract patterns, and build vendor-specific posting profiles that teach
the auto-post system to replicate human behavior.

Collections:
  - vendor_posting_profiles: Learned posting patterns per vendor
  - posting_pattern_analysis: Raw analysis results from BC queries
"""
import logging
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum invoices needed to build a reliable posting profile
MIN_INVOICES_FOR_PROFILE = 3
# Max invoices to analyze per vendor (recent history)
MAX_INVOICES_PER_VENDOR = 200


async def analyze_vendor_posting_patterns(
    db, bc_service, vendor_no: str, limit: int = MAX_INVOICES_PER_VENDOR
) -> Dict[str, Any]:
    """
    Analyze how humans post invoices for a specific vendor in BC.
    Returns a rich posting profile with GL patterns, line item templates,
    amount distributions, and field mapping patterns.
    """
    result = {
        "vendor_no": vendor_no,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "invoices_analyzed": 0,
        "lines_analyzed": 0,
    }

    # 1. Get posted invoices for this vendor
    pi_result = await bc_service.get_posted_purchase_invoices(vendor_id=vendor_no, limit=limit)
    invoices = pi_result.get("invoices", [])

    if not invoices:
        result["status"] = "no_invoices"
        result["error"] = pi_result.get("error")
        return result

    result["invoices_analyzed"] = len(invoices)

    # 2. Analyze invoice-level patterns
    amounts = []
    tax_amounts = []
    currencies = defaultdict(int)
    invoice_dates = []
    has_vendor_invoice_no = 0
    vendor_names_seen = set()

    for inv in invoices:
        amt = inv.get("totalAmountExcludingTax") or inv.get("totalAmountIncludingTax") or 0
        if isinstance(amt, (int, float)):
            amounts.append(float(amt))
        tax = inv.get("totalTaxAmount") or 0
        if isinstance(tax, (int, float)):
            tax_amounts.append(float(tax))
        curr = inv.get("currencyCode", "USD")
        currencies[curr or "USD"] += 1
        if inv.get("vendorInvoiceNumber"):
            has_vendor_invoice_no += 1
        if inv.get("vendorName"):
            vendor_names_seen.add(inv["vendorName"])
        if inv.get("invoiceDate"):
            invoice_dates.append(inv["invoiceDate"])

    # Amount statistics
    if amounts:
        result["amount_stats"] = {
            "count": len(amounts),
            "mean": round(statistics.mean(amounts), 2),
            "median": round(statistics.median(amounts), 2),
            "min": round(min(amounts), 2),
            "max": round(max(amounts), 2),
            "stdev": round(statistics.stdev(amounts), 2) if len(amounts) > 1 else 0,
        }
    else:
        result["amount_stats"] = {"count": 0}

    # Tax patterns
    has_tax = sum(1 for t in tax_amounts if t > 0)
    result["tax_pattern"] = {
        "invoices_with_tax": has_tax,
        "invoices_without_tax": len(tax_amounts) - has_tax,
        "tax_rate_typical": round(
            statistics.mean([t / max(a, 1) for t, a in zip(tax_amounts, amounts) if t > 0]) * 100, 1
        ) if has_tax > 0 else 0,
    }

    result["currency_distribution"] = dict(currencies)
    result["vendor_invoice_number_rate"] = round(has_vendor_invoice_no / max(len(invoices), 1), 3)
    result["vendor_names_seen"] = list(vendor_names_seen)

    # 3. Analyze line items for a sample of invoices (up to 20 to stay fast)
    sample_invoices = invoices[:20]
    all_lines = []
    line_type_counts = defaultdict(int)
    gl_account_counts = defaultdict(int)
    item_counts = defaultdict(int)
    description_patterns = defaultdict(int)
    lines_per_invoice = []

    for inv in sample_invoices:
        inv_id = inv.get("id")
        if not inv_id:
            continue
        try:
            lines = await bc_service.get_purchase_invoice_lines(inv_id)
            lines_per_invoice.append(len(lines))
            for line in lines:
                all_lines.append(line)
                line_type = line.get("lineType", "unknown")
                line_type_counts[line_type] += 1
                obj_no = line.get("lineObjectNumber", "")
                if obj_no:
                    if line_type == "Account":
                        gl_account_counts[obj_no] += 1
                    elif line_type == "Item":
                        item_counts[obj_no] += 1
                desc = line.get("description", "")
                if desc:
                    # Normalize description for pattern detection
                    desc_norm = desc.strip().upper()[:50]
                    description_patterns[desc_norm] += 1
        except Exception as e:
            logger.debug("Failed to get lines for PI %s: %s", inv_id, str(e))

    result["lines_analyzed"] = len(all_lines)

    # Line item patterns
    result["line_patterns"] = {
        "lines_per_invoice": {
            "mean": round(statistics.mean(lines_per_invoice), 1) if lines_per_invoice else 0,
            "median": statistics.median(lines_per_invoice) if lines_per_invoice else 0,
            "min": min(lines_per_invoice) if lines_per_invoice else 0,
            "max": max(lines_per_invoice) if lines_per_invoice else 0,
        },
        "line_types": dict(line_type_counts),
        "top_gl_accounts": dict(sorted(gl_account_counts.items(), key=lambda x: -x[1])[:10]),
        "top_items": dict(sorted(item_counts.items(), key=lambda x: -x[1])[:10]),
        "top_descriptions": dict(sorted(description_patterns.items(), key=lambda x: -x[1])[:15]),
    }

    # 4. Build the posting template (what the auto-post should do)
    result["posting_template"] = _build_posting_template(result)
    result["status"] = "analyzed"

    # 5. Store in DB
    await db.posting_pattern_analysis.update_one(
        {"vendor_no": vendor_no},
        {"$set": result},
        upsert=True,
    )

    return result


def _build_posting_template(analysis: Dict) -> Dict[str, Any]:
    """
    From the analysis, build a posting template that the auto-post
    service can use to create purchase invoices that match human behavior.
    """
    template = {
        "recommended_currency": "USD",
        "typical_line_count": 1,
        "line_templates": [],
        "tax_handling": "no_tax",
        "confidence": "low",
    }

    # Currency
    currencies = analysis.get("currency_distribution", {})
    if currencies:
        template["recommended_currency"] = max(currencies, key=currencies.get)

    # Line count
    lp = analysis.get("line_patterns", {}).get("lines_per_invoice", {})
    if lp.get("median"):
        template["typical_line_count"] = int(lp["median"])

    # Tax handling
    tp = analysis.get("tax_pattern", {})
    if tp.get("invoices_with_tax", 0) > tp.get("invoices_without_tax", 0):
        template["tax_handling"] = "taxable"
        template["typical_tax_rate"] = tp.get("tax_rate_typical", 0)
    else:
        template["tax_handling"] = "no_tax"

    # Build line templates from the most common patterns
    line_types = analysis.get("line_patterns", {}).get("line_types", {})
    gl_accounts = analysis.get("line_patterns", {}).get("top_gl_accounts", {})
    items = analysis.get("line_patterns", {}).get("top_items", {})
    descriptions = analysis.get("line_patterns", {}).get("top_descriptions", {})

    # Primary line template: most common GL account or item
    if gl_accounts:
        top_gl = max(gl_accounts, key=gl_accounts.get)
        top_gl_count = gl_accounts[top_gl]
        total_lines = sum(line_types.values()) or 1
        template["line_templates"].append({
            "type": "Account",
            "account_number": top_gl,
            "usage_rate": round(top_gl_count / total_lines, 2),
            "typical_description": list(descriptions.keys())[0] if descriptions else "",
        })

    if items:
        top_item = max(items, key=items.get)
        top_item_count = items[top_item]
        total_lines = sum(line_types.values()) or 1
        template["line_templates"].append({
            "type": "Item",
            "item_number": top_item,
            "usage_rate": round(top_item_count / total_lines, 2),
        })

    # Confidence
    inv_count = analysis.get("invoices_analyzed", 0)
    lines_count = analysis.get("lines_analyzed", 0)
    if inv_count >= 50 and lines_count >= 50:
        template["confidence"] = "high"
    elif inv_count >= 10:
        template["confidence"] = "medium"
    else:
        template["confidence"] = "low"

    return template


async def build_all_vendor_posting_profiles(db, bc_service, top_n: int = 50) -> Dict[str, Any]:
    """
    Build posting profiles for the top N vendors by invoice volume.
    Uses the vendor_invoice_profiles collection (from knowledge seed) to
    identify which vendors to analyze.
    """
    # Get top vendors by BC invoice count
    cursor = db.vendor_invoice_profiles.find(
        {"bc_invoice_count": {"$gte": MIN_INVOICES_FOR_PROFILE}},
        {"_id": 0, "vendor_no": 1, "vendor_name": 1, "bc_invoice_count": 1}
    ).sort("bc_invoice_count", -1).limit(top_n)

    vendors = await cursor.to_list(top_n)

    results = {"vendors_queued": len(vendors), "analyzed": 0, "errors": 0, "skipped": 0}
    vendor_results = []

    for v in vendors:
        vendor_no = v.get("vendor_no", "")
        if not vendor_no:
            continue

        # Check if we already have a recent analysis (< 7 days old)
        existing = await db.posting_pattern_analysis.find_one(
            {"vendor_no": vendor_no, "status": "analyzed"},
            {"_id": 0, "analyzed_at": 1}
        )
        if existing:
            analyzed_at = existing.get("analyzed_at", "")
            if analyzed_at:
                try:
                    dt = datetime.fromisoformat(analyzed_at.replace("Z", "+00:00"))
                    if (datetime.now(timezone.utc) - dt).days < 7:
                        results["skipped"] += 1
                        continue
                except (ValueError, TypeError):
                    pass

        try:
            analysis = await analyze_vendor_posting_patterns(db, bc_service, vendor_no)
            if analysis.get("status") == "analyzed":
                results["analyzed"] += 1
                vendor_results.append({
                    "vendor_no": vendor_no,
                    "vendor_name": v.get("vendor_name", ""),
                    "invoices": analysis.get("invoices_analyzed", 0),
                    "lines": analysis.get("lines_analyzed", 0),
                    "confidence": analysis.get("posting_template", {}).get("confidence", "?"),
                })
            else:
                results["errors"] += 1
        except Exception as e:
            logger.error("Failed to analyze vendor %s: %s", vendor_no, str(e))
            results["errors"] += 1

    results["vendor_details"] = vendor_results
    logger.info("[PostingPatterns] Analysis complete: %s", {k: v for k, v in results.items() if k != "vendor_details"})
    return results


async def get_posting_profile_for_vendor(db, vendor_no: str) -> Optional[Dict[str, Any]]:
    """Get the learned posting profile for a vendor (used by auto-post service)."""
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0}
    )
    return profile
