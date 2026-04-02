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
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum invoices needed to build a reliable posting profile
MIN_INVOICES_FOR_PROFILE = 3
# Max invoices to analyze per vendor (recent history)
MAX_INVOICES_PER_VENDOR = 200
# Max invoices to fetch lines for (balance between depth and BC API load)
MAX_LINE_SAMPLE = 75


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

    # Tax patterns (invoice-level)
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

    # 3. Analyze line items — sample up to MAX_LINE_SAMPLE invoices
    sample_size = min(len(invoices), MAX_LINE_SAMPLE)
    sample_invoices = invoices[:sample_size]
    all_lines = []
    line_type_counts = defaultdict(int)
    gl_account_counts = defaultdict(int)
    item_counts = defaultdict(int)
    description_patterns = defaultdict(int)
    uom_counts = defaultdict(int)
    tax_code_counts = defaultdict(int)
    line_amounts = []
    lines_per_invoice = []
    ref_pattern_counts = defaultdict(int)
    description2_patterns = defaultdict(int)
    # Track per-invoice item choices for consistency scoring
    per_invoice_items = []
    per_invoice_line_types = []
    # Track Charge-type lines separately
    charge_item_counts = defaultdict(int)

    for inv in sample_invoices:
        inv_id = inv.get("id")
        if not inv_id:
            continue
        try:
            lines = await bc_service.get_purchase_invoice_lines(inv_id)
            lines_per_invoice.append(len(lines))
            inv_items = []
            inv_line_types = []
            for line in lines:
                all_lines.append(line)
                line_type = line.get("lineType", "unknown")
                line_type_counts[line_type] += 1
                inv_line_types.append(line_type)
                # BC uses lineObjectNumber for both GL accounts and item numbers
                obj_no = line.get("lineObjectNumber", "")
                if obj_no:
                    if line_type == "Account":
                        gl_account_counts[obj_no] += 1
                    elif line_type == "Item":
                        item_counts[obj_no] += 1
                        inv_items.append(obj_no)
                    elif line_type == "Charge":
                        charge_item_counts[obj_no] += 1
                desc = line.get("description", "")
                desc2 = line.get("description2", "")
                if desc:
                    # Normalize description for pattern detection
                    desc_norm = desc.strip().upper()[:50]
                    description_patterns[desc_norm] += 1
                    # Classify the description pattern
                    _classify_description_ref(desc, ref_pattern_counts)
                if desc2:
                    description2_patterns[desc2.strip().upper()[:50]] += 1
                # Track unit of measure patterns
                uom = line.get("unitOfMeasureCode", "")
                if uom:
                    uom_counts[uom] += 1
                # Track tax codes (line-level — distinct from invoice-level tax)
                tax_code = line.get("taxCode", "")
                if tax_code:
                    tax_code_counts[tax_code] += 1
                # Track line amounts (BC uses netAmount, not lineAmount)
                line_amt = line.get("netAmount") or line.get("lineAmount") or line.get("unitCost", 0)
                if isinstance(line_amt, (int, float)) and line_amt > 0:
                    line_amounts.append(float(line_amt))
            per_invoice_items.append(tuple(sorted(inv_items)))
            per_invoice_line_types.append(tuple(sorted(inv_line_types)))
        except Exception as e:
            logger.debug("Failed to get lines for PI %s: %s", inv_id, str(e))

    result["lines_analyzed"] = len(all_lines)
    result["invoices_with_lines_analyzed"] = len(lines_per_invoice)

    # Line item patterns
    total_lines = sum(line_type_counts.values()) or 1
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
        "charge_items": dict(sorted(charge_item_counts.items(), key=lambda x: -x[1])[:5]),
        "top_descriptions": dict(sorted(description_patterns.items(), key=lambda x: -x[1])[:15]),
        "uom_distribution": dict(sorted(uom_counts.items(), key=lambda x: -x[1])[:5]),
        "tax_code_distribution": dict(sorted(tax_code_counts.items(), key=lambda x: -x[1])[:5]),
        "line_amount_stats": {
            "mean": round(statistics.mean(line_amounts), 2) if line_amounts else 0,
            "median": round(statistics.median(line_amounts), 2) if line_amounts else 0,
            "min": round(min(line_amounts), 2) if line_amounts else 0,
            "max": round(max(line_amounts), 2) if line_amounts else 0,
        } if line_amounts else {},
        "reference_in_description": dict(ref_pattern_counts),
        "description2_values": dict(sorted(description2_patterns.items(), key=lambda x: -x[1])[:10]),
    }

    # 4. Consistency scoring — how predictable is this vendor?
    result["consistency"] = _compute_consistency(
        per_invoice_items, per_invoice_line_types, lines_per_invoice,
        item_counts, gl_account_counts, total_lines,
        ref_pattern_counts, uom_counts, tax_code_counts, line_amounts,
    )

    # 5. Build the posting template (what the auto-post should do)
    result["posting_template"] = _build_posting_template(result)
    result["status"] = "analyzed"

    # 6. Store in DB
    await db.posting_pattern_analysis.update_one(
        {"vendor_no": vendor_no},
        {"$set": result},
        upsert=True,
    )

    return result


def _classify_description_ref(desc: str, ref_counts: Dict[str, int]):
    """Classify the reference pattern in a line description."""
    upper = desc.strip().upper()
    # "FREIGHT 49611" pattern
    if re.match(r'^FREIGHT\s+[A-Z0-9]{3,}', upper):
        ref_counts["freight_prefix_plus_ref"] += 1
        return
    # "PO 12345" or "PO#12345" pattern
    if re.match(r'^PO[#\s]+\d+', upper):
        ref_counts["po_prefix_plus_ref"] += 1
        return
    # "W110700" — order number starting with letter
    if re.match(r'^[A-Z]\d{4,}', upper):
        ref_counts["order_number_ref"] += 1
        return
    # Pure numeric reference "46133"
    if re.match(r'^\d{4,7}$', upper):
        ref_counts["bol_in_description"] += 1
        return
    # "INV 12345" or "INVOICE 12345"
    if re.match(r'^INV(OICE)?\s*#?\s*\d+', upper):
        ref_counts["invoice_ref_in_description"] += 1
        return
    # Any other string containing a numeric reference
    ref_match = re.search(r'[A-Z]?\d{4,7}', upper)
    if ref_match:
        ref_counts["embedded_ref"] += 1
        return
    # Descriptive text only (no reference number)
    if upper:
        ref_counts["descriptive_text_only"] += 1


def _compute_consistency(
    per_invoice_items, per_invoice_line_types, lines_per_invoice,
    item_counts, gl_account_counts, total_lines,
    ref_pattern_counts, uom_counts, tax_code_counts, line_amounts,
) -> Dict[str, Any]:
    """
    Compute a consistency score across 8 dimensions.
    High consistency = very predictable, safe to auto-post.

    Dimensions (weighted):
      1. line_count (15%)     — same # of lines every time?
      2. item_choice (20%)    — same item combo every time?
      3. line_type (10%)      — always Item / always Account?
      4. item_dominance (15%) — one clear winner item/GL?
      5. amount_tightness (10%) — coefficient of variation (stdev/mean)
      6. ref_coverage (10%)   — % of lines with structured reference numbers
      7. tax_uniformity (10%) — always same tax code?
      8. uom_uniformity (10%) — always same unit of measure?
    """
    scores = {}

    # 1. Line count consistency — do they always have the same # of lines?
    if lines_per_invoice and len(lines_per_invoice) > 1:
        most_common_count = max(set(lines_per_invoice), key=lines_per_invoice.count)
        same_count = sum(1 for c in lines_per_invoice if c == most_common_count)
        scores["line_count"] = round(same_count / len(lines_per_invoice), 3)
    elif lines_per_invoice:
        scores["line_count"] = 1.0
    else:
        scores["line_count"] = 0

    # 2. Item choice consistency — do they always use the same item combo?
    if per_invoice_items:
        non_empty = [t for t in per_invoice_items if t]
        if non_empty:
            most_common_combo = max(set(non_empty), key=non_empty.count)
            same_items = sum(1 for t in non_empty if t == most_common_combo)
            scores["item_choice"] = round(same_items / len(non_empty), 3)
        else:
            scores["item_choice"] = 0
    else:
        scores["item_choice"] = 0

    # 3. Line type consistency — always Item? Always Account? Mixed?
    if per_invoice_line_types:
        non_empty = [t for t in per_invoice_line_types if t]
        if non_empty:
            most_common_type = max(set(non_empty), key=non_empty.count)
            same_type = sum(1 for t in non_empty if t == most_common_type)
            scores["line_type"] = round(same_type / len(non_empty), 3)
        else:
            scores["line_type"] = 0
    else:
        scores["line_type"] = 0

    # 4. Dominant item/GL concentration — is there one clear winner?
    if item_counts:
        top_count = max(item_counts.values())
        total_item_lines = sum(item_counts.values()) or 1
        scores["item_dominance"] = round(top_count / total_item_lines, 3)
    elif gl_account_counts:
        top_count = max(gl_account_counts.values())
        total_gl_lines = sum(gl_account_counts.values()) or 1
        scores["item_dominance"] = round(top_count / total_gl_lines, 3)
    else:
        scores["item_dominance"] = 0

    # 5. Amount tightness — low coefficient of variation = tight range
    # CV < 0.3 = very tight (score ~1.0), CV > 1.5 = wild (score ~0.0)
    if line_amounts and len(line_amounts) > 1:
        mean_amt = statistics.mean(line_amounts)
        stdev_amt = statistics.stdev(line_amounts)
        cv = stdev_amt / mean_amt if mean_amt > 0 else 999
        # Map CV to 0-1 score: CV=0 → 1.0, CV=0.3 → 0.8, CV=1.0 → 0.3, CV=2.0 → 0.0
        scores["amount_tightness"] = round(max(0, min(1, 1.0 - (cv * 0.5))), 3)
    elif line_amounts:
        scores["amount_tightness"] = 1.0
    else:
        scores["amount_tightness"] = 0

    # 6. Reference coverage — % of lines that have ANY structured reference
    total_refs = sum(ref_pattern_counts.values())
    # Exclude "descriptive_text_only" — that's the absence of a reference
    structured_refs = total_refs - ref_pattern_counts.get("descriptive_text_only", 0)
    if total_lines > 0:
        scores["ref_coverage"] = round(structured_refs / total_lines, 3)
    else:
        scores["ref_coverage"] = 0

    # 7. Tax code uniformity — do they always use the same tax code?
    if tax_code_counts:
        top_tax = max(tax_code_counts.values())
        total_tax_lines = sum(tax_code_counts.values()) or 1
        scores["tax_uniformity"] = round(top_tax / total_tax_lines, 3)
    else:
        # No tax codes at all = perfectly uniform (they never use tax codes)
        scores["tax_uniformity"] = 1.0

    # 8. UOM uniformity — always same unit of measure?
    if uom_counts:
        top_uom = max(uom_counts.values())
        total_uom_lines = sum(uom_counts.values()) or 1
        scores["uom_uniformity"] = round(top_uom / total_uom_lines, 3)
    else:
        scores["uom_uniformity"] = 1.0

    # Overall consistency — weighted average across all 8 dimensions
    weights = {
        "line_count": 0.15,
        "item_choice": 0.20,
        "line_type": 0.10,
        "item_dominance": 0.15,
        "amount_tightness": 0.10,
        "ref_coverage": 0.10,
        "tax_uniformity": 0.10,
        "uom_uniformity": 0.10,
    }
    overall = sum(scores.get(k, 0) * w for k, w in weights.items())
    scores["overall"] = round(overall, 3)

    return scores


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

    # Tax handling — cross-reference invoice-level and line-level
    tp = analysis.get("tax_pattern", {})
    line_tax_codes = analysis.get("line_patterns", {}).get("tax_code_distribution", {})
    if tp.get("invoices_with_tax", 0) > tp.get("invoices_without_tax", 0):
        template["tax_handling"] = "taxable"
        template["typical_tax_rate"] = tp.get("tax_rate_typical", 0)
    else:
        template["tax_handling"] = "no_tax"
    # Note line-level tax codes even when invoice tax is $0
    if line_tax_codes:
        top_tax_code = max(line_tax_codes, key=line_tax_codes.get)
        total_tax_lines = sum(line_tax_codes.values()) or 1
        template["line_tax_code"] = {
            "code": top_tax_code,
            "usage_rate": round(line_tax_codes[top_tax_code] / total_tax_lines, 2),
            "note": "Line-level tax code assigned even though invoice-level tax may be $0"
            if tp.get("invoices_with_tax", 0) == 0 and line_tax_codes else "",
        }

    # Build line templates — ALL items and GL accounts with usage rates
    line_types = analysis.get("line_patterns", {}).get("line_types", {})
    gl_accounts = analysis.get("line_patterns", {}).get("top_gl_accounts", {})
    items = analysis.get("line_patterns", {}).get("top_items", {})
    charge_items = analysis.get("line_patterns", {}).get("charge_items", {})
    total_lines = sum(line_types.values()) or 1

    # Add ALL GL account templates (sorted by usage)
    for gl, count in sorted(gl_accounts.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        if rate < 0.02:
            continue  # Skip noise (< 2% usage)
        template["line_templates"].append({
            "type": "Account",
            "account_number": gl,
            "usage_rate": rate,
            "rank": "primary" if rate >= 0.5 else "secondary" if rate >= 0.1 else "rare",
        })

    # Add ALL Item templates (sorted by usage)
    for item, count in sorted(items.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        if rate < 0.02:
            continue
        template["line_templates"].append({
            "type": "Item",
            "item_number": item,
            "usage_rate": rate,
            "rank": "primary" if rate >= 0.5 else "secondary" if rate >= 0.1 else "rare",
        })

    # Add Charge-type templates
    for charge, count in sorted(charge_items.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        if rate < 0.02:
            continue
        template["line_templates"].append({
            "type": "Charge",
            "item_number": charge,
            "usage_rate": rate,
            "rank": "secondary",
        })

    # UOM
    uom = analysis.get("line_patterns", {}).get("uom_distribution", {})
    if uom:
        template["uom"] = max(uom, key=uom.get)

    # Confidence — consistency-weighted with hard floors
    # No path to HIGH without ≥50% consistency. No free rides on volume alone.
    inv_count = analysis.get("invoices_analyzed", 0)
    lines_count = analysis.get("lines_analyzed", 0)
    consistency = analysis.get("consistency", {}).get("overall", 0)

    # HIGH: requires BOTH sufficient data AND consistent patterns
    if consistency >= 0.5 and (
        (inv_count >= 30 and lines_count >= 25 and consistency >= 0.8) or
        (inv_count >= 50 and lines_count >= 40 and consistency >= 0.6) or
        (inv_count >= 100 and lines_count >= 50 and consistency >= 0.5)
    ):
        template["confidence"] = "high"
    # MEDIUM: reasonable data with some consistency, OR lots of data but messy
    elif (inv_count >= 10 and lines_count >= 8 and consistency >= 0.4) or \
         (inv_count >= 20 and lines_count >= 15 and consistency >= 0.3) or \
         (inv_count >= 50 and lines_count >= 30):
        template["confidence"] = "medium"
    else:
        template["confidence"] = "low"

    template["consistency_score"] = consistency

    # Reference number pattern — how humans put BOL/order refs on lines
    ref_patterns = analysis.get("line_patterns", {}).get("reference_in_description", {})
    desc2_values = analysis.get("line_patterns", {}).get("description2_values", {})
    if ref_patterns:
        total_refs = sum(ref_patterns.values())
        # Sort by frequency, build a ranked pattern list
        sorted_patterns = sorted(ref_patterns.items(), key=lambda x: -x[1])
        dominant_pattern = sorted_patterns[0][0]
        template["reference_handling"] = {
            "pattern": dominant_pattern,
            "usage_rate": round(total_refs / total_lines, 2),
            "description": _describe_ref_pattern(dominant_pattern),
            "all_patterns": {
                p: {"count": c, "rate": round(c / total_refs, 2)}
                for p, c in sorted_patterns
            },
            "lines_with_reference": total_refs,
            "lines_without_reference": total_lines - total_refs,
        }
    if desc2_values:
        template["description2_usage"] = {
            "has_data": True,
            "top_values": list(desc2_values.keys())[:5],
            "description": "description2 field carries additional reference data",
        }

    return template


def _describe_ref_pattern(pattern: str) -> str:
    """Human-readable description of a reference pattern."""
    descriptions = {
        "freight_prefix_plus_ref": "Human types 'FREIGHT' followed by BOL/reference number (e.g., 'FREIGHT 49611')",
        "bol_in_description": "Human types the BOL/reference number directly as the description (e.g., '46133')",
        "order_number_ref": "Human types an order/work number starting with a letter (e.g., 'W110700')",
        "po_prefix_plus_ref": "Human types 'PO' followed by PO number (e.g., 'PO 12345')",
        "invoice_ref_in_description": "Human types invoice reference in description (e.g., 'INV 12345')",
        "embedded_ref": "Reference number embedded within longer description text",
        "descriptive_text_only": "Free-form description without a structured reference number",
    }
    return descriptions.get(pattern, f"Pattern: {pattern}")


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
                    "consistency": analysis.get("consistency", {}).get("overall", 0),
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
