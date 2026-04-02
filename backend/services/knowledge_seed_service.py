"""
GPI Document Hub — Knowledge Seed Service

Phase 1: Bulk Knowledge Seeding
Mines existing data in BC Reference Cache, Spiro CRM, and historical documents
to pre-populate:
  1. Vendor aliases (from BC name variants + Spiro)
  2. Sender-domain → vendor mappings (from resolved documents)
  3. Vendor invoice profiles (from BC posted purchase invoices)

This is the "turn on the faucet" moment — the data already exists,
we just need to make it available to the pipeline.
"""

import logging
import uuid
import re
import statistics
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from collections import defaultdict

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 1. BULK VENDOR ALIAS GENERATION
# ═══════════════════════════════════════════════════════════════

async def seed_vendor_aliases_from_bc_cache(db) -> Dict[str, Any]:
    """
    Mine bc_reference_cache for every (vendor_no, vendor_name) pair.
    Create vendor aliases so the pipeline can match raw vendor names
    to BC vendor numbers without hitting the live API.

    Before: 7 aliases.  After: hundreds.
    """
    t0 = datetime.now(timezone.utc)
    logger.info("[KnowledgeSeed] Starting bulk vendor alias generation from BC cache...")

    # Aggregate all unique (vendor_no, vendor_name) pairs
    pipeline = [
        {"$match": {
            "bc_vendor_no": {"$ne": None, "$ne": ""},
            "bc_vendor_name": {"$ne": None, "$ne": ""},
        }},
        {"$group": {
            "_id": {"vendor_no": "$bc_vendor_no", "vendor_name": "$bc_vendor_name"},
            "doc_count": {"$sum": 1},
        }},
    ]

    pairs = []
    async for r in db.bc_reference_cache.aggregate(pipeline, allowDiskUse=True):
        pairs.append({
            "vendor_no": r["_id"]["vendor_no"],
            "vendor_name": r["_id"]["vendor_name"],
            "doc_count": r["doc_count"],
        })

    logger.info("[KnowledgeSeed] Found %d unique (vendor_no, vendor_name) pairs", len(pairs))

    # Group by vendor_no to find the "primary" name (most common)
    vendor_names = defaultdict(list)
    for p in pairs:
        vendor_names[p["vendor_no"]].append((p["vendor_name"], p["doc_count"]))

    created = 0
    skipped = 0
    vendors_processed = 0

    for vendor_no, name_counts in vendor_names.items():
        vendors_processed += 1
        # Primary name = most common
        name_counts.sort(key=lambda x: -x[1])
        primary_name = name_counts[0][0]

        for name, count in name_counts:
            normalized = name.strip().upper()
            if not normalized or len(normalized) < 2:
                continue

            # Skip if this exact alias already exists
            existing = await db.vendor_aliases.find_one({
                "$or": [
                    {"alias_string": name},
                    {"normalized_alias": normalized.lower()},
                    {"alias": normalized},
                ]
            })
            if existing:
                skipped += 1
                continue

            alias_doc = {
                "alias_id": str(uuid.uuid4()),
                "alias_string": name,
                "alias": normalized,
                "normalized_alias": normalized.lower(),
                "canonical_vendor_id": vendor_no,
                "vendor_no": vendor_no,
                "vendor_name": primary_name,
                "source": "bc_cache_seed",
                "bc_doc_count": count,
                "learned_at": t0.isoformat(),
                "created_at": t0.isoformat(),
            }
            try:
                await db.vendor_aliases.insert_one(alias_doc)
                created += 1
            except Exception as e:
                # Duplicate key or other error
                skipped += 1

    # Also seed from Spiro companies
    spiro_created = await _seed_aliases_from_spiro(db, vendor_names, t0)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    result = {
        "vendors_processed": vendors_processed,
        "aliases_created": created,
        "aliases_skipped": skipped,
        "spiro_aliases_created": spiro_created,
        "total_aliases": await db.vendor_aliases.count_documents({}),
        "elapsed_seconds": round(elapsed, 1),
    }
    logger.info("[KnowledgeSeed] Vendor alias seeding complete: %s", result)
    return result


async def _seed_aliases_from_spiro(db, bc_vendor_names: dict, t0) -> int:
    """
    Cross-reference Spiro company names with BC vendors.
    If a Spiro company matches a BC vendor (by normalized name),
    add the Spiro name as an alias.
    """
    from services.reference_helpers import normalize_company_name

    # Build a lookup: normalized_name → vendor_no from BC
    bc_lookup = {}
    for vendor_no, name_counts in bc_vendor_names.items():
        for name, _ in name_counts:
            norm = normalize_company_name(name)
            if norm and len(norm) >= 3:
                bc_lookup[norm] = (vendor_no, name)

    created = 0
    cursor = db.spiro_companies.find(
        {"name": {"$ne": None, "$ne": ""}},
        {"_id": 0, "name": 1, "name_normalized": 1, "spiro_id": 1}
    )

    async for company in cursor:
        spiro_name = company.get("name", "")
        spiro_norm = company.get("name_normalized", "") or normalize_company_name(spiro_name)

        if spiro_norm in bc_lookup:
            vendor_no, primary_name = bc_lookup[spiro_norm]
            normalized_upper = spiro_name.strip().upper()

            existing = await db.vendor_aliases.find_one({
                "$or": [
                    {"alias_string": spiro_name},
                    {"normalized_alias": normalized_upper.lower()},
                ]
            })
            if existing:
                continue

            alias_doc = {
                "alias_id": str(uuid.uuid4()),
                "alias_string": spiro_name,
                "alias": normalized_upper,
                "normalized_alias": normalized_upper.lower(),
                "canonical_vendor_id": vendor_no,
                "vendor_no": vendor_no,
                "vendor_name": primary_name,
                "source": "spiro_cross_ref",
                "spiro_id": company.get("spiro_id"),
                "learned_at": t0.isoformat(),
                "created_at": t0.isoformat(),
            }
            try:
                await db.vendor_aliases.insert_one(alias_doc)
                created += 1
            except Exception:
                pass

    return created


# ═══════════════════════════════════════════════════════════════
# 2. BULK SENDER-DOMAIN MAPPING
# ═══════════════════════════════════════════════════════════════

async def seed_sender_domain_mappings(db) -> Dict[str, Any]:
    """
    Build sender-email → vendor mappings from documents that were
    successfully resolved. When we know doc X from sender@example.com
    was matched to vendor TUMALOC, we can auto-resolve future docs
    from example.com.

    Also cross-references Spiro company email_domain fields.
    """
    t0 = datetime.now(timezone.utc)
    logger.info("[KnowledgeSeed] Starting sender-domain mapping generation...")

    created_email = 0
    created_domain = 0
    skipped = 0

    # Source 1: Documents with sender_email OR sender field + resolved vendor
    # Note: Some documents use "sender" instead of "sender_email" — check both
    cursor = db.hub_documents.find(
        {
            "$or": [
                {"sender_email": {"$exists": True, "$nin": [None, ""]}},
                {"sender": {"$exists": True, "$nin": [None, ""]}},
            ],
            "$and": [
                {"$or": [
                    {"bc_vendor_number": {"$exists": True, "$nin": [None, ""]}},
                    {"vendor_canonical": {"$exists": True, "$nin": [None, ""]}},
                    {"vendor_no": {"$exists": True, "$nin": [None, ""]}},
                ]}
            ],
        },
        {"_id": 0, "sender_email": 1, "sender": 1, "sender_domain": 1,
         "bc_vendor_number": 1, "vendor_canonical": 1, "vendor_no": 1}
    )

    domain_vendor_map = defaultdict(lambda: defaultdict(int))

    async for doc in cursor:
        sender = doc.get("sender_email") or doc.get("sender") or ""
        domain = doc.get("sender_domain", "")
        if not domain and "@" in sender:
            domain = sender.split("@")[1].lower()

        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        vendor_canonical = doc.get("vendor_canonical") or vendor_no

        if domain and vendor_canonical:
            domain_vendor_map[domain][vendor_canonical] += 1

    # For each domain, pick the vendor with the most documents
    for domain, vendors in domain_vendor_map.items():
        if not vendors:
            continue
        top_vendor = max(vendors.items(), key=lambda x: x[1])
        vendor_canonical = top_vendor[0]
        count = top_vendor[1]

        # Skip generic/internal domains
        if domain in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com",
                       "gamerpackaging.com"):
            continue

        existing = await db.sender_vendor_map.find_one({
            "sender_domain": domain, "vendor_canonical": vendor_canonical
        })
        if existing:
            skipped += 1
            continue

        await db.sender_vendor_map.insert_one({
            "sender_domain": domain,
            "vendor_canonical": vendor_canonical,
            "vendor_name": vendor_canonical,
            "vendor_no": "",
            "domain_confidence": count,
            "source": "document_history_seed",
            "created_at": t0.isoformat(),
            "updated_at": t0.isoformat(),
        })
        created_domain += 1

    # Source 2: Spiro companies with email_domain
    spiro_domains = await _seed_domains_from_spiro(db, t0)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    result = {
        "domains_from_documents": created_domain,
        "domains_from_spiro": spiro_domains,
        "skipped": skipped,
        "total_sender_mappings": await db.sender_vendor_map.count_documents({}),
        "elapsed_seconds": round(elapsed, 1),
    }
    logger.info("[KnowledgeSeed] Sender-domain mapping complete: %s", result)
    return result


async def _seed_domains_from_spiro(db, t0) -> int:
    """
    Spiro companies have email_domain fields. Cross-reference with
    BC vendor aliases to create domain → vendor mappings.
    """
    from services.reference_helpers import normalize_company_name

    created = 0

    # Build a lookup from alias → vendor_no
    alias_lookup = {}
    async for alias in db.vendor_aliases.find({}, {"_id": 0, "normalized_alias": 1, "vendor_no": 1, "vendor_name": 1}):
        norm = alias.get("normalized_alias", "")
        if norm:
            alias_lookup[norm] = (alias.get("vendor_no", ""), alias.get("vendor_name", ""))

    cursor = db.spiro_companies.find(
        {"email_domain": {"$ne": None, "$ne": ""}},
        {"_id": 0, "name": 1, "name_normalized": 1, "email_domain": 1}
    )

    async for company in cursor:
        domain = (company.get("email_domain") or "").lower().strip()
        name_norm = ((company.get("name_normalized") or "") or
                     normalize_company_name(company.get("name") or "")).lower()

        if not domain or not name_norm:
            continue

        # Skip generic domains
        if domain in ("gmail.com", "yahoo.com", "hotmail.com", "outlook.com"):
            continue

        # Check if this Spiro company matches a BC vendor
        match = alias_lookup.get(name_norm)
        if not match:
            continue

        vendor_no, vendor_name = match

        existing = await db.sender_vendor_map.find_one({"sender_domain": domain})
        if existing:
            continue

        await db.sender_vendor_map.insert_one({
            "sender_domain": domain,
            "vendor_canonical": vendor_name or vendor_no,
            "vendor_name": vendor_name,
            "vendor_no": vendor_no,
            "domain_confidence": 3,  # Spiro is curated CRM — high trust
            "source": "spiro_domain_seed",
            "created_at": t0.isoformat(),
            "updated_at": t0.isoformat(),
        })
        created += 1

    return created


# ═══════════════════════════════════════════════════════════════
# 3. VENDOR INVOICE PROFILES FROM BC CACHE
# ═══════════════════════════════════════════════════════════════

async def seed_vendor_profiles_from_bc_cache(db) -> Dict[str, Any]:
    """
    For every vendor in BC cache, aggregate their posted purchase invoices
    to build a rich profile:
      - Invoice count, amount stats (mean, median, stddev, min, max)
      - PO patterns (% with external_document_no, typical PO format)
      - Posting frequency
      - Whether PO is expected for this vendor

    This profile is then available to:
      - The LLM extraction prompt ("this vendor typically invoices $1,500")
      - The auto-post service (should we require a PO for this vendor?)
      - The validation service (is this amount anomalous?)
    """
    t0 = datetime.now(timezone.utc)
    logger.info("[KnowledgeSeed] Starting vendor profile generation from BC cache...")

    # Aggregate purchase invoices by vendor
    pipeline = [
        {"$match": {
            "bc_entity_type": "posted_purchase_invoice",
            "bc_vendor_no": {"$ne": None, "$ne": ""},
        }},
        {"$group": {
            "_id": "$bc_vendor_no",
            "vendor_names": {"$addToSet": "$bc_vendor_name"},
            "invoice_count": {"$sum": 1},
            "amounts": {"$push": "$bc_amount"},
            "external_refs": {"$push": "$bc_external_document_no"},
            "order_numbers": {"$push": "$bc_order_number"},
            "posting_dates": {"$push": "$bc_posting_date"},
            "statuses": {"$push": "$bc_status"},
        }},
    ]

    profiles_created = 0
    profiles_updated = 0
    vendors_processed = 0

    async for vendor_data in db.bc_reference_cache.aggregate(pipeline, allowDiskUse=True):
        vendors_processed += 1
        vendor_no = vendor_data["_id"]
        names = [n for n in vendor_data.get("vendor_names", []) if n]
        primary_name = names[0] if names else vendor_no

        # Amount statistics
        raw_amounts = [a for a in vendor_data.get("amounts", []) if a is not None and a > 0]
        amount_stats = _compute_amount_stats(raw_amounts)

        # PO/external ref analysis
        ext_refs = [r for r in vendor_data.get("external_refs", []) if r]
        order_nums = [o for o in vendor_data.get("order_numbers", []) if o]
        invoice_count = vendor_data["invoice_count"]

        has_external_ref_rate = len(ext_refs) / max(invoice_count, 1)
        has_order_number_rate = len(order_nums) / max(invoice_count, 1)

        # Determine if PO is expected
        # If <20% of invoices have a PO/external ref, PO is probably not expected
        po_expected = has_external_ref_rate >= 0.20 or has_order_number_rate >= 0.20

        # Detect PO format patterns
        po_patterns = _detect_po_patterns(ext_refs + order_nums)

        # Posting frequency
        dates = [d for d in vendor_data.get("posting_dates", []) if d]
        posting_frequency = _compute_posting_frequency(dates)

        # Payment status breakdown
        statuses = vendor_data.get("statuses", [])
        status_counts = defaultdict(int)
        for s in statuses:
            if s:
                status_counts[s] += 1

        profile = {
            "vendor_no": vendor_no,
            "vendor_name": primary_name,
            "vendor_name_variants": names,
            "source": "bc_cache_seed",
            "bc_invoice_count": invoice_count,
            "amount_stats": amount_stats,
            "po_expected": po_expected,
            "external_ref_rate": round(has_external_ref_rate, 3),
            "order_number_rate": round(has_order_number_rate, 3),
            "po_patterns": po_patterns,
            "posting_frequency": posting_frequency,
            "payment_status_breakdown": dict(status_counts),
            "last_updated": t0.isoformat(),
            "seeded_at": t0.isoformat(),
        }

        # Upsert — don't overwrite user-set fields
        existing = await db.vendor_invoice_profiles.find_one({"vendor_no": vendor_no})
        if existing:
            # Preserve user overrides
            if existing.get("po_expected_override") is not None:
                profile["po_expected"] = existing["po_expected_override"]
            await db.vendor_invoice_profiles.update_one(
                {"vendor_no": vendor_no},
                {"$set": profile}
            )
            profiles_updated += 1
        else:
            await db.vendor_invoice_profiles.insert_one(profile)
            profiles_created += 1

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    result = {
        "vendors_processed": vendors_processed,
        "profiles_created": profiles_created,
        "profiles_updated": profiles_updated,
        "total_profiles": await db.vendor_invoice_profiles.count_documents({}),
        "elapsed_seconds": round(elapsed, 1),
    }
    logger.info("[KnowledgeSeed] Vendor profile generation complete: %s", result)
    return result


def _compute_amount_stats(amounts: List[float]) -> Dict[str, Any]:
    """Compute descriptive statistics for invoice amounts."""
    if not amounts:
        return {"count": 0}

    return {
        "count": len(amounts),
        "mean": round(statistics.mean(amounts), 2),
        "median": round(statistics.median(amounts), 2),
        "stddev": round(statistics.stdev(amounts), 2) if len(amounts) > 1 else 0,
        "min": round(min(amounts), 2),
        "max": round(max(amounts), 2),
        "p25": round(sorted(amounts)[len(amounts) // 4], 2) if len(amounts) >= 4 else round(min(amounts), 2),
        "p75": round(sorted(amounts)[3 * len(amounts) // 4], 2) if len(amounts) >= 4 else round(max(amounts), 2),
    }


def _detect_po_patterns(references: List[str]) -> Dict[str, Any]:
    """Analyze PO/reference number patterns for a vendor."""
    if not references:
        return {"has_patterns": False}

    # Check for common patterns
    numeric_only = sum(1 for r in references if r.isdigit())
    has_dash = sum(1 for r in references if "-" in r)
    has_alpha = sum(1 for r in references if re.search(r"[A-Za-z]", r))

    # Length stats
    lengths = [len(r) for r in references if r]
    avg_len = statistics.mean(lengths) if lengths else 0

    # Prefix patterns
    prefixes = defaultdict(int)
    for r in references:
        if r and len(r) >= 2:
            # Try 2-char prefix
            prefixes[r[:2].upper()] += 1

    top_prefixes = sorted(prefixes.items(), key=lambda x: -x[1])[:3]

    total = len(references)
    return {
        "has_patterns": True,
        "total_refs": total,
        "numeric_only_pct": round(numeric_only / max(total, 1), 3),
        "has_dash_pct": round(has_dash / max(total, 1), 3),
        "has_alpha_pct": round(has_alpha / max(total, 1), 3),
        "avg_length": round(avg_len, 1),
        "common_prefixes": [{"prefix": p, "count": c} for p, c in top_prefixes],
    }


def _compute_posting_frequency(dates: List[str]) -> Dict[str, Any]:
    """Analyze posting frequency from date strings."""
    if not dates:
        return {"frequency": "unknown"}

    # Parse dates and sort
    parsed = []
    for d in dates:
        try:
            parsed.append(datetime.strptime(d[:10], "%Y-%m-%d"))
        except (ValueError, TypeError):
            continue

    if len(parsed) < 2:
        return {"frequency": "rare", "total_postings": len(parsed)}

    parsed.sort()
    span_days = (parsed[-1] - parsed[0]).days
    if span_days == 0:
        return {"frequency": "burst", "total_postings": len(parsed)}

    avg_per_month = len(parsed) / max(span_days / 30, 1)

    if avg_per_month >= 20:
        freq = "daily"
    elif avg_per_month >= 4:
        freq = "weekly"
    elif avg_per_month >= 1:
        freq = "monthly"
    else:
        freq = "quarterly"

    return {
        "frequency": freq,
        "total_postings": len(parsed),
        "span_days": span_days,
        "avg_per_month": round(avg_per_month, 1),
        "first_posting": parsed[0].isoformat()[:10],
        "last_posting": parsed[-1].isoformat()[:10],
    }


# ═══════════════════════════════════════════════════════════════
# ORCHESTRATOR — Run all seeders
# ═══════════════════════════════════════════════════════════════

async def run_full_knowledge_seed(db) -> Dict[str, Any]:
    """
    Run all Phase 1 knowledge seeders in sequence.
    Safe to run multiple times — uses upsert logic.
    """
    t0 = datetime.now(timezone.utc)
    logger.info("[KnowledgeSeed] === STARTING FULL KNOWLEDGE SEED ===")

    results = {}

    # Step 1: Vendor aliases (must run first — other steps depend on aliases)
    results["vendor_aliases"] = await seed_vendor_aliases_from_bc_cache(db)

    # Step 2: Sender-domain mappings (uses aliases from step 1)
    results["sender_domains"] = await seed_sender_domain_mappings(db)

    # Step 3: Vendor invoice profiles
    results["vendor_profiles"] = await seed_vendor_profiles_from_bc_cache(db)

    elapsed = (datetime.now(timezone.utc) - t0).total_seconds()
    results["total_elapsed_seconds"] = round(elapsed, 1)

    logger.info("[KnowledgeSeed] === FULL KNOWLEDGE SEED COMPLETE in %.1fs ===", elapsed)
    return results
