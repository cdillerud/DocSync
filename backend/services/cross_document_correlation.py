"""
GPI Document Hub — Cross-Document Correlation Service

Links documents that reference the same business event into clusters.
Clusters improve future resolver accuracy, allow missing references
to be inferred, and improve audit traceability.

Collection: document_reference_clusters
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# Cluster auto-expire after 90 days of inactivity
CLUSTER_EXPIRY_DAYS = 90


class CrossDocumentCorrelationService:
    """
    Maintains clusters of documents linked by shared reference signals.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.clusters = db.document_reference_clusters

    async def initialize(self):
        """Create indexes for cluster collection."""
        await self.clusters.create_index("cluster_id", unique=True)
        await self.clusters.create_index("document_ids")
        await self.clusters.create_index("reference_signals.value")
        await self.clusters.create_index("vendor_name")
        await self.clusters.create_index("customer_name")
        await self.clusters.create_index("updated_at")
        logger.info("[CrossDocCorrelation] Indexes created")

    async def update_cluster_from_document(self, document: Dict[str, Any]) -> Optional[str]:
        """
        After a document is resolved, update or create a cluster.

        Returns the cluster_id if the document was added to a cluster.
        """
        doc_id = document.get("id", "")
        if not doc_id:
            return None

        signals = self._extract_signals(document)
        if not signals:
            return None

        # Search for existing cluster that shares signals
        existing = await self._find_matching_cluster(signals, doc_id)

        now = datetime.now(timezone.utc).isoformat()

        if existing:
            cluster_id = existing["cluster_id"]
            # Merge signals and add document
            merged_signals = self._merge_signals(existing.get("reference_signals", []), signals)
            update = {
                "$addToSet": {"document_ids": doc_id},
                "$set": {
                    "reference_signals": merged_signals,
                    "updated_at": now,
                    "document_count": len(set(existing.get("document_ids", []) + [doc_id])),
                },
            }
            # Update vendor/customer if not set
            if not existing.get("vendor_name") and document.get("vendor_raw"):
                update["$set"]["vendor_name"] = document["vendor_raw"]
            if not existing.get("customer_name") and document.get("customer_name"):
                update["$set"]["customer_name"] = document["customer_name"]

            await self.clusters.update_one({"cluster_id": cluster_id}, update)
            logger.info("[CrossDocCorrelation] Added doc %s to cluster %s", doc_id[:8], cluster_id[:12])
            return cluster_id
        else:
            # Create new cluster
            import uuid
            cluster_id = f"cluster_{uuid.uuid4().hex[:12]}"
            cluster = {
                "cluster_id": cluster_id,
                "document_ids": [doc_id],
                "document_count": 1,
                "reference_signals": signals,
                "vendor_name": document.get("vendor_raw") or document.get("matched_vendor_name") or "",
                "customer_name": document.get("customer_name") or "",
                "bc_entity_types": [],
                "created_at": now,
                "updated_at": now,
            }

            # Add BC entity info if available
            ref_intel = document.get("reference_intelligence") or {}
            best = ref_intel.get("best_match") or {}
            if best.get("entity_type"):
                cluster["bc_entity_types"] = [best["entity_type"]]
            if best.get("bc_document_no"):
                cluster["reference_signals"].append({
                    "type": "bc_document_no",
                    "value": best["bc_document_no"],
                    "source": "resolution",
                })

            await self.clusters.insert_one(cluster)
            logger.info("[CrossDocCorrelation] Created cluster %s for doc %s", cluster_id[:12], doc_id[:8])
            return cluster_id

    async def get_cluster_for_document(self, doc_id: str) -> Optional[Dict]:
        """Get the cluster a document belongs to."""
        cluster = await self.clusters.find_one(
            {"document_ids": doc_id},
            {"_id": 0}
        )
        return cluster

    async def get_cluster_by_id(self, cluster_id: str) -> Optional[Dict]:
        return await self.clusters.find_one({"cluster_id": cluster_id}, {"_id": 0})

    async def find_related_documents(self, doc_id: str) -> List[str]:
        """Find all document IDs in the same cluster as this document."""
        cluster = await self.get_cluster_for_document(doc_id)
        if not cluster:
            return []
        return [d for d in cluster.get("document_ids", []) if d != doc_id]

    async def get_cluster_match_bonus(self, document: Dict[str, Any], bc_record: Dict) -> Dict:
        """
        Check if a BC record matches signals in the document's cluster.
        Returns bonus scoring info.
        """
        doc_id = document.get("id", "")
        cluster = await self.get_cluster_for_document(doc_id)
        if not cluster:
            return {"has_cluster_bonus": False, "cluster_bonus": 0.0}

        bc_doc_no = bc_record.get("number") or bc_record.get("bc_document_no") or ""
        bc_order_no = bc_record.get("orderNumber") or bc_record.get("order_number") or ""

        cluster_refs = {s["value"] for s in cluster.get("reference_signals", [])}

        bonus = 0.0
        reasons = []

        if bc_doc_no and bc_doc_no in cluster_refs:
            bonus += 0.05
            reasons.append(f"BC doc {bc_doc_no} found in cluster")
        if bc_order_no and bc_order_no in cluster_refs:
            bonus += 0.03
            reasons.append(f"Order {bc_order_no} found in cluster")

        return {
            "has_cluster_bonus": bonus > 0,
            "cluster_bonus": round(min(bonus, 0.08), 4),
            "cluster_id": cluster["cluster_id"],
            "cluster_size": cluster.get("document_count", 0),
            "reasons": reasons,
        }

    async def get_cluster_stats(self) -> Dict:
        """Aggregate stats for diagnostics."""
        total = await self.clusters.count_documents({})
        multi = await self.clusters.count_documents({"document_count": {"$gte": 2}})
        pipeline = [
            {"$group": {
                "_id": None,
                "avg_size": {"$avg": "$document_count"},
                "max_size": {"$max": "$document_count"},
                "total_docs": {"$sum": "$document_count"},
            }}
        ]
        agg = await self.clusters.aggregate(pipeline).to_list(1)
        stats = agg[0] if agg else {}
        return {
            "total_clusters": total,
            "multi_document_clusters": multi,
            "avg_cluster_size": round(stats.get("avg_size", 0) or 0, 2),
            "max_cluster_size": stats.get("max_size", 0),
            "total_clustered_documents": stats.get("total_docs", 0),
        }

    # =========================================================================
    # INTERNAL
    # =========================================================================

    def _extract_signals(self, document: Dict) -> List[Dict]:
        """Extract reference signals from a document for clustering."""
        signals = []
        seen = set()

        def _add(signal_type: str, value: str, source: str = "extraction"):
            if value and value not in seen:
                seen.add(value)
                signals.append({"type": signal_type, "value": value, "source": source})

        _add("po_number", document.get("po_number_clean") or "")
        _add("bol_number", document.get("bol_number") or "")
        _add("invoice_number", document.get("invoice_number_clean") or "")
        _add("shipment_number", document.get("shipment_number") or "")

        # From reference intelligence
        ref_intel = document.get("reference_intelligence") or {}
        for cand in ref_intel.get("reference_candidates") or []:
            _add(cand.get("detected_label", "REF"), cand.get("reference_value_normalized", ""), "candidate")

        best = ref_intel.get("best_match") or {}
        _add("bc_document_no", best.get("bc_document_no") or "", "resolution")

        return signals

    async def _find_matching_cluster(self, signals: List[Dict], doc_id: str) -> Optional[Dict]:
        """Find an existing cluster that shares at least one signal."""
        signal_values = [s["value"] for s in signals if s["value"]]
        if not signal_values:
            return None

        return await self.clusters.find_one(
            {
                "reference_signals.value": {"$in": signal_values},
                "document_ids": {"$ne": doc_id},
            },
            {"_id": 0}
        )

    def _merge_signals(self, existing: List[Dict], new: List[Dict]) -> List[Dict]:
        """Merge signal lists, deduplicating by value."""
        seen = {s["value"] for s in existing}
        merged = list(existing)
        for s in new:
            if s["value"] and s["value"] not in seen:
                seen.add(s["value"])
                merged.append(s)
        return merged
