"""
GPI Document Hub - Vendor Intelligence Service

Builds and maintains vendor behavior profiles from historical document data.
Profiles are used to improve reference resolution, scoring, and automation.

Key features:
- Vendor profile creation and updates from document processing
- Behavioral metrics: reference patterns, match rates, automation success
- Stable vendor detection
- Vendor-aware resolver hints (search order, scoring boost)
- In-memory cache for hot profiles
- Async, non-blocking updates
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Stable vendor thresholds
STABLE_VENDOR_MIN_INVOICES = 50
STABLE_VENDOR_MIN_AUTOMATION_RATE = 0.90
STABLE_VENDOR_MIN_CONSISTENCY = 0.70

# Vendor behavior weight in match scoring
VENDOR_BEHAVIOR_WEIGHT = 0.15


class VendorIntelligenceService:
    """
    Learns vendor behavior from processed documents and provides
    intelligence signals for resolution, scoring, and automation.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.collection = db.vendor_intelligence_profiles
        self._cache: Dict[str, Dict] = {}

    async def initialize(self):
        """Create indexes."""
        await self.collection.create_index("vendor_no", unique=True, sparse=True)
        await self.collection.create_index("vendor_name")
        await self.collection.create_index("stable_vendor_flag")
        await self.collection.create_index("invoice_count")
        logger.info("[VendorIntel] Indexes created")

    # =========================================================================
    # PROFILE CRUD
    # =========================================================================

    async def get_profile(self, vendor_id: str) -> Optional[Dict]:
        """Get a vendor profile by vendor_no or vendor_name."""
        if vendor_id in self._cache:
            return self._cache[vendor_id]

        profile = await self.collection.find_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}]},
            {"_id": 0}
        )
        if profile:
            self._cache[vendor_id] = profile
        return profile

    async def get_all_profiles(self, skip: int = 0, limit: int = 100, sort_by: str = "invoice_count") -> List[Dict]:
        """Get all vendor profiles, sorted."""
        cursor = self.collection.find({}, {"_id": 0}).sort(sort_by, -1).skip(skip).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_profile_count(self) -> int:
        return await self.collection.count_documents({})

    async def get_stats(self) -> Dict:
        """Aggregate stats across all vendor profiles."""
        total = await self.collection.count_documents({})
        stable = await self.collection.count_documents({"stable_vendor_flag": True})

        pipeline = [
            {"$group": {
                "_id": None,
                "total_docs": {"$sum": "$invoice_count"},
                "avg_automation": {"$avg": "$automation_success_rate"},
                "avg_resolution": {"$avg": "$reference_resolution_success_rate"},
                "top_domain_purchase": {"$sum": {"$cond": [{"$eq": ["$typical_reference_domain", "purchase"]}, 1, 0]}},
                "top_domain_sales": {"$sum": {"$cond": [{"$eq": ["$typical_reference_domain", "sales"]}, 1, 0]}},
                "top_domain_shipping": {"$sum": {"$cond": [{"$eq": ["$typical_reference_domain", "shipping"]}, 1, 0]}},
            }}
        ]
        agg = await self.collection.aggregate(pipeline).to_list(1)
        agg_data = agg[0] if agg else {}

        return {
            "total_vendors": total,
            "stable_vendors": stable,
            "total_documents_processed": agg_data.get("total_docs", 0),
            "avg_automation_rate": round(agg_data.get("avg_automation", 0) or 0, 3),
            "avg_resolution_rate": round(agg_data.get("avg_resolution", 0) or 0, 3),
            "domain_distribution": {
                "purchase": agg_data.get("top_domain_purchase", 0),
                "sales": agg_data.get("top_domain_sales", 0),
                "shipping": agg_data.get("top_domain_shipping", 0),
            },
            "cache_size": len(self._cache),
        }

    # =========================================================================
    # PROFILE UPDATES FROM DOCUMENTS
    # =========================================================================

    async def update_from_document(self, doc: Dict[str, Any]):
        """
        Update vendor profile based on a processed document.
        Called after resolution/validation completes.
        """
        vendor_name = (
            doc.get("vendor_raw")
            or doc.get("matched_vendor_name")
            or doc.get("vendor_canonical")
            or doc.get("vendor_normalized")
        )
        if not vendor_name:
            return

        vendor_no = ""
        uvm = doc.get("unified_vendor_match") or {}
        if uvm:
            vendor_no = uvm.get("bc_vendor_no", "")

        vendor_key = vendor_no or vendor_name

        doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
        has_po = bool(doc.get("po_number_clean"))
        has_bol = bool(doc.get("bol_number"))
        has_shipment_ref = False
        has_invoice_ref = bool(doc.get("invoice_number_clean"))

        ref_intel = doc.get("reference_intelligence") or {}
        outcome = doc.get("reference_intelligence_outcome") or ref_intel.get("match_outcome")
        best_match = ref_intel.get("best_match") or {}
        best_entity = best_match.get("entity_type", "")
        best_score = best_match.get("match_score", 0)
        candidates = ref_intel.get("reference_candidates") or []

        for c in candidates:
            if c.get("predicted_domain") == "shipping" or c.get("detected_label") in ("SHIPMENT", "BOL"):
                has_shipment_ref = True
                break

        resolution_success = outcome in ("exact_match", "likely_match")
        automation_success = resolution_success and doc.get("auto_cleared", False)

        is_freight = doc_type in ("Freight_Invoice", "Freight Invoice", "Freight")
        is_shipping = doc_type in ("Shipping_Document", "Shipping Document", "BOL", "Bill_of_Lading")

        # Determine dominant domain from this document
        doc_domain = "unknown"
        if "purchase" in best_entity:
            doc_domain = "purchase"
        elif "sales" in best_entity or "shipment" in best_entity:
            doc_domain = "sales" if "invoice" in best_entity else "shipping"
        elif is_freight or is_shipping:
            doc_domain = "shipping"
        elif has_po:
            doc_domain = "purchase"

        # Upsert profile
        now = datetime.now(timezone.utc).isoformat()

        existing = await self.collection.find_one(
            {"$or": [{"vendor_no": vendor_key}, {"vendor_name": vendor_name}]},
            {"_id": 0}
        )

        if existing:
            await self._update_existing_profile(
                existing, vendor_name, vendor_no, doc_type, doc_domain,
                has_po, has_bol, has_shipment_ref, has_invoice_ref,
                best_entity, best_score, resolution_success, automation_success,
                outcome, now
            )
        else:
            await self._create_new_profile(
                vendor_name, vendor_no, doc_type, doc_domain,
                has_po, has_bol, has_shipment_ref, has_invoice_ref,
                best_entity, best_score, resolution_success, automation_success,
                outcome, now
            )

        # Invalidate cache
        self._cache.pop(vendor_key, None)
        self._cache.pop(vendor_name, None)

    async def _create_new_profile(
        self, vendor_name, vendor_no, doc_type, doc_domain,
        has_po, has_bol, has_shipment_ref, has_invoice_ref,
        best_entity, best_score, resolution_success, automation_success,
        outcome, now
    ):
        profile = {
            "vendor_no": vendor_no or vendor_name,
            "vendor_name": vendor_name,
            "document_types_seen": [doc_type] if doc_type != "Unknown" else [],
            "typical_reference_domain": doc_domain,
            "reference_confidence_score": best_score,
            "invoice_count": 1,
            "freight_invoice_count": 1 if doc_type in ("Freight_Invoice", "Freight Invoice", "Freight") else 0,
            "shipping_document_count": 1 if doc_type in ("Shipping_Document", "BOL") else 0,
            "po_reference_count": 1 if has_po else 0,
            "po_reference_frequency": 1.0 if has_po else 0.0,
            "shipment_reference_count": 1 if has_shipment_ref else 0,
            "shipment_reference_frequency": 1.0 if has_shipment_ref else 0.0,
            "bol_count": 1 if has_bol else 0,
            "bol_presence_rate": 1.0 if has_bol else 0.0,
            "invoice_reference_count": 1 if has_invoice_ref else 0,
            "typical_bc_match_types": [best_entity] if best_entity else [],
            "bc_match_type_counts": {best_entity: 1} if best_entity else {},
            "resolution_success_count": 1 if resolution_success else 0,
            "reference_resolution_success_rate": 1.0 if resolution_success else 0.0,
            "automation_success_count": 1 if automation_success else 0,
            "automation_success_rate": 1.0 if automation_success else 0.0,
            "validation_pass_count": 1 if resolution_success else 0,
            "validation_pass_rate": 1.0 if resolution_success else 0.0,
            "avg_match_score": best_score,
            "match_outcome_counts": {outcome: 1} if outcome else {},
            "domain_counts": {doc_domain: 1},
            "stable_vendor_flag": False,
            "first_document_seen": now,
            "last_document_seen": now,
            "created_at": now,
            "updated_at": now,
        }

        await self.collection.insert_one(profile)
        logger.info("[VendorIntel] Created profile for %s", vendor_name)

        if self.event_service:
            await self.event_service.emit(
                event_type="vendor.profile.created",
                document_id="system",
                source_service="vendor_intelligence",
                payload={"vendor_name": vendor_name, "vendor_no": vendor_no}
            )

    async def _update_existing_profile(
        self, existing, vendor_name, vendor_no, doc_type, doc_domain,
        has_po, has_bol, has_shipment_ref, has_invoice_ref,
        best_entity, best_score, resolution_success, automation_success,
        outcome, now
    ):
        n = existing.get("invoice_count", 0) + 1

        # Incremental averages
        old_avg_score = existing.get("avg_match_score", 0)
        new_avg_score = old_avg_score + (best_score - old_avg_score) / n

        po_count = existing.get("po_reference_count", 0) + (1 if has_po else 0)
        bol_count = existing.get("bol_count", 0) + (1 if has_bol else 0)
        ship_count = existing.get("shipment_reference_count", 0) + (1 if has_shipment_ref else 0)
        inv_ref_count = existing.get("invoice_reference_count", 0) + (1 if has_invoice_ref else 0)
        res_success = existing.get("resolution_success_count", 0) + (1 if resolution_success else 0)
        auto_success = existing.get("automation_success_count", 0) + (1 if automation_success else 0)
        val_pass = existing.get("validation_pass_count", 0) + (1 if resolution_success else 0)
        freight_count = existing.get("freight_invoice_count", 0) + (1 if doc_type in ("Freight_Invoice", "Freight Invoice", "Freight") else 0)
        shipping_doc_count = existing.get("shipping_document_count", 0) + (1 if doc_type in ("Shipping_Document", "BOL") else 0)

        # Update doc types seen
        doc_types = existing.get("document_types_seen", [])
        if doc_type and doc_type != "Unknown" and doc_type not in doc_types:
            doc_types.append(doc_type)

        # Update BC match type counts
        match_counts = existing.get("bc_match_type_counts", {})
        if best_entity:
            match_counts[best_entity] = match_counts.get(best_entity, 0) + 1

        # Typical BC match types (top 3)
        sorted_types = sorted(match_counts.items(), key=lambda x: x[1], reverse=True)
        typical_types = [t[0] for t in sorted_types[:3]]

        # Update outcome counts
        outcome_counts = existing.get("match_outcome_counts", {})
        if outcome:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1

        # Update domain counts
        domain_counts = existing.get("domain_counts", {})
        domain_counts[doc_domain] = domain_counts.get(doc_domain, 0) + 1
        typical_domain = max(domain_counts, key=domain_counts.get) if domain_counts else "unknown"

        # Stable vendor check
        was_stable = existing.get("stable_vendor_flag", False)
        is_stable = (
            n >= STABLE_VENDOR_MIN_INVOICES
            and (auto_success / n if n > 0 else 0) >= STABLE_VENDOR_MIN_AUTOMATION_RATE
        )

        update_doc = {
            "$set": {
                "vendor_name": vendor_name,
                "document_types_seen": doc_types,
                "typical_reference_domain": typical_domain,
                "reference_confidence_score": round(new_avg_score, 4),
                "invoice_count": n,
                "freight_invoice_count": freight_count,
                "shipping_document_count": shipping_doc_count,
                "po_reference_count": po_count,
                "po_reference_frequency": round(po_count / n, 4),
                "shipment_reference_count": ship_count,
                "shipment_reference_frequency": round(ship_count / n, 4),
                "bol_count": bol_count,
                "bol_presence_rate": round(bol_count / n, 4),
                "invoice_reference_count": inv_ref_count,
                "typical_bc_match_types": typical_types,
                "bc_match_type_counts": match_counts,
                "resolution_success_count": res_success,
                "reference_resolution_success_rate": round(res_success / n, 4),
                "automation_success_count": auto_success,
                "automation_success_rate": round(auto_success / n, 4),
                "validation_pass_count": val_pass,
                "validation_pass_rate": round(val_pass / n, 4),
                "avg_match_score": round(new_avg_score, 4),
                "match_outcome_counts": outcome_counts,
                "domain_counts": domain_counts,
                "stable_vendor_flag": is_stable,
                "last_document_seen": now,
                "updated_at": now,
            }
        }

        if vendor_no and not existing.get("vendor_no"):
            update_doc["$set"]["vendor_no"] = vendor_no

        filter_q = {"$or": [
            {"vendor_no": existing.get("vendor_no", "")},
            {"vendor_name": vendor_name}
        ]}
        await self.collection.update_one(filter_q, update_doc)

        if self.event_service:
            await self.event_service.emit(
                event_type="vendor.profile.updated",
                document_id="system",
                source_service="vendor_intelligence",
                payload={
                    "vendor_name": vendor_name,
                    "invoice_count": n,
                    "automation_rate": round(auto_success / n, 4),
                }
            )

        if is_stable and not was_stable:
            logger.info("[VendorIntel] Vendor %s is now STABLE", vendor_name)
            if self.event_service:
                await self.event_service.emit(
                    event_type="vendor.stable.detected",
                    document_id="system",
                    source_service="vendor_intelligence",
                    payload={
                        "vendor_name": vendor_name,
                        "invoice_count": n,
                        "automation_rate": round(auto_success / n, 4),
                    }
                )

    # =========================================================================
    # RESOLVER HINTS
    # =========================================================================

    async def get_resolver_hints(self, vendor_name: str) -> Dict[str, Any]:
        """
        Get vendor-aware hints for the reference resolver.
        Returns search order priority adjustments and scoring signals.
        
        v2: Now includes preferred_search_order for dynamic strategy.
        """
        profile = await self.get_profile(vendor_name)
        if not profile or profile.get("invoice_count", 0) < 3:
            return {"has_hints": False}

        hints = {"has_hints": True, "vendor_name": vendor_name}

        domain = profile.get("typical_reference_domain", "unknown")
        hints["preferred_domain"] = domain

        # Search order hints based on frequency
        ship_freq = profile.get("shipment_reference_frequency", 0)
        po_freq = profile.get("po_reference_frequency", 0)
        hints["bol_rate"] = profile.get("bol_presence_rate", 0)

        if ship_freq > 0.7:
            hints["prioritize_entity"] = "posted_sales_shipment"
            hints["search_order_boost"] = ["posted_sales_shipment", "sales_order"]
        elif po_freq > 0.7:
            hints["prioritize_entity"] = "purchase_order"
            hints["search_order_boost"] = ["purchase_order", "posted_purchase_invoice"]

        # v2: Build preferred_search_order from match type counts
        match_counts = profile.get("bc_match_type_counts", {})
        if match_counts:
            sorted_types = sorted(match_counts.items(), key=lambda x: x[1], reverse=True)
            hints["preferred_search_order"] = [t for t, _ in sorted_types if t]

        # v2: Reference formatting patterns
        hints["reference_patterns"] = {
            "po_frequency": po_freq,
            "shipment_frequency": ship_freq,
            "bol_rate": profile.get("bol_presence_rate", 0),
            "invoice_ref_count": profile.get("invoice_reference_count", 0),
        }

        # v2: Common match targets
        hints["common_match_targets"] = [
            t for t, c in sorted(match_counts.items(), key=lambda x: x[1], reverse=True)[:3]
            if c >= 2
        ]

        # Scoring signals
        typical_types = profile.get("typical_bc_match_types", [])
        hints["typical_match_types"] = typical_types
        hints["behavior_score_boost"] = VENDOR_BEHAVIOR_WEIGHT

        hints["stable_vendor"] = profile.get("stable_vendor_flag", False)
        hints["automation_rate"] = profile.get("automation_success_rate", 0)

        # Label correction patterns
        hints["label_correction_patterns"] = profile.get("label_correction_patterns", {})

        return hints

    # =========================================================================
    # LABEL CORRECTION PATTERN LEARNING
    # =========================================================================

    async def update_label_correction_patterns(self, vendor_id: str, correction: Dict[str, Any]):
        """
        Update vendor profile with a new label correction pattern.
        Tracks which labels are consistently mislabeled for this vendor.
        """
        predicted = correction.get("predicted_label", "")
        correct = correction.get("correct_label", "")
        entity = correction.get("actual_entity_type", "")
        if not predicted or not correct:
            return

        profile = await self.get_profile(vendor_id)
        if not profile:
            return

        patterns = profile.get("label_correction_patterns", {})
        key = f"{predicted}->{correct}"
        if key in patterns:
            patterns[key]["count"] = patterns[key].get("count", 0) + 1
            patterns[key]["last_seen"] = datetime.now(timezone.utc).isoformat()
        else:
            patterns[key] = {
                "predicted_label": predicted,
                "correct_label": correct,
                "actual_entity_type": entity,
                "count": 1,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }

        filter_q = {"$or": [
            {"vendor_no": profile.get("vendor_no", "")},
            {"vendor_name": profile.get("vendor_name", "")}
        ]}
        await self.collection.update_one(
            filter_q,
            {"$set": {
                "label_correction_patterns": patterns,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }}
        )

        # Invalidate cache
        self._cache.pop(vendor_id, None)
        self._cache.pop(profile.get("vendor_name", ""), None)

        logger.info(
            "[VendorIntel] Label pattern updated for %s: %s→%s (count=%d)",
            vendor_id[:20], predicted, correct, patterns[key]["count"]
        )

    # =========================================================================
    # REBUILD FROM HISTORY
    # =========================================================================

    async def rebuild_all_profiles(self) -> Dict[str, Any]:
        """
        Rebuild all vendor profiles from historical document data.
        This processes all documents and builds fresh profiles.
        """
        import time
        start = time.time()

        await self.collection.delete_many({})
        self._cache.clear()

        cursor = self.db.hub_documents.find(
            {"$or": [
                {"vendor_raw": {"$exists": True, "$ne": None}},
                {"matched_vendor_name": {"$exists": True, "$ne": None}},
                {"vendor_canonical": {"$exists": True, "$ne": None}},
            ]},
            {"_id": 0}
        )

        count = 0
        async for doc in cursor:
            try:
                await self.update_from_document(doc)
                count += 1
            except Exception as e:
                logger.warning("[VendorIntel] Error processing doc %s: %s", doc.get("id", "?")[:8], str(e))

        duration_ms = int((time.time() - start) * 1000)

        if self.event_service:
            await self.event_service.emit(
                event_type="vendor.profile.rebuilt",
                document_id="system",
                source_service="vendor_intelligence",
                payload={"documents_processed": count, "duration_ms": duration_ms}
            )

        logger.info("[VendorIntel] Rebuilt profiles from %d documents in %dms", count, duration_ms)

        return {
            "status": "completed",
            "documents_processed": count,
            "duration_ms": duration_ms,
            "profiles_created": await self.get_profile_count()
        }


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_vendor_intel_service: Optional[VendorIntelligenceService] = None


def get_vendor_intelligence_service() -> Optional[VendorIntelligenceService]:
    return _vendor_intel_service


def set_vendor_intelligence_service(db, event_service=None) -> VendorIntelligenceService:
    global _vendor_intel_service
    _vendor_intel_service = VendorIntelligenceService(db, event_service)
    return _vendor_intel_service
