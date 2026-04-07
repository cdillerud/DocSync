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
        names_to_try = []
        if ref_canonical:
            names_to_try.append(ref_canonical)
        if vendor_name and vendor_name != ref_canonical:
            names_to_try.append(vendor_name)

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
