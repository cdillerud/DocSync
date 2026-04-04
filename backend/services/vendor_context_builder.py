"""
GPI Document Hub — Vendor Context Builder

Builds rich context from BC Reference Cache and vendor profiles
to inject into LLM extraction and classification prompts.

This is the Phase 2 "context-rich LLM calls" — the LLM sees real
historical data before processing each document.
"""

import logging
import statistics
from typing import Dict, Any, List, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


async def build_extraction_context(db, vendor_no: str = "", vendor_name: str = "") -> str:
    """
    Build rich extraction context for the LLM from BC historical data.
    
    Returns a string to prepend to the extraction prompt with:
    - Vendor profile summary (amounts, PO patterns)
    - 3 real invoice examples from BC cache
    - Known name variants
    
    This gives the LLM concrete examples: "Here's what this vendor's
    invoices actually look like in BC."
    """
    if not vendor_no and not vendor_name:
        return ""

    parts = []

    # 1. Get vendor profile
    profile = await _get_vendor_profile(db, vendor_no, vendor_name)
    if profile:
        parts.append(_format_profile_context(profile))

    # 2. Get real BC invoice examples (few-shot)
    examples = await _get_bc_invoice_examples(db, vendor_no or profile.get("vendor_no", ""))
    if examples:
        parts.append(_format_invoice_examples(examples))

    # 3. Get vendor aliases
    aliases = await _get_vendor_aliases(db, vendor_no or profile.get("vendor_no", ""))
    if aliases:
        parts.append(_format_alias_context(aliases))

    if not parts:
        return ""

    header = "== VENDOR INTELLIGENCE — USE THIS DATA TO IMPROVE EXTRACTION ACCURACY =="
    return header + "\n" + "\n\n".join(parts)


async def build_amount_intelligence_context(db, vendor_no: str) -> str:
    """
    Build amount intelligence context for the LLM.
    Tells the AI what typical invoice amounts look like for this vendor,
    so it can validate extracted amounts and flag anomalies.
    """
    if not vendor_no:
        return ""

    record = await db.amount_patterns.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if not record or record.get("count", 0) < 3:
        return ""

    avg = record.get("avg_amount", 0)
    stddev = record.get("stddev", 0)
    min_amt = record.get("min_amount", 0)
    max_amt = record.get("max_amount", 0)
    count = record.get("count", 0)

    parts = [
        f"AMOUNT INTELLIGENCE for vendor '{vendor_no}' (from {count} historical invoices):",
        f"  - Typical amount: ${avg:,.2f} (std dev: ${stddev:,.2f})",
        f"  - Range seen: ${min_amt:,.2f} – ${max_amt:,.2f}",
    ]

    if stddev > 0:
        low = max(0, avg - 2 * stddev)
        high = avg + 2 * stddev
        parts.append(f"  - Expected range (95%): ${low:,.2f} – ${high:,.2f}")
        parts.append(
            "  - If the extracted amount falls outside this range, double-check "
            "the extraction — it may be reading a subtotal or wrong field."
        )

    return "\n".join(parts)


async def build_classification_context(db, vendor_no: str = "", vendor_name: str = "",
                                        sender_email: str = "", sender_domain: str = "") -> str:
    """
    Build classification context for the LLM.
    
    Tells the AI what type of documents this vendor typically sends,
    based on BC history:
    - Entity type distribution (purchase invoices vs sales shipments)
    - Document count signals ("18K purchase invoices → likely AP_Invoice")
    - Sender domain hints ("invoices@vendor.com → AP_Invoice")
    """
    if not vendor_no and not vendor_name and not sender_email:
        return ""

    parts = []

    # 1. BC entity type distribution for this vendor
    resolved_vendor_no = vendor_no
    if not resolved_vendor_no and vendor_name:
        resolved_vendor_no = await _resolve_vendor_no(db, vendor_name)

    if resolved_vendor_no:
        dist = await _get_vendor_entity_distribution(db, resolved_vendor_no)
        if dist:
            parts.append(_format_entity_distribution(dist, resolved_vendor_no))

    # 2. Sender domain → vendor type hint
    domain = sender_domain
    if not domain and sender_email and "@" in sender_email:
        domain = sender_email.split("@")[1].lower()

    if domain:
        domain_hint = await _get_domain_vendor_hint(db, domain)
        if domain_hint:
            parts.append(domain_hint)

    # 3. Historical doc types for this vendor in hub_documents
    if resolved_vendor_no or vendor_name:
        hist = await _get_historical_doc_types(db, resolved_vendor_no, vendor_name)
        if hist:
            parts.append(hist)

    if not parts:
        return ""

    header = "== CLASSIFICATION INTELLIGENCE — USE THIS TO DETERMINE DOCUMENT TYPE =="
    return header + "\n" + "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════

async def _get_vendor_profile(db, vendor_no: str, vendor_name: str) -> Optional[Dict]:
    """Look up vendor invoice profile."""
    query_parts = []
    if vendor_no:
        query_parts.append({"vendor_no": vendor_no})
        query_parts.append({"vendor_no": vendor_no.upper()})
    if vendor_name:
        query_parts.append({"vendor_name": {"$regex": f"^{vendor_name}$", "$options": "i"}})

    if not query_parts:
        return None

    return await db.vendor_invoice_profiles.find_one(
        {"$or": query_parts}, {"_id": 0}
    )


async def _get_bc_invoice_examples(db, vendor_no: str, limit: int = 3) -> List[Dict]:
    """Get real BC invoice records as few-shot examples."""
    if not vendor_no:
        return []

    # Get recent invoices with non-zero amounts
    cursor = db.bc_reference_cache.find(
        {
            "bc_entity_type": "posted_purchase_invoice",
            "bc_vendor_no": vendor_no,
            "bc_amount": {"$gt": 0},
        },
        {"_id": 0, "bc_document_no": 1, "bc_external_document_no": 1,
         "bc_amount": 1, "bc_posting_date": 1, "bc_vendor_name": 1, "bc_status": 1}
    ).sort("bc_posting_date", -1).limit(limit)

    return await cursor.to_list(limit)


async def _get_vendor_aliases(db, vendor_no: str, limit: int = 5) -> List[str]:
    """Get known vendor name variants."""
    if not vendor_no:
        return []

    cursor = db.vendor_aliases.find(
        {"$or": [{"vendor_no": vendor_no}, {"canonical_vendor_id": vendor_no}]},
        {"_id": 0, "alias_string": 1}
    ).limit(limit)

    aliases = await cursor.to_list(limit)
    return list({a.get("alias_string", "") for a in aliases if a.get("alias_string")})


async def _resolve_vendor_no(db, vendor_name: str) -> str:
    """Try to resolve a vendor name to a vendor number via aliases."""
    if not vendor_name:
        return ""

    alias = await db.vendor_aliases.find_one(
        {"$or": [
            {"normalized_alias": vendor_name.lower().strip()},
            {"alias_string": {"$regex": f"^{vendor_name}$", "$options": "i"}},
        ]},
        {"_id": 0, "vendor_no": 1, "canonical_vendor_id": 1}
    )
    if alias:
        return alias.get("vendor_no") or alias.get("canonical_vendor_id", "")
    return ""


async def _get_vendor_entity_distribution(db, vendor_no: str) -> Dict[str, int]:
    """Get count of each BC entity type for a vendor."""
    pipeline = [
        {"$match": {"bc_vendor_no": vendor_no}},
        {"$group": {"_id": "$bc_entity_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    dist = {}
    async for r in db.bc_reference_cache.aggregate(pipeline):
        dist[r["_id"]] = r["count"]
    return dist


async def _get_domain_vendor_hint(db, domain: str) -> str:
    """Check if this sender domain is mapped to a vendor."""
    mapping = await db.sender_vendor_map.find_one(
        {"sender_domain": domain},
        {"_id": 0, "vendor_canonical": 1, "vendor_no": 1}
    )
    if mapping and mapping.get("vendor_canonical"):
        return (f"SENDER DOMAIN MATCH: '{domain}' is known to be from "
                f"vendor '{mapping['vendor_canonical']}' ({mapping.get('vendor_no', '')}).\n"
                f"Documents from this domain are typically AP invoices.")
    return ""


async def _get_historical_doc_types(db, vendor_no: str, vendor_name: str) -> str:
    """Check what doc types this vendor has sent historically in hub_documents."""
    query_parts = []
    if vendor_no:
        query_parts.append({"bc_vendor_number": vendor_no})
        query_parts.append({"matched_vendor_no": vendor_no})
    if vendor_name:
        query_parts.append({"vendor_canonical": {"$regex": f"^{vendor_name}$", "$options": "i"}})

    if not query_parts:
        return ""

    pipeline = [
        {"$match": {"$or": query_parts, "doc_type": {"$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$doc_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]

    types = []
    async for r in db.hub_documents.aggregate(pipeline):
        types.append(f"  - {r['_id']}: {r['count']} documents")

    if types:
        return "HISTORICAL DOCUMENT TYPES for this vendor:\n" + "\n".join(types)
    return ""


# ═══════════════════════════════════════════════════════════════
# FORMATTERS
# ═══════════════════════════════════════════════════════════════

def _format_profile_context(profile: Dict) -> str:
    """Format vendor profile as prompt context."""
    parts = [f"VENDOR PROFILE — '{profile.get('vendor_name', '?')}' ({profile.get('vendor_no', '?')}):"]

    stats = profile.get("amount_stats", {})
    if stats.get("count", 0) > 0:
        parts.append(
            f"  - Historical invoices: {stats['count']:,}, "
            f"avg amount: ${stats.get('mean', 0):,.2f}, "
            f"median: ${stats.get('median', 0):,.2f}, "
            f"range: ${stats.get('min', 0):,.2f} – ${stats.get('max', 0):,.2f}"
        )

    if profile.get("po_expected") is not None:
        if profile["po_expected"]:
            parts.append("  - PO EXPECTED: YES — look for Purchase Order numbers on this invoice")
        else:
            parts.append("  - PO EXPECTED: NO — this vendor does NOT use PO numbers (e.g., freight carrier)")

    po_pat = profile.get("po_patterns", {})
    if po_pat.get("has_patterns"):
        parts.append(
            f"  - Typical reference format: avg length {po_pat.get('avg_length', '?')}, "
            f"{po_pat.get('numeric_only_pct', 0)*100:.0f}% are numeric-only"
        )
        prefixes = po_pat.get("common_prefixes", [])
        if prefixes:
            prefix_str = ", ".join(f"'{p['prefix']}'" for p in prefixes[:3])
            parts.append(f"  - Common reference prefixes: {prefix_str}")

    freq = profile.get("posting_frequency", {})
    if freq.get("frequency") and freq["frequency"] != "unknown":
        parts.append(f"  - Posting frequency: {freq['frequency']} ({freq.get('avg_per_month', '?')}/month)")

    return "\n".join(parts)


def _format_invoice_examples(examples: List[Dict]) -> str:
    """Format BC invoice records as few-shot examples."""
    parts = ["REAL INVOICE EXAMPLES from BC (use these as reference):"]

    for i, ex in enumerate(examples, 1):
        amount = ex.get("bc_amount", 0)
        ext_ref = ex.get("bc_external_document_no", "")
        date = ex.get("bc_posting_date", "")
        doc_no = ex.get("bc_document_no", "")
        status = ex.get("bc_status", "")

        line = f"  Example {i}: Invoice #{doc_no}"
        if ext_ref:
            line += f", PO/Ref: {ext_ref}"
        if amount:
            line += f", Amount: ${amount:,.2f}"
        if date:
            line += f", Posted: {date}"
        if status:
            line += f" ({status})"
        parts.append(line)

    return "\n".join(parts)


def _format_alias_context(aliases: List[str]) -> str:
    """Format vendor aliases as context."""
    if not aliases:
        return ""
    alias_str = ", ".join(f"'{a}'" for a in aliases[:5])
    return f"KNOWN NAME VARIANTS for this vendor: {alias_str}"


def _format_entity_distribution(dist: Dict[str, int], vendor_no: str) -> str:
    """Format entity type distribution as classification hint."""
    total = sum(dist.values())
    parts = [f"BC ENTITY HISTORY for vendor '{vendor_no}' ({total:,} total records):"]

    type_labels = {
        "posted_purchase_invoice": "AP Invoices (purchase)",
        "purchase_order": "Purchase Orders",
        "posted_sales_shipment": "Sales Shipments",
        "posted_sales_invoice": "Sales Invoices",
    }

    for entity_type, count in sorted(dist.items(), key=lambda x: -x[1]):
        pct = count / total * 100
        label = type_labels.get(entity_type, entity_type)
        parts.append(f"  - {label}: {count:,} ({pct:.0f}%)")

    # Add classification suggestion based on distribution
    if dist.get("posted_purchase_invoice", 0) > 0:
        ppi_pct = dist["posted_purchase_invoice"] / total * 100
        if ppi_pct > 80:
            parts.append(f"  → STRONG SIGNAL: {ppi_pct:.0f}% of this vendor's BC records are purchase invoices.")
            parts.append("  → Documents from this vendor are very likely AP_Invoice type.")

    return "\n".join(parts)
