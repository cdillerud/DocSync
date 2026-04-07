"""
Vendor Profile Rebuild — Recompute vendor intelligence profiles from actual document data.

Fixes:
  1. Duplicate vendor profiles (case/punctuation variants)
  2. Zero-value rates (automation, resolution, validation)
  3. Inaccurate doc counts

Endpoints:
  POST /api/vendor-profiles/rebuild/dry-run  — Preview what would change
  POST /api/vendor-profiles/rebuild/run      — Full rebuild from documents
"""

import logging
import re
import time
from datetime import datetime, timezone
from collections import defaultdict

from fastapi import APIRouter
from deps import get_db

logger = logging.getLogger("vendor_profile_rebuild")
router = APIRouter(prefix="/vendor-profiles", tags=["Vendor Profiles"])


def _normalize_vendor_name(name: str) -> str:
    """Normalize vendor name for dedup: lowercase, strip suffixes/punctuation, collapse whitespace."""
    if not name:
        return ""
    s = name.lower().strip()
    # Remove common business suffixes that vary
    s = re.sub(r'\b(inc\.?|llc\.?|ltd\.?|corp\.?|co\.?|company|corporation|pte\.?|int\'?l\.?|international)\b', '', s, flags=re.IGNORECASE)
    # Remove punctuation (including apostrophes, hyphens, etc.)
    s = re.sub(r'[.,;:\'\"()\-/&!@#$%^*_+=\[\]{}|\\<>?~`]', ' ', s)
    # Collapse whitespace
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def _pick_best_display_name(names: list) -> str:
    """Pick the best display name from a list of variants."""
    if not names:
        return "Unknown"
    # Prefer the one with most mixed case (not all-caps), then longest
    scored = []
    for n in names:
        has_mixed = not n.isupper() and not n.islower()
        scored.append((has_mixed, len(n), n))
    scored.sort(reverse=True)
    return scored[0][2]


@router.post("/rebuild/dry-run")
async def rebuild_dry_run():
    """Preview vendor profile rebuild with consolidation report."""
    db = get_db()
    start = time.time()

    groups, vendor_no_map = await _aggregate_vendor_data(db)

    current_profiles = await db.vendor_intelligence_profiles.find(
        {}, {"_id": 0, "vendor_name": 1, "vendor_no": 1}
    ).to_list(5000)

    # Find profiles that would be merged (multiple name variants)
    consolidation_report = []
    for key, data in sorted(groups.items(), key=lambda x: len(x[1]["name_variants"]), reverse=True):
        if len(data["name_variants"]) > 1:
            consolidation_report.append({
                "canonical": data["display_name"],
                "vendor_no": data.get("vendor_no", ""),
                "total_docs": data["doc_count"],
                "variants": data["name_variants"],
                "variant_count": len(data["name_variants"]),
            })

    return {
        "current_profiles": len(current_profiles),
        "new_profiles": len(groups),
        "would_merge": len(current_profiles) - len(groups) if len(current_profiles) > len(groups) else 0,
        "consolidation_report": consolidation_report[:30],
        "top_vendors": [
            {
                "name": data["display_name"],
                "vendor_no": data.get("vendor_no", ""),
                "docs": data["doc_count"],
                "auto_cleared": data["auto_cleared_count"],
                "validation_passed": data["validation_passed_count"],
                "vendor_resolved": data["vendor_resolved_count"],
                "auto_rate": round(data["auto_cleared_count"] / max(data["doc_count"], 1), 3),
                "resolution_rate": round(data["vendor_resolved_count"] / max(data["doc_count"], 1), 3),
                "variants": data["name_variants"][:5],
            }
            for _, data in sorted(groups.items(), key=lambda x: x[1]["doc_count"], reverse=True)[:20]
        ],
        "duration_ms": int((time.time() - start) * 1000),
    }


@router.post("/rebuild/run")
async def rebuild_run():
    """Full rebuild of vendor intelligence profiles from document data."""
    db = get_db()
    start = time.time()
    errors = []

    try:
        groups, vendor_no_map = await _aggregate_vendor_data(db)
    except Exception as e:
        logger.error("[RebuildRun] Failed to aggregate vendor data: %s", str(e))
        return {"status": "error", "message": f"Aggregation failed: {str(e)}"}

    # Preserve manual overrides from existing profiles (match by vendor_no or normalized name)
    existing = {}
    try:
        async for p in db.vendor_intelligence_profiles.find({}, {"_id": 0}):
            vno = (p.get("vendor_no") or "").strip()
            norm = _normalize_vendor_name(p.get("vendor_name", ""))
            override_data = {
                "manual_override_status": p.get("manual_override_status"),
                "manual_override_reason": p.get("manual_override_reason"),
                "manual_override_by": p.get("manual_override_by"),
                "manual_override_at": p.get("manual_override_at"),
                "manual_override_note": p.get("manual_override_note"),
                "manual_override_expires_at": p.get("manual_override_expires_at"),
                "stable_vendor_last_evaluated": p.get("stable_vendor_last_evaluated"),
            }
            if vno:
                existing[vno] = override_data
            if norm and norm not in existing:
                existing[norm] = override_data
    except Exception as e:
        logger.warning("[RebuildRun] Error reading existing overrides (continuing): %s", str(e))

    # Load stable vendor config ONCE before the loop
    try:
        sv_cfg = await db.stable_vendor_config.find_one(
            {"config_id": "stable_vendor_defaults"}, {"_id": 0}
        ) or {}
    except Exception:
        sv_cfg = {}

    # Drop all existing profiles, then drop+recreate indexes to avoid conflicts
    await db.vendor_intelligence_profiles.delete_many({})
    try:
        await db.vendor_intelligence_profiles.drop_index("vendor_no_1")
    except Exception:
        pass  # Index may not exist

    now = datetime.now(timezone.utc).isoformat()
    created = 0
    skipped = 0
    seen_vendor_nos = set()

    for norm_name, data in groups.items():
        try:
            doc_count = data.get("doc_count", 0) or 0
            if doc_count == 0:
                skipped += 1
                continue

            auto_cleared = data.get("auto_cleared_count", 0) or 0
            val_passed = data.get("validation_passed_count", 0) or 0
            vendor_resolved = data.get("vendor_resolved_count", 0) or 0
            ref_resolved = data.get("ref_resolved_count", 0) or 0

            auto_rate = round(auto_cleared / max(doc_count, 1), 4)
            val_rate = round(val_passed / max(doc_count, 1), 4)
            resolution_rate = round(vendor_resolved / max(doc_count, 1), 4)
            ref_rate = round(ref_resolved / max(doc_count, 1), 4)

            is_stable = (
                doc_count >= sv_cfg.get("min_documents_processed", 10)
                and auto_rate >= sv_cfg.get("min_automation_success_rate", 0.50)
                and resolution_rate >= sv_cfg.get("min_reference_resolution_rate", 0.70)
                and val_rate >= sv_cfg.get("min_validation_pass_rate", 0.05)
            )

            correction_rate = data.get("correction_rate", 0) or 0
            score = round(
                min(doc_count / 50, 1.0) * 0.15
                + auto_rate * 0.30
                + resolution_rate * 0.25
                + val_rate * 0.20
                + (1 - correction_rate) * 0.10
            , 4)

            # Determine vendor_no — use bc vendor number if available, else normalized name as key
            raw_vendor_no = (data.get("vendor_no") or "").strip()
            display_name = data.get("display_name") or "Unknown"
            name_variants = data.get("name_variants", []) or []

            if raw_vendor_no:
                vendor_no = raw_vendor_no
            else:
                # For name-only groups, use the normalized name as the vendor_no key
                vendor_no = norm_name or display_name

            # Deduplicate: if we already inserted a profile with this vendor_no, skip
            if vendor_no in seen_vendor_nos:
                logger.warning("[RebuildRun] Duplicate vendor_no '%s' (display: %s) — skipping", vendor_no[:30], display_name[:30])
                skipped += 1
                continue
            seen_vendor_nos.add(vendor_no)

            # Restore manual overrides (try vendor_no first, then normalized name)
            overrides = existing.get(vendor_no, existing.get(norm_name, {}))

            # Safely convert doc_types set to list
            try:
                doc_types_list = list(data.get("doc_types", set()) or set())
            except Exception:
                doc_types_list = []

            # Compute behavioral metrics
            po_count = data.get("po_count", 0) or 0
            bol_count = data.get("bol_count", 0) or 0
            shipment_ref_count = data.get("shipment_ref_count", 0) or 0
            invoice_ref_count = data.get("invoice_ref_count", 0) or 0
            freight_count = data.get("freight_count", 0) or 0
            shipping_doc_count = data.get("shipping_doc_count", 0) or 0
            domain_counts = data.get("domain_counts", {}) or {}
            bc_match_type_counts = data.get("bc_match_type_counts", {}) or {}
            match_scores = data.get("match_scores", []) or []
            match_outcome_counts = data.get("match_outcome_counts", {}) or {}

            # Determine typical domain
            typical_domain = max(domain_counts, key=domain_counts.get) if domain_counts else "unknown"

            # Top 3 BC match types
            sorted_types = sorted(bc_match_type_counts.items(), key=lambda x: x[1], reverse=True)
            typical_bc_match_types = [t[0] for t in sorted_types[:3]]

            # Average match score
            avg_match_score = round(sum(match_scores) / len(match_scores), 4) if match_scores else 0

            profile = {
                "vendor_no": vendor_no,
                "vendor_name": display_name,
                "vendor_name_normalized": norm_name,
                "name_variants": name_variants,
                "invoice_count": doc_count,
                "document_types_seen": doc_types_list,
                "automation_success_count": auto_cleared,
                "automation_success_rate": auto_rate,
                "validation_pass_count": val_passed,
                "validation_pass_rate": val_rate,
                "resolution_success_count": vendor_resolved,
                "reference_resolution_success_rate": resolution_rate,
                "reference_intelligence_rate": ref_rate,
                "stable_vendor_flag": is_stable,
                "stable_vendor_score": score,
                "stable_vendor_last_evaluated": now,
                "correction_rate": correction_rate,
                # Behavioral fields
                "typical_reference_domain": typical_domain,
                "po_reference_count": po_count,
                "po_reference_frequency": round(po_count / max(doc_count, 1), 4),
                "bol_count": bol_count,
                "bol_presence_rate": round(bol_count / max(doc_count, 1), 4),
                "shipment_reference_count": shipment_ref_count,
                "shipment_reference_frequency": round(shipment_ref_count / max(doc_count, 1), 4),
                "invoice_reference_count": invoice_ref_count,
                "freight_invoice_count": freight_count,
                "shipping_document_count": shipping_doc_count,
                "typical_bc_match_types": typical_bc_match_types,
                "bc_match_type_counts": bc_match_type_counts,
                "avg_match_score": avg_match_score,
                "match_outcome_counts": match_outcome_counts,
                "domain_counts": domain_counts,
                "reference_confidence_score": avg_match_score,
                # Timestamps
                "created_at": now,
                "updated_at": now,
                "manual_override_status": overrides.get("manual_override_status", "none") if overrides else "none",
                "manual_override_reason": overrides.get("manual_override_reason", "") if overrides else "",
                "manual_override_by": overrides.get("manual_override_by", "") if overrides else "",
                "manual_override_at": overrides.get("manual_override_at") if overrides else None,
                "manual_override_note": overrides.get("manual_override_note", "") if overrides else "",
                "manual_override_expires_at": overrides.get("manual_override_expires_at") if overrides else None,
            }

            await db.vendor_intelligence_profiles.insert_one(profile)
            created += 1

        except Exception as e:
            err_msg = f"Error on vendor '{norm_name[:40]}': {str(e)}"
            logger.warning("[RebuildRun] %s", err_msg)
            errors.append(err_msg)
            skipped += 1

    # Recreate indexes after all inserts
    try:
        await db.vendor_intelligence_profiles.create_index("vendor_no", unique=True, sparse=True)
        await db.vendor_intelligence_profiles.create_index("vendor_name")
        await db.vendor_intelligence_profiles.create_index("vendor_name_normalized")
        await db.vendor_intelligence_profiles.create_index("stable_vendor_flag")
    except Exception as e:
        logger.warning("[RebuildRun] Index creation issue: %s", str(e))

    duration_ms = int((time.time() - start) * 1000)

    stable_count = await db.vendor_intelligence_profiles.count_documents({"stable_vendor_flag": True})

    # Build consolidation report
    consolidation_report = []
    for key, data in sorted(groups.items(), key=lambda x: len(x[1].get("name_variants", [])), reverse=True):
        variants = data.get("name_variants", []) or []
        if len(variants) > 1:
            consolidation_report.append({
                "canonical": data.get("display_name", "Unknown"),
                "vendor_no": data.get("vendor_no", ""),
                "total_docs": data.get("doc_count", 0),
                "variants": variants,
                "variant_count": len(variants),
            })

    logger.info("[RebuildRun] Complete: created=%d, skipped=%d, errors=%d, duration=%dms",
                created, skipped, len(errors), duration_ms)

    return {
        "status": "completed",
        "profiles_created": created,
        "stable_vendors": stable_count,
        "consolidation_report": consolidation_report[:30],
        "merged_count": len(consolidation_report),
        "skipped": skipped,
        "errors": errors[:10],
        "duration_ms": duration_ms,
        "timestamp": now,
    }


async def _aggregate_vendor_data(db):
    """
    Aggregate document data grouped by CONSOLIDATED vendor identity.

    Three-pass consolidation:
      1. Group by bc_vendor_number (if available from doc or vendor_aliases)
      2. Group remaining by normalized vendor name
      3. Merge name-groups into bc_vendor_number groups via alias lookup
    """
    groups = defaultdict(lambda: {
        "doc_count": 0,
        "auto_cleared_count": 0,
        "validation_passed_count": 0,
        "vendor_resolved_count": 0,
        "ref_resolved_count": 0,
        "name_variants": [],
        "display_name": "",
        "vendor_no": "",
        "doc_types": set(),
        "correction_rate": 0,
        "po_count": 0,
        "bol_count": 0,
        "shipment_ref_count": 0,
        "invoice_ref_count": 0,
        "freight_count": 0,
        "shipping_doc_count": 0,
        "domain_counts": {},
        "bc_match_type_counts": {},
        "match_scores": [],
        "match_outcome_counts": {},
    })
    vendor_no_map = {}
    merge_log = []

    # Pre-load alias map: raw vendor name → bc_vendor_no
    alias_map = {}  # normalized_name → vendor_no
    try:
        aliases = await db.vendor_aliases.find(
            {}, {"_id": 0, "alias_string": 1, "normalized_alias": 1, "vendor_no": 1, "vendor_name": 1}
        ).to_list(5000)
        for a in aliases:
            alias_str = (a.get("alias_string") or "").strip()
            norm_alias = (a.get("normalized_alias") or _normalize_vendor_name(alias_str)).strip()
            vno = (a.get("vendor_no") or "").strip()
            if norm_alias and vno:
                alias_map[norm_alias] = vno
            if alias_str:
                alias_map[_normalize_vendor_name(alias_str)] = vno
    except Exception:
        pass

    # Also build a map from BC reference cache: vendor name → vendor_no
    bc_vendor_name_to_no = {}
    try:
        bc_vendors = await db.bc_reference_cache.find(
            {"bc_entity_type": "vendor"},
            {"_id": 0, "bc_vendor_name": 1, "bc_vendor_no": 1}
        ).limit(2000).to_list(2000)
        for v in bc_vendors:
            name = (v.get("bc_vendor_name") or "").strip()
            vno = (v.get("bc_vendor_no") or "").strip()
            if name and vno:
                bc_vendor_name_to_no[_normalize_vendor_name(name)] = vno
                bc_vendor_name_to_no[name.lower()] = vno
    except Exception:
        pass

    def _resolve_vendor_no(raw_name, doc):
        """Determine the BC vendor number for a document, using multiple sources."""
        # 1. Direct from document fields
        vno = (doc.get("bc_vendor_number") or "").strip()
        if vno:
            return vno

        # 2. From unified_vendor_match
        uvm = doc.get("unified_vendor_match") or doc.get("validation_results", {}).get("unified_vendor_match", {})
        if uvm:
            vno = (uvm.get("bc_vendor_no") or "").strip()
            if vno:
                return vno

        # 3. From vendor_resolution
        vr = doc.get("vendor_resolution") or {}
        vno = (vr.get("vendor_no") or "").strip()
        if vno:
            return vno

        # 4. From alias map
        norm = _normalize_vendor_name(raw_name)
        if norm in alias_map:
            return alias_map[norm]

        # 5. From BC vendor cache (exact name match)
        if norm in bc_vendor_name_to_no:
            return bc_vendor_name_to_no[norm]
        if raw_name.lower() in bc_vendor_name_to_no:
            return bc_vendor_name_to_no[raw_name.lower()]

        return ""

    def _accum_doc(g, doc, raw_name):
        """Accumulate document stats into a group."""
        g["doc_count"] += 1

        if raw_name not in g["name_variants"]:
            g["name_variants"].append(raw_name)
        g["display_name"] = _pick_best_display_name(g["name_variants"])

        status = (doc.get("status") or "").lower()
        workflow_status = (doc.get("workflow_status") or "").lower()
        if (doc.get("auto_cleared")
            or status in ("completed", "posted", "linkedtobc", "storedinsp", "archived")
            or workflow_status in ("completed", "processed", "exported", "validation_passed")):
            g["auto_cleared_count"] += 1

        val_state = (doc.get("validation_state") or "").lower()
        val_results = doc.get("validation_results") or {}
        if (val_state == "pass"
            or val_results.get("all_passed")
            or status in ("validationpassed", "validated", "storedinsp", "readytolink", "linkedtobc", "completed", "posted")):
            g["validation_passed_count"] += 1

        match_method = doc.get("vendor_match_method") or ""
        has_vendor = bool(doc.get("vendor_canonical")) or match_method not in ("", "none", None)
        if has_vendor:
            g["vendor_resolved_count"] += 1

        ref_intel = doc.get("reference_intelligence") or {}
        outcome = ref_intel.get("match_outcome", "")
        if outcome in ("exact_match", "likely_match"):
            g["ref_resolved_count"] += 1

        dt = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type")
        if dt:
            g["doc_types"].add(dt)

        # --- Behavioral tracking ---
        has_po = bool(doc.get("po_number_clean"))
        has_bol = bool(doc.get("bol_number"))
        has_invoice_ref = bool(doc.get("invoice_number_clean"))
        if has_po:
            g["po_count"] += 1
        if has_bol:
            g["bol_count"] += 1
        if has_invoice_ref:
            g["invoice_ref_count"] += 1

        # Shipment reference detection from candidates
        has_shipment_ref = False
        candidates = ref_intel.get("reference_candidates") or []
        for c in candidates:
            if c.get("predicted_domain") == "shipping" or c.get("detected_label") in ("SHIPMENT", "BOL"):
                has_shipment_ref = True
                break
        if has_shipment_ref:
            g["shipment_ref_count"] += 1

        # Freight / shipping doc type tracking
        if dt in ("Freight_Invoice", "Freight Invoice", "Freight"):
            g["freight_count"] += 1
        if dt in ("Shipping_Document", "Shipping Document", "BOL", "Bill_of_Lading"):
            g["shipping_doc_count"] += 1

        # Match type and score from reference intelligence
        best_match = ref_intel.get("best_match") or {}
        best_entity = best_match.get("entity_type", "")
        best_score = best_match.get("match_score", 0)
        if best_entity:
            g["bc_match_type_counts"][best_entity] = g["bc_match_type_counts"].get(best_entity, 0) + 1
        if best_score:
            g["match_scores"].append(best_score)
        if outcome:
            g["match_outcome_counts"][outcome] = g["match_outcome_counts"].get(outcome, 0) + 1

        # Domain detection
        doc_domain = "unknown"
        if "purchase" in best_entity:
            doc_domain = "purchase"
        elif "sales" in best_entity or "shipment" in best_entity:
            doc_domain = "sales" if "invoice" in best_entity else "shipping"
        elif dt in ("Freight_Invoice", "Freight Invoice", "Freight", "Shipping_Document", "BOL"):
            doc_domain = "shipping"
        elif has_po:
            doc_domain = "purchase"
        g["domain_counts"][doc_domain] = g["domain_counts"].get(doc_domain, 0) + 1

    # Pass 1: Process all documents
    cursor = db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "$or": [
                {"vendor_canonical": {"$exists": True, "$ne": None}},
                {"vendor_raw": {"$exists": True, "$ne": None}},
                {"matched_vendor_name": {"$exists": True, "$ne": None}},
                {"bc_vendor_number": {"$exists": True, "$ne": ""}},
            ],
        },
        {
            "_id": 0, "id": 1,
            "vendor_canonical": 1, "vendor_raw": 1, "matched_vendor_name": 1,
            "vendor_normalized": 1, "bc_vendor_number": 1,
            "auto_cleared": 1, "status": 1, "workflow_status": 1,
            "vendor_match_method": 1, "vendor_resolution": 1,
            "validation_results": 1, "validation_state": 1,
            "reference_intelligence": 1,
            "doc_type": 1, "document_type": 1, "suggested_job_type": 1,
            "unified_vendor_match": 1,
            "po_number_clean": 1, "bol_number": 1, "invoice_number_clean": 1,
        },
    ).batch_size(200)

    async for doc in cursor:
        try:
            raw_name = (
                doc.get("vendor_canonical")
                or doc.get("matched_vendor_name")
                or doc.get("vendor_raw")
                or doc.get("vendor_normalized")
            )
            if not raw_name or raw_name.lower() in ("unknown", "none", "n/a", ""):
                continue

            # Determine the best grouping key: BC vendor number preferred
            vendor_no = _resolve_vendor_no(raw_name, doc)

            if vendor_no:
                group_key = f"bc:{vendor_no}"
                g = groups[group_key]
                g["vendor_no"] = vendor_no
                _accum_doc(g, doc, raw_name)
            else:
                norm = _normalize_vendor_name(raw_name)
                if not norm:
                    continue
                group_key = f"name:{norm}"
                g = groups[group_key]
                _accum_doc(g, doc, raw_name)
        except Exception as e:
            logger.warning("[VendorAggregation] Error processing doc %s: %s",
                          str(doc.get("id", "?"))[:12], str(e))

    # Pass 2: Try to merge name-grouped profiles into bc-grouped via aliases
    name_groups = {k: v for k, v in groups.items() if k.startswith("name:")}
    for name_key, data in list(name_groups.items()):
        norm = name_key[5:]  # strip "name:" prefix
        # Check if any name variant has an alias
        target_vno = alias_map.get(norm) or bc_vendor_name_to_no.get(norm) or ""
        if not target_vno:
            for variant in data["name_variants"]:
                vn_norm = _normalize_vendor_name(variant)
                target_vno = alias_map.get(vn_norm) or bc_vendor_name_to_no.get(vn_norm) or ""
                if target_vno:
                    break

        if target_vno:
            bc_key = f"bc:{target_vno}"
            if bc_key in groups:
                # Merge into existing bc group
                target = groups[bc_key]
                target["doc_count"] += data["doc_count"]
                target["auto_cleared_count"] += data["auto_cleared_count"]
                target["validation_passed_count"] += data["validation_passed_count"]
                target["vendor_resolved_count"] += data["vendor_resolved_count"]
                target["ref_resolved_count"] += data["ref_resolved_count"]
                target["po_count"] += data.get("po_count", 0)
                target["bol_count"] += data.get("bol_count", 0)
                target["shipment_ref_count"] += data.get("shipment_ref_count", 0)
                target["invoice_ref_count"] += data.get("invoice_ref_count", 0)
                target["freight_count"] += data.get("freight_count", 0)
                target["shipping_doc_count"] += data.get("shipping_doc_count", 0)
                target["match_scores"].extend(data.get("match_scores", []))
                for k, v in data.get("bc_match_type_counts", {}).items():
                    target["bc_match_type_counts"][k] = target["bc_match_type_counts"].get(k, 0) + v
                for k, v in data.get("match_outcome_counts", {}).items():
                    target["match_outcome_counts"][k] = target["match_outcome_counts"].get(k, 0) + v
                for k, v in data.get("domain_counts", {}).items():
                    target["domain_counts"][k] = target["domain_counts"].get(k, 0) + v
                for v in data["name_variants"]:
                    if v not in target["name_variants"]:
                        target["name_variants"].append(v)
                target["display_name"] = _pick_best_display_name(target["name_variants"])
                target["doc_types"].update(data["doc_types"])
                merge_log.append(f"Merged '{data['display_name']}' ({data['doc_count']} docs) → {target_vno}")
            else:
                # Promote name group to bc group
                data["vendor_no"] = target_vno
                groups[bc_key] = data
                merge_log.append(f"Promoted '{data['display_name']}' ({data['doc_count']} docs) → {target_vno}")
            del groups[name_key]

    # Clean up keys — remove prefixes for output
    clean_groups = {}
    for key, data in groups.items():
        clean_key = key.split(":", 1)[1] if ":" in key else key
        clean_groups[clean_key] = data

    if merge_log:
        logger.info("[VendorConsolidation] Merged %d profile groups:\n  %s",
                     len(merge_log), "\n  ".join(merge_log))

    return clean_groups, vendor_no_map
