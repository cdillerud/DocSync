"""
GPI Document Hub - Reference Label Correction Service

Self-learning mechanism that records and learns from mislabeled references.
When the resolver successfully matches a reference but the detected label
didn't match the actual entity type (e.g., a "PO" label that resolves to
a "Shipment"), we record that correction.

Over time, the service builds vendor-specific label correction patterns
that feed back into the resolver's scoring model.

Key features:
- Record corrections from successful resolutions
- Query vendor+label correction history
- Aggregate correction patterns per vendor
- Provide scoring adjustments based on learned patterns
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Mapping from BC entity type to the "correct" reference label
ENTITY_TO_LABEL = {
    "purchase_order": "PO",
    "purchase_invoice": "INVOICE",
    "posted_purchase_invoice": "INVOICE",
    "sales_order": "ORDER",
    "sales_invoice": "INVOICE",
    "posted_sales_invoice": "INVOICE",
    "sales_shipment": "SHIPMENT",
    "posted_sales_shipment": "SHIPMENT",
}

# Labels that are considered "compatible" with an entity type (no correction needed)
COMPATIBLE_LABELS = {
    "purchase_order": {"PO", "ORDER", "REF"},
    "purchase_invoice": {"INVOICE", "REF"},
    "posted_purchase_invoice": {"INVOICE", "REF"},
    "sales_order": {"ORDER", "PO", "REF", "CUSTOMER_REF"},
    "sales_invoice": {"INVOICE", "REF"},
    "posted_sales_invoice": {"INVOICE", "REF"},
    "sales_shipment": {"SHIPMENT", "BOL", "LOAD", "PRO", "REF"},
    "posted_sales_shipment": {"SHIPMENT", "BOL", "LOAD", "PRO", "REF"},
}


class LabelCorrectionService:
    """
    Records and queries reference label corrections to enable
    self-learning in the resolver's scoring model.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.collection = db.reference_label_corrections

    async def initialize(self):
        """Create indexes for efficient queries."""
        await self.collection.create_index("vendor_no")
        await self.collection.create_index("vendor_name")
        await self.collection.create_index([("vendor_no", 1), ("predicted_label", 1)])
        await self.collection.create_index("document_id")
        await self.collection.create_index("created_at")
        logger.info("[LabelCorrection] Indexes created")

    async def record_correction(
        self,
        document_id: str,
        reference_value: str,
        predicted_label: str,
        actual_entity_type: str,
        vendor_no: str = "",
        vendor_name: str = "",
        match_score: float = 0.0,
        match_outcome: str = "",
    ) -> Optional[Dict]:
        """
        Record a label correction when a reference's detected label
        doesn't match the entity type it actually resolved to.

        Returns the correction record if stored, None if no correction needed.
        """
        # Determine if a correction is warranted
        correct_label = ENTITY_TO_LABEL.get(actual_entity_type, "UNKNOWN")
        compatible = COMPATIBLE_LABELS.get(actual_entity_type, set())

        if predicted_label in compatible:
            return None

        now = datetime.now(timezone.utc).isoformat()
        correction = {
            "document_id": document_id,
            "reference_value": reference_value,
            "predicted_label": predicted_label,
            "correct_label": correct_label,
            "actual_entity_type": actual_entity_type,
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "match_score": round(match_score, 4),
            "match_outcome": match_outcome,
            "created_at": now,
        }

        await self.collection.insert_one(correction)
        logger.info(
            "[LabelCorrection] Recorded: %s → %s (was '%s') for vendor %s, doc %s",
            reference_value, correct_label, predicted_label,
            vendor_name[:20] or vendor_no, document_id[:8]
        )

        if self.event_service:
            await self.event_service.emit(
                event_type="label_correction.recorded",
                document_id=document_id,
                source_service="label_correction",
                payload={
                    "predicted_label": predicted_label,
                    "correct_label": correct_label,
                    "actual_entity_type": actual_entity_type,
                    "vendor_no": vendor_no,
                }
            )

        return correction

    async def detect_and_record(
        self,
        document_id: str,
        resolution_result: Dict[str, Any],
        document: Dict[str, Any],
    ) -> List[Dict]:
        """
        Given a resolution result, detect any label mismatches
        and record corrections. Called after successful resolution.

        Returns list of corrections recorded.
        """
        best_match = resolution_result.get("best_match")
        if not best_match:
            return []

        outcome = resolution_result.get("match_outcome", "")
        if outcome not in ("exact_match", "likely_match"):
            return []

        entity_type = best_match.get("entity_type", "")
        match_score = best_match.get("match_score", 0)

        # Part 1 learning rule: only learn from high-confidence matches (≥ 0.70)
        if match_score < 0.70:
            return []
        bc_doc_no = best_match.get("bc_document_no", "")

        # Get vendor info
        uvm = document.get("unified_vendor_match") or {}
        vendor_no = uvm.get("bc_vendor_no", "")
        vendor_name = (
            document.get("vendor_raw")
            or document.get("matched_vendor_name")
            or document.get("vendor_canonical")
            or ""
        )

        # Check each candidate that contributed to this match
        candidates = resolution_result.get("reference_candidates", [])
        corrections = []

        for candidate in candidates:
            ref_normalized = candidate.get("reference_value_normalized", "")
            detected_label = candidate.get("detected_label", "")

            # Only check candidates whose normalized value matches the best match
            if ref_normalized and bc_doc_no:
                from services.reference_intelligence_service import normalize_reference
                if normalize_reference(bc_doc_no) != ref_normalized:
                    continue

            correction = await self.record_correction(
                document_id=document_id,
                reference_value=ref_normalized,
                predicted_label=detected_label,
                actual_entity_type=entity_type,
                vendor_no=vendor_no,
                vendor_name=vendor_name,
                match_score=match_score,
                match_outcome=outcome,
            )
            if correction:
                corrections.append(correction)

        return corrections

    async def get_vendor_patterns(self, vendor_id: str) -> Dict[str, Any]:
        """
        Get aggregated label correction patterns for a vendor.
        Returns the most common corrections and suggested label remappings.
        """
        pipeline = [
            {"$match": {"$or": [
                {"vendor_no": vendor_id},
                {"vendor_name": vendor_id},
            ]}},
            {"$group": {
                "_id": {
                    "predicted_label": "$predicted_label",
                    "correct_label": "$correct_label",
                    "actual_entity_type": "$actual_entity_type",
                },
                "count": {"$sum": 1},
                "avg_score": {"$avg": "$match_score"},
                "last_seen": {"$max": "$created_at"},
            }},
            {"$sort": {"count": -1}},
        ]

        results = await self.collection.aggregate(pipeline).to_list(50)
        if not results:
            return {"has_patterns": False, "vendor_id": vendor_id}

        total = sum(r["count"] for r in results)
        patterns = []
        label_remaps = {}

        for r in results:
            predicted = r["_id"]["predicted_label"]
            correct = r["_id"]["correct_label"]
            entity = r["_id"]["actual_entity_type"]
            count = r["count"]

            patterns.append({
                "predicted_label": predicted,
                "correct_label": correct,
                "actual_entity_type": entity,
                "count": count,
                "frequency": round(count / max(total, 1), 3),
                "avg_score": round(r.get("avg_score", 0), 4),
                "last_seen": r.get("last_seen"),
            })

            # Build label remaps — if a label consistently resolves to a different entity
            if count >= 2:
                key = predicted
                if key not in label_remaps or label_remaps[key]["count"] < count:
                    label_remaps[key] = {
                        "remap_to": correct,
                        "actual_entity_type": entity,
                        "count": count,
                        "confidence": round(count / max(total, 1), 3),
                    }

        # Detect unstable patterns — conflicting corrections for the same label
        unstable_labels = set()
        label_entity_map = {}
        for r in results:
            predicted = r["_id"]["predicted_label"]
            entity = r["_id"]["actual_entity_type"]
            count = r["count"]
            if predicted not in label_entity_map:
                label_entity_map[predicted] = []
            label_entity_map[predicted].append({"entity": entity, "count": count})
        
        for label, entities in label_entity_map.items():
            if len(entities) > 1:
                # Multiple different entity types for the same label correction
                top_count = max(e["count"] for e in entities)
                second_count = sorted([e["count"] for e in entities], reverse=True)[1] if len(entities) > 1 else 0
                # If the second entity has at least 40% of the top count, mark as unstable
                if second_count >= top_count * 0.4:
                    unstable_labels.add(label)

        return {
            "has_patterns": True,
            "vendor_id": vendor_id,
            "total_corrections": total,
            "patterns": patterns,
            "label_remaps": label_remaps,
            "unstable_labels": list(unstable_labels),
            "pattern_stability": "unstable" if unstable_labels else "stable",
        }

    async def get_scoring_hints(self, vendor_id: str, predicted_label: str) -> Dict[str, Any]:
        """
        Get scoring adjustments for a specific vendor+label combination.
        Used by the resolver to boost/penalize entity type scores.
        """
        pipeline = [
            {"$match": {
                "$or": [{"vendor_no": vendor_id}, {"vendor_name": vendor_id}],
                "predicted_label": predicted_label,
            }},
            {"$group": {
                "_id": "$actual_entity_type",
                "count": {"$sum": 1},
                "avg_score": {"$avg": "$match_score"},
            }},
            {"$sort": {"count": -1}},
        ]

        results = await self.collection.aggregate(pipeline).to_list(10)
        if not results:
            return {"has_hints": False}

        total = sum(r["count"] for r in results)
        entity_boosts = {}
        
        # Check if this label has conflicting corrections (unstable pattern)
        is_unstable = len(results) > 1
        if is_unstable:
            top_count = results[0]["count"]
            second_count = results[1]["count"] if len(results) > 1 else 0
            is_unstable = second_count >= top_count * 0.4

        for r in results:
            entity = r["_id"]
            freq = r["count"] / max(total, 1)
            # Boost proportional to frequency: max 0.15 for labels that always mismatch
            # Cap at 0.08 for unstable patterns to prevent runaway bias
            max_boost = 0.08 if is_unstable else 0.15
            boost = min(freq * 0.15, max_boost)
            entity_boosts[entity] = {
                "boost": round(boost, 4),
                "count": r["count"],
                "frequency": round(freq, 3),
            }

        return {
            "has_hints": True,
            "predicted_label": predicted_label,
            "total_corrections": total,
            "entity_boosts": entity_boosts,
            "is_unstable": is_unstable,
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get overall label correction statistics."""
        total = await self.collection.count_documents({})
        if total == 0:
            return {
                "total_corrections": 0,
                "unique_vendors": 0,
                "top_corrections": [],
            }

        # Top correction patterns
        pipeline = [
            {"$group": {
                "_id": {
                    "predicted_label": "$predicted_label",
                    "correct_label": "$correct_label",
                },
                "count": {"$sum": 1},
                "vendors": {"$addToSet": "$vendor_name"},
            }},
            {"$sort": {"count": -1}},
            {"$limit": 10},
        ]
        top = await self.collection.aggregate(pipeline).to_list(10)

        unique_vendors_pipeline = [
            {"$group": {"_id": "$vendor_no"}},
            {"$count": "count"},
        ]
        vendor_count = await self.collection.aggregate(unique_vendors_pipeline).to_list(1)

        return {
            "total_corrections": total,
            "unique_vendors": vendor_count[0]["count"] if vendor_count else 0,
            "top_corrections": [
                {
                    "predicted": r["_id"]["predicted_label"],
                    "correct": r["_id"]["correct_label"],
                    "count": r["count"],
                    "vendor_count": len(r.get("vendors", [])),
                }
                for r in top
            ],
        }

    async def get_corrections_for_document(self, document_id: str) -> List[Dict]:
        """Get all corrections associated with a document."""
        cursor = self.collection.find(
            {"document_id": document_id}, {"_id": 0}
        ).sort("created_at", -1)
        return await cursor.to_list(50)

    async def get_recent_corrections(self, limit: int = 20) -> List[Dict]:
        """Get most recent corrections."""
        cursor = self.collection.find(
            {}, {"_id": 0}
        ).sort("created_at", -1).limit(limit)
        return await cursor.to_list(limit)


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_label_correction_service: Optional[LabelCorrectionService] = None


def get_label_correction_service() -> Optional[LabelCorrectionService]:
    return _label_correction_service


def set_label_correction_service(db, event_service=None) -> LabelCorrectionService:
    global _label_correction_service
    _label_correction_service = LabelCorrectionService(db, event_service)
    return _label_correction_service
