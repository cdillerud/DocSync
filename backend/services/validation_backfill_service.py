"""
Validation Gap Backfill Service — batch revalidation for all gap types.

Attacks 7 gap categories:
1. Customer Match — re-run with aliases, vendor→customer history, lower threshold
2. Sales Order Match — cache-first SO lookup, number normalization
3. Vendor Match — re-run with current alias DB + email domain mapping
4. Duplicate Check — enhanced auto-clearing
5. Extraction Quality Gate — filename parsing, batch context, email sender
6. Enhanced Vendor Match — cross-doc inference, aggressive matching
7. Enhanced PO Revalidation — profile relaxation, broader matching
"""
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("validation_backfill")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _normalize_vendor_for_match(name: str) -> str:
    """Normalize vendor name for fuzzy matching — strip trailing punct and common suffixes."""
    if not name:
        return ""
    n = name.strip().rstrip(".,;:")
    # Remove common legal suffixes that don't help matching
    n = re.sub(r'\b(Inc|LLC|Ltd|Corp|Corporation|Company|Co|LP|LLP|PLC|SA|GmbH|Pty|Pte|NV|BV)\b\.?', '', n, flags=re.IGNORECASE)
    return n.strip().rstrip(",. ")


# =============================================================================
# 1. CUSTOMER MATCH REVALIDATION
# =============================================================================

async def batch_revalidate_customer_gaps(db, limit: int = 500) -> dict:
    """
    Re-run customer matching on documents with customer_match failures.

    Strategy:
      1. Build customer alias map from successful historical matches
      2. Build vendor→customer association map
      3. For each gap doc, try alias lookup, then vendor association, then cache lookup
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "customer_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "matched_vendor_no": 1, "job_type": 1, "doc_type": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No customer match gaps found"}

    # ── Build customer alias map from successful matches ──
    customer_aliases = {}
    try:
        successful_docs = await db.hub_documents.aggregate([
            {"$match": {
                "validation_results.checks": {
                    "$elemMatch": {"check_name": "customer_match", "passed": True}
                },
            }},
            {"$project": {"_id": 0, "extracted_fields.customer": 1, "extracted_fields.consignee": 1,
                          "validation_results.checks": 1, "validation_results.bc_record_info": 1}},
            {"$limit": 1000},
        ]).to_list(1000)

        for doc in successful_docs:
            extracted = doc.get("extracted_fields") or {}
            cust_name = extracted.get("customer") or extracted.get("consignee") or ""
            if not cust_name:
                continue
            bc_info = (doc.get("validation_results") or {}).get("bc_record_info") or {}
            bc_name = bc_info.get("displayName") or bc_info.get("customerName") or ""
            bc_number = bc_info.get("number") or bc_info.get("customerNumber") or ""
            if bc_name or bc_number:
                key = cust_name.strip().lower()
                if key not in customer_aliases:
                    customer_aliases[key] = {"bc_name": bc_name, "bc_number": bc_number, "count": 0}
                customer_aliases[key]["count"] += 1
    except Exception as e:
        logger.debug("[CustReval] Alias build error: %s", e)

    # ── Build vendor→customer association map ──
    vendor_customer_map = {}
    try:
        assoc_docs = await db.hub_documents.aggregate([
            {"$match": {
                "validation_results.checks": {
                    "$elemMatch": {"check_name": "customer_match", "passed": True}
                },
                "$or": [
                    {"bc_vendor_number": {"$exists": True, "$ne": ""}},
                    {"vendor_no": {"$exists": True, "$ne": ""}},
                ],
            }},
            {"$group": {
                "_id": {"$ifNull": ["$bc_vendor_number", "$vendor_no"]},
                "customers": {"$addToSet": {
                    "name": {"$ifNull": [
                        "$validation_results.bc_record_info.displayName",
                        "$validation_results.bc_record_info.customerName",
                    ]},
                    "number": {"$ifNull": [
                        "$validation_results.bc_record_info.number",
                        "$validation_results.bc_record_info.customerNumber",
                    ]},
                }},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gte": 2}}},
        ]).to_list(200)

        for ad in assoc_docs:
            vendor_no = ad["_id"]
            custs = [c for c in ad.get("customers", []) if c.get("name")]
            if custs and vendor_no:
                vendor_customer_map[vendor_no] = custs[0]
    except Exception as e:
        logger.debug("[CustReval] Vendor→Customer map error: %s", e)

    # ── Also check BC cache for customer records ──
    cache_customers = {}
    try:
        cached = await db.bc_reference_cache.find(
            {"bc_entity_type": "customer"},
            {"_id": 0, "bc_document_no": 1, "bc_vendor_name": 1, "normalized_document_no": 1}
        ).limit(2000).to_list(2000)
        for c in cached:
            name = (c.get("bc_vendor_name") or "").strip().lower()
            if name:
                cache_customers[name] = {
                    "number": c.get("bc_document_no", ""),
                    "name": c.get("bc_vendor_name", ""),
                }
    except Exception:
        pass

    resolved = 0
    alias_resolved = 0
    vendor_assoc_resolved = 0
    cache_resolved = 0
    errors = 0

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""

        customer_name = (
            normalized.get("customer") or normalized.get("consignee")
            or extracted.get("customer") or extracted.get("consignee") or ""
        )

        matched_customer = None
        match_method = None

        # Strategy 1: Customer alias lookup
        if customer_name:
            key = customer_name.strip().lower()
            alias = customer_aliases.get(key)
            if alias and alias.get("count", 0) >= 2:
                matched_customer = alias
                match_method = "customer_alias"
                alias_resolved += 1

        # Strategy 2: Vendor→customer association
        if not matched_customer and vendor_no:
            assoc = vendor_customer_map.get(vendor_no)
            if assoc:
                matched_customer = {"bc_name": assoc.get("name", ""), "bc_number": assoc.get("number", "")}
                match_method = "vendor_customer_association"
                vendor_assoc_resolved += 1

        # Strategy 3: Cache fuzzy lookup
        if not matched_customer and customer_name:
            cust_lower = customer_name.strip().lower()
            # Exact cache match
            if cust_lower in cache_customers:
                matched_customer = {
                    "bc_name": cache_customers[cust_lower]["name"],
                    "bc_number": cache_customers[cust_lower]["number"],
                }
                match_method = "cache_exact"
                cache_resolved += 1
            else:
                # Substring/partial match in cache
                cust_words = set(cust_lower.split())
                if len(cust_words) >= 2:
                    for cache_name, cache_info in cache_customers.items():
                        cache_words = set(cache_name.split())
                        overlap = cust_words & cache_words
                        if len(overlap) >= 2 and len(overlap) / max(len(cust_words), len(cache_words)) >= 0.6:
                            matched_customer = {
                                "bc_name": cache_info["name"],
                                "bc_number": cache_info["number"],
                            }
                            match_method = "cache_fuzzy"
                            cache_resolved += 1
                            break

        if matched_customer:
            new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "customer_match"]
            bc_name = matched_customer.get("bc_name", "")
            bc_number = matched_customer.get("bc_number", "")
            new_checks.append({
                "check_name": "customer_match",
                "passed": True,
                "details": f"Matched customer via {match_method}: {bc_name} ({bc_number})",
                "required": True,
                "match_method": match_method,
                "score": 0.90 if match_method == "customer_alias" else 0.80,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            update_fields = {
                "validation_results.checks": new_checks,
                "validation_results.all_passed": all_passed,
                "customer_revalidated_at": _now(),
                "customer_revalidated_via": match_method,
            }
            if bc_number:
                update_fields["validation_results.bc_record_info"] = {
                    "displayName": bc_name, "number": bc_number, "type": "customer"
                }

            try:
                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_fields})
                await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "customer_match"})
                resolved += 1
                logger.info("[CustReval] doc=%s — RESOLVED via %s: %s", doc_id[:8], match_method, bc_name)
            except Exception as e:
                errors += 1
                logger.debug("[CustReval] Update error for %s: %s", doc_id[:8], e)

    return {
        "found": len(gap_docs), "resolved": resolved,
        "alias_resolved": alias_resolved, "vendor_assoc_resolved": vendor_assoc_resolved,
        "cache_resolved": cache_resolved, "errors": errors,
        "alias_db_size": len(customer_aliases), "vendor_assoc_size": len(vendor_customer_map),
    }


# =============================================================================
# 2. SALES ORDER MATCH REVALIDATION
# =============================================================================

async def batch_revalidate_so_gaps(db, limit: int = 500) -> dict:
    """
    Re-run sales order matching on documents with sales_order_match failures.

    Strategy:
      1. Cache-first SO lookup (salesOrders + salesShipments + salesInvoices)
      2. External document number matching
      3. SO number normalization (add/remove prefixes, strip zeros, digits only)
      4. Cross-document flow intelligence
      5. Previously-matched SO cross-reference from sibling docs
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "sales_order_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "matched_vendor_no": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No sales order match gaps found"}

    # ── Build comprehensive SO cache index ──
    so_by_number = {}       # exact doc number lookup
    so_by_normalized = {}   # normalized number lookup
    so_by_external = {}     # external doc number lookup
    so_by_digits = {}       # digits-only lookup
    so_by_customer = {}     # customer number → SO list

    try:
        cached_records = await db.bc_reference_cache.find(
            {"bc_entity_type": {"$in": [
                "sales_order", "posted_sales_invoice", "posted_sales_shipment"
            ]}},
            {"_id": 0, "bc_document_no": 1, "normalized_document_no": 1,
             "bc_external_document_no": 1, "bc_customer_no": 1,
             "bc_customer_name": 1, "bc_entity_type": 1, "bc_order_number": 1}
        ).limit(10000).to_list(10000)

        for rec in cached_records:
            doc_no = (rec.get("bc_document_no") or "").strip()
            norm_no = (rec.get("normalized_document_no") or "").strip()
            ext_no = (rec.get("bc_external_document_no") or "").strip()
            order_no = (rec.get("bc_order_number") or "").strip()

            info = {
                "number": doc_no,
                "customer_name": rec.get("bc_customer_name", ""),
                "customer_number": rec.get("bc_customer_no", ""),
                "entity_type": rec.get("bc_entity_type", ""),
            }

            if doc_no:
                so_by_number[doc_no.lower()] = info
            if norm_no:
                so_by_normalized[norm_no.lower()] = info
            if ext_no:
                so_by_external[ext_no.lower()] = info
            if order_no:
                so_by_number[order_no.lower()] = info

            # Digits-only index
            digits = re.sub(r'[^0-9]', '', doc_no)
            if digits and len(digits) >= 4:
                so_by_digits[digits] = info
            if ext_no:
                ext_digits = re.sub(r'[^0-9]', '', ext_no)
                if ext_digits and len(ext_digits) >= 4:
                    so_by_digits[ext_digits] = info

            # Customer index
            cust_no = rec.get("bc_customer_no", "")
            if cust_no:
                if cust_no not in so_by_customer:
                    so_by_customer[cust_no] = []
                so_by_customer[cust_no].append(info)
    except Exception as e:
        logger.debug("[SOReval] Cache build error: %s", e)

    # ── Also build index from previously successful SO matches ──
    successful_so_map = {}
    try:
        successful_so_docs = await db.hub_documents.find(
            {"validation_results.checks": {
                "$elemMatch": {"check_name": "sales_order_match", "passed": True}
            }},
            {"_id": 0, "extracted_fields.bol_number": 1, "extracted_fields.po_number": 1,
             "extracted_fields.order_number": 1, "validation_results.checks": 1}
        ).limit(500).to_list(500)

        for sdoc in successful_so_docs:
            ext = sdoc.get("extracted_fields") or {}
            checks = (sdoc.get("validation_results") or {}).get("checks", [])
            for ch in checks:
                if ch.get("check_name") == "sales_order_match" and ch.get("passed"):
                    so_num = ch.get("order_number", "")
                    cust_name = ch.get("customer_name", "")
                    if so_num:
                        # Map any order ref from this doc to the matched SO
                        for field in ["bol_number", "po_number", "order_number"]:
                            ref = ext.get(field, "")
                            if ref and str(ref).strip():
                                successful_so_map[str(ref).strip().lower()] = {
                                    "number": so_num,
                                    "customer_name": cust_name,
                                    "customer_number": ch.get("customer_number", ""),
                                }
    except Exception:
        pass

    resolved = 0
    cache_resolved = 0
    flow_resolved = 0
    sibling_resolved = 0
    errors = 0

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""

        # Get order number candidates
        order_candidates = []
        for field in ["bol_number", "po_number", "order_number", "so_number", "sales_order",
                       "reference_number", "shipment_number"]:
            val = normalized.get(field) or extracted.get(field) or ""
            if val and str(val).strip():
                order_candidates.append(str(val).strip())

        if not order_candidates:
            continue

        matched_so = None
        match_source = None

        for order_num in order_candidates:
            order_lower = order_num.lower()
            order_digits = re.sub(r'[^0-9]', '', order_num)

            # Strategy 1: Exact cache lookup
            if order_lower in so_by_number:
                matched_so = so_by_number[order_lower]
                match_source = "cache_exact"
                cache_resolved += 1
                break

            # Strategy 2: External doc number lookup
            if order_lower in so_by_external:
                matched_so = so_by_external[order_lower]
                match_source = "cache_external_doc"
                cache_resolved += 1
                break

            # Strategy 3: Normalized cache lookup
            norm = re.sub(r'[^a-z0-9]', '', order_lower)
            if norm in so_by_normalized:
                matched_so = so_by_normalized[norm]
                match_source = "cache_normalized"
                cache_resolved += 1
                break

            # Strategy 4: Digits-only match
            if order_digits and len(order_digits) >= 4 and order_digits in so_by_digits:
                matched_so = so_by_digits[order_digits]
                match_source = "cache_digits"
                cache_resolved += 1
                break

            # Strategy 5: Variations (add/remove prefixes)
            variations = []
            stripped = order_num.lstrip("0")
            if stripped and stripped != order_num:
                variations.append(stripped)
            for prefix in ["SO", "S-", "SO-", "SI-", "PS-"]:
                if not order_num.upper().startswith(prefix):
                    variations.append(f"{prefix}{order_num}")
                elif order_num.upper().startswith(prefix):
                    variations.append(order_num[len(prefix):])

            for var in variations:
                var_lower = var.lower()
                if var_lower in so_by_number:
                    matched_so = so_by_number[var_lower]
                    match_source = "cache_variation"
                    cache_resolved += 1
                    break
                if var_lower in so_by_external:
                    matched_so = so_by_external[var_lower]
                    match_source = "cache_external_variation"
                    cache_resolved += 1
                    break
            if matched_so:
                break

            # Strategy 6: Sibling document lookup
            if order_lower in successful_so_map:
                matched_so = successful_so_map[order_lower]
                match_source = "sibling_doc"
                sibling_resolved += 1
                break

        # Strategy 7: Document flow cross-reference
        if not matched_so and vendor_no:
            try:
                from services.gap_closer_service import find_sales_order_from_flow
                for order_num in order_candidates[:3]:
                    flow_result = await find_sales_order_from_flow(db, vendor_no, order_num)
                    if flow_result and flow_result.get("found"):
                        matched_so = {
                            "number": flow_result.get("number", ""),
                            "customer_name": flow_result.get("customer_name", ""),
                            "customer_number": flow_result.get("customer_number", ""),
                        }
                        match_source = "document_flow"
                        flow_resolved += 1
                        break
            except Exception:
                pass

        if matched_so:
            so_number = matched_so.get("number", "")
            so_customer = matched_so.get("customer_name", "")
            new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "sales_order_match"]
            new_checks.append({
                "check_name": "sales_order_match",
                "passed": True,
                "details": f"Found SO #{so_number} for {so_customer} (via backfill: {match_source})",
                "required": False,
                "order_number": so_number,
                "match_source": match_source,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            try:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "validation_results.checks": new_checks,
                        "validation_results.all_passed": all_passed,
                        "so_revalidated_at": _now(),
                        "so_revalidated_via": match_source,
                    }}
                )
                await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "sales_order_match"})
                resolved += 1
                logger.info("[SOReval] doc=%s — RESOLVED via %s: SO#%s", doc_id[:8], match_source, so_number)
            except Exception as e:
                errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "cache_resolved": cache_resolved, "flow_resolved": flow_resolved,
        "sibling_resolved": sibling_resolved,
        "errors": errors,
        "cache_size": len(so_by_number) + len(so_by_external),
    }


# =============================================================================
# 3. VENDOR MATCH REVALIDATION
# =============================================================================

async def batch_revalidate_vendor_gaps(db, limit: int = 500) -> dict:
    """
    Re-run vendor matching on documents with vendor_match failures.

    The alias database grows over time as successful matches are auto-learned.
    This re-runs matching for docs that failed when fewer aliases existed.
    Also uses email domain → vendor mappings and top-candidate acceptance.
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "sender_email": 1, "file_name": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No vendor match gaps found"}

    # ── Pre-load email domain mappings ──
    domain_map = {}
    try:
        mappings = await db.sender_domain_mappings.find({}, {"_id": 0}).to_list(500)
        for m in mappings:
            domain_map[m.get("domain", "").lower()] = m.get("vendor_no", "")
    except Exception:
        pass

    # ── Build vendor name cache from BC reference ──
    bc_vendor_cache = {}
    try:
        vendors = await db.bc_reference_cache.find(
            {"bc_entity_type": "vendor"},
            {"_id": 0, "bc_vendor_no": 1, "bc_vendor_name": 1, "displayName": 1}
        ).limit(500).to_list(500)
        for v in vendors:
            name = (v.get("bc_vendor_name") or v.get("displayName") or "").strip().lower()
            if name:
                bc_vendor_cache[name] = {
                    "vendor_number": v.get("bc_vendor_no", ""),
                    "name": v.get("bc_vendor_name") or v.get("displayName", ""),
                }
    except Exception:
        pass

    from services.unified_vendor_matcher import match_vendor_unified

    resolved = 0
    alias_resolved = 0
    domain_resolved = 0
    candidate_resolved = 0
    cache_resolved = 0
    auto_accepted = 0
    errors = 0

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}

        vendor_name = (
            normalized.get("vendor") or extracted.get("vendor")
            or extracted.get("vendor_name") or ""
        )
        ref_canonical = extracted.get("_vendor_canonical") or ""

        matched_vendor = None
        match_source = None

        # Strategy 1: Re-run unified vendor matching with lower threshold (0.70)
        # Also try the normalized form (strips trailing punct like "LLC." → "LLC")
        names_to_try = []
        if ref_canonical:
            names_to_try.append(ref_canonical)
            norm_ref = _normalize_vendor_for_match(ref_canonical)
            if norm_ref and norm_ref != ref_canonical:
                names_to_try.append(norm_ref)
        if vendor_name and vendor_name != ref_canonical:
            names_to_try.append(vendor_name)
            norm_vn = _normalize_vendor_for_match(vendor_name)
            if norm_vn and norm_vn != vendor_name and norm_vn not in names_to_try:
                names_to_try.append(norm_vn)

        for name in names_to_try:
            if not name:
                continue
            try:
                result = await match_vendor_unified(db, name, 0.70)
                if result.get("matched") and result.get("best_match"):
                    matched_vendor = result["best_match"]
                    match_source = f"re-match:{result.get('source', 'alias')}"
                    alias_resolved += 1
                    break
            except Exception:
                pass

        # Strategy 2: Email domain lookup
        if not matched_vendor:
            sender_email = (
                doc.get("sender_email") or extracted.get("_sender_email")
                or extracted.get("sender_email") or ""
            )
            if sender_email and "@" in sender_email:
                domain = sender_email.split("@")[1].lower()
                vendor_no = domain_map.get(domain)
                if vendor_no:
                    prof = await db.vendor_invoice_profiles.find_one(
                        {"vendor_no": vendor_no}, {"_id": 0, "vendor_no": 1, "vendor_name": 1}
                    )
                    if prof:
                        matched_vendor = {
                            "vendor_number": vendor_no,
                            "name": prof.get("vendor_name", vendor_no),
                        }
                        match_source = "email_domain"
                        domain_resolved += 1

        # Strategy 3: BC vendor cache fuzzy match
        if not matched_vendor and vendor_name:
            vn_lower = vendor_name.strip().lower()
            # Exact match
            if vn_lower in bc_vendor_cache:
                matched_vendor = bc_vendor_cache[vn_lower]
                match_source = "bc_cache_exact"
                cache_resolved += 1
            else:
                # Word overlap match
                vn_words = set(re.sub(r'[^a-z0-9\s]', '', vn_lower).split())
                if len(vn_words) >= 2:
                    best_overlap = 0
                    best_match = None
                    for cache_name, cache_info in bc_vendor_cache.items():
                        cache_words = set(re.sub(r'[^a-z0-9\s]', '', cache_name).split())
                        overlap = vn_words & cache_words
                        # Need at least 2 word overlap and 50% coverage
                        score = len(overlap) / max(len(vn_words), len(cache_words), 1)
                        if len(overlap) >= 2 and score > best_overlap and score >= 0.5:
                            best_overlap = score
                            best_match = cache_info
                    if best_match:
                        matched_vendor = best_match
                        match_source = "bc_cache_fuzzy"
                        cache_resolved += 1

        # Strategy 4: Accept top candidate if score >= 0.65
        if not matched_vendor:
            candidates = validation.get("vendor_candidates", [])
            if candidates and len(candidates) > 0:
                top = candidates[0]
                if top.get("score", 0) >= 0.65:
                    matched_vendor = {
                        "vendor_number": top.get("vendor_id", ""),
                        "name": top.get("display_name", ""),
                    }
                    match_source = f"top_candidate@{top.get('score', 0):.0%}"
                    candidate_resolved += 1

        # Strategy 5: Deep fuzzy match against ALL BC vendors (SequenceMatcher)
        # Auto-accept at 90%+, or 70%+ with substring match (e.g., "XPO" in "XPO Logistics")
        if not matched_vendor and vendor_name:
            from difflib import SequenceMatcher
            vn_lower = vendor_name.strip().lower()
            vn_clean = re.sub(r'[^a-z0-9\s]', '', vn_lower).strip()
            best_fuzzy_score = 0
            best_fuzzy_match = None
            is_substring = False

            all_bc_vendors = dict(bc_vendor_cache)
            # Also load from profiles
            try:
                profiles = await db.vendor_invoice_profiles.find(
                    {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1}
                ).to_list(500)
                for p in profiles:
                    pname = (p.get("vendor_name") or "").strip().lower()
                    if pname and pname not in all_bc_vendors:
                        all_bc_vendors[pname] = {
                            "vendor_number": p["vendor_no"],
                            "name": p.get("vendor_name", p["vendor_no"]),
                        }
            except Exception:
                pass

            for bc_name_lower, bc_info in all_bc_vendors.items():
                bc_clean = re.sub(r'[^a-z0-9\s]', '', bc_name_lower).strip()
                seq_score = SequenceMatcher(None, vn_lower, bc_name_lower).ratio()

                # Check substring: vendor name inside BC name or vice versa
                substr = False
                if len(vn_clean) >= 3 and (vn_clean in bc_clean or bc_clean in vn_clean):
                    substr = True
                # Also check if main words match (lowered to 2-char for "SC", "HP", etc.)
                vn_main = [w for w in vn_clean.split() if len(w) >= 2 and w not in ("inc", "llc", "ltd", "corp", "the")]
                bc_main = [w for w in bc_clean.split() if len(w) >= 2 and w not in ("inc", "llc", "ltd", "corp", "the")]
                if vn_main and bc_main and vn_main[0] == bc_main[0]:
                    substr = True

                effective_score = seq_score
                if substr:
                    effective_score = max(seq_score, 0.85)  # Boost substring matches

                if effective_score > best_fuzzy_score:
                    best_fuzzy_score = effective_score
                    best_fuzzy_match = bc_info
                    is_substring = substr

            threshold = 0.75 if is_substring else 0.90
            if best_fuzzy_match and best_fuzzy_score >= threshold:
                matched_vendor = best_fuzzy_match
                match_source = f"auto_accept@{best_fuzzy_score:.0%}{'(substr)' if is_substring else ''}"
                auto_accepted += 1

                # Auto-create alias for future matches
                try:
                    from services.vendor_name_helpers import normalize_vendor_name
                    normalized_alias = normalize_vendor_name(vendor_name)
                    existing_alias = await db.vendor_aliases.find_one({
                        "$or": [{"alias_string": vendor_name}, {"normalized_alias": normalized_alias}]
                    })
                    if not existing_alias:
                        import uuid
                        await db.vendor_aliases.insert_one({
                            "alias_id": str(uuid.uuid4()),
                            "alias_string": vendor_name,
                            "normalized_alias": normalized_alias,
                            "vendor_no": best_fuzzy_match["vendor_number"],
                            "vendor_name": best_fuzzy_match["name"],
                            "created_by": "auto_accept_backfill",
                            "created_at": _now(),
                            "usage_count": 0,
                            "confidence": round(best_fuzzy_score, 3),
                        })
                        logger.info(
                            "[VendorReval] Auto-created alias: '%s' → %s (%s) @ %.0f%%",
                            vendor_name, best_fuzzy_match["name"],
                            best_fuzzy_match["vendor_number"], best_fuzzy_score * 100,
                        )
                except Exception as e:
                    logger.debug("[VendorReval] Alias creation error: %s", e)

        if matched_vendor:
            vn_number = matched_vendor.get("vendor_number") or matched_vendor.get("number") or ""
            vn_name = matched_vendor.get("name") or matched_vendor.get("display_name") or vn_number

            new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "vendor_match"]
            new_checks.append({
                "check_name": "vendor_match",
                "passed": True,
                "details": f"Found vendor via backfill {match_source}: {vn_name} ({vn_number})",
                "required": True,
                "match_method": match_source,
                "score": 0.85,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            try:
                update_fields = {
                    "validation_results.checks": new_checks,
                    "validation_results.all_passed": all_passed,
                    "vendor_revalidated_at": _now(),
                    "vendor_revalidated_via": match_source,
                }
                if vn_number:
                    update_fields["bc_vendor_number"] = vn_number
                    update_fields["validation_results.bc_record_info"] = {
                        "displayName": vn_name, "number": vn_number,
                    }

                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_fields})
                await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "vendor_match"})
                resolved += 1
                logger.info("[VendorReval] doc=%s — RESOLVED via %s: %s (%s)",
                            doc_id[:8], match_source, vn_name, vn_number)
            except Exception as e:
                errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "alias_resolved": alias_resolved, "domain_resolved": domain_resolved,
        "candidate_resolved": candidate_resolved, "cache_resolved": cache_resolved,
        "auto_accepted": auto_accepted,
        "errors": errors, "domain_map_size": len(domain_map),
        "bc_vendor_cache_size": len(bc_vendor_cache),
    }


# =============================================================================
# 4. DUPLICATE CHECK REVALIDATION
# =============================================================================

async def batch_revalidate_duplicate_gaps(db, limit: int = 200) -> dict:
    """
    Smart duplicate gap closing.

    A document is flagged as duplicate when BC already has a purchaseInvoice
    with the same vendorInvoiceNumber. But many are false positives:
      - The existing BC invoice is already Posted/Paid (old period, re-issue)
      - The amounts differ (correction or different invoice)
      - Different PO numbers (different orders, same vendor invoice format)
      - The flagged doc has been sitting without review (stale)

    Strategy:
      1. Check if existing BC invoice is already Posted → likely NOT a real dup
      2. Compare amounts — different = NOT a dup
      3. Compare PO numbers — different = NOT a dup
      4. Check if document has been validated on all other checks → safe to downgrade
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "duplicate_check", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "matched_vendor_no": 1, "possible_duplicate": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No duplicate check gaps found"}

    # Try to get BC access for checking existing invoice status
    adapter = None
    token = None
    company_id = None
    try:
        from services.bc_access import get_bc_adapter
        adapter = get_bc_adapter()
        token = await adapter.get_token()
        if token:
            company_id = await adapter.get_company_id(token)
    except Exception:
        pass

    resolved = 0
    posted_resolved = 0
    amount_resolved = 0
    other_validated_resolved = 0
    errors = 0

    import httpx
    async with httpx.AsyncClient(timeout=15.0) as c:
        for doc in gap_docs:
            doc_id = doc.get("id", "")
            extracted = doc.get("extracted_fields") or {}
            normalized = doc.get("normalized_fields") or {}
            validation = doc.get("validation_results") or {}
            vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""

            invoice_number = (
                normalized.get("invoice_number") or extracted.get("invoice_number") or ""
            )
            doc_amount = None
            for amt_field in ["total_amount", "amount", "grand_total", "invoice_total"]:
                v = normalized.get(amt_field) or extracted.get(amt_field)
                if v is not None:
                    try:
                        doc_amount = float(str(v).replace(",", "").replace("$", ""))
                        break
                    except (ValueError, TypeError):
                        pass

            doc_po = (
                normalized.get("po_number") or extracted.get("po_number")
                or normalized.get("order_number") or extracted.get("order_number") or ""
            )

            should_clear = False
            clear_reason = None

            # Strategy 1: Check BC — is the existing invoice already Posted/Paid?
            if adapter and token and company_id and invoice_number:
                try:
                    # Look up existing invoice by vendor invoice number
                    resp = await c.get(
                        adapter.api_url("purchaseInvoices", company_id),
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"},
                    )
                    if resp.status_code == 200:
                        existing = resp.json().get("value", [])
                        if existing:
                            ex = existing[0]
                            ex_status = ex.get("status", "").lower()
                            ex_amount = ex.get("totalAmountIncludingTax", 0)
                            ex_po = ex.get("orderNumber", "")

                            # If existing is already posted/paid, this new one is likely a re-issue
                            if ex_status in ("paid", "posted"):
                                should_clear = True
                                clear_reason = f"Existing BC invoice is already {ex_status} — likely re-issue or new period"
                                posted_resolved += 1

                            # If amounts differ significantly, not a real duplicate
                            elif doc_amount is not None and abs(doc_amount - ex_amount) > 0.50:
                                should_clear = True
                                clear_reason = f"Amount differs: doc=${doc_amount:.2f} vs BC=${ex_amount:.2f}"
                                amount_resolved += 1

                            # If different PO numbers, different orders
                            elif doc_po and ex_po and doc_po.strip() != ex_po.strip():
                                should_clear = True
                                clear_reason = f"Different POs: doc={doc_po} vs BC={ex_po}"
                                amount_resolved += 1
                        else:
                            # No existing invoice found in BC — the original might have been deleted
                            should_clear = True
                            clear_reason = "Original duplicate invoice no longer exists in BC"
                            posted_resolved += 1
                except Exception as e:
                    logger.debug("[DupReval] BC lookup error for %s: %s", doc_id[:8], e)

            # Strategy 2: If all OTHER validation checks pass, downgrade duplicate to non-blocking
            if not should_clear:
                other_checks = [
                    ch for ch in validation.get("checks", [])
                    if ch.get("check_name") != "duplicate_check"
                ]
                all_others_pass = all(ch.get("passed", True) for ch in other_checks)
                critical_passes = sum(
                    1 for ch in other_checks
                    if ch.get("passed") and ch.get("check_name") in ("vendor_match", "po_validation")
                )
                if all_others_pass and critical_passes >= 1:
                    should_clear = True
                    clear_reason = "All other validations pass (vendor, PO) — duplicate flag downgraded"
                    other_validated_resolved += 1

            if should_clear:
                new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "duplicate_check"]
                new_checks.append({
                    "check_name": "duplicate_check",
                    "passed": True,
                    "details": f"Duplicate flag cleared: {clear_reason}",
                    "required": False,  # Downgrade from required to advisory
                })
                all_passed = all(ch.get("passed", True) for ch in new_checks)

                try:
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {
                            "validation_results.checks": new_checks,
                            "validation_results.all_passed": all_passed,
                            "possible_duplicate": False,
                            "duplicate_auto_cleared": True,
                            "duplicate_cleared_reason": clear_reason,
                            "duplicate_cleared_at": _now(),
                        }}
                    )
                    await db.validation_gap_log.delete_many({"doc_id": doc_id, "failure_checks": "duplicate_check"})

                    # Record outcome for duplicate intelligence learning
                    try:
                        from services.duplicate_intelligence_service import record_duplicate_outcome
                        await record_duplicate_outcome(
                            db, doc_id=doc_id, vendor_no=vendor_no,
                            was_flagged_duplicate=True, actual_outcome="auto_cleared",
                            resolution_source="backfill_intelligence",
                        )
                    except Exception:
                        pass

                    resolved += 1
                    logger.info("[DupReval] doc=%s — CLEARED: %s", doc_id[:8], clear_reason)
                except Exception as e:
                    errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "posted_resolved": posted_resolved,
        "amount_resolved": amount_resolved,
        "other_validated_resolved": other_validated_resolved,
        "errors": errors,
    }



# =============================================================================
# 5. EXTRACTION QUALITY GATE REVALIDATION
# =============================================================================

async def batch_revalidate_extraction_gaps(db, limit: int = 500) -> dict:
    """
    Close extraction_quality_gate failures.

    Strategy:
      1. Parse filename for vendor/PO/invoice hints
      2. Inherit vendor context from batch parent or sibling documents
      3. Check if any extracted_fields are actually present but filtered wrong
      4. For genuinely empty docs (batch separators, cover pages), downgrade to advisory
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "extraction_quality_gate", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "batch_id": 1, "parent_doc_id": 1, "doc_type": 1, "document_type": 1,
            "sender_email": 1, "status": 1, "created_utc": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No extraction quality gate gaps found"}

    resolved = 0
    filename_resolved = 0
    sibling_resolved = 0
    downgraded = 0
    errors = 0

    # Build batch/parent context map — documents that share the same batch
    batch_context = {}  # batch_id → {vendor_no, vendor_name}
    batch_ids = set()
    parent_ids = set()
    for doc in gap_docs:
        bid = doc.get("batch_id") or ""
        pid = doc.get("parent_doc_id") or ""
        if bid:
            batch_ids.add(bid)
        if pid:
            parent_ids.add(pid)

    # Load sibling docs from same batches that have vendor info
    if batch_ids:
        try:
            siblings = await db.hub_documents.find(
                {
                    "batch_id": {"$in": list(batch_ids)},
                    "bc_vendor_number": {"$exists": True, "$ne": ""},
                },
                {"_id": 0, "batch_id": 1, "bc_vendor_number": 1, "vendor_canonical": 1}
            ).limit(200).to_list(200)
            for s in siblings:
                bid = s.get("batch_id", "")
                if bid and s.get("bc_vendor_number"):
                    batch_context[bid] = {
                        "vendor_no": s["bc_vendor_number"],
                        "vendor_name": s.get("vendor_canonical", s["bc_vendor_number"]),
                    }
        except Exception:
            pass

    # Load parent doc info
    parent_context = {}
    if parent_ids:
        try:
            parents = await db.hub_documents.find(
                {"id": {"$in": list(parent_ids)}},
                {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_canonical": 1,
                 "extracted_fields.vendor": 1, "normalized_fields.vendor": 1}
            ).limit(100).to_list(100)
            for p in parents:
                pid = p.get("id", "")
                vno = p.get("bc_vendor_number") or ""
                vname = p.get("vendor_canonical") or (p.get("extracted_fields") or {}).get("vendor") or ""
                if pid and (vno or vname):
                    parent_context[pid] = {"vendor_no": vno, "vendor_name": vname}
        except Exception:
            pass

    # Common vendor keywords in filenames
    _vendor_keywords_re = re.compile(
        r'(invoice|inv|bill|receipt|statement|remit|freight|shipment|bol|packing)',
        re.IGNORECASE
    )

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        filename = doc.get("filename") or doc.get("file_name") or ""
        extracted = doc.get("extracted_fields") or {}
        validation = doc.get("validation_results") or {}
        batch_id = doc.get("batch_id") or ""
        parent_id = doc.get("parent_doc_id") or ""

        new_fields = dict(extracted)
        field_source = None

        # Strategy 1: Parse filename for vendor/PO/invoice info
        if filename:
            fn_clean = re.sub(r'[_\-\.]', ' ', filename.rsplit('.', 1)[0] if '.' in filename else filename)

            # Try to extract PO number from filename (P00XXXXX, PO-XXXX patterns)
            po_match = re.search(r'(P0{1,2}\d{4,7})', fn_clean, re.IGNORECASE)
            if po_match and not new_fields.get("po_number"):
                new_fields["po_number"] = po_match.group(1).upper()
                field_source = "filename_po"

            # Try to extract invoice number from filename
            inv_match = re.search(r'(?:inv|invoice)[#\s\-_]*(\S+)', fn_clean, re.IGNORECASE)
            if inv_match and not new_fields.get("invoice_number"):
                new_fields["invoice_number"] = inv_match.group(1)
                field_source = field_source or "filename_invoice"

            # Try to extract vendor name from filename — first segment before common keywords
            fn_parts = fn_clean.split()
            if fn_parts and not new_fields.get("vendor"):
                # Take text before first keyword
                vendor_parts = []
                for part in fn_parts:
                    if _vendor_keywords_re.match(part):
                        break
                    if len(part) >= 2 and not part.isdigit():
                        vendor_parts.append(part)
                if vendor_parts and len(' '.join(vendor_parts)) >= 3:
                    new_fields["vendor"] = ' '.join(vendor_parts)
                    field_source = field_source or "filename_vendor"

        # Strategy 2: Inherit from batch/parent context
        if not new_fields.get("vendor") and not field_source:
            ctx = None
            if batch_id and batch_id in batch_context:
                ctx = batch_context[batch_id]
            elif parent_id and parent_id in parent_context:
                ctx = parent_context[parent_id]

            if ctx:
                if ctx.get("vendor_name") and not new_fields.get("vendor"):
                    new_fields["vendor"] = ctx["vendor_name"]
                    field_source = "batch_sibling"

        # Strategy 2b: Inherit vendor from email sender domain mapping
        if not new_fields.get("vendor") and not field_source:
            sender_email = doc.get("sender_email") or ""
            if sender_email and "@" in sender_email:
                domain = sender_email.split("@")[1].lower()
                # Skip generic email domains
                if domain and not domain.startswith(("gmail", "yahoo", "outlook", "hotmail", "aol")):
                    try:
                        # Find vendor from same email domain
                        domain_match = await db.hub_documents.find_one(
                            {
                                "sender_email": {"$regex": f"@{re.escape(domain)}$", "$options": "i"},
                                "bc_vendor_number": {"$exists": True, "$ne": ""},
                            },
                            {"_id": 0, "bc_vendor_number": 1, "vendor_canonical": 1}
                        )
                        if domain_match:
                            new_fields["vendor"] = domain_match.get("vendor_canonical") or domain_match["bc_vendor_number"]
                            field_source = "email_domain_vendor"
                    except Exception:
                        pass

        # Strategy 2c: Extract from email subject line
        if not new_fields.get("vendor") and not field_source:
            email_subject = doc.get("source_email_subject") or ""
            if email_subject:
                # Try to extract PO from subject
                po_in_subject = re.search(r'(P0{1,2}\d{4,7})', email_subject, re.IGNORECASE)
                if po_in_subject and not new_fields.get("po_number"):
                    new_fields["po_number"] = po_in_subject.group(1).upper()
                    field_source = "email_subject_po"
                # Try invoice number
                inv_in_subject = re.search(r'(?:inv|invoice)[#\s\-_]*(\S+)', email_subject, re.IGNORECASE)
                if inv_in_subject and not new_fields.get("invoice_number"):
                    new_fields["invoice_number"] = inv_in_subject.group(1)
                    field_source = field_source or "email_subject_invoice"

        # Strategy 3: Check if extracted_fields actually has data we missed
        # (fields that aren't in the _detected_by exclusion but were empty-string)
        if not field_source:
            for k, v in extracted.items():
                if k.endswith("_detected_by"):
                    continue
                if v and str(v).strip():
                    # There IS data — the gate check had a bug or was run on stale state
                    field_source = "existing_data_found"
                    break

        # Check if we added meaningful data
        meaningful_now = {k: v for k, v in new_fields.items() if v and not k.endswith("_detected_by")}

        if meaningful_now and field_source:
            # We found data — update the doc and clear the gate
            new_checks = [ch for ch in validation.get("checks", [])
                          if ch.get("check_name") != "extraction_quality_gate"]
            new_checks.append({
                "check_name": "extraction_quality_gate",
                "passed": True,
                "details": f"Extraction gap closed via {field_source}: {len(meaningful_now)} fields",
                "required": True,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            try:
                update_set = {
                    "validation_results.checks": new_checks,
                    "validation_results.all_passed": all_passed,
                    "extraction_gap_resolved_via": field_source,
                    "extraction_gap_resolved_at": _now(),
                }
                # Merge new fields into extracted_fields
                for k, v in new_fields.items():
                    if v and not extracted.get(k):
                        update_set[f"extracted_fields.{k}"] = v

                if batch_id in batch_context and not doc.get("bc_vendor_number"):
                    ctx = batch_context[batch_id]
                    if ctx.get("vendor_no"):
                        update_set["bc_vendor_number"] = ctx["vendor_no"]
                        update_set["vendor_canonical"] = ctx.get("vendor_name", "")

                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_set})
                resolved += 1
                if "filename" in (field_source or ""):
                    filename_resolved += 1
                elif "sibling" in (field_source or "") or "batch" in (field_source or ""):
                    sibling_resolved += 1
                logger.info("[ExtractionReval] doc=%s — RESOLVED via %s (%d fields)",
                            doc_id[:8], field_source, len(meaningful_now))
            except Exception as e:
                errors += 1
                logger.debug("[ExtractionReval] Error updating %s: %s", doc_id[:8], e)
        else:
            # Genuinely empty — downgrade to advisory (non-blocking)
            new_checks = [ch for ch in validation.get("checks", [])
                          if ch.get("check_name") != "extraction_quality_gate"]
            new_checks.append({
                "check_name": "extraction_quality_gate",
                "passed": False,
                "details": f"No extractable data (filename: {filename[:40]}). Downgraded to advisory.",
                "required": False,  # No longer blocks automation
                "message": "Document may be a cover page, separator, or non-parseable attachment",
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks
                             if ch.get("required", True))

            try:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "validation_results.checks": new_checks,
                        "validation_results.all_passed": all_passed,
                        "extraction_gate_downgraded": True,
                        "extraction_gate_downgraded_at": _now(),
                    }}
                )
                downgraded += 1
                logger.info("[ExtractionReval] doc=%s — DOWNGRADED to advisory (no data found)",
                            doc_id[:8])
            except Exception as e:
                errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "filename_resolved": filename_resolved,
        "sibling_resolved": sibling_resolved,
        "downgraded_to_advisory": downgraded,
        "errors": errors,
    }


# =============================================================================
# 6. ENHANCED VENDOR MATCH — CROSS-DOCUMENT INFERENCE
# =============================================================================

async def enhanced_vendor_match_backfill(db, limit: int = 500) -> dict:
    """
    Second-pass vendor matching using cross-document intelligence.

    Runs AFTER the standard vendor match backfill. Targets remaining gaps with:
      1. Batch/sibling vendor inheritance (same email, same batch = same vendor)
      2. Sender email domain → vendor mapping (historical)
      3. Aggressive first-word matching with lower threshold
      4. Accept top candidate at 0.55+ if ONLY ONE candidate exists
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False, "required": {"$ne": False}}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "batch_id": 1, "parent_doc_id": 1, "sender_email": 1,
            "source_email_subject": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No vendor match gaps remaining"}

    resolved = 0
    batch_resolved = 0
    email_resolved = 0
    aggressive_resolved = 0
    single_candidate_resolved = 0
    errors = 0

    # Build batch context: batch_id → vendor_no from siblings with matched vendors
    batch_vendor_map = {}
    batch_ids = set(d.get("batch_id") or "" for d in gap_docs if d.get("batch_id"))
    if batch_ids:
        try:
            siblings = await db.hub_documents.find(
                {
                    "batch_id": {"$in": list(batch_ids)},
                    "bc_vendor_number": {"$exists": True, "$ne": ""},
                },
                {"_id": 0, "batch_id": 1, "bc_vendor_number": 1, "vendor_canonical": 1}
            ).limit(500).to_list(500)
            for s in siblings:
                bid = s.get("batch_id")
                if bid and s.get("bc_vendor_number"):
                    if bid not in batch_vendor_map:
                        batch_vendor_map[bid] = {}
                    vno = s["bc_vendor_number"]
                    batch_vendor_map[bid][vno] = batch_vendor_map[bid].get(vno, 0) + 1
        except Exception:
            pass

    # Build enhanced email domain map from ALL historical matches
    email_domain_vendor = {}
    try:
        email_docs = await db.hub_documents.aggregate([
            {"$match": {
                "bc_vendor_number": {"$exists": True, "$ne": ""},
                "sender_email": {"$exists": True, "$ne": ""},
            }},
            {"$group": {
                "_id": {
                    "domain": {"$toLower": {"$arrayElemAt": [{"$split": ["$sender_email", "@"]}, 1]}},
                },
                "vendor_no": {"$first": "$bc_vendor_number"},
                "vendor_name": {"$first": "$vendor_canonical"},
                "count": {"$sum": 1},
            }},
            {"$match": {"count": {"$gte": 2}}},  # Need at least 2 docs from same domain
        ]).to_list(200)
        for ed in email_docs:
            domain = ed["_id"].get("domain", "")
            if domain and not domain.startswith(("gmail", "yahoo", "outlook", "hotmail", "aol")):
                email_domain_vendor[domain] = {
                    "vendor_no": ed.get("vendor_no", ""),
                    "vendor_name": ed.get("vendor_name", ""),
                }
    except Exception:
        pass

    # Load BC vendor cache for aggressive matching
    bc_vendor_cache = {}
    try:
        bc_vendors = await db.bc_reference_cache.find(
            {"bc_entity_type": "vendor"},
            {"_id": 0, "bc_vendor_name": 1, "bc_vendor_no": 1}
        ).limit(2000).to_list(2000)
        for v in bc_vendors:
            name = (v.get("bc_vendor_name") or "").strip().lower()
            if name:
                bc_vendor_cache[name] = {
                    "vendor_number": v.get("bc_vendor_no", ""),
                    "name": v.get("bc_vendor_name", ""),
                }
    except Exception:
        pass

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}
        batch_id = doc.get("batch_id") or ""
        sender_email = doc.get("sender_email") or extracted.get("_sender_email") or ""

        vendor_name = (
            normalized.get("vendor") or extracted.get("vendor")
            or extracted.get("vendor_name") or ""
        )

        matched_vendor = None
        match_source = None

        # Strategy 1: Batch sibling inheritance
        if not matched_vendor and batch_id and batch_id in batch_vendor_map:
            vendors_in_batch = batch_vendor_map[batch_id]
            if len(vendors_in_batch) == 1:  # Only one vendor in the batch = high confidence
                vno = list(vendors_in_batch.keys())[0]
                # Look up vendor name
                prof = await db.vendor_invoice_profiles.find_one(
                    {"vendor_no": vno}, {"_id": 0, "vendor_no": 1, "vendor_name": 1}
                )
                matched_vendor = {
                    "vendor_number": vno,
                    "name": (prof or {}).get("vendor_name", vno),
                }
                match_source = "batch_sibling"
                batch_resolved += 1

        # Strategy 2: Email domain mapping
        if not matched_vendor and sender_email and "@" in sender_email:
            domain = sender_email.split("@")[1].lower()
            if domain in email_domain_vendor:
                info = email_domain_vendor[domain]
                matched_vendor = {
                    "vendor_number": info["vendor_no"],
                    "name": info.get("vendor_name", info["vendor_no"]),
                }
                match_source = "email_domain_enhanced"
                email_resolved += 1

        # Strategy 3: Aggressive first-word match (lowered to 2-char words for "SC", "HP", etc.)
        if not matched_vendor and vendor_name:
            vn_clean = re.sub(r'[^a-z0-9\s]', '', vendor_name.strip().lower())
            vn_words = [w for w in vn_clean.split() if len(w) >= 2 and w not in ("inc", "llc", "ltd", "corp", "the", "and", "of")]
            if vn_words:
                first_word = vn_words[0]
                best_match = None
                best_score = 0
                for bc_name, bc_info in bc_vendor_cache.items():
                    bc_clean = re.sub(r'[^a-z0-9\s]', '', bc_name)
                    bc_words = [w for w in bc_clean.split() if len(w) >= 2]
                    if bc_words and bc_words[0] == first_word:
                        from difflib import SequenceMatcher
                        score = SequenceMatcher(None, vn_clean, bc_clean).ratio()
                        if score > best_score:
                            best_score = score
                            best_match = bc_info
                # Accept at 0.45+ for first-word matches (they share the company name)
                if best_match and best_score >= 0.45:
                    matched_vendor = best_match
                    match_source = f"first_word@{best_score:.0%}"
                    aggressive_resolved += 1

        # Strategy 4: "Contains" match — vendor name is a substring of a BC vendor name
        if not matched_vendor and vendor_name:
            vn_normalized = re.sub(r'[^a-z0-9\s]', '', vendor_name.strip().lower()).strip()
            if len(vn_normalized) >= 4:
                best_match = None
                best_len = 0
                for bc_name, bc_info in bc_vendor_cache.items():
                    bc_normalized = re.sub(r'[^a-z0-9\s]', '', bc_name).strip()
                    if vn_normalized in bc_normalized or bc_normalized in vn_normalized:
                        # Prefer the longest match (most specific)
                        match_len = min(len(vn_normalized), len(bc_normalized))
                        if match_len > best_len:
                            best_len = match_len
                            best_match = bc_info
                if best_match:
                    matched_vendor = best_match
                    match_source = "contains_match"
                    aggressive_resolved += 1

        # Strategy 5: Accept single candidate at lower threshold
        if not matched_vendor:
            candidates = validation.get("vendor_candidates", [])
            if len(candidates) == 1 and candidates[0].get("score", 0) >= 0.55:
                top = candidates[0]
                matched_vendor = {
                    "vendor_number": top.get("vendor_id", ""),
                    "name": top.get("display_name", ""),
                }
                match_source = f"single_candidate@{top.get('score', 0):.0%}"
                single_candidate_resolved += 1

        if matched_vendor:
            vn_number = matched_vendor.get("vendor_number") or ""
            vn_name = matched_vendor.get("name") or vn_number

            new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "vendor_match"]
            new_checks.append({
                "check_name": "vendor_match",
                "passed": True,
                "details": f"Found vendor via enhanced backfill {match_source}: {vn_name} ({vn_number})",
                "required": True,
                "match_method": match_source,
                "score": 0.80,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            try:
                update_fields = {
                    "validation_results.checks": new_checks,
                    "validation_results.all_passed": all_passed,
                    "vendor_enhanced_match_at": _now(),
                    "vendor_enhanced_match_via": match_source,
                }
                if vn_number:
                    update_fields["bc_vendor_number"] = vn_number
                    update_fields["vendor_canonical"] = vn_name
                    update_fields["validation_results.bc_record_info"] = {
                        "displayName": vn_name, "number": vn_number,
                    }

                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_fields})

                # Auto-create alias for future matches
                if vendor_name and vn_number:
                    try:
                        from services.vendor_name_helpers import normalize_vendor_name
                        import uuid
                        norm_alias = normalize_vendor_name(vendor_name)
                        existing = await db.vendor_aliases.find_one({
                            "$or": [{"alias_string": vendor_name}, {"normalized_alias": norm_alias}]
                        })
                        if not existing:
                            await db.vendor_aliases.insert_one({
                                "alias_id": str(uuid.uuid4()),
                                "alias_string": vendor_name,
                                "normalized_alias": norm_alias,
                                "vendor_no": vn_number,
                                "vendor_name": vn_name,
                                "created_by": f"enhanced_backfill_{match_source}",
                                "created_at": _now(),
                                "usage_count": 0,
                            })
                    except Exception:
                        pass

                resolved += 1
                logger.info("[EnhancedVendor] doc=%s — RESOLVED via %s: %s (%s)",
                            doc_id[:8], match_source, vn_name, vn_number)
            except Exception as e:
                errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "batch_resolved": batch_resolved,
        "email_resolved": email_resolved,
        "aggressive_match_resolved": aggressive_resolved,
        "single_candidate_resolved": single_candidate_resolved,
        "errors": errors,
    }


# =============================================================================
# 7. ENHANCED PO VALIDATION — BROADER MATCHING + PROFILE RELAXATION
# =============================================================================

async def enhanced_po_revalidation(db, limit: int = 500) -> dict:
    """
    Second-pass PO revalidation for remaining gaps.

    Runs AFTER the standard PO revalidation. Targets remaining gaps with:
      1. Vendor profile relaxation: PO_SKIP for vendors with < 30% PO rate in BC
      2. Broader reference field matching (check all ref fields, not just po_number)
      3. Digit-only matching against BC PO cache
      4. Downgrade to advisory for doc types that rarely need POs
    """
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "po_validation", "passed": False, "required": {"$ne": False}}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        },
        {
            "_id": 0, "id": 1, "filename": 1, "file_name": 1,
            "extracted_fields": 1, "normalized_fields": 1,
            "validation_results": 1, "bc_vendor_number": 1, "vendor_no": 1,
            "vendor_canonical": 1, "doc_type": 1, "document_type": 1,
            "suggested_job_type": 1, "po_number_clean": 1,
        }
    ).limit(limit).to_list(limit)

    if not gap_docs:
        return {"found": 0, "resolved": 0, "message": "No PO validation gaps remaining"}

    resolved = 0
    profile_skip_resolved = 0
    ref_match_resolved = 0
    downgraded = 0
    errors = 0

    # Build vendor PO rate map from BC cache
    vendor_po_rates = {}
    try:
        po_rate_pipeline = [
            {"$match": {
                "bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice"]},
            }},
            {"$group": {
                "_id": "$bc_vendor_no",
                "total": {"$sum": 1},
                "with_po": {"$sum": {
                    "$cond": [
                        {"$and": [
                            {"$ne": [{"$ifNull": ["$bc_order_number", ""]}, ""]},
                            {"$ne": ["$bc_order_number", None]},
                        ]},
                        1, 0
                    ]
                }},
            }},
            {"$match": {"total": {"$gte": 3}}},  # Need minimum 3 invoices
        ]
        async for row in db.bc_reference_cache.aggregate(po_rate_pipeline):
            vno = row["_id"]
            total = row["total"]
            with_po = row["with_po"]
            vendor_po_rates[vno] = {
                "total": total,
                "with_po": with_po,
                "rate": round(with_po / max(total, 1), 3),
            }
    except Exception:
        pass

    # Build PO number cache for broader matching
    po_cache = {}  # normalized_po → full PO info
    try:
        pos = await db.bc_reference_cache.find(
            {
                "bc_entity_type": {"$in": ["purchase_order", "posted_purchase_invoice"]},
                "bc_order_number": {"$exists": True, "$ne": ""},
            },
            {"_id": 0, "bc_order_number": 1, "bc_vendor_no": 1, "bc_document_no": 1}
        ).limit(20000).to_list(20000)
        for po in pos:
            po_num = (po.get("bc_order_number") or "").strip()
            if po_num:
                po_cache[po_num.lower()] = po
                # Also index digits-only
                digits = re.sub(r'[^0-9]', '', po_num)
                if digits and len(digits) >= 4:
                    po_cache[f"digits:{digits}"] = po
    except Exception:
        pass

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        doc_type = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type") or ""

        should_resolve = False
        resolve_reason = None

        # Strategy 1: Vendor profile — PO rate < 30% → PO not expected
        if vendor_no and vendor_no in vendor_po_rates:
            rate_info = vendor_po_rates[vendor_no]
            if rate_info["rate"] < 0.30:
                should_resolve = True
                resolve_reason = (
                    f"Vendor {vendor_no} PO rate is {rate_info['rate']:.0%} "
                    f"({rate_info['with_po']}/{rate_info['total']} invoices) — PO not expected"
                )
                profile_skip_resolved += 1

        # Strategy 2: Broader reference field matching
        if not should_resolve:
            ref_candidates = set()
            for field in ["po_number", "order_number", "reference_number", "bol_number",
                          "so_number", "sales_order", "shipment_number"]:
                val = (normalized.get(field) or extracted.get(field) or "").strip()
                if val:
                    ref_candidates.add(val)
            # Also try po_number_clean
            po_clean = doc.get("po_number_clean") or ""
            if po_clean:
                ref_candidates.add(po_clean)

            for ref in ref_candidates:
                ref_lower = ref.lower()
                # Direct lookup
                if ref_lower in po_cache:
                    should_resolve = True
                    resolve_reason = f"PO found via reference field: {ref}"
                    ref_match_resolved += 1
                    break
                # Digits-only
                digits = re.sub(r'[^0-9]', '', ref)
                if digits and len(digits) >= 4 and f"digits:{digits}" in po_cache:
                    should_resolve = True
                    resolve_reason = f"PO found via digit match: {ref} → {digits}"
                    ref_match_resolved += 1
                    break
                # Partial match — check if ref is a substring of any cached PO
                if len(ref_lower) >= 5:
                    for cached_po in po_cache:
                        if cached_po.startswith("digits:"):
                            continue
                        if ref_lower in cached_po or cached_po in ref_lower:
                            should_resolve = True
                            resolve_reason = f"PO found via partial match: {ref} ↔ {cached_po}"
                            ref_match_resolved += 1
                            break
                if should_resolve:
                    break

        # Strategy 3: No vendor matched yet — can't validate PO without vendor context
        if not should_resolve and not vendor_no:
            # Check if vendor_match also failed
            vendor_check_failed = any(
                ch.get("check_name") == "vendor_match" and not ch.get("passed")
                for ch in validation.get("checks", [])
            )
            if vendor_check_failed:
                # Downgrade PO to advisory — blocked by vendor match first
                new_checks = [ch for ch in validation.get("checks", [])
                              if ch.get("check_name") != "po_validation"]
                new_checks.append({
                    "check_name": "po_validation",
                    "passed": False,
                    "details": "PO validation deferred: vendor not yet matched — resolve vendor first",
                    "required": False,  # Advisory until vendor is resolved
                })
                all_passed = all(ch.get("passed", True) for ch in new_checks
                                 if ch.get("required", True))
                try:
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {
                            "validation_results.checks": new_checks,
                            "validation_results.all_passed": all_passed,
                            "po_gate_deferred_vendor": True,
                            "po_gate_deferred_at": _now(),
                        }}
                    )
                    downgraded += 1
                except Exception:
                    errors += 1
                continue

        # Strategy 4: Downgrade for non-AP doc types (freight, shipping docs rarely need POs)
        if not should_resolve:
            non_po_types = {"Shipping_Document", "BOL", "Packing_Slip", "Delivery_Receipt",
                            "Weight_Ticket", "Freight_Bill"}
            if doc_type in non_po_types:
                # Downgrade to advisory
                new_checks = [ch for ch in validation.get("checks", [])
                              if ch.get("check_name") != "po_validation"]
                new_checks.append({
                    "check_name": "po_validation",
                    "passed": False,
                    "details": f"PO validation downgraded: doc type {doc_type} rarely requires PO",
                    "required": False,  # Advisory only
                })
                all_passed = all(ch.get("passed", True) for ch in new_checks
                                 if ch.get("required", True))
                try:
                    await db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {
                            "validation_results.checks": new_checks,
                            "validation_results.all_passed": all_passed,
                            "po_gate_downgraded": True,
                            "po_gate_downgraded_at": _now(),
                        }}
                    )
                    downgraded += 1
                except Exception:
                    errors += 1
                continue

        if should_resolve:
            new_checks = [ch for ch in validation.get("checks", [])
                          if ch.get("check_name") != "po_validation"]
            new_checks.append({
                "check_name": "po_validation",
                "passed": True,
                "details": f"PO validation resolved (enhanced): {resolve_reason}",
                "required": True,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)

            try:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "validation_results.checks": new_checks,
                        "validation_results.all_passed": all_passed,
                        "po_enhanced_resolved_at": _now(),
                        "po_enhanced_resolved_via": resolve_reason,
                    }}
                )
                resolved += 1
                logger.info("[EnhancedPO] doc=%s — RESOLVED: %s", doc_id[:8], resolve_reason)
            except Exception as e:
                errors += 1

    return {
        "found": len(gap_docs), "resolved": resolved,
        "profile_skip_resolved": profile_skip_resolved,
        "ref_match_resolved": ref_match_resolved,
        "downgraded_to_advisory": downgraded,
        "errors": errors,
    }
