"""
Sales Order Graph & Linkage Service (v2.5.13)
──────────────────────────────────────────────

Surface-level linkage for the "visualize docs related by Sales Order"
feature. Given a SO# or PO#, walk the hub_documents collection and
return every doc that references it directly or indirectly, with:
    * node metadata (doc_type, vendor, status, dates)
    * edge metadata (which field matched, exact vs fuzzy, confidence)
    * timeline placement (for Phase 2 UI)

This is Phase 1 — backend only. curl-testable immediately.

Design notes
    * Linkage strategy C: exact-match on known ref fields FIRST, then
      fuzzy-match on filename / extracted_fields. Fuzzy matches carry a
      `confidence` badge so the UI can de-emphasize them.
    * LEARN hook: every fuzzy hit is logged to
      `sales_order_graph_feedback` so a future Phase 4 can train a
      confidence model from reviewer confirmations.
    * The service is read-only. No mutations to hub_documents.
"""
from __future__ import annotations

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from deps import get_db

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
# Reference-field conventions
# ─────────────────────────────────────────────────────────────

# Fields on hub_documents that MAY contain a PO number.
_PO_FIELDS = (
    "po_number", "po_number_clean", "linked_po",
    "extracted_fields.po_number", "normalized_fields.po_number",
    "order_number", "extracted_fields.order_number",
)
_SO_FIELDS = (
    "so_number", "linked_so", "sales_order_number",
    "extracted_fields.so_number", "normalized_fields.so_number",
    "reference_numbers", "extracted_fields.reference_numbers",
)
_SHIPMENT_FIELDS = (
    "shipment_number", "bol_number", "container_number",
    "extracted_fields.shipment_number", "extracted_fields.bol_number",
)

# Doc_type → role in the lifecycle (used for timeline swimlanes).
# Case-insensitive match — we normalize before lookup.
_ROLE_MAP: Dict[str, str] = {
    # PO side
    "purchase_order": "PO",
    "po": "PO",
    # SO side
    "sales_order": "SO",
    "so": "SO",
    # Shipping / logistics
    "bol": "Shipping",
    "shipping_document": "Shipping",
    "receiving_report": "Shipping",
    "warehouse_activity": "Shipping",
    # AP / invoicing
    "ap_invoice": "AP_Invoice",
    "freight_invoice": "AP_Invoice",
    "ar_statement": "AR_Invoice",
    "sales_invoice": "AR_Invoice",
    # Ancillary / compliance
    "w9_form": "Compliance",
    "loa": "Compliance",
    "quality_doc": "Compliance",
    # Fallback
    "unknown": "Unknown",
}


def _role_for(doc_type: Optional[str]) -> str:
    if not doc_type:
        return "Unknown"
    return _ROLE_MAP.get(str(doc_type).strip().lower(), "Other")


# ─────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────

_NON_ALNUM = re.compile(r"[^A-Z0-9]")


def normalize_ref(value: Any) -> Optional[str]:
    """Uppercase + strip non-alphanumerics. Matches the convention used
    by `po_number_clean` so exact-match works cross-field."""
    if not value:
        return None
    if isinstance(value, list):
        value = value[0] if value else None
        if not value:
            return None
    s = str(value).strip().upper()
    cleaned = _NON_ALNUM.sub("", s)
    return cleaned or None


def _extract_value(doc: Dict[str, Any], dotted: str) -> Any:
    """Walk `a.b.c` through a dict. Returns None if missing."""
    node: Any = doc
    for part in dotted.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    return node


def doc_references(doc: Dict[str, Any]) -> Dict[str, Set[str]]:
    """Pull every PO / SO / shipment ref off one doc, normalized.

    Returns:
        {"po": {...}, "so": {...}, "shipment": {...}}
    """
    out: Dict[str, Set[str]] = {"po": set(), "so": set(), "shipment": set()}
    for key, fields in (
        ("po", _PO_FIELDS), ("so", _SO_FIELDS), ("shipment", _SHIPMENT_FIELDS),
    ):
        for f in fields:
            v = _extract_value(doc, f)
            if v is None:
                continue
            if isinstance(v, list):
                for item in v:
                    n = normalize_ref(item)
                    if n:
                        out[key].add(n)
            else:
                n = normalize_ref(v)
                if n:
                    out[key].add(n)
    return out


# ─────────────────────────────────────────────────────────────
# Filename fuzzy-match
# ─────────────────────────────────────────────────────────────

_PO_PATTERN = re.compile(r"P\d{6,8}", re.I)          # e.g. P0024333
_SO_PATTERN = re.compile(r"S\d{6,8}", re.I)          # e.g. S174123
_SHIPMENT_PATTERN = re.compile(r"W\d{5,7}")           # e.g. W117765


def fuzzy_refs_from_filename(fn: Optional[str]) -> Dict[str, Set[str]]:
    """Best-effort ref extraction from filenames like
    `P0024333 - 07 - W117765 - 10611479 - CN000106C.pdf`."""
    out: Dict[str, Set[str]] = {"po": set(), "so": set(), "shipment": set()}
    if not fn:
        return out
    for m in _PO_PATTERN.findall(fn):
        n = normalize_ref(m)
        if n:
            out["po"].add(n)
    for m in _SO_PATTERN.findall(fn):
        n = normalize_ref(m)
        if n:
            out["so"].add(n)
    for m in _SHIPMENT_PATTERN.findall(fn):
        n = normalize_ref(m)
        if n:
            out["shipment"].add(n)
    return out


# ─────────────────────────────────────────────────────────────
# Graph build
# ─────────────────────────────────────────────────────────────

_NODE_PROJECTION = {
    "_id": 0, "id": 1, "file_name": 1, "doc_type": 1, "document_type": 1,
    "vendor_canonical": 1, "vendor_name": 1, "customer": 1,
    "status": 1, "workflow_status": 1, "created_utc": 1, "updated_utc": 1,
    "po_number": 1, "po_number_clean": 1, "linked_po": 1, "order_number": 1,
    "so_number": 1, "linked_so": 1, "sales_order_number": 1,
    "reference_numbers": 1, "shipment_number": 1, "bol_number": 1,
    "container_number": 1, "extracted_fields": 1, "normalized_fields": 1,
    "duplicate_of": 1, "filename_heuristic_rule": 1,
}


def _node_from(doc: Dict[str, Any], edges: List[Dict[str, Any]]) -> Dict[str, Any]:
    dt = doc.get("doc_type") or doc.get("document_type") or "Unknown"
    return {
        "id": doc.get("id"),
        "file_name": doc.get("file_name"),
        "doc_type": dt,
        "role": _role_for(dt),
        "vendor": doc.get("vendor_canonical") or doc.get("vendor_name"),
        "customer": doc.get("customer"),
        "status": doc.get("status"),
        "workflow_status": doc.get("workflow_status"),
        "created_utc": doc.get("created_utc"),
        "updated_utc": doc.get("updated_utc"),
        "is_duplicate": bool(doc.get("duplicate_of")),
        "filename_heuristic_rule": doc.get("filename_heuristic_rule"),
        "edges": edges,
    }


async def build_graph(
    *,
    so_number: Optional[str] = None,
    po_number: Optional[str] = None,
    include_fuzzy: bool = True,
    max_nodes: int = 200,
    db=None,
) -> Dict[str, Any]:
    """Walk the doc collection and return every doc that references the
    given SO / PO. Follows 1 hop of chain expansion (e.g. find PO(s)
    referenced by the SO, then find all docs referencing those POs)."""
    db = db if db is not None else get_db()

    seed_so = normalize_ref(so_number)
    seed_po = normalize_ref(po_number)
    if not seed_so and not seed_po:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "error": "Provide at least one of so_number or po_number.",
            "nodes": [], "edges_total": 0,
        }

    # Keys to match on. Start with the seeds; we'll accumulate more as
    # we discover related docs.
    po_keys: Set[str] = set([seed_po] if seed_po else [])
    so_keys: Set[str] = set([seed_so] if seed_so else [])
    shipment_keys: Set[str] = set()

    visited_ids: Set[str] = set()
    nodes: List[Dict[str, Any]] = []
    edge_counts: Counter = Counter()
    role_counts: Counter = Counter()

    # We do up to 3 expansion passes (seed → direct → 1-hop chain).
    for hop in range(3):
        if len(nodes) >= max_nodes:
            break
        # Build a query that hits any doc mentioning any known key.
        or_clauses: List[Dict[str, Any]] = []
        for k in po_keys:
            or_clauses.extend([
                {"po_number_clean": k},
                {"po_number": k},
                {"linked_po": k},
                {"order_number": k},
                {"extracted_fields.po_number": k},
                {"normalized_fields.po_number": k},
            ])
        for k in so_keys:
            or_clauses.extend([
                {"so_number": k},
                {"linked_so": k},
                {"sales_order_number": k},
                {"extracted_fields.so_number": k},
                {"normalized_fields.so_number": k},
                {"reference_numbers": k},
            ])
        for k in shipment_keys:
            or_clauses.extend([
                {"shipment_number": k},
                {"bol_number": k},
                {"container_number": k},
            ])
        # Fuzzy filename regex — finds docs whose only reference to a key
        # is embedded in the filename (e.g. Ball Metal
        # `P0024333 - 07 - W117765 - ...pdf`). Only when include_fuzzy.
        if include_fuzzy:
            for k in po_keys | so_keys | shipment_keys:
                # Escape key for safe regex usage (all normalized refs are
                # alphanumeric already, but stay defensive).
                or_clauses.append({
                    "file_name": {"$regex": re.escape(k), "$options": "i"},
                })
        if not or_clauses:
            break

        q = {"$or": or_clauses}
        cursor = db.hub_documents.find(q, _NODE_PROJECTION).limit(max_nodes)
        new_po: Set[str] = set()
        new_so: Set[str] = set()
        new_ship: Set[str] = set()

        async for d in cursor:
            did = d.get("id")
            if not did or did in visited_ids:
                continue
            visited_ids.add(did)
            edges = _edges_from(d, po_keys, so_keys, shipment_keys)
            # Collect its own refs to expand the search next hop.
            refs = doc_references(d)
            new_po |= refs["po"]
            new_so |= refs["so"]
            new_ship |= refs["shipment"]
            # Fuzzy from filename (lower-weight; only if asked). Always
            # emit an edge when the filename contains a known key — that
            # IS the evidence for inclusion. Separately, expand the
            # search with any NEW keys the filename surfaces.
            if include_fuzzy:
                fz = fuzzy_refs_from_filename(d.get("file_name"))
                for k in fz["po"]:
                    if k in po_keys or k in new_po:
                        edges.append({
                            "ref_type": "po", "ref_value": k,
                            "matched_field": "filename_fuzzy",
                            "match_type": "fuzzy", "confidence": 0.60,
                        })
                for k in fz["so"]:
                    if k in so_keys or k in new_so:
                        edges.append({
                            "ref_type": "so", "ref_value": k,
                            "matched_field": "filename_fuzzy",
                            "match_type": "fuzzy", "confidence": 0.60,
                        })
                for k in fz["shipment"]:
                    if k in shipment_keys or k in new_ship:
                        edges.append({
                            "ref_type": "shipment", "ref_value": k,
                            "matched_field": "filename_fuzzy",
                            "match_type": "fuzzy", "confidence": 0.60,
                        })
                new_po |= fz["po"]
                new_so |= fz["so"]
                new_ship |= fz["shipment"]
            node = _node_from(d, edges)
            nodes.append(node)
            role_counts[node["role"]] += 1
            for e in edges:
                edge_counts[e["match_type"]] += 1
            if len(nodes) >= max_nodes:
                break

        # Expand the search set for the next hop.
        pre = (len(po_keys), len(so_keys), len(shipment_keys))
        po_keys |= new_po
        so_keys |= new_so
        shipment_keys |= new_ship
        post = (len(po_keys), len(so_keys), len(shipment_keys))
        if pre == post:
            break  # No new refs discovered → stop expanding.

    # Sort nodes by created_utc for timeline consumption.
    nodes.sort(key=lambda n: n.get("created_utc") or "")

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "seed": {"so_number": seed_so, "po_number": seed_po},
        "expanded_keys": {
            "po": sorted(po_keys), "so": sorted(so_keys),
            "shipment": sorted(shipment_keys),
        },
        "nodes_total": len(nodes),
        "edges_total": sum(edge_counts.values()),
        "edge_counts_by_type": dict(edge_counts),
        "role_counts": dict(role_counts),
        "nodes": nodes,
    }


def _edges_from(
    doc: Dict[str, Any],
    po_keys: Set[str], so_keys: Set[str], shipment_keys: Set[str],
) -> List[Dict[str, Any]]:
    """Figure out exactly which field of `doc` matched one of our keys."""
    edges: List[Dict[str, Any]] = []
    for field in _PO_FIELDS:
        v = _extract_value(doc, field)
        vals = v if isinstance(v, list) else [v]
        for vv in vals:
            n = normalize_ref(vv)
            if n and n in po_keys:
                edges.append({
                    "ref_type": "po", "ref_value": n,
                    "matched_field": field,
                    "match_type": "exact", "confidence": 1.0,
                })
    for field in _SO_FIELDS:
        v = _extract_value(doc, field)
        vals = v if isinstance(v, list) else [v]
        for vv in vals:
            n = normalize_ref(vv)
            if n and n in so_keys:
                edges.append({
                    "ref_type": "so", "ref_value": n,
                    "matched_field": field,
                    "match_type": "exact", "confidence": 1.0,
                })
    for field in _SHIPMENT_FIELDS:
        v = _extract_value(doc, field)
        vals = v if isinstance(v, list) else [v]
        for vv in vals:
            n = normalize_ref(vv)
            if n and n in shipment_keys:
                edges.append({
                    "ref_type": "shipment", "ref_value": n,
                    "matched_field": field,
                    "match_type": "exact", "confidence": 1.0,
                })
    return edges


# ─────────────────────────────────────────────────────────────
# Exception hunt — orders with incomplete doc-type coverage
# ─────────────────────────────────────────────────────────────

# The "complete" lifecycle we expect for a healthy order. Keyed by role,
# value = min expected count.
_EXPECTED_ROLES = ("PO", "SO", "Shipping", "AP_Invoice")


async def incomplete_orders(
    *,
    limit: int = 500,
    min_nodes_per_order: int = 2,
    db=None,
) -> Dict[str, Any]:
    """Scan hub_documents, group by every SO# found across all reference
    fields, and flag those missing any of the expected lifecycle roles.
    """
    db = db if db is not None else get_db()
    cursor = db.hub_documents.find(
        {"duplicate_of": {"$in": [None, "", False]}},
        _NODE_PROJECTION,
    ).limit(20000)

    by_so: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    async for d in cursor:
        refs = doc_references(d)
        for so in refs["so"]:
            by_so[so].append(d)

    results: List[Dict[str, Any]] = []
    for so, docs in by_so.items():
        if len(docs) < min_nodes_per_order:
            continue
        role_set = {_role_for(d.get("doc_type")) for d in docs}
        missing = [r for r in _EXPECTED_ROLES if r not in role_set]
        if not missing:
            continue
        results.append({
            "so_number": so,
            "nodes_total": len(docs),
            "roles_present": sorted(role_set),
            "roles_missing": missing,
            "sample_file_names": [d.get("file_name") for d in docs[:3]],
            "latest_activity_utc": max(
                (d.get("updated_utc") or d.get("created_utc") or "" for d in docs),
                default="",
            ),
        })
    # Worst offenders first (most missing roles, then most recent activity).
    results.sort(key=lambda r: (-len(r["roles_missing"]), r["latest_activity_utc"]),
                 reverse=False)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expected_roles": list(_EXPECTED_ROLES),
        "scanned_docs_cap": 20000,
        "orders_with_gaps": len(results),
        "sample": results[:limit],
    }


# ─────────────────────────────────────────────────────────────
# Linkage-learning feedback hook (Phase 4 seed — just the log)
# ─────────────────────────────────────────────────────────────

async def record_link_feedback(
    *,
    so_number: str, doc_id: str,
    confirmed: bool, actor: str = "reviewer",
    reason: Optional[str] = None, db=None,
) -> Dict[str, Any]:
    """Persist a reviewer's confirm/reject on a fuzzy link so Phase 4
    can train confidence adjustments. Write-only for now."""
    db = db if db is not None else get_db()
    entry = {
        "so_number": normalize_ref(so_number),
        "doc_id": doc_id,
        "confirmed": bool(confirmed),
        "actor": actor,
        "reason": reason,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.sales_order_graph_feedback.insert_one(entry)
    entry.pop("_id", None)
    return entry


# ─────────────────────────────────────────────────────────────
# Quick diagnostic — what does the data look like?
# ─────────────────────────────────────────────────────────────

async def diagnostic_snapshot(db=None) -> Dict[str, Any]:
    """One-shot DB introspection for building the graph feature.
    Tells us: what doc_type values exist (+ counts), which reference
    fields are populated on recent docs, and one sample per doc_type."""
    db = db if db is not None else get_db()
    type_counts: Counter = Counter()
    field_popularity: Counter = Counter()
    samples: Dict[str, Dict[str, Any]] = {}

    cursor = db.hub_documents.find(
        {}, _NODE_PROJECTION,
    ).sort("created_utc", -1).limit(2000)
    async for d in cursor:
        dt = d.get("doc_type") or d.get("document_type") or "Unknown"
        type_counts[dt] += 1
        # Count any ref field that carries a non-empty value.
        for f in _PO_FIELDS + _SO_FIELDS + _SHIPMENT_FIELDS:
            v = _extract_value(d, f)
            if v:
                field_popularity[f] += 1
        if dt not in samples:
            samples[dt] = {
                "id": d.get("id"),
                "file_name": d.get("file_name"),
                "vendor": d.get("vendor_canonical") or d.get("vendor_name"),
                "refs": {k: sorted(list(v)) for k, v in doc_references(d).items()},
                "filename_fuzzy": {k: sorted(list(v)) for k, v in
                                   fuzzy_refs_from_filename(d.get("file_name")).items()},
            }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scanned": sum(type_counts.values()),
        "doc_types": type_counts.most_common(50),
        "ref_field_popularity": field_popularity.most_common(30),
        "samples_by_doc_type": samples,
    }


__all__ = [
    "normalize_ref", "doc_references", "fuzzy_refs_from_filename",
    "build_graph", "incomplete_orders", "record_link_feedback",
    "diagnostic_snapshot",
]
