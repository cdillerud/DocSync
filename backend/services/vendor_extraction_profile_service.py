"""
GPI Document Hub - Vendor Extraction Profile Service

Adaptive interpretation layer that improves extraction accuracy for vendors
with consistent behavior patterns while preserving layout independence.

KEY PRINCIPLES:
- NEVER relies on page coordinates
- NEVER assumes a fixed document layout
- NEVER overrides base extraction logic
- Only provides probabilistic interpretation hints

Profiles are auto-generated from:
- Vendor Intelligence engine behavioral data
- Label Correction feedback loop patterns
- Reference resolution history

Integration point: AFTER general extraction, BEFORE resolver scoring.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Profile learning interval (1 hour)
PROFILE_LEARN_INTERVAL = 3600

# Minimum documents to generate a profile
MIN_DOCS_FOR_PROFILE = 5

# Maximum bias values (safety caps)
MAX_MATCH_BOOST = 0.15
MAX_MATCH_PENALTY = -0.10
MAX_LABEL_BIAS = 0.15


def _compute_reference_priority(profile_data: Dict) -> List[str]:
    """Derive reference priority order from vendor behavior."""
    freqs = {
        "BOL": profile_data.get("bol_presence_rate", 0),
        "SHIPMENT": profile_data.get("shipment_reference_frequency", 0),
        "PO": profile_data.get("po_reference_frequency", 0),
        "INVOICE": profile_data.get("invoice_reference_count", 0) / max(profile_data.get("invoice_count", 1), 1),
    }
    # Sort by frequency descending
    priority = sorted(freqs.keys(), key=lambda k: freqs[k], reverse=True)
    # Map to entity search names
    label_to_entities = {
        "BOL": "posted_sales_shipment",
        "SHIPMENT": "posted_sales_shipment",
        "PO": "purchase_order",
        "INVOICE": "posted_purchase_invoice",
    }
    seen = set()
    entity_priority = []
    for label in priority:
        entity = label_to_entities.get(label, "")
        if entity and entity not in seen:
            entity_priority.append(entity)
            seen.add(entity)
    # Always include sales_order
    if "sales_order" not in seen:
        entity_priority.append("sales_order")
    return entity_priority


def _compute_label_bias(correction_patterns: Dict) -> Dict[str, Dict]:
    """Derive label bias from correction patterns."""
    bias = {}
    for key, pattern in correction_patterns.items():
        predicted = pattern.get("predicted_label", "")
        correct = pattern.get("correct_label", "")
        entity = pattern.get("actual_entity_type", "")
        count = pattern.get("count", 0)

        if count < 2 or not predicted or not correct:
            continue

        # Compute bias strength (proportional to count, capped)
        strength = min(count * 0.02, MAX_LABEL_BIAS)

        bias[predicted] = {
            "target_entity": entity,
            "target_label": correct,
            "boost": round(strength, 4),
            "penalty": round(max(-strength * 0.5, MAX_MATCH_PENALTY), 4),
            "count": count,
            "source": "correction_feedback",
        }

    return bias


def _compute_confidence_adjustments(
    profile_data: Dict, correction_patterns: Dict
) -> Dict[str, float]:
    """Derive entity-type confidence adjustments."""
    adjustments = {}

    # Boost entities that the vendor frequently matches
    match_counts = profile_data.get("bc_match_type_counts", {})
    total_matches = sum(match_counts.values()) if match_counts else 0

    if total_matches > 0:
        for entity_type, count in match_counts.items():
            freq = count / total_matches
            if freq > 0.5:
                adjustments[f"{entity_type}_boost"] = round(min(freq * 0.12, MAX_MATCH_BOOST), 4)
            elif freq < 0.1:
                adjustments[f"{entity_type}_penalty"] = round(max(-0.05, MAX_MATCH_PENALTY), 4)

    # Add correction-derived adjustments
    for key, pattern in correction_patterns.items():
        entity = pattern.get("actual_entity_type", "")
        count = pattern.get("count", 0)
        if entity and count >= 2:
            boost_key = f"{entity}_correction_boost"
            adjustments[boost_key] = round(min(count * 0.015, MAX_MATCH_BOOST), 4)

    return adjustments


def _determine_doc_type_bias(profile_data: Dict) -> str:
    """Determine the dominant document type for this vendor."""
    domain = profile_data.get("typical_reference_domain", "unknown")
    doc_types = profile_data.get("document_type_counts", {})

    if doc_types:
        top_type = max(doc_types.items(), key=lambda x: x[1], default=("Unknown", 0))
        if top_type[1] > 0:
            return top_type[0]

    domain_to_type = {
        "shipping": "freight_invoice",
        "purchase": "purchase_invoice",
        "sales": "sales_document",
    }
    return domain_to_type.get(domain, "unknown")


class VendorExtractionProfileService:
    """
    Manages vendor extraction profiles — probabilistic interpretation hints
    that improve accuracy without using templates or coordinates.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.collection = db.vendor_extraction_profiles
        self._learn_task = None
        self._running = False

    async def initialize(self):
        """Create indexes."""
        await self.collection.create_index("vendor_no", unique=True, sparse=True)
        await self.collection.create_index("vendor_name")
        await self.collection.create_index("last_updated")
        await self.collection.create_index("enabled")
        logger.info("[VendorExtractionProfiles] Indexes created")

    # =========================================================================
    # PROFILE GENERATION (Part 3)
    # =========================================================================

    async def generate_profile(self, vendor_id: str) -> Optional[Dict]:
        """
        Generate or update a vendor extraction profile from existing data.
        Sources: Vendor Intelligence + Label Corrections + Resolution History.
        """
        # 1. Get vendor intelligence profile
        vi_profile = await self.db.vendor_intelligence_profiles.find_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}]},
            {"_id": 0}
        )
        if not vi_profile or vi_profile.get("invoice_count", 0) < MIN_DOCS_FOR_PROFILE:
            return None

        vendor_name = vi_profile.get("vendor_name", vendor_id)
        vendor_no = vi_profile.get("vendor_no", "")

        # 2. Get label correction patterns
        correction_patterns = vi_profile.get("label_correction_patterns", {})

        # 3. Compute profile components
        reference_priority = _compute_reference_priority(vi_profile)
        label_bias = _compute_label_bias(correction_patterns)
        confidence_adjustments = _compute_confidence_adjustments(vi_profile, correction_patterns)
        doc_type_bias = _determine_doc_type_bias(vi_profile)

        now = datetime.now(timezone.utc).isoformat()
        learning_sources = ["vendor_intelligence"]
        if correction_patterns:
            learning_sources.append("correction_feedback")

        profile = {
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "document_type_bias": doc_type_bias,
            "reference_priority_order": reference_priority,
            "reference_label_bias": label_bias,
            "confidence_adjustments": confidence_adjustments,
            "enabled": True,
            "last_updated": now,
            "learning_source": learning_sources,
            "source_invoice_count": vi_profile.get("invoice_count", 0),
            "source_correction_count": sum(p.get("count", 0) for p in correction_patterns.values()),
            "source_automation_rate": vi_profile.get("automation_success_rate", 0),
            "source_match_rate": vi_profile.get("reference_resolution_success_rate", 0),
        }

        # Upsert
        await self.collection.update_one(
            {"$or": [{"vendor_no": vendor_no}, {"vendor_name": vendor_name}]},
            {"$set": profile, "$setOnInsert": {"created_at": now}},
            upsert=True
        )

        logger.info(
            "[VendorExtractionProfiles] Generated profile for %s: priority=%s, bias_count=%d, adjustments=%d",
            vendor_name[:25], reference_priority[:3], len(label_bias), len(confidence_adjustments)
        )
        return profile

    async def generate_all_profiles(self) -> Dict[str, Any]:
        """Generate profiles for all vendors with sufficient data."""
        cursor = self.db.vendor_intelligence_profiles.find(
            {"invoice_count": {"$gte": MIN_DOCS_FOR_PROFILE}},
            {"_id": 0, "vendor_no": 1, "vendor_name": 1}
        )
        vendors = await cursor.to_list(500)

        created = 0
        updated = 0
        skipped = 0

        for v in vendors:
            vid = v.get("vendor_no") or v.get("vendor_name", "")
            if not vid:
                skipped += 1
                continue

            existing = await self.collection.find_one(
                {"$or": [{"vendor_no": vid}, {"vendor_name": v.get("vendor_name", "")}]},
                {"_id": 0, "vendor_no": 1}
            )

            profile = await self.generate_profile(vid)
            if profile:
                if existing:
                    updated += 1
                else:
                    created += 1
            else:
                skipped += 1

        result = {
            "vendors_evaluated": len(vendors),
            "profiles_created": created,
            "profiles_updated": updated,
            "skipped": skipped,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        logger.info("[VendorExtractionProfiles] Batch generation: %s", result)
        return result

    # =========================================================================
    # PROFILE QUERY (Part 4 - Resolver Integration)
    # =========================================================================

    async def get_profile(self, vendor_id: str) -> Optional[Dict]:
        """Get a vendor extraction profile for resolver integration."""
        profile = await self.collection.find_one(
            {"$or": [
                {"vendor_no": vendor_id},
                {"vendor_name": vendor_id},
            ]},
            {"_id": 0}
        )
        return profile

    async def get_resolver_adjustments(self, vendor_id: str) -> Dict[str, Any]:
        """
        Get resolver-ready adjustments from the vendor profile.
        Returns structured data that the scoring function can directly consume.
        """
        profile = await self.get_profile(vendor_id)
        if not profile or not profile.get("enabled", True):
            return {"has_profile": False}

        return {
            "has_profile": True,
            "vendor_name": profile.get("vendor_name", ""),
            "document_type_bias": profile.get("document_type_bias"),
            "reference_priority_order": profile.get("reference_priority_order", []),
            "reference_label_bias": profile.get("reference_label_bias", {}),
            "confidence_adjustments": profile.get("confidence_adjustments", {}),
            "learning_source": profile.get("learning_source", []),
            "source_invoice_count": profile.get("source_invoice_count", 0),
        }

    async def get_all_profiles(self) -> List[Dict]:
        """Get all vendor extraction profiles."""
        cursor = self.collection.find({}, {"_id": 0}).sort("last_updated", -1)
        return await cursor.to_list(200)

    async def get_profile_stats(self) -> Dict[str, Any]:
        """Get aggregate stats about all profiles."""
        total = await self.collection.count_documents({})
        enabled = await self.collection.count_documents({"enabled": True})
        with_bias = await self.collection.count_documents({"reference_label_bias": {"$ne": {}}})

        return {
            "total_profiles": total,
            "enabled": enabled,
            "disabled": total - enabled,
            "with_label_bias": with_bias,
        }

    # =========================================================================
    # ADMIN CONTROLS (Part 7)
    # =========================================================================

    async def toggle_profile(self, vendor_id: str, enabled: bool) -> bool:
        """Enable or disable a vendor profile."""
        result = await self.collection.update_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}]},
            {"$set": {"enabled": enabled, "last_updated": datetime.now(timezone.utc).isoformat()}}
        )
        return result.modified_count > 0

    async def reset_profile(self, vendor_id: str) -> bool:
        """Delete a vendor profile (it will be regenerated on next learning cycle)."""
        result = await self.collection.delete_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}]}
        )
        return result.deleted_count > 0

    async def adjust_confidence(self, vendor_id: str, adjustments: Dict[str, float]) -> bool:
        """Admin override: adjust confidence weights for a vendor profile."""
        # Validate bounds
        for key, val in adjustments.items():
            adjustments[key] = max(MAX_MATCH_PENALTY, min(val, MAX_MATCH_BOOST))

        result = await self.collection.update_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}]},
            {"$set": {
                "confidence_adjustments": adjustments,
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "admin_override": True,
            }}
        )
        return result.modified_count > 0

    # =========================================================================
    # BACKGROUND LEARNING (Part 5)
    # =========================================================================

    def start_background_learning(self):
        """Start periodic profile learning."""
        if not self._running:
            self._running = True
            self._learn_task = asyncio.create_task(self._learn_loop())
            logger.info("[VendorExtractionProfiles] Background learning started (interval: %ds)", PROFILE_LEARN_INTERVAL)

    def stop_background_learning(self):
        self._running = False
        if self._learn_task:
            self._learn_task.cancel()

    async def _learn_loop(self):
        while self._running:
            try:
                await self.generate_all_profiles()
            except Exception as e:
                logger.error("[VendorExtractionProfiles] Learning error: %s", str(e))
            await asyncio.sleep(PROFILE_LEARN_INTERVAL)


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_vep_service: Optional[VendorExtractionProfileService] = None


def get_vep_service() -> Optional[VendorExtractionProfileService]:
    return _vep_service


def set_vep_service(db, event_service=None) -> VendorExtractionProfileService:
    global _vep_service
    _vep_service = VendorExtractionProfileService(db, event_service)
    return _vep_service
