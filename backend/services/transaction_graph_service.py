"""
GPI Document Hub — Transaction Graph Service

Models relationships between business documents (POs, Invoices, Shipments,
BOLs, Customs Entries, etc.) as a directed graph of nodes and edges.

Design principles:
  - ADDITIVE: the graph is never a hard dependency for the pipeline
  - PROBABILISTIC: every edge carries confidence + provenance
  - TRANSACTION-AWARE: groups documents by business transaction
  - ZETADOCS-REPLACEMENT-ALIGNED: enables BC linking, transaction
    attachment, and retrieval by business record

Collections:
  - transaction_graph_nodes   — one per unique reference entity
  - transaction_graph_edges   — probabilistic links between nodes

Node types model business entities:
  document, purchase_order, sales_order, invoice, shipment,
  bill_of_lading, customs_entry, bc_record

Edge provenance tracks HOW the link was discovered:
  linked_by_extraction, linked_by_resolver, linked_by_processor,
  linked_by_shared_reference, linked_by_bc_linkage, manual
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

# ─── Node type constants ───────────────────────────────────────────────
NODE_TYPE_DOCUMENT = "document"
NODE_TYPE_PURCHASE_ORDER = "purchase_order"
NODE_TYPE_SALES_ORDER = "sales_order"
NODE_TYPE_INVOICE = "invoice"
NODE_TYPE_SHIPMENT = "shipment"
NODE_TYPE_BILL_OF_LADING = "bill_of_lading"
NODE_TYPE_CUSTOMS_ENTRY = "customs_entry"
NODE_TYPE_BC_RECORD = "bc_record"

# ─── Edge type constants ──────────────────────────────────────────────
EDGE_CONTAINS_REFERENCE = "contains_reference"
EDGE_INVOICES_FOR = "invoices_for"
EDGE_SHIPS_FOR = "ships_for"
EDGE_CUSTOMS_FOR = "customs_for"
EDGE_LINKED_TO_BC = "linked_to_bc"
EDGE_SAME_TRANSACTION = "same_transaction"
EDGE_SHARED_REFERENCE = "shared_reference"

# ─── Provenance constants ────────────────────────────────────────────
PROV_EXTRACTION = "linked_by_extraction"
PROV_RESOLVER = "linked_by_resolver"
PROV_PROCESSOR = "linked_by_processor"
PROV_SHARED_REF = "linked_by_shared_reference"
PROV_BC_LINKAGE = "linked_by_bc_linkage"
PROV_MANUAL = "manual"

# Map doc_type → node_type for reference nodes
_DOC_TYPE_TO_REF_NODE = {
    "AP_INVOICE": NODE_TYPE_INVOICE,
    "PURCHASE_ORDER": NODE_TYPE_PURCHASE_ORDER,
    "SALES_ORDER": NODE_TYPE_SALES_ORDER,
    "SALES_INVOICE": NODE_TYPE_INVOICE,
    "Freight_Invoice": NODE_TYPE_INVOICE,
    "Shipping_Document": NODE_TYPE_SHIPMENT,
    "BOL": NODE_TYPE_BILL_OF_LADING,
    "Bill_of_Lading": NODE_TYPE_BILL_OF_LADING,
    "Customs_Entry": NODE_TYPE_CUSTOMS_ENTRY,
}

# Map reference label → node type
_REF_LABEL_TO_NODE = {
    "PO": NODE_TYPE_PURCHASE_ORDER,
    "po_number": NODE_TYPE_PURCHASE_ORDER,
    "ORDER": NODE_TYPE_SALES_ORDER,
    "order_number": NODE_TYPE_SALES_ORDER,
    "INVOICE": NODE_TYPE_INVOICE,
    "invoice_number": NODE_TYPE_INVOICE,
    "BOL": NODE_TYPE_BILL_OF_LADING,
    "bol_number": NODE_TYPE_BILL_OF_LADING,
    "SHIPMENT": NODE_TYPE_SHIPMENT,
    "shipment_number": NODE_TYPE_SHIPMENT,
    "PRO": NODE_TYPE_SHIPMENT,
    "LOAD": NODE_TYPE_SHIPMENT,
    "CUSTOMER_REF": NODE_TYPE_SALES_ORDER,
}

# Map reference node type → edge type from document
_NODE_TO_EDGE_TYPE = {
    NODE_TYPE_PURCHASE_ORDER: EDGE_CONTAINS_REFERENCE,
    NODE_TYPE_SALES_ORDER: EDGE_CONTAINS_REFERENCE,
    NODE_TYPE_INVOICE: EDGE_CONTAINS_REFERENCE,
    NODE_TYPE_BILL_OF_LADING: EDGE_CONTAINS_REFERENCE,
    NODE_TYPE_SHIPMENT: EDGE_CONTAINS_REFERENCE,
    NODE_TYPE_CUSTOMS_ENTRY: EDGE_CUSTOMS_FOR,
    NODE_TYPE_BC_RECORD: EDGE_LINKED_TO_BC,
}


class TransactionGraphService:
    """Build and query the transaction graph."""

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.nodes = db.transaction_graph_nodes
        self.edges = db.transaction_graph_edges

    # ───────────────────────────────────────────────────────────────────
    # INITIALIZATION
    # ───────────────────────────────────────────────────────────────────
    async def initialize(self):
        """Create indexes."""
        await self.nodes.create_index("node_id", unique=True)
        await self.nodes.create_index("node_type")
        await self.nodes.create_index("reference_value")
        await self.nodes.create_index("source_document_id")
        await self.nodes.create_index([("node_type", 1), ("reference_value", 1)])

        await self.edges.create_index("edge_id", unique=True)
        await self.edges.create_index("from_node")
        await self.edges.create_index("to_node")
        await self.edges.create_index("edge_type")
        await self.edges.create_index("provenance")
        await self.edges.create_index([("from_node", 1), ("to_node", 1), ("edge_type", 1)])

        logger.info("[TransactionGraph] Indexes created")

    # ───────────────────────────────────────────────────────────────────
    # NODE OPERATIONS
    # ───────────────────────────────────────────────────────────────────
    async def upsert_node(
        self,
        node_type: str,
        reference_value: str,
        reference_type: str = "",
        source_document_id: str = "",
        bc_entity_type: str = "",
        bc_document_no: str = "",
        vendor_name: str = "",
        customer_name: str = "",
        metadata: Optional[Dict] = None,
    ) -> str:
        """Create or update a node. Dedup by (node_type, reference_value).
        Returns the node_id."""
        if not reference_value:
            return ""

        existing = await self.nodes.find_one(
            {"node_type": node_type, "reference_value": reference_value},
            {"_id": 0, "node_id": 1},
        )
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            node_id = existing["node_id"]
            update: Dict[str, Any] = {"$set": {"updated_at": now}}
            if source_document_id:
                update["$addToSet"] = {"source_document_ids": source_document_id}
            if vendor_name:
                update["$set"]["vendor_name"] = vendor_name
            if customer_name:
                update["$set"]["customer_name"] = customer_name
            if bc_document_no:
                update["$set"]["bc_document_no"] = bc_document_no
            if bc_entity_type:
                update["$set"]["bc_entity_type"] = bc_entity_type
            if metadata:
                for k, v in metadata.items():
                    update["$set"][f"metadata.{k}"] = v
            await self.nodes.update_one({"node_id": node_id}, update)
            return node_id

        node_id = f"node_{uuid.uuid4().hex[:12]}"
        node = {
            "node_id": node_id,
            "node_type": node_type,
            "reference_value": reference_value,
            "reference_type": reference_type,
            "source_document_id": source_document_id,
            "source_document_ids": [source_document_id] if source_document_id else [],
            "bc_entity_type": bc_entity_type,
            "bc_document_no": bc_document_no,
            "vendor_name": vendor_name,
            "customer_name": customer_name,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        await self.nodes.insert_one(node)
        return node_id

    async def get_node(self, node_id: str) -> Optional[Dict]:
        return await self.nodes.find_one({"node_id": node_id}, {"_id": 0})

    async def get_node_by_ref(self, node_type: str, reference_value: str) -> Optional[Dict]:
        return await self.nodes.find_one(
            {"node_type": node_type, "reference_value": reference_value}, {"_id": 0}
        )

    # ───────────────────────────────────────────────────────────────────
    # EDGE OPERATIONS
    # ───────────────────────────────────────────────────────────────────
    async def create_edge(
        self,
        from_node: str,
        to_node: str,
        edge_type: str,
        confidence: float,
        provenance: str,
        evidence: Optional[List[Dict]] = None,
    ) -> str:
        """Create an edge. Dedup by (from_node, to_node, edge_type).
        Updates confidence if higher. Returns edge_id."""
        if not from_node or not to_node:
            return ""

        existing = await self.edges.find_one(
            {"from_node": from_node, "to_node": to_node, "edge_type": edge_type},
            {"_id": 0, "edge_id": 1, "confidence": 1},
        )
        now = datetime.now(timezone.utc).isoformat()

        if existing:
            edge_id = existing["edge_id"]
            update: Dict[str, Any] = {"$set": {"updated_at": now}}
            if confidence > existing.get("confidence", 0):
                update["$set"]["confidence"] = confidence
                update["$set"]["provenance"] = provenance
            if evidence:
                update["$addToSet"] = {"evidence": {"$each": evidence}}
            await self.edges.update_one({"edge_id": edge_id}, update)
            return edge_id

        edge_id = f"edge_{uuid.uuid4().hex[:12]}"
        edge = {
            "edge_id": edge_id,
            "from_node": from_node,
            "to_node": to_node,
            "edge_type": edge_type,
            "confidence": round(confidence, 4),
            "provenance": provenance,
            "evidence": evidence or [],
            "created_at": now,
            "updated_at": now,
        }
        await self.edges.insert_one(edge)
        return edge_id

    async def get_edges_for_node(self, node_id: str) -> List[Dict]:
        """Get all edges where node is either from_node or to_node."""
        cursor = self.edges.find(
            {"$or": [{"from_node": node_id}, {"to_node": node_id}]},
            {"_id": 0},
        )
        return await cursor.to_list(length=200)

    # ───────────────────────────────────────────────────────────────────
    # DOCUMENT INGESTION — auto-populate graph
    # ───────────────────────────────────────────────────────────────────
    async def ingest_document(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called after a document is processed/resolved.
        Extracts nodes and edges from the document.
        Returns summary of what was created.

        This is ADDITIVE — failures here never block the pipeline.
        """
        doc_id = document.get("id", "")
        if not doc_id:
            return {"status": "skipped", "reason": "no doc_id"}

        summary = {"doc_id": doc_id, "nodes_created": 0, "edges_created": 0, "links": []}

        try:
            # 1. Create document node
            doc_type = document.get("document_type") or document.get("suggested_job_type") or "OTHER"
            doc_node_id = await self.upsert_node(
                node_type=NODE_TYPE_DOCUMENT,
                reference_value=doc_id,
                reference_type="document_id",
                source_document_id=doc_id,
                vendor_name=document.get("vendor_raw") or document.get("matched_vendor_name") or "",
                customer_name=document.get("customer_name") or "",
                metadata={
                    "doc_type": doc_type,
                    "file_name": document.get("file_name", ""),
                    "status": document.get("status", ""),
                },
            )
            summary["nodes_created"] += 1
            summary["doc_node_id"] = doc_node_id

            # 2. Extract reference nodes from extracted fields
            ref_nodes = await self._create_reference_nodes(document, doc_node_id, summary)

            # 3. Create edges from reference_intelligence if available
            await self._create_resolver_edges(document, doc_node_id, ref_nodes, summary)

            # 4. Create edges from processor_result if available
            await self._create_processor_edges(document, doc_node_id, ref_nodes, summary)

            # 5. Create BC linkage edges if document is linked
            await self._create_bc_edges(document, doc_node_id, summary)

            # 6. Cross-link: find other document nodes sharing the same reference nodes
            await self._create_shared_reference_edges(doc_node_id, ref_nodes, summary)

            logger.info(
                "[TransactionGraph] Ingested doc %s: %d nodes, %d edges",
                doc_id[:8], summary["nodes_created"], summary["edges_created"],
            )

        except Exception as e:
            logger.error("[TransactionGraph] Error ingesting doc %s: %s", doc_id[:8], str(e))
            summary["error"] = str(e)

        return summary

    # ───────────────────────────────────────────────────────────────────
    # QUERY — document connections
    # ───────────────────────────────────────────────────────────────────
    async def get_document_connections(self, doc_id: str) -> Dict[str, Any]:
        """Get the full transaction context for a document."""
        doc_node = await self.get_node_by_ref(NODE_TYPE_DOCUMENT, doc_id)
        if not doc_node:
            return {"doc_id": doc_id, "found": False, "nodes": [], "edges": []}

        doc_node_id = doc_node["node_id"]

        # Get direct edges
        direct_edges = await self.get_edges_for_node(doc_node_id)

        # Collect all connected node IDs
        connected_ids = set()
        for e in direct_edges:
            connected_ids.add(e["from_node"])
            connected_ids.add(e["to_node"])
        connected_ids.discard(doc_node_id)

        # Get 2nd-degree edges (edges of connected nodes)
        second_degree_edges = []
        second_degree_ids = set()
        for nid in list(connected_ids):
            edges = await self.get_edges_for_node(nid)
            for e in edges:
                if e["edge_id"] not in {de["edge_id"] for de in direct_edges}:
                    second_degree_edges.append(e)
                    second_degree_ids.add(e["from_node"])
                    second_degree_ids.add(e["to_node"])

        all_ids = connected_ids | second_degree_ids
        all_ids.add(doc_node_id)

        # Fetch all nodes
        nodes = []
        if all_ids:
            cursor = self.nodes.find(
                {"node_id": {"$in": list(all_ids)}}, {"_id": 0}
            )
            nodes = await cursor.to_list(length=500)

        all_edges = direct_edges + second_degree_edges
        # Deduplicate edges
        seen_edge_ids = set()
        unique_edges = []
        for e in all_edges:
            if e["edge_id"] not in seen_edge_ids:
                seen_edge_ids.add(e["edge_id"])
                unique_edges.append(e)

        # Identify connected documents (other document nodes)
        connected_docs = []
        for n in nodes:
            if n["node_type"] == NODE_TYPE_DOCUMENT and n["reference_value"] != doc_id:
                connected_docs.append({
                    "doc_id": n["reference_value"],
                    "doc_type": n.get("metadata", {}).get("doc_type", ""),
                    "file_name": n.get("metadata", {}).get("file_name", ""),
                    "vendor_name": n.get("vendor_name", ""),
                })

        return {
            "doc_id": doc_id,
            "found": True,
            "doc_node_id": doc_node_id,
            "nodes": nodes,
            "edges": unique_edges,
            "connected_documents": connected_docs,
            "node_count": len(nodes),
            "edge_count": len(unique_edges),
            "connected_document_count": len(connected_docs),
        }

    # ───────────────────────────────────────────────────────────────────
    # GRAPH LINKAGE BONUS — for resolver scoring
    # ───────────────────────────────────────────────────────────────────
    async def get_linkage_bonus(self, document: Dict, bc_record: Dict) -> Dict:
        """
        Calculate a graph-assisted scoring bonus for the resolver.
        Checks if a BC record appears in the same transaction graph
        as the document being resolved.

        Returns:
            {
                "has_graph_bonus": bool,
                "graph_bonus": float (0.0–0.10),
                "graph_evidence": [str],
                "connected_document_count": int,
            }
        """
        doc_id = document.get("id", "")
        bc_doc_no = bc_record.get("number") or bc_record.get("bc_document_no") or ""
        bc_order_no = bc_record.get("orderNumber") or bc_record.get("order_number") or ""

        result = {
            "has_graph_bonus": False,
            "graph_bonus": 0.0,
            "graph_evidence": [],
            "connected_document_count": 0,
        }

        if not doc_id:
            return result

        doc_node = await self.get_node_by_ref(NODE_TYPE_DOCUMENT, doc_id)
        if not doc_node:
            return result

        doc_node_id = doc_node["node_id"]
        edges = await self.get_edges_for_node(doc_node_id)
        connected_node_ids = set()
        for e in edges:
            connected_node_ids.add(e["from_node"])
            connected_node_ids.add(e["to_node"])
        connected_node_ids.discard(doc_node_id)

        if not connected_node_ids:
            return result

        # Fetch connected nodes
        cursor = self.nodes.find(
            {"node_id": {"$in": list(connected_node_ids)}}, {"_id": 0}
        )
        connected_nodes = await cursor.to_list(length=200)

        bonus = 0.0
        evidence = []

        for node in connected_nodes:
            ref_val = node.get("reference_value", "")
            node_bc_no = node.get("bc_document_no", "")

            # Check if BC record's number matches a connected node
            if bc_doc_no and (ref_val == bc_doc_no or node_bc_no == bc_doc_no):
                bonus += 0.05
                evidence.append(f"BC doc {bc_doc_no} found in transaction graph")

            # Check if BC order number matches
            if bc_order_no and ref_val == bc_order_no:
                bonus += 0.03
                evidence.append(f"BC order {bc_order_no} found in transaction graph")

        # Count connected documents for context
        doc_count = sum(1 for n in connected_nodes if n["node_type"] == NODE_TYPE_DOCUMENT)

        result["has_graph_bonus"] = bonus > 0
        result["graph_bonus"] = round(min(bonus, 0.10), 4)
        result["graph_evidence"] = evidence
        result["connected_document_count"] = doc_count

        return result

    # ───────────────────────────────────────────────────────────────────
    # STATISTICS
    # ───────────────────────────────────────────────────────────────────
    async def get_stats(self) -> Dict[str, Any]:
        """Aggregate graph statistics."""
        total_nodes = await self.nodes.count_documents({})
        total_edges = await self.edges.count_documents({})

        # Count by node type
        node_type_pipeline = [
            {"$group": {"_id": "$node_type", "count": {"$sum": 1}}}
        ]
        node_types = {}
        async for doc in self.nodes.aggregate(node_type_pipeline):
            node_types[doc["_id"]] = doc["count"]

        # Count by edge type
        edge_type_pipeline = [
            {"$group": {"_id": "$edge_type", "count": {"$sum": 1}}}
        ]
        edge_types = {}
        async for doc in self.edges.aggregate(edge_type_pipeline):
            edge_types[doc["_id"]] = doc["count"]

        # Count by provenance
        prov_pipeline = [
            {"$group": {"_id": "$provenance", "count": {"$sum": 1}}}
        ]
        provenances = {}
        async for doc in self.edges.aggregate(prov_pipeline):
            provenances[doc["_id"]] = doc["count"]

        # Average confidence
        conf_pipeline = [
            {"$group": {"_id": None, "avg_confidence": {"$avg": "$confidence"}}}
        ]
        conf_agg = await self.edges.aggregate(conf_pipeline).to_list(1)
        avg_confidence = round((conf_agg[0]["avg_confidence"] if conf_agg else 0) or 0, 4)

        # Documents with graph entries
        docs_with_graph = await self.nodes.count_documents({"node_type": NODE_TYPE_DOCUMENT})

        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "nodes_by_type": node_types,
            "edges_by_type": edge_types,
            "edges_by_provenance": provenances,
            "avg_edge_confidence": avg_confidence,
            "documents_in_graph": docs_with_graph,
        }

    # ───────────────────────────────────────────────────────────────────
    # SEARCH — find by reference
    # ───────────────────────────────────────────────────────────────────
    async def search_by_reference(self, reference_value: str) -> Dict[str, Any]:
        """Find all nodes and connections for a reference value."""
        cursor = self.nodes.find(
            {"reference_value": reference_value}, {"_id": 0}
        )
        matching_nodes = await cursor.to_list(length=50)

        if not matching_nodes:
            return {"reference_value": reference_value, "found": False, "nodes": [], "edges": []}

        node_ids = [n["node_id"] for n in matching_nodes]

        # Get edges for all matching nodes
        edge_cursor = self.edges.find(
            {"$or": [{"from_node": {"$in": node_ids}}, {"to_node": {"$in": node_ids}}]},
            {"_id": 0},
        )
        edges = await edge_cursor.to_list(length=500)

        # Collect all connected node IDs
        all_ids = set(node_ids)
        for e in edges:
            all_ids.add(e["from_node"])
            all_ids.add(e["to_node"])

        # Fetch all nodes
        all_nodes_cursor = self.nodes.find({"node_id": {"$in": list(all_ids)}}, {"_id": 0})
        all_nodes = await all_nodes_cursor.to_list(length=500)

        return {
            "reference_value": reference_value,
            "found": True,
            "nodes": all_nodes,
            "edges": edges,
            "node_count": len(all_nodes),
            "edge_count": len(edges),
        }

    # ===================================================================
    # INTERNAL HELPERS
    # ===================================================================
    async def _create_reference_nodes(
        self, document: Dict, doc_node_id: str, summary: Dict
    ) -> Dict[str, str]:
        """Create nodes for extracted references and link them to the document."""
        ref_nodes: Dict[str, str] = {}  # ref_value -> node_id

        extracted = document.get("extracted_fields") or {}

        # Direct field extractions
        field_map = {
            "po_number": ("po_number_clean", NODE_TYPE_PURCHASE_ORDER),
            "invoice_number": ("invoice_number_clean", NODE_TYPE_INVOICE),
            "bol_number": ("bol_number", NODE_TYPE_BILL_OF_LADING),
            "shipment_number": ("shipment_number", NODE_TYPE_SHIPMENT),
            "order_number": ("order_number", NODE_TYPE_SALES_ORDER),
        }

        for ref_type, (field_key, node_type) in field_map.items():
            value = document.get(field_key) or extracted.get(field_key) or extracted.get(ref_type) or ""
            if not value:
                continue

            node_id = await self.upsert_node(
                node_type=node_type,
                reference_value=str(value),
                reference_type=ref_type,
                vendor_name=document.get("vendor_raw") or "",
                customer_name=document.get("customer_name") or "",
            )
            ref_nodes[str(value)] = node_id
            summary["nodes_created"] += 1

            # Edge: document → reference
            edge_id = await self.create_edge(
                from_node=doc_node_id,
                to_node=node_id,
                edge_type=EDGE_CONTAINS_REFERENCE,
                confidence=0.85,
                provenance=PROV_EXTRACTION,
                evidence=[{"type": ref_type, "value": str(value), "source": "extracted_fields"}],
            )
            if edge_id:
                summary["edges_created"] += 1
                summary["links"].append({"type": ref_type, "value": str(value)})

        return ref_nodes

    async def _create_resolver_edges(
        self, document: Dict, doc_node_id: str, ref_nodes: Dict[str, str], summary: Dict
    ):
        """Create edges from reference_intelligence results."""
        ref_intel = document.get("reference_intelligence") or {}
        best_match = ref_intel.get("best_match") or {}

        if not best_match.get("bc_document_no"):
            return

        bc_no = best_match["bc_document_no"]
        entity_type = best_match.get("entity_type", "")
        match_score = best_match.get("match_score", 0.5)

        # Create BC record node
        bc_node_id = await self.upsert_node(
            node_type=NODE_TYPE_BC_RECORD,
            reference_value=bc_no,
            reference_type=entity_type,
            bc_entity_type=entity_type,
            bc_document_no=bc_no,
        )
        summary["nodes_created"] += 1

        # Edge: document → BC record
        edge_id = await self.create_edge(
            from_node=doc_node_id,
            to_node=bc_node_id,
            edge_type=EDGE_LINKED_TO_BC,
            confidence=min(match_score, 1.0),
            provenance=PROV_RESOLVER,
            evidence=[{
                "type": "resolver_match",
                "bc_document_no": bc_no,
                "entity_type": entity_type,
                "match_score": match_score,
            }],
        )
        if edge_id:
            summary["edges_created"] += 1

        # Also link reference candidates
        for cand in ref_intel.get("reference_candidates") or []:
            cand_value = cand.get("reference_value_normalized") or cand.get("reference_value") or ""
            cand_label = cand.get("detected_label", "REF")
            if cand_value and cand_value not in ref_nodes:
                node_type = _REF_LABEL_TO_NODE.get(cand_label, NODE_TYPE_SHIPMENT)
                node_id = await self.upsert_node(
                    node_type=node_type,
                    reference_value=cand_value,
                    reference_type=cand_label,
                )
                ref_nodes[cand_value] = node_id
                summary["nodes_created"] += 1

                await self.create_edge(
                    from_node=doc_node_id,
                    to_node=node_id,
                    edge_type=EDGE_CONTAINS_REFERENCE,
                    confidence=0.70,
                    provenance=PROV_RESOLVER,
                    evidence=[{"type": cand_label, "value": cand_value, "source": "resolver_candidate"}],
                )
                summary["edges_created"] += 1

    async def _create_processor_edges(
        self, document: Dict, doc_node_id: str, ref_nodes: Dict[str, str], summary: Dict
    ):
        """Create edges from processor_result suggested_references."""
        proc_result = document.get("processor_result") or {}
        suggested = proc_result.get("suggested_references") or []

        for ref in suggested:
            ref_value = ref.get("value", "")
            ref_label = ref.get("label", "REF")
            if not ref_value or ref_value in ref_nodes:
                continue

            node_type = _REF_LABEL_TO_NODE.get(ref_label, NODE_TYPE_SHIPMENT)
            node_id = await self.upsert_node(
                node_type=node_type,
                reference_value=ref_value,
                reference_type=ref_label,
            )
            ref_nodes[ref_value] = node_id
            summary["nodes_created"] += 1

            await self.create_edge(
                from_node=doc_node_id,
                to_node=node_id,
                edge_type=EDGE_CONTAINS_REFERENCE,
                confidence=0.75,
                provenance=PROV_PROCESSOR,
                evidence=[{"type": ref_label, "value": ref_value, "source": "processor"}],
            )
            summary["edges_created"] += 1

    async def _create_bc_edges(self, document: Dict, doc_node_id: str, summary: Dict):
        """Create edges for BC-linked documents."""
        bc_doc_id = document.get("bc_document_id") or ""
        if not bc_doc_id:
            return

        bc_node_id = await self.upsert_node(
            node_type=NODE_TYPE_BC_RECORD,
            reference_value=bc_doc_id,
            reference_type="bc_linked",
            bc_document_no=bc_doc_id,
            bc_entity_type=document.get("linked_entity_type") or "",
        )
        summary["nodes_created"] += 1

        await self.create_edge(
            from_node=doc_node_id,
            to_node=bc_node_id,
            edge_type=EDGE_LINKED_TO_BC,
            confidence=1.0,
            provenance=PROV_BC_LINKAGE,
            evidence=[{"type": "bc_linked", "value": bc_doc_id}],
        )
        summary["edges_created"] += 1

    async def _create_shared_reference_edges(
        self, doc_node_id: str, ref_nodes: Dict[str, str], summary: Dict
    ):
        """Find other documents sharing the same reference nodes and link them."""
        for ref_value, ref_node_id in ref_nodes.items():
            # Find other edges pointing to this reference node
            cursor = self.edges.find(
                {
                    "to_node": ref_node_id,
                    "from_node": {"$ne": doc_node_id},
                    "edge_type": EDGE_CONTAINS_REFERENCE,
                },
                {"_id": 0, "from_node": 1},
            )
            other_doc_edges = await cursor.to_list(length=50)

            for ode in other_doc_edges:
                other_doc_node_id = ode["from_node"]
                # Verify it's a document node
                other_node = await self.get_node(other_doc_node_id)
                if not other_node or other_node.get("node_type") != NODE_TYPE_DOCUMENT:
                    continue

                # Create bidirectional same_transaction edge
                await self.create_edge(
                    from_node=doc_node_id,
                    to_node=other_doc_node_id,
                    edge_type=EDGE_SAME_TRANSACTION,
                    confidence=0.60,
                    provenance=PROV_SHARED_REF,
                    evidence=[{"type": "shared_reference", "value": ref_value}],
                )
                summary["edges_created"] += 1


# ═══════════════════════════════════════════════════════════════════════
# Module-level singleton management
# ═══════════════════════════════════════════════════════════════════════
_instance: Optional[TransactionGraphService] = None


def set_transaction_graph_service(db, event_service=None) -> TransactionGraphService:
    global _instance
    _instance = TransactionGraphService(db, event_service)
    return _instance


def get_transaction_graph_service() -> Optional[TransactionGraphService]:
    return _instance
