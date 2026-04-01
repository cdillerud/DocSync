"""
Vendor Invoice Profile Service — Learn from BC History

Queries Business Central for historical purchase invoices per vendor,
builds a profile of how that vendor's invoices are typically entered,
and uses the profile to auto-populate new PI payloads.

Profile includes:
  - Default line type (Item vs G/L Account) and object numbers
  - Common G/L accounts with frequency
  - Typical description patterns
  - Payment terms, posting groups
  - Amount statistics for deviation detection
  - Line count patterns

Usage:
    profile = await get_or_build_profile(db, "MEXUS")
    lines   = build_smart_pi_lines(doc, profile)
    flags   = detect_deviations(doc, profile)
"""

import logging
import os
import re
import statistics
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

import httpx

from services.bc_access import get_bc_adapter, BCAccessAdapter

logger = logging.getLogger(__name__)

BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
BC_READ_ENVIRONMENT = os.environ.get("BC_READ_ENVIRONMENT") or os.environ.get("BC_PROD_ENVIRONMENT", "Production")
BC_WRITE_ENVIRONMENT = os.environ.get("BC_WRITE_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "Sandbox_11_3_2025")

PROFILE_CACHE_TTL_HOURS = 24
MAX_INVOICES_TO_ANALYZE = 30


async def _bc_token_and_company(adapter: BCAccessAdapter) -> Tuple[Optional[str], Optional[str]]:
    """Get token + company ID from the shared adapter."""
    token = await adapter.get_token()
    if not token:
        return None, None
    company_id = await adapter.get_company_id(token)
    return token, company_id


async def fetch_vendor_card(vendor_no: str) -> Optional[Dict]:
    """Fetch vendor card details from BC (READ environment).
    Returns payment terms, posting group, contact info, etc.
    """
    adapter = get_bc_adapter()
    token, company_id = await _bc_token_and_company(adapter)
    if not token or not company_id:
        return None

    url = f"{BC_API_BASE}/{adapter.tenant_id}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors"
    params = {
        "$filter": f"number eq '{vendor_no}'",
        "$select": "id,number,displayName,paymentTermsId,paymentMethodId,currencyCode,taxLiable,blocked",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                vendors = resp.json().get("value", [])
                if vendors:
                    return vendors[0]
    except Exception as e:
        logger.warning("[VendorProfile] Vendor card fetch error for %s: %s", vendor_no, e)
    return None


async def fetch_vendor_payment_terms(vendor_no: str) -> Optional[Dict]:
    """Fetch the vendor's payment terms details from BC."""
    adapter = get_bc_adapter()
    token, company_id = await _bc_token_and_company(adapter)
    if not token or not company_id:
        return None

    url = f"{BC_API_BASE}/{adapter.tenant_id}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors"
    params = {
        "$filter": f"number eq '{vendor_no}'",
        "$expand": "paymentTerm",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                vendors = resp.json().get("value", [])
                if vendors:
                    pt = vendors[0].get("paymentTerm")
                    return pt
    except Exception as e:
        logger.warning("[VendorProfile] Payment terms fetch error: %s", e)
    return None


async def fetch_vendor_invoices_from_bc(
    vendor_no: str,
    environment: str = None,
    max_invoices: int = MAX_INVOICES_TO_ANALYZE,
) -> List[Dict]:
    """Fetch purchase invoices (with lines) for a vendor from BC.

    Queries BOTH the read environment for historical data and optionally
    the write environment for drafts.
    """
    adapter = get_bc_adapter()
    token, company_id = await _bc_token_and_company(adapter)
    if not token or not company_id:
        logger.warning("[VendorProfile] No BC credentials for invoice history fetch")
        return []

    env = environment or BC_READ_ENVIRONMENT
    url = f"{BC_API_BASE}/{adapter.tenant_id}/{env}/api/v2.0/companies({company_id})/purchaseInvoices"
    params = {
        "$filter": f"buyFromVendorNumber eq '{vendor_no}'",
        "$select": "id,number,vendorInvoiceNumber,buyFromVendorNumber,buyFromVendorName,postingDate,dueDate,currencyCode,totalAmountIncludingTax,totalAmountExcludingTax,status,paymentTermsId",
        "$expand": "purchaseInvoiceLines($select=id,lineType,lineObjectNumber,description,quantity,unitCost,totalAmountExcludingTax)",
        "$top": str(max_invoices),
        "$orderby": "postingDate desc",
    }

    invoices = []
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                invoices = resp.json().get("value", [])
                logger.info("[VendorProfile] Fetched %d purchase invoices for vendor %s from %s", len(invoices), vendor_no, env)
            else:
                logger.warning("[VendorProfile] BC API %d for vendor %s invoices: %s", resp.status_code, vendor_no, resp.text[:300])
    except Exception as e:
        logger.warning("[VendorProfile] BC invoice fetch error for %s: %s", vendor_no, e)

    # Also try the write environment for drafts (if different)
    if env != BC_WRITE_ENVIRONMENT:
        try:
            write_url = f"{BC_API_BASE}/{adapter.tenant_id}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.get(write_url, headers={"Authorization": f"Bearer {token}"}, params=params)
                if resp.status_code == 200:
                    write_invoices = resp.json().get("value", [])
                    if write_invoices:
                        invoices.extend(write_invoices)
                        logger.info("[VendorProfile] +%d draft invoices from write env for %s", len(write_invoices), vendor_no)
        except Exception as e:
            logger.debug("[VendorProfile] Write env invoice fetch error: %s", e)

    return invoices



async def _learn_from_reference_cache(db, vendor_no: str) -> Optional[Dict]:
    """Learn vendor patterns from the BC reference cache.
    
    The cache stores posted purchase invoices synced from BC, with fields like
    bc_amount, bc_order_number, bc_external_document_no, bc_posting_date, etc.
    When the BC API returns 0 (creds fail, timeout), the cache is our fallback.
    """
    try:
        pipeline = [
            {"$match": {"bc_vendor_no": vendor_no, "bc_entity_type": "posted_purchase_invoice"}},
            {"$group": {
                "_id": None,
                "count": {"$sum": 1},
                "total_amount": {"$sum": "$bc_amount"},
                "avg_amount": {"$avg": "$bc_amount"},
                "min_amount": {"$min": "$bc_amount"},
                "max_amount": {"$max": "$bc_amount"},
                "has_order_count": {"$sum": {
                    "$cond": [{"$and": [
                        {"$ne": ["$bc_order_number", ""]},
                        {"$ne": ["$bc_order_number", None]},
                    ]}, 1, 0]
                }},
                "has_external_doc_count": {"$sum": {
                    "$cond": [{"$and": [
                        {"$ne": ["$bc_external_document_no", ""]},
                        {"$ne": ["$bc_external_document_no", None]},
                    ]}, 1, 0]
                }},
            }},
        ]
        results = await db.bc_reference_cache.aggregate(pipeline).to_list(length=1)
        if not results:
            return None
        
        s = results[0]
        count = s["count"]
        po_rate = s["has_order_count"] / count if count > 0 else 0
        
        return {
            "count": count,
            "po_rate": po_rate,
            "has_order_count": s["has_order_count"],
            "has_external_doc_count": s["has_external_doc_count"],
            "amount_stats": {
                "avg_amount": round(s["avg_amount"], 2) if s["avg_amount"] else 0,
                "amount_stddev": 0,  # Can't compute stddev in simple aggregation
                "min_amount": round(s["min_amount"], 2) if s["min_amount"] else 0,
                "max_amount": round(s["max_amount"], 2) if s["max_amount"] else 0,
                "sample_count": count,
            },
        }
    except Exception as e:
        logger.warning("[VendorProfile] Cache stats error for %s: %s", vendor_no, e)
        return None



async def fetch_local_posting_history(db, vendor_no: str, limit: int = 20) -> List[Dict]:
    """Fetch previously posted documents from our own MongoDB for this vendor.
    These represent invoices we successfully created in BC before.
    """
    docs = await db.hub_documents.find(
        {
            "$or": [
                {"bc_vendor_number": vendor_no},
                {"vendor_no": vendor_no},
            ],
            "bc_purchase_invoice": {"$exists": True},
            "bc_purchase_invoice.success": True,
        },
        {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "extracted_fields": 1,
            "normalized_fields": 1,
            "bc_purchase_invoice": 1,
            "bc_pi_lines_posted": 1,
            "created_utc": 1,
        }
    ).sort("created_utc", -1).limit(limit).to_list(limit)
    return docs


def _analyze_line_patterns(invoices: List[Dict]) -> Dict:
    """Analyze line items across invoices to find patterns."""
    line_type_counter = Counter()
    gl_account_counter = Counter()
    item_counter = Counter()
    description_samples = []
    line_counts = []
    line_costs = []

    for inv in invoices:
        lines = inv.get("purchaseInvoiceLines", [])
        line_counts.append(len(lines))

        for line in lines:
            lt = line.get("lineType", "")
            obj_no = line.get("lineObjectNumber", "")
            desc = line.get("description", "")
            unit_cost = line.get("unitCost", 0) or 0

            if lt:
                line_type_counter[lt] += 1
            if lt == "Account" and obj_no:
                gl_account_counter[obj_no] += 1
            elif lt == "Item" and obj_no:
                item_counter[obj_no] += 1
            if desc:
                description_samples.append(desc)
            if unit_cost > 0:
                line_costs.append(unit_cost)

    total_lines = sum(line_type_counter.values()) or 1

    # Build ranked GL accounts
    gl_accounts = [
        {"account": acct, "count": cnt, "frequency": round(cnt / total_lines, 2)}
        for acct, cnt in gl_account_counter.most_common(10)
    ]

    # Build ranked items
    items = [
        {"item_no": item, "count": cnt, "frequency": round(cnt / total_lines, 2)}
        for item, cnt in item_counter.most_common(10)
    ]

    # Dominant line type
    dominant_line_type = line_type_counter.most_common(1)[0][0] if line_type_counter else "Account"

    # Typical description pattern
    desc_pattern = _detect_description_pattern(description_samples)

    return {
        "dominant_line_type": dominant_line_type,
        "line_type_distribution": dict(line_type_counter),
        "common_gl_accounts": gl_accounts,
        "common_items": items,
        "description_pattern": desc_pattern,
        "description_samples": description_samples[:10],
        "avg_line_count": round(statistics.mean(line_counts), 1) if line_counts else 1,
        "avg_unit_cost": round(statistics.mean(line_costs), 2) if line_costs else 0,
        "cost_stddev": round(statistics.stdev(line_costs), 2) if len(line_costs) >= 2 else 0,
    }


def _detect_description_pattern(descriptions: List[str]) -> str:
    """Detect the dominant description pattern from samples.
    Common patterns: PO reference, BOL reference, invoice number, free text.
    """
    if not descriptions:
        return "unknown"

    po_pattern = re.compile(r'^\d{4,7}$|^PO\s*\d+|^\d{5,6}-?\d*$', re.IGNORECASE)
    bol_pattern = re.compile(r'^BOL|^B/L|^PRO\s*\d', re.IGNORECASE)
    inv_pattern = re.compile(r'^INV|^INVOICE', re.IGNORECASE)

    counts = {"po_reference": 0, "bol_reference": 0, "invoice_reference": 0, "free_text": 0}
    for d in descriptions:
        d = d.strip()
        if po_pattern.search(d):
            counts["po_reference"] += 1
        elif bol_pattern.search(d):
            counts["bol_reference"] += 1
        elif inv_pattern.search(d):
            counts["invoice_reference"] += 1
        else:
            counts["free_text"] += 1

    return max(counts, key=counts.get)


async def build_vendor_profile(
    db, vendor_no: str, force_refresh: bool = False
) -> Dict[str, Any]:
    """Build a comprehensive vendor invoice profile from BC history + local history.

    Cached in MongoDB (`vendor_invoice_profiles` collection) for 24h.
    """
    # Check cache first (unless force refresh)
    if not force_refresh:
        cached = await db.vendor_invoice_profiles.find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )
        if cached:
            updated = cached.get("last_updated", "")
            if updated:
                try:
                    last_dt = datetime.fromisoformat(updated.replace("Z", "+00:00"))
                    if datetime.now(timezone.utc) - last_dt < timedelta(hours=PROFILE_CACHE_TTL_HOURS):
                        logger.info("[VendorProfile] Cache hit for %s (updated %s)", vendor_no, updated)
                        return cached
                except (ValueError, TypeError):
                    pass

    logger.info("[VendorProfile] Building profile for vendor %s", vendor_no)

    # Fetch data from all sources in parallel-ish fashion
    vendor_card = await fetch_vendor_card(vendor_no)
    bc_invoices = await fetch_vendor_invoices_from_bc(vendor_no)
    local_history = await fetch_local_posting_history(db, vendor_no)

    # ── FALLBACK: Learn from BC reference cache when API returns 0 ──
    # The cache has posted purchase invoices synced from BC.
    # This covers cases where API calls fail (creds, timeout) but cache has rich data.
    cache_stats = None
    if not bc_invoices:
        cache_stats = await _learn_from_reference_cache(db, vendor_no)
        if cache_stats and cache_stats.get("count", 0) > 0:
            logger.info(
                "[VendorProfile] BC API returned 0 invoices for %s but cache has %d — using cache data",
                vendor_no, cache_stats["count"],
            )

    # Analyze BC invoice patterns
    line_patterns = _analyze_line_patterns(bc_invoices) if bc_invoices else {}

    # Amount statistics — from BC invoices first, fallback to cache
    amounts = []
    for inv in bc_invoices:
        amt = inv.get("totalAmountExcludingTax") or inv.get("totalAmountIncludingTax") or 0
        if amt and float(amt) > 0:
            amounts.append(float(amt))

    amount_stats = {}
    if amounts:
        amount_stats = {
            "avg_amount": round(statistics.mean(amounts), 2),
            "amount_stddev": round(statistics.stdev(amounts), 2) if len(amounts) >= 2 else 0,
            "min_amount": round(min(amounts), 2),
            "max_amount": round(max(amounts), 2),
            "sample_count": len(amounts),
        }
    elif cache_stats and cache_stats.get("amount_stats"):
        amount_stats = cache_stats["amount_stats"]

    # Determine PO expectation from cache data.
    # If a vendor has thousands of posted PIs and NONE have bc_order_number,
    # POs are clearly not part of their workflow. The system learns this from BC history.
    po_expected = True  # default
    po_rate = 0.0
    if cache_stats and cache_stats.get("count", 0) >= 10:
        po_rate = cache_stats.get("po_rate", 1.0)
        if po_rate < 0.05:  # Less than 5% of invoices have a PO
            po_expected = False
            logger.info(
                "[VendorProfile] Learned from BC: vendor %s has %d posted PIs, %.1f%% have POs → po_expected=False",
                vendor_no, cache_stats["count"], po_rate * 100,
            )

    invoice_count = len(bc_invoices) or (cache_stats.get("count", 0) if cache_stats else 0)

    # Build the profile
    profile = {
        "vendor_no": vendor_no,
        "vendor_name": vendor_card.get("displayName", "") if vendor_card else "",
        "vendor_card": {
            "payment_terms_id": vendor_card.get("paymentTermsId", "") if vendor_card else "",
            "payment_method_id": vendor_card.get("paymentMethodId", "") if vendor_card else "",
            "currency_code": vendor_card.get("currencyCode", "") if vendor_card else "",
            "tax_liable": vendor_card.get("taxLiable", False) if vendor_card else False,
            "blocked": vendor_card.get("blocked", "") if vendor_card else "",
        },
        "bc_invoice_count": invoice_count,
        "local_posting_count": len(local_history),
        "po_expected": po_expected,
        "line_patterns": line_patterns,
        "amount_stats": amount_stats,
        "default_line_type": line_patterns.get("dominant_line_type", "Account"),
        "default_gl_account": (
            line_patterns.get("common_gl_accounts", [{}])[0].get("account", "")
            if line_patterns.get("common_gl_accounts") else ""
        ),
        "default_item_code": (
            line_patterns.get("common_items", [{}])[0].get("item_no", "")
            if line_patterns.get("common_items") else ""
        ),
        "description_pattern": line_patterns.get("description_pattern", "po_reference"),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "bc_invoices": len(bc_invoices),
            "bc_cache": cache_stats.get("count", 0) if cache_stats else 0,
            "local_documents": len(local_history),
            "vendor_card": bool(vendor_card),
        },
    }

    # Persist to MongoDB
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vendor_no},
        {"$set": profile},
        upsert=True,
    )
    logger.info(
        "[VendorProfile] Profile built for %s: %d invoices (api=%d, cache=%d), po_expected=%s, default=%s/%s, avg=$%s",
        vendor_no, invoice_count, len(bc_invoices),
        cache_stats.get("count", 0) if cache_stats else 0,
        po_expected,
        profile["default_line_type"], profile["default_gl_account"] or profile["default_item_code"],
        amount_stats.get("avg_amount", "N/A"),
    )

    return profile


async def get_or_build_profile(db, vendor_no: str) -> Dict[str, Any]:
    """Get cached profile or build a new one. Never returns None."""
    if not vendor_no:
        return _empty_profile("")
    return await build_vendor_profile(db, vendor_no)


def build_smart_pi_lines(
    doc: Dict, profile: Dict, po_reference: str = ""
) -> List[Dict]:
    """Build Purchase Invoice lines using the vendor's historical profile.

    Instead of blindly defaulting to FREIGHT item, we use what BC history
    tells us this vendor's invoices typically look like.

    Returns a list of BC-compatible line dicts.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    default_line_type = profile.get("default_line_type", "Account")
    default_gl = profile.get("default_gl_account", "")
    default_item = profile.get("default_item_code", "")
    desc_pattern = profile.get("description_pattern", "po_reference")

    # Fallback GL/Item from environment
    fallback_gl = os.environ.get("BC_PI_FALLBACK_GL_ACCOUNT", "60500")
    fallback_item = os.environ.get("BC_PI_FREIGHT_ITEM", os.environ.get("BC_DEFAULT_ITEM_CODE", "FREIGHT"))

    # Build description based on the vendor's historical pattern
    if desc_pattern == "po_reference" and po_reference:
        description = po_reference
    elif desc_pattern == "bol_reference":
        description = (
            nf.get("bol_number") or ef.get("bol_number") or po_reference or ""
        )
    elif desc_pattern == "invoice_reference":
        inv_no = ef.get("invoice_number") or nf.get("invoice_number") or ""
        description = f"Inv {inv_no}" if inv_no else po_reference
    else:
        description = po_reference or ""

    # Collect extracted line items
    line_items = nf.get("line_items") or ef.get("line_items") or doc.get("line_items") or []

    # No extracted lines — create a single line from total amount
    if not line_items:
        total_amount = _extract_total_amount(doc)
        if total_amount <= 0:
            return []
        line_items = [{
            "description": description or f"Per invoice {ef.get('invoice_number', '')}".strip(),
            "quantity": 1,
            "unit_price": total_amount,
        }]

    bc_lines = []
    for li in line_items:
        desc = str(li.get("description", "")).strip()
        qty = float(li.get("quantity", 1) or 1)
        unit_cost = float(li.get("unit_price", 0) or li.get("unitCost", 0) or li.get("unit_cost", 0) or 0)
        if unit_cost == 0:
            unit_cost = float(li.get("total", 0) or li.get("amount", 0) or 0)

        # Check for explicit item/GL from extraction first
        explicit_item = li.get("item_number") or li.get("sku") or li.get("lineObjectNumber") or ""
        explicit_gl = li.get("gl_account") or li.get("account_number") or ""

        if explicit_item:
            bc_line = {
                "lineType": "Item",
                "lineObjectNumber": explicit_item,
                "description": description if description else desc,
                "quantity": qty,
                "unitCost": unit_cost,
                "source": "extracted_item",
            }
        elif explicit_gl:
            bc_line = {
                "lineType": "Account",
                "lineObjectNumber": explicit_gl,
                "description": description if description else desc,
                "quantity": qty,
                "unitCost": unit_cost,
                "source": "extracted_gl",
            }
        elif default_line_type == "Account" and default_gl:
            # Use vendor's historical GL account
            bc_line = {
                "lineType": "Account",
                "lineObjectNumber": default_gl,
                "description": description if description else desc,
                "quantity": qty,
                "unitCost": unit_cost,
                "source": "vendor_profile_gl",
            }
        elif default_line_type == "Item" and default_item:
            # Use vendor's historical item code
            bc_line = {
                "lineType": "Item",
                "lineObjectNumber": default_item,
                "description": description if description else desc,
                "quantity": qty,
                "unitCost": unit_cost,
                "source": "vendor_profile_item",
            }
        else:
            # Final fallback — use env defaults
            bc_line = {
                "lineType": "Account" if fallback_gl else "Item",
                "lineObjectNumber": fallback_gl or fallback_item,
                "description": description if description else desc,
                "quantity": qty,
                "unitCost": unit_cost,
                "source": "env_default",
            }

        bc_lines.append(bc_line)

    return bc_lines


def detect_deviations(
    doc: Dict, profile: Dict, planned_lines: List[Dict]
) -> List[Dict]:
    """Detect deviations between the current invoice and the vendor's historical profile.

    Returns a list of deviation flags with severity (info/warning/critical).
    """
    deviations = []
    amount_stats = profile.get("amount_stats", {})
    line_patterns = profile.get("line_patterns", {})

    if not amount_stats.get("sample_count"):
        deviations.append({
            "type": "no_history",
            "severity": "info",
            "message": f"No historical invoices found in BC for vendor {profile.get('vendor_no', '')}. Using system defaults.",
        })
        return deviations

    # 1. Amount deviation
    total = _extract_total_amount(doc)
    avg = amount_stats.get("avg_amount", 0)
    stddev = amount_stats.get("amount_stddev", 0)

    if total > 0 and avg > 0 and stddev > 0:
        deviation_factor = abs(total - avg) / stddev if stddev > 0 else 0
        if deviation_factor > 3:
            deviations.append({
                "type": "amount_outlier",
                "severity": "critical",
                "message": f"Invoice amount ${total:,.2f} is {deviation_factor:.1f}σ from vendor average ${avg:,.2f} (±${stddev:,.2f})",
                "value": total,
                "expected_range": [round(avg - 2 * stddev, 2), round(avg + 2 * stddev, 2)],
            })
        elif deviation_factor > 2:
            deviations.append({
                "type": "amount_unusual",
                "severity": "warning",
                "message": f"Invoice amount ${total:,.2f} is {deviation_factor:.1f}σ from vendor average ${avg:,.2f}",
                "value": total,
                "expected_range": [round(avg - 2 * stddev, 2), round(avg + 2 * stddev, 2)],
            })

    # 2. Line type deviation
    for line in planned_lines:
        lt = line.get("lineType", "")
        obj_no = line.get("lineObjectNumber", "")
        source = line.get("source", "")

        if source == "env_default":
            deviations.append({
                "type": "default_fallback",
                "severity": "warning",
                "message": f"Line using system default ({lt}/{obj_no}) — no vendor history available for line mapping",
            })

        # Check if GL account is unusual for this vendor
        if lt == "Account" and obj_no:
            known_gls = {a["account"] for a in line_patterns.get("common_gl_accounts", [])}
            if known_gls and obj_no not in known_gls:
                deviations.append({
                    "type": "unusual_gl",
                    "severity": "warning",
                    "message": f"G/L account {obj_no} not seen in vendor's invoice history. Known accounts: {', '.join(sorted(known_gls))}",
                })

        if lt == "Item" and obj_no:
            known_items = {i["item_no"] for i in line_patterns.get("common_items", [])}
            if known_items and obj_no not in known_items:
                deviations.append({
                    "type": "unusual_item",
                    "severity": "warning",
                    "message": f"Item {obj_no} not seen in vendor's invoice history. Known items: {', '.join(sorted(known_items))}",
                })

    # 3. Line count deviation
    expected_lines = line_patterns.get("avg_line_count", 1)
    if expected_lines and len(planned_lines) > expected_lines * 2:
        deviations.append({
            "type": "line_count_high",
            "severity": "info",
            "message": f"Invoice has {len(planned_lines)} lines, vendor typically has ~{expected_lines:.0f}",
        })

    return deviations


def _extract_total_amount(doc: Dict) -> float:
    """Extract total invoice amount from document fields."""
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    for field in ["amount", "amount_float", "invoice_amount", "total_amount", "balance_due"]:
        val = nf.get(field) or ef.get(field) or doc.get(field)
        if val:
            cleaned = str(val).replace("$", "").replace(",", "").strip()
            try:
                return float(cleaned)
            except (ValueError, TypeError):
                continue
    return 0.0


def _empty_profile(vendor_no: str) -> Dict:
    """Return an empty profile when vendor_no is missing."""
    return {
        "vendor_no": vendor_no,
        "vendor_name": "",
        "vendor_card": {},
        "bc_invoice_count": 0,
        "local_posting_count": 0,
        "po_expected": True,
        "line_patterns": {},
        "amount_stats": {},
        "default_line_type": "Account",
        "default_gl_account": os.environ.get("BC_PI_FALLBACK_GL_ACCOUNT", "60500"),
        "default_item_code": "",
        "description_pattern": "po_reference",
        "last_updated": None,
        "sources": {"bc_invoices": 0, "bc_cache": 0, "local_documents": 0, "vendor_card": False},
    }
