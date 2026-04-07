"""
Validation Gap Backfill Service — batch revalidation for all gap types.

Attacks 4 gap categories:
1. Customer Match — re-run with aliases, vendor→customer history, lower threshold
2. Sales Order Match — cache-first SO lookup, number normalization
3. Vendor Match — re-run with current alias DB + email domain mapping
4. Duplicate Check — enhanced auto-clearing
"""
import re
import logging
from datetime import datetime, timezone

logger = logging.getLogger("validation_backfill")


def _now():
    return datetime.now(timezone.utc).isoformat()


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
      1. Cache-first SO lookup (bc_reference_cache)
      2. SO number normalization (add/remove prefixes, strip zeros)
      3. Cross-document flow intelligence
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

    # ── Build SO cache index ──
    so_cache = {}
    so_normalized = {}
    try:
        cached_sos = await db.bc_reference_cache.find(
            {"bc_entity_type": {"$in": ["sales_order", "posted_sales_invoice"]}},
            {"_id": 0, "bc_document_no": 1, "normalized_document_no": 1,
             "bc_vendor_name": 1, "bc_vendor_no": 1}
        ).limit(5000).to_list(5000)
        for so in cached_sos:
            doc_no = (so.get("bc_document_no") or "").strip()
            norm_no = (so.get("normalized_document_no") or "").strip()
            if doc_no:
                so_cache[doc_no.lower()] = so
            if norm_no:
                so_normalized[norm_no.lower()] = so
    except Exception:
        pass

    resolved = 0
    cache_resolved = 0
    flow_resolved = 0
    errors = 0

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        extracted = doc.get("extracted_fields") or {}
        normalized = doc.get("normalized_fields") or {}
        validation = doc.get("validation_results") or {}
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or ""

        # Get order number candidates
        order_candidates = []
        for field in ["bol_number", "po_number", "order_number", "so_number", "sales_order"]:
            val = normalized.get(field) or extracted.get(field) or ""
            if val and str(val).strip():
                order_candidates.append(str(val).strip())

        if not order_candidates:
            continue

        matched_so = None
        match_source = None

        for order_num in order_candidates:
            order_lower = order_num.lower()

            # Strategy 1: Exact cache lookup
            if order_lower in so_cache:
                matched_so = so_cache[order_lower]
                match_source = "cache_exact"
                cache_resolved += 1
                break

            # Strategy 2: Normalized cache lookup
            norm = re.sub(r'[^a-z0-9]', '', order_lower)
            if norm in so_normalized:
                matched_so = so_normalized[norm]
                match_source = "cache_normalized"
                cache_resolved += 1
                break

            # Strategy 3: Variations
            variations = []
            stripped = order_num.lstrip("0")
            if stripped and stripped != order_num:
                variations.append(stripped)
            for prefix in ["SO", "S-", "SO-"]:
                if not order_num.upper().startswith(prefix):
                    variations.append(f"{prefix}{order_num}")
                elif order_num.upper().startswith(prefix):
                    variations.append(order_num[len(prefix):])

            for var in variations:
                var_lower = var.lower()
                if var_lower in so_cache:
                    matched_so = so_cache[var_lower]
                    match_source = "cache_variation"
                    cache_resolved += 1
                    break
                var_norm = re.sub(r'[^a-z0-9]', '', var_lower)
                if var_norm in so_normalized:
                    matched_so = so_normalized[var_norm]
                    match_source = "cache_normalized_variation"
                    cache_resolved += 1
                    break
            if matched_so:
                break

        # Strategy 4: Document flow cross-reference
        if not matched_so and vendor_no:
            try:
                from services.gap_closer_service import find_sales_order_from_flow
                for order_num in order_candidates[:3]:
                    flow_result = await find_sales_order_from_flow(db, vendor_no, order_num)
                    if flow_result and flow_result.get("found"):
                        matched_so = {
                            "bc_document_no": flow_result.get("number", ""),
                            "bc_vendor_name": flow_result.get("customer_name", ""),
                        }
                        match_source = "document_flow"
                        flow_resolved += 1
                        break
            except Exception:
                pass

        if matched_so:
            so_number = matched_so.get("bc_document_no", "")
            so_customer = matched_so.get("bc_vendor_name", "")
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
        "errors": errors, "so_cache_size": len(so_cache),
    }


# =============================================================================
# 3. VENDOR MATCH REVALIDATION
# =============================================================================

async def batch_revalidate_vendor_gaps(db, limit: int = 500) -> dict:
    """
    Re-run vendor matching on documents with vendor_match failures.

    The alias database grows over time as successful matches are auto-learned.
    This re-runs matching for docs that failed when fewer aliases existed.
    Also uses email domain → vendor mappings.
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

    from services.unified_vendor_matcher import match_vendor_unified

    resolved = 0
    alias_resolved = 0
    domain_resolved = 0
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

        # Strategy 1: Re-run unified vendor matching (may use new aliases)
        names_to_try = []
        if ref_canonical:
            names_to_try.append(ref_canonical)
        if vendor_name and vendor_name != ref_canonical:
            names_to_try.append(vendor_name)

        for name in names_to_try:
            if not name:
                continue
            try:
                result = await match_vendor_unified(db, name, 0.75)
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
                    # Get vendor details from profile or cache
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
        "errors": errors, "domain_map_size": len(domain_map),
    }
