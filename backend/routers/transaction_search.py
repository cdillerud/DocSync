"""
GPI Document Hub — Transaction Search Router

Read-only search and chain retrieval across the transaction graph.
Replaces Zetadocs-style document retrieval by exposing the full
connected chain of related documents for any business reference.

Endpoints:
  GET /api/transaction-search           — Main search (exact → normalized → fuzzy)
  GET /api/transaction-search/node/{node_id}/chain  — Chain from a node
  GET /api/transaction-search/document/{doc_id}/chain — Chain from a document
"""

import re
import logging
from fastapi import APIRouter, HTTPException, Query
from typing import Optional, List, Dict, Any

from services.transaction_graph_service import (
    get_transaction_graph_service,
    NODE_TYPE_DOCUMENT,
)
from services.reference_intelligence_service import normalize_reference

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/transaction-search", tags=["Transaction Search"])

MAX_CHAIN_DEPTH = 5
DEFAULT_CHAIN_DEPTH = 3


def _svc():
    svc = get_transaction_graph_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Transaction Graph service not initialized")
    return svc


def _normalize_query(raw: str) -> str:
    """Normalize a search query using the resolver's normalization rules."""
    return normalize_reference(raw.strip())


def _fuzzy_variants(raw: str) -> List[str]:
    """Generate fuzzy search variants for OCR-tolerant matching."""
    normalized = _normalize_query(raw)
    variants = {normalized}

    # Stripped-of-all-non-alnum
    alnum = re.sub(r'[^A-Za-z0-9]', '', raw.strip())
    if alnum:
        variants.add(alnum.upper())
        stripped = alnum.upper().lstrip('0') or '0'
        variants.add(stripped)

    # Common OCR substitutions
    ocr_map = {'O': '0', '0': 'O', 'I': '1', '1': 'I', 'S': '5', '5': 'S', 'B': '8', '8': 'B'}
    for i, ch in enumerate(normalized):
        if ch in ocr_map:
            variant = normalized[:i] + ocr_map[ch] + normalized[i + 1:]
            variants.add(variant)

    variants.discard('')
    return list(variants)


async def _search_nodes(
    svc,
    query: str,
    node_type: Optional[str] = None,
    vendor: Optional[str] = None,
    doc_type: Optional[str] = None,
    min_confidence: float = 0.0,
    limit: int = 30,
) -> Dict[str, Any]:
    """
    Three-tier search: exact → normalized → fuzzy.
    Returns results with match_tier labels.
    """
    results = []
    seen_node_ids = set()

    # ── Tier 1: Exact match ────────────────────────────────────────
    q_filter: Dict[str, Any] = {"reference_value": query}
    if node_type:
        q_filter["node_type"] = node_type
    if vendor:
        q_filter["vendor_name"] = {"$regex": vendor, "$options": "i"}

    cursor = svc.nodes.find(q_filter, {"_id": 0}).limit(limit)
    exact_nodes = await cursor.to_list(length=limit)
    for n in exact_nodes:
        if n["node_id"] not in seen_node_ids:
            seen_node_ids.add(n["node_id"])
            results.append({**n, "match_tier": "exact", "match_confidence": 1.0})

    # ── Tier 2: Normalized match ──────────────────────────────────
    normalized = _normalize_query(query)
    if normalized and normalized != query:
        q2: Dict[str, Any] = {"reference_value": normalized}
        if node_type:
            q2["node_type"] = node_type
        if vendor:
            q2["vendor_name"] = {"$regex": vendor, "$options": "i"}

        cursor2 = svc.nodes.find(q2, {"_id": 0}).limit(limit)
        norm_nodes = await cursor2.to_list(length=limit)
        for n in norm_nodes:
            if n["node_id"] not in seen_node_ids:
                seen_node_ids.add(n["node_id"])
                results.append({**n, "match_tier": "normalized", "match_confidence": 0.90})

    # ── Tier 3: Fuzzy / partial / regex ───────────────────────────
    remaining = limit - len(results)
    if remaining > 0:
        # Regex partial match on reference_value
        escaped = re.escape(normalized or query)
        regex_filter: Dict[str, Any] = {
            "reference_value": {"$regex": escaped, "$options": "i"},
        }
        if node_type:
            regex_filter["node_type"] = node_type
        if vendor:
            regex_filter["vendor_name"] = {"$regex": vendor, "$options": "i"}

        cursor3 = svc.nodes.find(regex_filter, {"_id": 0}).limit(remaining + 20)
        partial_nodes = await cursor3.to_list(length=remaining + 20)
        for n in partial_nodes:
            if n["node_id"] not in seen_node_ids:
                seen_node_ids.add(n["node_id"])
                results.append({**n, "match_tier": "likely", "match_confidence": 0.70})
                if len(results) >= limit:
                    break

    # ── Tier 4: OCR-tolerant fuzzy variants ──────────────────────
    remaining = limit - len(results)
    if remaining > 0 and len(results) < 5:
        variants = _fuzzy_variants(query)
        for v in variants:
            if len(results) >= limit:
                break
            vf: Dict[str, Any] = {"reference_value": v}
            if node_type:
                vf["node_type"] = node_type
            cursor4 = svc.nodes.find(vf, {"_id": 0}).limit(5)
            fuzzy_nodes = await cursor4.to_list(length=5)
            for n in fuzzy_nodes:
                if n["node_id"] not in seen_node_ids:
                    seen_node_ids.add(n["node_id"])
                    results.append({**n, "match_tier": "fuzzy", "match_confidence": 0.50})

    # ── Filter by doc_type (post-filter on document nodes) ────────
    if doc_type:
        results = [
            r for r in results
            if r.get("node_type") != NODE_TYPE_DOCUMENT
            or (r.get("metadata", {}).get("doc_type", "")).lower() == doc_type.lower()
        ]

    return {
        "query": query,
        "normalized": normalized,
        "total_results": len(results),
        "results": results[:limit],
    }


async def _build_chain(
    svc,
    start_node_id: str,
    max_depth: int = DEFAULT_CHAIN_DEPTH,
    min_confidence: float = 0.0,
) -> Dict[str, Any]:
    """
    BFS traversal from a starting node to build the transaction chain.
    Returns all connected nodes and edges up to max_depth.
    """
    depth = min(max_depth, MAX_CHAIN_DEPTH)
    visited_nodes = set()
    visited_edges = set()
    all_nodes = []
    all_edges = []
    queue = [(start_node_id, 0)]
    connected_documents = []

    while queue:
        current_id, current_depth = queue.pop(0)
        if current_id in visited_nodes:
            continue
        visited_nodes.add(current_id)

        node = await svc.get_node(current_id)
        if not node:
            continue
        node["_depth"] = current_depth
        all_nodes.append(node)

        if node["node_type"] == NODE_TYPE_DOCUMENT and current_id != start_node_id:
            connected_documents.append({
                "doc_id": node["reference_value"],
                "doc_type": node.get("metadata", {}).get("doc_type", ""),
                "file_name": node.get("metadata", {}).get("file_name", ""),
                "vendor_name": node.get("vendor_name", ""),
                "status": node.get("metadata", {}).get("status", ""),
            })

        if current_depth >= depth:
            continue

        edges = await svc.get_edges_for_node(current_id)
        for e in edges:
            if e["edge_id"] in visited_edges:
                continue
            if min_confidence > 0 and e.get("confidence", 0) < min_confidence:
                continue
            visited_edges.add(e["edge_id"])
            all_edges.append(e)

            next_id = e["to_node"] if e["from_node"] == current_id else e["from_node"]
            if next_id not in visited_nodes:
                queue.append((next_id, current_depth + 1))

    # Build ordered chain (sort by depth)
    chain_steps = []
    for n in sorted(all_nodes, key=lambda x: x.get("_depth", 0)):
        node_edges = [e for e in all_edges if e["from_node"] == n["node_id"] or e["to_node"] == n["node_id"]]
        step = {
            "node_id": n["node_id"],
            "node_type": n["node_type"],
            "reference_value": n["reference_value"],
            "vendor_name": n.get("vendor_name", ""),
            "bc_document_no": n.get("bc_document_no", ""),
            "bc_entity_type": n.get("bc_entity_type", ""),
            "metadata": n.get("metadata", {}),
            "depth": n.get("_depth", 0),
            "edges": [{
                "edge_id": e["edge_id"],
                "edge_type": e["edge_type"],
                "confidence": e.get("confidence", 0),
                "provenance": e.get("provenance", ""),
                "direction": "outgoing" if e["from_node"] == n["node_id"] else "incoming",
                "connected_to": e["to_node"] if e["from_node"] == n["node_id"] else e["from_node"],
            } for e in node_edges],
        }
        chain_steps.append(step)

    return {
        "start_node_id": start_node_id,
        "chain_steps": chain_steps,
        "connected_documents": connected_documents,
        "total_nodes": len(all_nodes),
        "total_edges": len(all_edges),
        "max_depth_used": depth,
    }


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

@router.get("")
async def transaction_search(
    q: str = Query(..., min_length=1, description="Reference value to search"),
    node_type: Optional[str] = Query(None, description="Filter by node type"),
    vendor: Optional[str] = Query(None, description="Filter by vendor name"),
    doc_type: Optional[str] = Query(None, description="Filter by document type"),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    limit: int = Query(30, ge=1, le=100),
):
    """
    Search the transaction graph by any reference value.
    Returns exact → normalized → likely → fuzzy results.
    """
    svc = _svc()
    search_results = await _search_nodes(
        svc, q.strip(), node_type=node_type, vendor=vendor,
        doc_type=doc_type, min_confidence=min_confidence, limit=limit,
    )

    # Enrich each result with connected count
    for r in search_results["results"]:
        edges = await svc.get_edges_for_node(r["node_id"])
        r["connected_count"] = len(edges)
        # Find connected documents count
        doc_edges = [e for e in edges if e["edge_type"] in ("contains_reference", "same_transaction")]
        r["connected_doc_hint"] = len(doc_edges)

    return search_results


@router.get("/node/{node_id}/chain")
async def node_chain(
    node_id: str,
    max_depth: int = Query(DEFAULT_CHAIN_DEPTH, ge=1, le=MAX_CHAIN_DEPTH),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get the full transaction chain starting from a graph node."""
    svc = _svc()
    node = await svc.get_node(node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Node not found")

    chain = await _build_chain(svc, node_id, max_depth=max_depth, min_confidence=min_confidence)
    chain["start_node"] = node
    return chain


@router.get("/document/{doc_id}/chain")
async def document_chain(
    doc_id: str,
    max_depth: int = Query(DEFAULT_CHAIN_DEPTH, ge=1, le=MAX_CHAIN_DEPTH),
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
):
    """Get the full transaction chain for a document."""
    svc = _svc()
    doc_node = await svc.get_node_by_ref(NODE_TYPE_DOCUMENT, doc_id)
    if not doc_node:
        raise HTTPException(status_code=404, detail="Document not found in graph")

    chain = await _build_chain(svc, doc_node["node_id"], max_depth=max_depth, min_confidence=min_confidence)
    chain["doc_id"] = doc_id
    chain["start_node"] = doc_node
    return chain
