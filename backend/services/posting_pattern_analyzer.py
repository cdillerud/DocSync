"""
GPI Document Hub — BC Posting Pattern Analyzer

"Work backwards from BC": Query how humans have posted invoices to BC,
extract patterns, and build vendor-specific posting profiles that teach
the auto-post system to replicate human behavior.

Collections:
  - vendor_posting_profiles: Learned posting patterns per vendor
  - posting_pattern_analysis: Raw analysis results from BC queries
"""
import asyncio
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
# Page size for BC API pagination
BC_PAGE_SIZE = 500
# Sleep between line fetches to avoid BC API throttling (seconds)
LINE_FETCH_DELAY = 0.1


async def analyze_vendor_posting_patterns(
    db, bc_service, vendor_no: str, limit: int = 0
) -> Dict[str, Any]:
    """
    Analyze how humans post invoices for a specific vendor in BC.
    Pulls from ALL sources: purchaseInvoices (all statuses) AND
    postedPurchaseInvoices (historical). No artificial caps — if there
    are 5 years and 2,000 invoices, we eat them all.
    """
    result = {
        "vendor_no": vendor_no,
        "analyzed_at": datetime.now(timezone.utc).isoformat(),
        "invoices_analyzed": 0,
        "lines_analyzed": 0,
    }

    # 1a. Paginate through ALL purchase invoices (all statuses) for this vendor
    invoices = []
    seen_ids = set()
    skip = 0
    pi_error = None
    while True:
        page_size = min(BC_PAGE_SIZE, limit - len(invoices)) if limit > 0 else BC_PAGE_SIZE
        if page_size <= 0:
            break
        try:
            pi_result = await bc_service.get_posted_purchase_invoices(
                vendor_id=vendor_no, limit=page_size, skip=skip
            )
        except Exception as e:
            logger.warning("[PostingPatterns] %s: BC purchaseInvoices fetch failed: %s", vendor_no, str(e))
            pi_error = str(e)
            break
        page = pi_result.get("invoices", [])
        if not page:
            break
        for inv in page:
            inv_id = inv.get("id", "")
            if inv_id and inv_id not in seen_ids:
                seen_ids.add(inv_id)
                inv["_source"] = "purchaseInvoices"
                invoices.append(inv)
        logger.info("[PostingPatterns] %s: fetched page %d from purchaseInvoices (%d invoices so far)",
                     vendor_no, skip // BC_PAGE_SIZE + 1, len(invoices))
        if len(page) < page_size:
            break  # Last page
        skip += len(page)
        if limit > 0 and len(invoices) >= limit:
            break

    # 1b. Also paginate through historical posted purchase invoices
    historical_count = 0
    skip = 0
    historical_source = None
    while True:
        remaining = (limit - len(invoices)) if limit > 0 else BC_PAGE_SIZE
        if remaining <= 0:
            break
        page_size = min(BC_PAGE_SIZE, remaining)
        try:
            hist_result = await bc_service.get_historical_posted_purchase_invoices(
                vendor_id=vendor_no, limit=page_size, skip=skip
            )
        except Exception as e:
            logger.warning("[PostingPatterns] %s: historical PI fetch failed: %s", vendor_no, str(e))
            break
        page = hist_result.get("invoices", [])
        if historical_source is None:
            historical_source = hist_result.get("source", "none_available")
        if not page:
            break
        for inv in page:
            inv_id = inv.get("id", "")
            if inv_id and inv_id not in seen_ids:
                seen_ids.add(inv_id)
                inv["_source"] = hist_result.get("source", "postedPurchaseInvoices")
                invoices.append(inv)
                historical_count += 1
        logger.info("[PostingPatterns] %s: fetched page %d from historical PIs (+%d new, %d total)",
                     vendor_no, skip // BC_PAGE_SIZE + 1, historical_count, len(invoices))
        if len(page) < page_size:
            break
        skip += len(page)
        if limit > 0 and len(invoices) >= limit:
            break

    if historical_count > 0:
        logger.info("[PostingPatterns] %s: merged %d historical invoices (source: %s). Total dataset: %d",
                     vendor_no, historical_count, historical_source, len(invoices))

    if not invoices:
        result["status"] = "no_invoices"
        result["error"] = pi_error or (pi_result.get("error") if 'pi_result' in dir() else None)
        return result

    result["data_sources"] = {
        "purchase_invoices": len(invoices) - historical_count,
        "historical_posted": historical_count,
        "historical_source": historical_source or "not_queried",
        "total": len(invoices),
    }

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

    # 3. Analyze line items from ALL invoices — no sampling, no caps
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
    # Per-item metadata: descriptions, quantities, costs, UOMs
    item_metadata = defaultdict(lambda: {
        "descriptions": defaultdict(int), "quantities": [], "unit_costs": [],
        "uoms": defaultdict(int), "tax_codes": defaultdict(int),
        "line_type": None, "appearances": 0,
        "invoices_present_on": set(),  # Track which invoices this item appears on
        "amount_as_pct_of_total": [],  # Item amount / invoice total — for identifying value carriers
    })
    # Comment line tracking
    comment_descriptions = defaultdict(int)
    comment_count_per_invoice = []

    # Track statuses seen for data-source auditing
    statuses_seen = defaultdict(int)

    for idx, inv in enumerate(invoices):
        inv_id = inv.get("id")
        if not inv_id:
            continue
        inv_status = inv.get("status", "unknown")
        statuses_seen[inv_status] += 1
        try:
            # Use appropriate line-fetch method based on data source
            inv_source = inv.get("_source", "purchaseInvoices")
            if inv_source and inv_source != "purchaseInvoices" and inv_source != "none_available":
                lines = await bc_service.get_historical_invoice_lines(inv_id, source=inv_source)
            else:
                lines = await bc_service.get_purchase_invoice_lines(inv_id)
            lines_per_invoice.append(len(lines))
            inv_items = []
            inv_line_types = []
            inv_comment_count = 0
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
                # Track per-item metadata for template enrichment
                if obj_no and line_type in ("Item", "Account", "Charge"):
                    meta = item_metadata[obj_no]
                    meta["appearances"] += 1
                    meta["line_type"] = line_type
                    meta["invoices_present_on"].add(idx)  # Track per-invoice presence
                    desc = line.get("description", "")
                    if desc:
                        meta["descriptions"][desc.strip()] += 1
                    qty = line.get("quantity", 0)
                    if isinstance(qty, (int, float)):
                        meta["quantities"].append(qty)
                    uc = line.get("unitCost", 0)
                    if isinstance(uc, (int, float)):
                        meta["unit_costs"].append(uc)
                    # Track what % of invoice total this line represents
                    inv_total = inv.get("totalAmountExcludingTax") or inv.get("totalAmountIncludingTax", 0) or 1
                    line_net = line.get("netAmount") or line.get("lineAmount") or 0
                    if isinstance(line_net, (int, float)) and isinstance(inv_total, (int, float)) and inv_total > 0:
                        meta["amount_as_pct_of_total"].append(round(line_net / inv_total, 4))
                    line_uom = line.get("unitOfMeasureCode", "")
                    if line_uom:
                        meta["uoms"][line_uom] += 1
                    line_tc = line.get("taxCode", "")
                    if line_tc:
                        meta["tax_codes"][line_tc] += 1
                # Track Comment lines
                if line_type == "Comment":
                    inv_comment_count += 1
                    cdesc = line.get("description", "").strip()
                    if cdesc:
                        comment_descriptions[cdesc] += 1
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
            comment_count_per_invoice.append(inv_comment_count)
        except Exception as e:
            logger.debug("Failed to get lines for PI %s: %s", inv_id, str(e))

        # Throttle to avoid BC API rate limits + log progress every 50 invoices
        if idx > 0 and idx % 50 == 0:
            logger.info("[PostingPatterns] %s: analyzed lines for %d/%d invoices (%d lines so far)",
                         vendor_no, idx, len(invoices), len(all_lines))
        await asyncio.sleep(LINE_FETCH_DELAY)

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

    # Build per-item metadata summary for template enrichment
    item_meta_summary = {}
    total_invoices = len(lines_per_invoice) or 1
    for item_no, meta in item_metadata.items():
        descs = meta["descriptions"]
        qtys = meta["quantities"]
        costs = meta["unit_costs"]
        pct_of_totals = meta["amount_as_pct_of_total"]
        top_desc = max(descs, key=descs.get) if descs else ""
        top_uom = max(meta["uoms"], key=meta["uoms"].get) if meta["uoms"] else ""
        top_tc = max(meta["tax_codes"], key=meta["tax_codes"].get) if meta["tax_codes"] else ""
        is_zero_cost = sum(1 for c in costs if c == 0) >= len(costs) * 0.90 if costs else True
        typical_qty = round(statistics.median(qtys), 2) if qtys else 0
        typical_cost = round(statistics.median(costs), 2) if costs else 0
        unique_descs = len(descs)
        invoices_present = len(meta["invoices_present_on"])
        invoice_presence_rate = round(invoices_present / total_invoices, 3)

        # Amount variability (coefficient of variation)
        if costs and len(costs) > 1:
            cost_mean = statistics.mean(costs)
            cost_stdev = statistics.stdev(costs)
            amount_cv = round(cost_stdev / max(cost_mean, 0.01), 3)
        else:
            amount_cv = 0

        # Typical % of invoice total this item represents
        typical_pct_of_total = round(statistics.median(pct_of_totals), 4) if pct_of_totals else 0

        # Structural classification:
        # "structural_constant" — appears on >70% of invoices with consistent description
        # "variable_product"   — appears frequently but with many unique SKUs/descriptions
        # "surcharge"          — non-zero cost but small % of total (<10%)
        # "structural_zero"    — always present, always $0 (packaging/tracking)
        # "optional"           — appears on <50% of invoices
        if invoice_presence_rate >= 0.70:
            if is_zero_cost:
                slot_type = "structural_zero"
            elif unique_descs > 10 and typical_pct_of_total > 0.3:
                slot_type = "variable_product"
            elif typical_pct_of_total < 0.10 and not is_zero_cost:
                slot_type = "surcharge"
            elif unique_descs <= 3:
                slot_type = "structural_constant"
            else:
                slot_type = "structural_variable"
        elif invoice_presence_rate >= 0.30:
            if unique_descs > 5 and typical_pct_of_total > 0.3:
                slot_type = "variable_product"
            else:
                slot_type = "frequent"
        else:
            slot_type = "optional"

        item_meta_summary[item_no] = {
            "common_description": top_desc,
            "typical_qty": typical_qty,
            "typical_unit_cost": typical_cost,
            "is_zero_cost": is_zero_cost,
            "uom": top_uom,
            "tax_code": top_tc,
            "line_type": meta["line_type"],
            "appearances": meta["appearances"],
            "unique_descriptions": unique_descs,
            "invoice_presence_rate": invoice_presence_rate,
            "amount_cv": amount_cv,
            "typical_pct_of_total": typical_pct_of_total,
            "slot_type": slot_type,
        }
    result["line_patterns"]["item_metadata"] = item_meta_summary

    # Comment line patterns
    typical_comments = round(statistics.median(comment_count_per_invoice), 0) if comment_count_per_invoice else 0
    result["line_patterns"]["comment_patterns"] = {
        "total_comments": sum(comment_count_per_invoice),
        "typical_per_invoice": int(typical_comments),
        "top_descriptions": dict(sorted(comment_descriptions.items(), key=lambda x: -x[1])[:10]),
    }

    # 4. Consistency scoring — how predictable is this vendor?
    result["consistency"] = _compute_consistency(
        per_invoice_items, per_invoice_line_types, lines_per_invoice,
        item_counts, gl_account_counts, total_lines,
        ref_pattern_counts, uom_counts, tax_code_counts, line_amounts,
    )

    # 4b. Status distribution — what statuses are in the learning dataset?
    result["status_distribution"] = dict(statuses_seen)

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
    Compute a STRUCTURAL consistency score — how predictably does the
    human construct invoices for this vendor?

    Key insight: FREIGHT-DS vs FREIGHT-WH are not "inconsistency" — they're
    contextual routing variants of the same FREIGHT family. The system should
    score family consistency (always freight?) separately from exact item
    choice (always FREIGHT-DS specifically?).

    Dimensions (weighted for structural format):
      1. line_count (18%)              — same # of lines every time
      2. item_family (20%)             — always same item FAMILY (FREIGHT-*, etc.)
      3. item_dominance (12%)          — one clear primary item within family
      4. line_type (10%)               — always Item / always Account
      5. ref_pattern_uniformity (15%)  — same description format every time
      6. tax_uniformity (10%)          — always same tax code
      7. uom_uniformity (10%)          — always same unit of measure
      8. ref_coverage (5%)             — lines with structured reference #

    NOT weighted (informational only):
      - amount_tightness — dollar variability doesn't affect posting structure
      - exact_item_choice — tracked but item_family is what matters
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

    # 2. Item FAMILY consistency — group items by prefix
    # FREIGHT-DS, FREIGHT-WH, FREIGHT-INTL → all "FREIGHT" family
    # 5100-010, 5100-020 → all "5100" family
    all_items = {**item_counts, **gl_account_counts}
    if all_items:
        family_counts = defaultdict(int)
        for item_code, count in all_items.items():
            family = _extract_item_family(item_code)
            family_counts[family] += count
        total_item_lines = sum(family_counts.values()) or 1
        top_family_count = max(family_counts.values())
        scores["item_family"] = round(top_family_count / total_item_lines, 3)
        scores["item_families_seen"] = dict(family_counts)
    else:
        scores["item_family"] = 0
        scores["item_families_seen"] = {}

    # Also track exact item choice (informational, not in overall)
    if per_invoice_items:
        non_empty = [t for t in per_invoice_items if t]
        if non_empty:
            most_common_combo = max(set(non_empty), key=non_empty.count)
            same_items = sum(1 for t in non_empty if t == most_common_combo)
            scores["exact_item_choice"] = round(same_items / len(non_empty), 3)
        else:
            scores["exact_item_choice"] = 0
    else:
        scores["exact_item_choice"] = 0

    # 3. Item dominance — within the family, is there one clear primary?
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

    # 4. Line type consistency — always Item? Always Account? Mixed?
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

    # 5. Amount tightness — informational only, NOT weighted
    if line_amounts and len(line_amounts) > 1:
        mean_amt = statistics.mean(line_amounts)
        stdev_amt = statistics.stdev(line_amounts)
        cv = stdev_amt / mean_amt if mean_amt > 0 else 999
        scores["amount_tightness"] = round(max(0, min(1, 1.0 - (cv * 0.5))), 3)
    elif line_amounts:
        scores["amount_tightness"] = 1.0
    else:
        scores["amount_tightness"] = 0

    # 6. Reference pattern uniformity — same description FORMAT every time
    total_refs = sum(ref_pattern_counts.values())
    if total_refs > 0:
        top_ref_pattern_count = max(ref_pattern_counts.values())
        scores["ref_pattern_uniformity"] = round(top_ref_pattern_count / total_refs, 3)
        structured_refs = total_refs - ref_pattern_counts.get("descriptive_text_only", 0)
        scores["ref_coverage"] = round(structured_refs / max(total_lines, 1), 3)
    else:
        scores["ref_pattern_uniformity"] = 0
        scores["ref_coverage"] = 0

    # 7. Tax code uniformity — always same tax code?
    if tax_code_counts:
        top_tax = max(tax_code_counts.values())
        total_tax_lines = sum(tax_code_counts.values()) or 1
        scores["tax_uniformity"] = round(top_tax / total_tax_lines, 3)
    else:
        scores["tax_uniformity"] = 1.0

    # 8. UOM uniformity — always same unit of measure?
    if uom_counts:
        top_uom = max(uom_counts.values())
        total_uom_lines = sum(uom_counts.values()) or 1
        scores["uom_uniformity"] = round(top_uom / total_uom_lines, 3)
    else:
        scores["uom_uniformity"] = 1.0

    # Overall consistency — STRUCTURAL FORMAT ONLY
    # "Does the human always build the invoice the same WAY?"
    # Item family > exact item. Dollar amounts excluded.
    weights = {
        "line_count": 0.18,
        "item_family": 0.20,
        "item_dominance": 0.12,
        "line_type": 0.10,
        "ref_pattern_uniformity": 0.15,
        "tax_uniformity": 0.10,
        "uom_uniformity": 0.10,
        "ref_coverage": 0.05,
    }
    overall = sum(scores.get(k, 0) * w for k, w in weights.items())
    scores["overall"] = round(overall, 3)

    return scores


def _extract_item_family(item_code: str) -> str:
    """
    Extract the family/category from an item code.
    FREIGHT-DS, FREIGHT-WH, FREIGHT-INTL → "FREIGHT"
    5100-010, 5100-020 → "5100"
    PALLET-48x40, PALLET-48x48 → "PALLET"
    """
    code = item_code.strip().upper()
    # Split on common delimiters: dash, period, space
    for delim in ['-', '.', ' ']:
        if delim in code:
            return code.split(delim)[0]
    # If no delimiter, try to split at the boundary of letters→digits
    match = re.match(r'^([A-Z]+)', code)
    if match and len(match.group(1)) >= 2:
        return match.group(1)
    # No clear family — the whole code IS the family
    return code


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
    item_meta = analysis.get("line_patterns", {}).get("item_metadata", {})
    total_lines = sum(line_types.values()) or 1

    # Add ALL GL account templates (sorted by usage)
    for gl, count in sorted(gl_accounts.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        if rate < 0.02:
            continue  # Skip noise (< 2% usage)
        meta = item_meta.get(gl, {})
        template["line_templates"].append({
            "type": "Account",
            "account_number": gl,
            "usage_rate": rate,
            "rank": "primary" if rate >= 0.5 else "secondary" if rate >= 0.1 else "rare",
            "slot_type": meta.get("slot_type", "unknown"),
            "common_description": meta.get("common_description", ""),
            "typical_qty": meta.get("typical_qty", 1),
            "typical_unit_cost": meta.get("typical_unit_cost", 0),
            "is_zero_cost": meta.get("is_zero_cost", False),
            "uom": meta.get("uom", ""),
            "tax_code": meta.get("tax_code", ""),
            "unique_descriptions": meta.get("unique_descriptions", 0),
            "invoice_presence_rate": meta.get("invoice_presence_rate", 0),
            "amount_cv": meta.get("amount_cv", 0),
            "typical_pct_of_total": meta.get("typical_pct_of_total", 0),
        })

    # Add ALL Item templates (sorted by usage)
    # Use per-invoice appearance rate, not just per-line rate, to avoid
    # filtering out structural items like Z-POP that appear on many invoices
    # but are a small % of total lines
    inv_count = analysis.get("invoices_analyzed", 0) or 1
    for item, count in sorted(items.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        meta = item_meta.get(item, {})
        per_invoice_rate = meta.get("appearances", count) / inv_count
        # Include if >2% of lines OR appears on >10% of invoices
        if rate < 0.02 and per_invoice_rate < 0.10:
            continue
        template["line_templates"].append({
            "type": "Item",
            "item_number": item,
            "usage_rate": rate,
            "rank": "primary" if rate >= 0.5 else "secondary" if rate >= 0.1 else "rare",
            "slot_type": meta.get("slot_type", "unknown"),
            "common_description": meta.get("common_description", ""),
            "typical_qty": meta.get("typical_qty", 1),
            "typical_unit_cost": meta.get("typical_unit_cost", 0),
            "is_zero_cost": meta.get("is_zero_cost", False),
            "uom": meta.get("uom", ""),
            "tax_code": meta.get("tax_code", ""),
            "unique_descriptions": meta.get("unique_descriptions", 0),
            "invoice_presence_rate": meta.get("invoice_presence_rate", 0),
            "amount_cv": meta.get("amount_cv", 0),
            "typical_pct_of_total": meta.get("typical_pct_of_total", 0),
            "per_invoice_rate": round(per_invoice_rate, 3),
        })

    # Add Charge-type templates
    for charge, count in sorted(charge_items.items(), key=lambda x: -x[1]):
        rate = round(count / total_lines, 3)
        if rate < 0.02:
            continue
        meta = item_meta.get(charge, {})
        template["line_templates"].append({
            "type": "Charge",
            "item_number": charge,
            "usage_rate": rate,
            "rank": "secondary",
            "common_description": meta.get("common_description", ""),
            "typical_qty": meta.get("typical_qty", 1),
            "typical_unit_cost": meta.get("typical_unit_cost", 0),
            "is_zero_cost": meta.get("is_zero_cost", False),
            "uom": meta.get("uom", ""),
            "tax_code": meta.get("tax_code", ""),
        })

    # Add Comment line template if vendor commonly uses comments
    comment_patterns = analysis.get("line_patterns", {}).get("comment_patterns", {})
    typical_comments = comment_patterns.get("typical_per_invoice", 0)
    if typical_comments > 0:
        template["comment_lines"] = {
            "typical_count": typical_comments,
            "top_descriptions": list(comment_patterns.get("top_descriptions", {}).keys())[:5],
        }

    # Build variability profile — the AI's understanding of invoice structure
    # This answers: "What's always the same? What changes? What's the skeleton?"
    slot_type_groups = defaultdict(list)
    for lt in template["line_templates"]:
        st = lt.get("slot_type", "unknown")
        item_id = lt.get("item_number") or lt.get("account_number", "")
        slot_type_groups[st].append({
            "item": item_id,
            "description": lt.get("common_description", ""),
            "presence_rate": lt.get("invoice_presence_rate", 0),
            "pct_of_total": lt.get("typical_pct_of_total", 0),
            "amount_cv": lt.get("amount_cv", 0),
        })

    structural_items = len(slot_type_groups.get("structural_constant", [])) + \
                       len(slot_type_groups.get("structural_zero", []))
    variable_items = len(slot_type_groups.get("variable_product", []))
    surcharge_items = len(slot_type_groups.get("surcharge", []))

    template["variability_profile"] = {
        "structural_constant_items": [s["item"] for s in slot_type_groups.get("structural_constant", [])],
        "structural_zero_items": [s["item"] for s in slot_type_groups.get("structural_zero", [])],
        "variable_product_slots": [s["item"] for s in slot_type_groups.get("variable_product", [])],
        "surcharge_items": [s["item"] for s in slot_type_groups.get("surcharge", [])],
        "optional_items": [s["item"] for s in slot_type_groups.get("optional", [])],
        "frequent_items": [s["item"] for s in slot_type_groups.get("frequent", [])],
        "structural_variable_items": [s["item"] for s in slot_type_groups.get("structural_variable", [])],
        "comment_slots": typical_comments,
        "summary": (
            f"{structural_items} fixed structural items, "
            f"{variable_items} variable product slot(s), "
            f"{surcharge_items} surcharge(s), "
            f"{typical_comments} comment lines"
        ),
        "automation_assessment": (
            "FULLY AUTOMATABLE — all items are predictable" if variable_items == 0 and structural_items > 0
            else f"SEMI-AUTOMATABLE — {structural_items} fixed items can be pre-filled, "
                 f"{variable_items} product slot(s) need document data"
            if structural_items > 0
            else "MANUAL — too much variability for automation"
        ),
    }

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


async def learn_from_posting(db, vendor_no: str, doc: Dict, pi_lines: List[Dict], pi_result: Dict):
    """
    Incremental learning: update a vendor's posting profile after a
    successful purchase invoice creation. Called automatically on every
    successful BC posting — the system gets smarter with every invoice.

    This updates the raw dimensional data without re-querying all of BC.
    If no profile exists yet, it seeds a minimal one.
    """
    if not vendor_no:
        return

    now = datetime.now(timezone.utc).isoformat()

    # Extract structural features from what was just posted
    line_types = defaultdict(int)
    items_used = []
    gl_accounts_used = []
    uoms_used = []
    tax_codes_used = []
    ref_patterns_found = defaultdict(int)

    for line in (pi_lines or []):
        lt = line.get("lineType") or line.get("type", "Item")
        line_types[lt] += 1
        obj = line.get("lineObjectNumber") or line.get("item_number") or line.get("account_number", "")
        if obj:
            if lt == "Item":
                items_used.append(obj)
            elif lt == "Account":
                gl_accounts_used.append(obj)
        uom = line.get("unitOfMeasureCode") or line.get("uom", "")
        if uom:
            uoms_used.append(uom)
        tax = line.get("taxCode") or line.get("tax_code", "")
        if tax:
            tax_codes_used.append(tax)
        desc = line.get("description", "")
        if desc:
            _classify_description_ref(desc, ref_patterns_found)

    amount = 0
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    try:
        raw = ef.get("amount") or nf.get("amount") or 0
        amount = float(str(raw).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        pass

    # Build the incremental learning record
    learning_event = {
        "vendor_no": vendor_no,
        "doc_id": doc.get("id", ""),
        "posted_at": now,
        "line_count": len(pi_lines or []),
        "line_types": dict(line_types),
        "items_used": items_used,
        "gl_accounts_used": gl_accounts_used,
        "uoms": uoms_used,
        "tax_codes": tax_codes_used,
        "ref_patterns": dict(ref_patterns_found),
        "amount": amount,
        "item_families": [_extract_item_family(i) for i in items_used],
    }

    # Store the learning event for audit trail
    await db.posting_learning_events.insert_one(learning_event)

    # Update the aggregate profile incrementally
    existing = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"}, {"_id": 0}
    )

    if existing:
        # Increment counters
        inc_ops = {
            "invoices_analyzed": 1,
            "lines_analyzed": len(pi_lines or []),
            "continuous_learning_count": 1,
        }
        for lt_name, lt_count in line_types.items():
            inc_ops[f"line_patterns.line_types.{lt_name}"] = lt_count
        for item in items_used:
            inc_ops[f"line_patterns.top_items.{item}"] = 1
        for gl in gl_accounts_used:
            inc_ops[f"line_patterns.top_gl_accounts.{gl}"] = 1
        for uom in uoms_used:
            inc_ops[f"line_patterns.uom_distribution.{uom}"] = 1
        for tc in tax_codes_used:
            inc_ops[f"line_patterns.tax_code_distribution.{tc}"] = 1
        for rp, rpc in ref_patterns_found.items():
            inc_ops[f"line_patterns.reference_in_description.{rp}"] = rpc

        await db.posting_pattern_analysis.update_one(
            {"vendor_no": vendor_no, "status": "analyzed"},
            {
                "$inc": inc_ops,
                "$set": {
                    "last_learned_from": doc.get("id", ""),
                    "last_learned_at": now,
                },
            }
        )
        logger.info(
            "[PostingPatterns] Incremental learn for %s: +%d lines, items=%s",
            vendor_no, len(pi_lines or []), items_used,
        )
    else:
        # No profile yet — seed a minimal one from this single posting
        # (Full analysis will replace this next time analyze is run)
        logger.info(
            "[PostingPatterns] Seeding new profile for %s from first posting (%d lines)",
            vendor_no, len(pi_lines or []),
        )
        seed = {
            "vendor_no": vendor_no,
            "analyzed_at": now,
            "invoices_analyzed": 1,
            "lines_analyzed": len(pi_lines or []),
            "invoices_with_lines_analyzed": 1,
            "line_patterns": {
                "line_types": dict(line_types),
                "top_items": {i: 1 for i in items_used},
                "top_gl_accounts": {g: 1 for g in gl_accounts_used},
                "uom_distribution": {u: 1 for u in uoms_used},
                "tax_code_distribution": {t: 1 for t in tax_codes_used},
                "reference_in_description": dict(ref_patterns_found),
                "lines_per_invoice": {"mean": len(pi_lines or []), "median": len(pi_lines or []), "min": len(pi_lines or []), "max": len(pi_lines or [])},
            },
            "amount_stats": {"count": 1, "mean": amount, "median": amount, "min": amount, "max": amount, "stdev": 0},
            "posting_template": {"confidence": "low", "typical_line_count": len(pi_lines or [])},
            "consistency": {"overall": 0, "line_count": 0, "item_family": 0},
            "continuous_learning_count": 1,
            "last_learned_from": doc.get("id", ""),
            "last_learned_at": now,
            "status": "analyzed",
            "vendor_names_seen": [doc.get("vendor_canonical", vendor_no)],
        }
        await db.posting_pattern_analysis.update_one(
            {"vendor_no": vendor_no},
            {"$set": seed},
            upsert=True,
        )
