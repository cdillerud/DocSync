"""
Vendor Re-Processing Router — Batch re-run vendor matching on existing documents.

Use this after deploying vendor matching fixes to re-evaluate all documents
against the updated logic (normalized exact match, shared fuzzy scorer,
fuzzy_candidate vs fuzzy_match semantics).

Endpoints:
  POST /api/vendor-reprocess/run          — Re-process all vendor-applicable docs
  GET  /api/vendor-reprocess/status        — Check status of last re-processing run
  POST /api/vendor-reprocess/dry-run       — Preview what would change without writing
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Query
from deps import get_db

logger = logging.getLogger("vendor_reprocess")

router = APIRouter(prefix="/vendor-reprocess", tags=["Vendor Re-Processing"])

# Module-level state for tracking the last run
_last_run: Dict[str, Any] = {"status": "idle"}

VENDOR_APPLICABLE_TYPES = [
    "AP_Invoice", "AP_INVOICE", "PurchaseInvoice", "PurchaseOrder",
    "Remittance", "REMITTANCE", "Credit_Memo", "CREDIT_MEMO",
    "Purchase_Invoice", "PURCHASE_INVOICE",
]


async def _get_vendor_raw(doc: dict) -> str:
    """Extract the raw vendor string from a document."""
    extracted = doc.get("extracted_fields") or {}
    return (
        doc.get("vendor_raw_ocr")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or extracted.get("supplier")
        or doc.get("vendor_name_raw")
        or ""
    ).strip()


async def _reprocess_single(doc: dict, dry_run: bool = False) -> dict:
    """Re-run vendor matching on a single document. Returns change summary."""
    from services.vendor_matching import lookup_vendor_alias, lookup_vendor_by_sender, learn_sender_vendor
    from services.vendor_name_helpers import normalize_vendor_name
    from services.vendor_resolution_service import build_resolution_object

    doc_id = doc.get("id", "?")
    old_method = doc.get("vendor_match_method", "none")
    old_canonical = doc.get("vendor_canonical")
    old_resolution = doc.get("vendor_resolution") or {}
    old_status = old_resolution.get("status", "none")

    # Check sender email first (learned mapping)
    sender_email = doc.get("email_sender") or ""
    match_result = {"vendor_canonical": None, "vendor_match_method": "none"}
    if sender_email:
        match_result = await lookup_vendor_by_sender(sender_email)

    # Fall back to text-based vendor matching
    if not match_result.get("vendor_canonical"):
        vendor_raw = await _get_vendor_raw(doc)
        if not vendor_raw:
            return {
                "doc_id": doc_id,
                "action": "skipped",
                "reason": "no_vendor_raw_string",
                "old_method": old_method,
            }

        vendor_normalized = normalize_vendor_name(vendor_raw)
        if not vendor_normalized:
            return {
                "doc_id": doc_id,
                "action": "skipped",
                "reason": "normalized_to_empty",
                "vendor_raw": vendor_raw,
                "old_method": old_method,
            }
        match_result = await lookup_vendor_alias(vendor_normalized)
    else:
        vendor_raw = await _get_vendor_raw(doc)
        vendor_normalized = ""

    new_method = match_result.get("vendor_match_method", "none")
    new_canonical = match_result.get("vendor_canonical")
    new_score = match_result.get("match_score")
    new_resolution_status = match_result.get("resolution_status")

    # Build the resolution object using the correct signature
    resolution = build_resolution_object(vendor_raw, match_result)
    # If the match itself says needs_review, override the resolution status
    if new_resolution_status == "needs_review":
        resolution["status"] = "needs_review"

    changed = (
        new_method != old_method
        or str(new_canonical) != str(old_canonical)
        or resolution.get("status") != old_status
    )

    result = {
        "doc_id": doc_id,
        "vendor_raw": vendor_raw,
        "vendor_normalized": vendor_normalized,
        "old": {
            "method": old_method,
            "canonical": old_canonical,
            "status": old_status,
        },
        "new": {
            "method": new_method,
            "canonical": new_canonical,
            "status": resolution.get("status"),
            "score": new_score,
            "vendor_name": match_result.get("vendor_name"),
            "guardrail_downgraded": match_result.get("guardrail_downgraded", False),
        },
        "changed": changed,
        "action": "would_update" if changed else "no_change",
    }

    if not dry_run and changed:
        db = get_db()
        update = {
            "vendor_match_method": new_method,
            "vendor_resolution": resolution,
        }
        if new_canonical:
            update["vendor_canonical"] = new_canonical
            update["vendor_name"] = match_result.get("vendor_name")
            update["vendor_no"] = match_result.get("vendor_no")
        update["vendor_reprocessed_at"] = datetime.now(timezone.utc).isoformat()

        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})
        result["action"] = "updated"
        
        # LEARN: Record sender→vendor mapping
        if new_canonical and sender_email:
            try:
                await learn_sender_vendor(
                    sender_email=sender_email,
                    vendor_canonical=new_canonical,
                    vendor_name=match_result.get("vendor_name", ""),
                    vendor_no=match_result.get("vendor_no", ""),
                )
            except Exception:
                pass

    return result


@router.post("/run")
async def run_reprocess(
    limit: int = Query(500, ge=1, le=5000),
    force_all: bool = Query(False, description="Re-process even if already processed by new logic"),
):
    """
    Re-process vendor matching on all vendor-applicable documents.
    
    This re-runs lookup_vendor_alias with the fixed logic:
    - Normalized exact match (not regex against raw displayName)
    - Shared fuzzy scorer (calculate_fuzzy_score)
    - fuzzy_match (>=0.90 auto-resolve) vs fuzzy_candidate (<0.90 review)
    """
    global _last_run
    db = get_db()

    _last_run = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    # Find vendor-applicable docs
    match_filter = {
        "$or": [
            {"doc_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"suggested_job_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }
    if not force_all:
        match_filter["vendor_reprocessed_at"] = {"$exists": False}

    cursor = db.hub_documents.find(match_filter, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    results = {
        "total_docs": len(docs),
        "updated": 0,
        "no_change": 0,
        "skipped": 0,
        "errors": 0,
        "method_transitions": {},
        "details": [],
    }

    for doc in docs:
        try:
            r = await _reprocess_single(doc, dry_run=False)
            if r["action"] == "updated":
                results["updated"] += 1
                transition = f"{r['old']['method']} -> {r['new']['method']}"
                results["method_transitions"][transition] = results["method_transitions"].get(transition, 0) + 1
            elif r["action"] == "no_change":
                results["no_change"] += 1
            else:
                results["skipped"] += 1
            results["details"].append(r)
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "doc_id": doc.get("id", "?"),
                "action": "error",
                "error": str(e),
            })
            logger.warning("Reprocess error for %s: %s", doc.get("id"), e)

    _last_run = {
        "status": "complete",
        "started_at": _last_run.get("started_at"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "summary": {k: v for k, v in results.items() if k != "details"},
    }

    logger.info(
        "Vendor re-processing complete: %d docs, %d updated, %d no_change, %d skipped, %d errors",
        results["total_docs"], results["updated"], results["no_change"],
        results["skipped"], results["errors"],
    )

    return results


@router.post("/dry-run")
async def dry_run_reprocess(limit: int = Query(500, ge=1, le=5000)):
    """
    Preview what would change without writing. Returns same structure as /run
    but with action='would_update' instead of 'updated'.
    """
    db = get_db()

    match_filter = {
        "$or": [
            {"doc_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"suggested_job_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }

    cursor = db.hub_documents.find(match_filter, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    results = {
        "total_docs": len(docs),
        "would_update": 0,
        "no_change": 0,
        "skipped": 0,
        "errors": 0,
        "method_transitions": {},
        "details": [],
    }

    for doc in docs:
        try:
            r = await _reprocess_single(doc, dry_run=True)
            if r["action"] == "would_update":
                results["would_update"] += 1
                transition = f"{r['old']['method']} -> {r['new']['method']}"
                results["method_transitions"][transition] = results["method_transitions"].get(transition, 0) + 1
            elif r["action"] == "no_change":
                results["no_change"] += 1
            else:
                results["skipped"] += 1
            results["details"].append(r)
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "doc_id": doc.get("id", "?"),
                "action": "error",
                "error": str(e),
            })

    return results


@router.get("/status")
async def reprocess_status():
    """Check the status/result of the last re-processing run."""
    return _last_run



@router.post("/learn-from-history")
async def learn_sender_mappings_from_history():
    """
    Scan all documents with resolved vendors AND sender emails.
    Record every sender→vendor mapping into the learning table.
    This bootstraps the feedback loop from existing data.
    """
    from services.vendor_matching import learn_sender_vendor
    db = get_db()

    docs = await db.hub_documents.find(
        {
            "vendor_canonical": {"$exists": True, "$ne": None, "$ne": ""},
            "email_sender": {"$exists": True, "$ne": None, "$ne": ""},
        },
        {"_id": 0, "email_sender": 1, "vendor_canonical": 1,
         "vendor_name": 1, "vendor_no": 1, "id": 1}
    ).to_list(5000)

    learned = 0
    senders_seen = set()
    for d in docs:
        sender = (d.get("email_sender") or "").strip()
        vendor = (d.get("vendor_canonical") or "").strip()
        if sender and vendor:
            await learn_sender_vendor(
                sender_email=sender,
                vendor_canonical=vendor,
                vendor_name=d.get("vendor_name", ""),
                vendor_no=d.get("vendor_no", ""),
            )
            learned += 1
            senders_seen.add(sender)

    # Return what was learned
    mappings = await db.sender_vendor_map.find(
        {"sender_email": {"$exists": True}},
        {"_id": 0}
    ).sort("confirmation_count", -1).to_list(100)

    return {
        "docs_scanned": len(docs),
        "mappings_recorded": learned,
        "unique_senders": len(senders_seen),
        "sender_mappings": mappings,
    }


@router.get("/sender-mappings")
async def get_sender_mappings():
    """View all learned sender email → vendor mappings."""
    db = get_db()
    mappings = await db.sender_vendor_map.find(
        {}, {"_id": 0}
    ).sort("confirmation_count", -1).to_list(200)
    return {
        "total": len(mappings),
        "mappings": mappings,
    }


@router.post("/sender-mappings/clear")
async def clear_sender_mappings():
    """
    Delete ALL learned sender→vendor mappings.
    Use this to wipe polluted data before re-running learn-from-history.
    """
    db = get_db()
    result = await db.sender_vendor_map.delete_many({})
    return {
        "status": "cleared",
        "deleted_count": result.deleted_count,
    }


@router.post("/auto-map-domains")
async def auto_map_unresolved_domains(
    dry_run: bool = Query(True),
):
    """
    Automatically map unresolved sender domains to vendors by cross-referencing:
    1. Existing resolved hub_documents (vendor_canonical from alias_match, etc.)
    2. Bakeoff benchmark data (gpi_vendor)
    3. Domain name similarity to known vendor names
    """
    from services.vendor_matching import learn_sender_vendor
    from services.vendor_resolution_service import build_resolution_object
    db = get_db()

    EXCLUDED_DOMAINS = {"gamerpackaging.com"}

    # Step 1: Get all unresolved domains
    pipeline = [
        {"$match": {"vendor_match_method": {"$in": ["none", None]},
                     "email_sender": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$addFields": {"_domain": {"$arrayElemAt": [{"$split": ["$email_sender", "@"]}, 1]}}},
        {"$group": {"_id": "$_domain", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    unresolved = await db.hub_documents.aggregate(pipeline).to_list(200)

    # Step 2: Build known vendor name list from resolved docs
    vendor_pipeline = [
        {"$match": {"vendor_canonical": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$vendor_canonical",
                     "vendor_name": {"$first": "$vendor_name"},
                     "vendor_no": {"$first": "$vendor_no"},
                     "count": {"$sum": 1}}},
    ]
    known_vendors = await db.hub_documents.aggregate(vendor_pipeline).to_list(500)

    # Also pull from bakeoff
    bakeoff_vendors = await db.bakeoff_documents.aggregate([
        {"$match": {"gpi_vendor": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$group": {"_id": "$gpi_vendor", "count": {"$sum": 1}}},
    ]).to_list(500)

    # Merge into a lookup: normalized name → {canonical, vendor_name, vendor_no}
    vendor_lookup = {}
    for v in known_vendors:
        canonical = v["_id"]
        if not canonical:
            continue
        name = v.get("vendor_name") or canonical
        vendor_lookup[canonical.lower()] = {
            "vendor_canonical": canonical, "vendor_name": name,
            "vendor_no": v.get("vendor_no") or canonical,
        }
        vendor_lookup[name.lower()] = vendor_lookup[canonical.lower()]

    for v in bakeoff_vendors:
        name = v["_id"]
        nl = name.lower()
        if nl not in vendor_lookup:
            vendor_lookup[nl] = {
                "vendor_canonical": name, "vendor_name": name, "vendor_no": "",
            }

    # Step 3: Match domains to vendors
    import re
    mappings = []
    for entry in unresolved:
        domain = entry["_id"]
        doc_count = entry["count"]
        if not domain or domain in EXCLUDED_DOMAINS:
            continue

        # Extract company-like tokens from domain (e.g., "citi-cargo.com" → "citi cargo")
        domain_base = domain.rsplit(".", 1)[0]  # remove TLD
        domain_tokens = re.split(r'[-_.]', domain_base)
        domain_search = " ".join(domain_tokens).lower()

        best_match = None
        best_score = 0

        for key, vendor in vendor_lookup.items():
            # Check if domain tokens appear in vendor name
            key_lower = key.lower()
            score = 0
            for token in domain_tokens:
                if len(token) >= 3 and token.lower() in key_lower:
                    score += len(token)

            # Also check reverse: vendor name tokens in domain
            for vtoken in re.split(r'[\s\-_&,.]', key_lower):
                if len(vtoken) >= 3 and vtoken in domain_search:
                    score += len(vtoken)

            if score > best_score:
                best_score = score
                best_match = vendor

        if best_match and best_score >= 5:
            mappings.append({
                "domain": domain,
                "docs": doc_count,
                "vendor_canonical": best_match["vendor_canonical"],
                "vendor_name": best_match["vendor_name"],
                "vendor_no": best_match["vendor_no"],
                "confidence_score": best_score,
            })

    # Step 4: Apply if not dry_run
    total_resolved = 0
    if not dry_run:
        now = datetime.now(timezone.utc).isoformat()
        for m in mappings:
            # Create domain mapping
            await db.sender_vendor_map.update_one(
                {"sender_domain": m["domain"], "sender_email": {"$exists": False}},
                {"$set": {
                    "sender_domain": m["domain"],
                    "vendor_canonical": m["vendor_canonical"],
                    "vendor_name": m["vendor_name"],
                    "vendor_no": m["vendor_no"],
                    "domain_confidence": max(m["docs"], 5),
                    "source": "auto_map",
                    "updated_at": now,
                }, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            # Resolve docs
            match_result = {
                "vendor_canonical": m["vendor_canonical"],
                "vendor_match_method": "sender_domain",
                "vendor_name": m["vendor_name"],
                "vendor_no": m["vendor_no"],
            }
            docs = await db.hub_documents.find(
                {"vendor_match_method": {"$in": ["none", None]},
                 "email_sender": {"$regex": f"@{m['domain']}$", "$options": "i"}},
                {"_id": 0, "id": 1, "email_sender": 1, "vendor_name_raw": 1, "extracted_fields": 1}
            ).to_list(5000)
            for doc in docs:
                vendor_raw = (doc.get("vendor_name_raw") or
                              (doc.get("extracted_fields") or {}).get("vendor") or "")
                resolution = build_resolution_object(vendor_raw, match_result)
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "vendor_canonical": m["vendor_canonical"],
                        "vendor_match_method": "sender_domain",
                        "vendor_name": m["vendor_name"],
                        "vendor_no": m["vendor_no"],
                        "vendor_resolution": resolution,
                        "vendor_reprocessed_at": now,
                    }}
                )
                total_resolved += 1
                sender = (doc.get("email_sender") or "").strip()
                if sender:
                    try:
                        await learn_sender_vendor(sender, m["vendor_canonical"],
                                                   m["vendor_name"], m["vendor_no"])
                    except Exception:
                        pass

    return {
        "dry_run": dry_run,
        "mappings_found": len(mappings),
        "total_would_resolve": sum(m["docs"] for m in mappings),
        "total_resolved": total_resolved,
        "mappings": mappings,
        "unmapped_domains": [
            {"domain": e["_id"], "docs": e["count"]}
            for e in unresolved
            if e["_id"] and e["_id"] not in EXCLUDED_DOMAINS
            and not any(m["domain"] == e["_id"] for m in mappings)
        ][:20],
    }


@router.post("/teach-domain")
async def teach_domain_vendor(
    domain: str = Query(..., description="Email domain (e.g. valleydist.com)"),
    vendor_canonical: str = Query(..., description="BC vendor code (e.g. VALLEY)"),
    vendor_name: str = Query("", description="Vendor display name"),
    vendor_no: str = Query("", description="BC vendor number"),
    dry_run: bool = Query(False),
):
    """
    Teach the system that a sender domain maps to a specific vendor.
    1. Creates a sender domain mapping in the learning table
    2. Resolves ALL unresolved docs from that domain
    """
    from services.vendor_matching import learn_sender_vendor
    from services.vendor_resolution_service import build_resolution_object
    db = get_db()

    domain = domain.strip().lower()
    if not vendor_no:
        vendor_no = vendor_canonical

    # Find all unresolved docs from this domain
    docs = await db.hub_documents.find(
        {
            "vendor_match_method": {"$in": ["none", None]},
            "email_sender": {"$regex": f"@{domain}$", "$options": "i"},
        },
        {"_id": 0, "id": 1, "email_sender": 1, "vendor_name_raw": 1, "extracted_fields": 1}
    ).to_list(5000)

    if dry_run:
        return {
            "domain": domain,
            "vendor_canonical": vendor_canonical,
            "docs_found": len(docs),
            "action": "dry_run — no changes made",
        }

    # Create/update the domain mapping
    now = datetime.now(timezone.utc).isoformat()
    await db.sender_vendor_map.update_one(
        {"sender_domain": domain, "sender_email": {"$exists": False}},
        {"$set": {
            "sender_domain": domain,
            "vendor_canonical": vendor_canonical,
            "vendor_name": vendor_name,
            "vendor_no": vendor_no,
            "domain_confidence": max(len(docs), 5),
            "source": "manual_teach",
            "updated_at": now,
        }, "$setOnInsert": {"created_at": now}},
        upsert=True,
    )

    # Resolve all matching docs
    resolved = 0
    match_result = {
        "vendor_canonical": vendor_canonical,
        "vendor_match_method": "sender_domain",
        "vendor_name": vendor_name,
        "vendor_no": vendor_no,
    }
    for doc in docs:
        vendor_raw = (doc.get("vendor_name_raw") or
                      (doc.get("extracted_fields") or {}).get("vendor") or "")
        resolution = build_resolution_object(vendor_raw, match_result)
        await db.hub_documents.update_one(
            {"id": doc["id"]},
            {"$set": {
                "vendor_canonical": vendor_canonical,
                "vendor_match_method": "sender_domain",
                "vendor_name": vendor_name,
                "vendor_no": vendor_no,
                "vendor_resolution": resolution,
                "vendor_reprocessed_at": now,
            }}
        )
        resolved += 1

        # Also learn each individual email
        sender = (doc.get("email_sender") or "").strip()
        if sender:
            try:
                await learn_sender_vendor(sender, vendor_canonical, vendor_name, vendor_no)
            except Exception:
                pass

    return {
        "domain": domain,
        "vendor_canonical": vendor_canonical,
        "docs_found": len(docs),
        "resolved": resolved,
    }


@router.get("/unresolved-domains")
async def list_unresolved_domains():
    """List all sender domains with unresolved vendor docs, sorted by count."""
    db = get_db()
    pipeline = [
        {"$match": {"vendor_match_method": {"$in": ["none", None]},
                     "email_sender": {"$exists": True, "$ne": None, "$ne": ""}}},
        {"$addFields": {"_domain": {"$arrayElemAt": [{"$split": ["$email_sender", "@"]}, 1]}}},
        {"$group": {"_id": "$_domain", "count": {"$sum": 1},
                     "sample_sender": {"$first": "$email_sender"}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(50)
    return {
        "total_unresolved_domains": len(results),
        "domains": [{"domain": r["_id"], "count": r["count"],
                      "sample": r.get("sample_sender", "")} for r in results],
    }


@router.post("/resolve-by-sender")
async def resolve_unresolved_by_sender(
    limit: int = Query(2000, ge=1, le=5000),
    dry_run: bool = Query(False),
):
    """
    Find ALL docs with vendor_match_method='none' that have an email_sender,
    and try to resolve them via sender email/domain lookup.
    No doc_type restriction — this catches docs the main reprocess misses.
    """
    from services.vendor_matching import lookup_vendor_by_sender, learn_sender_vendor
    from services.vendor_resolution_service import build_resolution_object
    db = get_db()

    EXCLUDED_SENDER_DOMAINS = {"gamerpackaging.com"}

    docs = await db.hub_documents.find(
        {
            "vendor_match_method": {"$in": ["none", None]},
            "email_sender": {"$exists": True, "$ne": None, "$ne": ""},
        },
        {"_id": 0, "id": 1, "email_sender": 1, "vendor_canonical": 1,
         "vendor_match_method": 1, "vendor_resolution": 1,
         "vendor_name_raw": 1, "extracted_fields": 1}
    ).limit(limit).to_list(limit)

    resolved = 0
    skipped_internal = 0
    no_match = 0
    already_resolved = 0
    details = []

    for doc in docs:
        doc_id = doc.get("id", "?")
        sender = (doc.get("email_sender") or "").strip().lower()
        domain = sender.split("@")[-1] if "@" in sender else ""

        if domain in EXCLUDED_SENDER_DOMAINS:
            skipped_internal += 1
            continue

        if doc.get("vendor_canonical"):
            already_resolved += 1
            continue

        match_result = await lookup_vendor_by_sender(sender)
        vendor = match_result.get("vendor_canonical")

        if not vendor:
            # Try domain-level: find ANY email mapping from this domain
            domain_entries = await db.sender_vendor_map.find(
                {"sender_domain": domain, "vendor_canonical": {"$exists": True, "$ne": None}},
                {"_id": 0, "vendor_canonical": 1, "vendor_name": 1, "vendor_no": 1}
            ).to_list(50)
            # Only use domain if ALL entries agree on the same vendor
            vendors_seen = set(e["vendor_canonical"] for e in domain_entries if e.get("vendor_canonical"))
            if len(vendors_seen) == 1:
                v = domain_entries[0]
                match_result = {
                    "vendor_canonical": v["vendor_canonical"],
                    "vendor_match_method": "sender_domain",
                    "vendor_name": v.get("vendor_name", ""),
                    "vendor_no": v.get("vendor_no", ""),
                }
                vendor = v["vendor_canonical"]

        if not vendor:
            no_match += 1
            if len(details) < 30:
                details.append({"doc_id": doc_id, "sender": sender, "action": "no_match"})
            continue

        if dry_run:
            resolved += 1
            details.append({"doc_id": doc_id, "sender": sender, "vendor": vendor, "action": "would_resolve"})
            continue

        vendor_raw = (doc.get("vendor_name_raw") or
                      (doc.get("extracted_fields") or {}).get("vendor") or "")
        resolution = build_resolution_object(vendor_raw, match_result)

        update = {
            "vendor_canonical": vendor,
            "vendor_match_method": match_result.get("vendor_match_method", "sender_domain"),
            "vendor_name": match_result.get("vendor_name", ""),
            "vendor_no": match_result.get("vendor_no", ""),
            "vendor_resolution": resolution,
            "vendor_reprocessed_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})
        resolved += 1

        # Reinforce learning
        try:
            await learn_sender_vendor(
                sender_email=sender,
                vendor_canonical=vendor,
                vendor_name=match_result.get("vendor_name", ""),
                vendor_no=match_result.get("vendor_no", ""),
            )
        except Exception:
            pass

        if len(details) < 30:
            details.append({"doc_id": doc_id, "sender": sender, "vendor": vendor, "action": "resolved"})

    return {
        "total_scanned": len(docs),
        "resolved": resolved,
        "no_match": no_match,
        "skipped_internal": skipped_internal,
        "already_resolved": already_resolved,
        "dry_run": dry_run,
        "sample_details": details,
    }
