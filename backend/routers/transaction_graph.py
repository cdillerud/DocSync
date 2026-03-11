"""
GPI Document Hub — Transaction Graph API Router

Endpoints for querying the transaction graph, viewing document connections,
searching by reference, and getting graph statistics.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import logging

from services.transaction_graph_service import get_transaction_graph_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/graph", tags=["Transaction Graph"])


def _svc():
    svc = get_transaction_graph_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Transaction Graph service not initialized")
    return svc


@router.get("/stats")
async def graph_stats():
    """Get aggregate graph statistics."""
    return await _svc().get_stats()


@router.get("/document/{doc_id}/connections")
async def document_connections(doc_id: str):
    """Get the full transaction graph context for a document."""
    result = await _svc().get_document_connections(doc_id)
    if not result.get("found"):
        return {"doc_id": doc_id, "found": False, "nodes": [], "edges": [], "connected_documents": []}
    return result


@router.get("/search")
async def search_graph(reference: str = Query(..., description="Reference value to search for")):
    """Search the graph by reference value (PO, invoice, BOL, etc.)."""
    if not reference or len(reference) < 2:
        raise HTTPException(status_code=400, detail="Reference must be at least 2 characters")
    return await _svc().search_by_reference(reference)


@router.get("/node/{node_id}")
async def get_node(node_id: str):
    """Get a single graph node by ID."""
    node = await _svc().get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")
    return node


@router.get("/node/{node_id}/edges")
async def get_node_edges(node_id: str):
    """Get all edges for a node."""
    edges = await _svc().get_edges_for_node(node_id)
    return {"node_id": node_id, "edges": edges, "count": len(edges)}


@router.get("/nodes")
async def list_nodes(
    node_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """List graph nodes with optional type filter."""
    svc = _svc()
    query = {}
    if node_type:
        query["node_type"] = node_type
    cursor = svc.nodes.find(query, {"_id": 0}).skip(skip).limit(limit)
    nodes = await cursor.to_list(length=limit)
    total = await svc.nodes.count_documents(query)
    return {"nodes": nodes, "total": total, "limit": limit, "skip": skip}


@router.get("/edges")
async def list_edges(
    edge_type: Optional[str] = None,
    provenance: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """List graph edges with optional filters."""
    svc = _svc()
    query = {}
    if edge_type:
        query["edge_type"] = edge_type
    if provenance:
        query["provenance"] = provenance
    cursor = svc.edges.find(query, {"_id": 0}).skip(skip).limit(limit)
    edges = await cursor.to_list(length=limit)
    total = await svc.edges.count_documents(query)
    return {"edges": edges, "total": total, "limit": limit, "skip": skip}


@router.post("/document/{doc_id}/ingest")
async def manually_ingest_document(doc_id: str):
    """Manually trigger graph ingestion for a document (admin/debug)."""
    svc = _svc()
    doc = await svc.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    result = await svc.ingest_document(doc)
    return result


@router.post("/bulk-ingest")
async def bulk_ingest(limit: int = Query(100, ge=1, le=1000)):
    """Bulk-ingest existing documents into the graph (admin/backfill)."""
    svc = _svc()
    cursor = svc.db.hub_documents.find({}, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(length=limit)

    results = {"total": len(docs), "ingested": 0, "errors": 0}
    for doc in docs:
        try:
            summary = await svc.ingest_document(doc)
            if summary.get("error"):
                results["errors"] += 1
            else:
                results["ingested"] += 1
        except Exception:
            results["errors"] += 1

    return results


@router.get("/document/{doc_id}/linkage-bonus")
async def document_linkage_bonus(doc_id: str, bc_document_no: str = Query(...)):
    """Calculate graph linkage bonus for a document + BC record pair (debug)."""
    svc = _svc()
    doc = await svc.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    bc_record = {"number": bc_document_no, "bc_document_no": bc_document_no}
    return await svc.get_linkage_bonus(doc, bc_record)
