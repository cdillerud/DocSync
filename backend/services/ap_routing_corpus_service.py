"""Supervised AP routing corpus builder.

Reads the live GamerAccounting AP Temp tree as routing-label authority. No
SharePoint writes are performed. Files in the Temp root itself are review/
unresolved examples and are deliberately excluded from positive route labels.

DocsNAV/Zetadocs is NOT used here because archive disposition is not routing
truth; it belongs in separate layout-coverage sampling.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote, unquote

import httpx

from services.ap_bc_routing_context_service import resolve_ap_routing_context
from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import (
    LABEL_SOURCE_ACCOUNTING_TEMP,
    normalize_route_path,
    prepare_routing_example,
    upsert_routing_example,
)
from services.document_bundle_reference_service import extract_supporting_references
from services.ap_primary_document_service import classify_primary_document
from services.sharepoint_service import _get_graph_token

logger = logging.getLogger(__name__)

ACCOUNTING_HOST = os.environ.get("AP_ROUTING_AUTHORITY_HOST", "gamerpackaging1.sharepoint.com")
ACCOUNTING_SITE_PATH = os.environ.get("AP_ROUTING_AUTHORITY_SITE", "/sites/GamerAccounting")
ACCOUNTING_DRIVE_NAME = os.environ.get("AP_ROUTING_AUTHORITY_DRIVE", "Documents")
ACCOUNTING_TEMP_PATH = os.environ.get(
    "AP_ROUTING_AUTHORITY_TEMP_PATH",
    "General/Accounting/Accounts Payable/Temp Folder",
)
GRAPH_TIMEOUT = float(os.environ.get("AP_ROUTING_GRAPH_TIMEOUT", "60"))

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".png",
    ".jpg",
    ".jpeg",
    ".tif",
    ".tiff",
}


def _normalize_graph_path(value: str) -> str:
    return "/".join(part for part in str(value or "").replace("\\", "/").split("/") if part)


def _route_from_folder_path(folder_path: str) -> str:
    base = _normalize_graph_path(ACCOUNTING_TEMP_PATH)
    folder = _normalize_graph_path(folder_path)
    if folder == base:
        return ""
    prefix = base + "/"
    if not folder.startswith(prefix):
        raise ValueError(f"Folder is outside AP Temp authority: {folder}")
    return folder[len(prefix) :]


def _supported_file(name: str) -> bool:
    return Path(str(name or "")).suffix.lower() in SUPPORTED_EXTENSIONS


def _static_contract_routes(contract: Optional[Dict[str, Any]]) -> List[str]:
    if not contract:
        return []
    routes = {
        normalize_route_path(route)
        for route in (contract.get("static_routes") or [])
        if normalize_route_path(route)
    }
    return sorted(routes, key=lambda value: (value.count("/"), len(value)), reverse=True)


def _learning_excluded_routes(contract: Optional[Dict[str, Any]]) -> List[str]:
    if not contract:
        return []
    routes = {
        normalize_route_path(route)
        for route in (contract.get("learning_excluded_routes") or [])
        if normalize_route_path(route)
    }
    return sorted(routes, key=lambda value: (value.count("/"), len(value)), reverse=True)


def _learning_exclusion_for_route(
    raw_route: str,
    contract: Optional[Dict[str, Any]],
) -> str:
    normalized = normalize_route_path(raw_route)
    for excluded in _learning_excluded_routes(contract):
        if normalized == excluded or normalized.startswith(excluded + "/"):
            return excluded
    return ""


def _nearest_static_contract_route(
    raw_route: str,
    contract: Optional[Dict[str, Any]],
) -> str:
    """Collapse a live placement to the nearest routable Accounting queue.

    The AP Temp tree contains many nested work/archive folders beneath queues:
    years under DO NOT PAY, customer return folders under Canpack, issue folders,
    completed folders, and project folders. Those are useful provenance but are
    not necessarily intake destinations. The versioned routing contract defines
    the queue boundary. Verified dynamic routes are recovered after BC hydration.
    """
    normalized = normalize_route_path(raw_route)
    if not normalized:
        return ""
    if not contract:
        return normalized

    for route in _static_contract_routes(contract):
        if normalized == route or normalized.startswith(route + "/"):
            return route
    return ""


def _canonicalize_discovered_labels(
    labels: List[Dict[str, Any]],
    contract: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Preserve raw placement while mapping examples to legitimate intake queues.

    Contract-declared downstream/processed states remain visible in raw audit
    counts but are deliberately excluded from supervised intake learning. This
    prevents a terminal archive state from becoming a false destination label.
    """
    if not contract:
        copied = [dict(label) for label in labels]
        return {
            "labels": copied,
            "canonical_route_counts": dict(Counter(normalize_route_path(x.get("route_path")) for x in copied)),
            "collapsed_path_count": 0,
            "unmapped_route_counts": {},
            "excluded_learning_route_counts": {},
            "excluded_learning_file_count": 0,
        }

    canonical: List[Dict[str, Any]] = []
    collapsed = 0
    unmapped = Counter()
    excluded_learning = Counter()
    for label in labels:
        raw_route = normalize_route_path(label.get("route_path"))
        excluded_route = _learning_exclusion_for_route(raw_route, contract)
        if excluded_route:
            excluded_learning[excluded_route] += 1
            continue

        queue_route = _nearest_static_contract_route(raw_route, contract)
        if not queue_route:
            unmapped[raw_route or "<root>"] += 1
            continue
        item = dict(label)
        item["source_route_path"] = raw_route
        item["route_path"] = queue_route
        item["route_label_resolution"] = (
            "exact_static_queue" if raw_route == queue_route else "nearest_static_queue"
        )
        if raw_route != queue_route:
            collapsed += 1
        canonical.append(item)

    return {
        "labels": canonical,
        "canonical_route_counts": dict(Counter(x["route_path"] for x in canonical)),
        "collapsed_path_count": collapsed,
        "unmapped_route_counts": dict(unmapped),
        "excluded_learning_route_counts": dict(excluded_learning),
        "excluded_learning_file_count": sum(excluded_learning.values()),
    }


async def _graph_get(client: httpx.AsyncClient, token: str, url: str) -> Dict[str, Any]:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    response.raise_for_status()
    return response.json()


async def _resolve_site_and_drive(client: httpx.AsyncClient, token: str) -> tuple[str, str]:
    site_url = f"https://graph.microsoft.com/v1.0/sites/{ACCOUNTING_HOST}:{ACCOUNTING_SITE_PATH}"
    site = await _graph_get(client, token, site_url)
    site_id = site["id"]
    drives = await _graph_get(
        client,
        token,
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives?$top=100&$select=id,name,webUrl",
    )
    match = next((d for d in drives.get("value", []) if d.get("name") == ACCOUNTING_DRIVE_NAME), None)
    if not match:
        raise RuntimeError(f"Accounting drive not found: {ACCOUNTING_DRIVE_NAME}")
    return site_id, match["id"]


async def _resolve_temp_root(client: httpx.AsyncClient, token: str, drive_id: str) -> Dict[str, Any]:
    encoded = quote(_normalize_graph_path(ACCOUNTING_TEMP_PATH), safe="/")
    return await _graph_get(
        client,
        token,
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{encoded}?$select=id,name,parentReference,webUrl",
    )


async def discover_accounting_temp_labels(
    *,
    max_files: int = 50000,
    include_review_root: bool = False,
) -> Dict[str, Any]:
    """Enumerate Temp files and their human-assigned parent placement read-only."""
    token = await _get_graph_token()
    timeout = httpx.Timeout(GRAPH_TIMEOUT, connect=20.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        _, drive_id = await _resolve_site_and_drive(client, token)
        root = await _resolve_temp_root(client, token, drive_id)
        queue: List[Dict[str, str]] = [{"item_id": root["id"], "path": _normalize_graph_path(ACCOUNTING_TEMP_PATH)}]
        files: List[Dict[str, Any]] = []
        folder_count = 0

        while queue and len(files) < max_files:
            current = queue.pop(0)
            folder_count += 1
            url = (
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{current['item_id']}/children"
                "?$top=200&$select=id,name,size,file,folder,parentReference,webUrl,createdDateTime,lastModifiedDateTime"
            )
            while url and len(files) < max_files:
                data = await _graph_get(client, token, url)
                for item in data.get("value", []):
                    name = item.get("name") or ""
                    child_path = current["path"] + "/" + name
                    if item.get("folder") is not None:
                        queue.append({"item_id": item["id"], "path": child_path})
                        continue
                    if item.get("file") is None or not _supported_file(name):
                        continue
                    route_path = _route_from_folder_path(current["path"])
                    if not route_path and not include_review_root:
                        continue
                    files.append(
                        {
                            "drive_id": drive_id,
                            "item_id": item["id"],
                            "file_name": name,
                            "route_path": route_path,
                            "size": item.get("size", 0),
                            "web_url": item.get("webUrl", ""),
                            "created_at": item.get("createdDateTime"),
                            "modified_at": item.get("lastModifiedDateTime"),
                            "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
                        }
                    )
                    if len(files) >= max_files:
                        break
                url = data.get("@odata.nextLink")

    route_counts = Counter(f["route_path"] for f in files)
    return {
        "authority": f"{ACCOUNTING_HOST}{ACCOUNTING_SITE_PATH}/{ACCOUNTING_TEMP_PATH}",
        "drive_id": drive_id,
        "folder_count": folder_count,
        "file_count": len(files),
        "route_counts": dict(route_counts),
        "files": files,
    }


async def _download_graph_file(drive_id: str, item_id: str, suffix: str) -> str:
    token = await _get_graph_token()
    timeout = httpx.Timeout(GRAPH_TIMEOUT, connect=20.0)
    url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        tmp = tempfile.NamedTemporaryFile(prefix="ap-route-corpus-", suffix=suffix, delete=False)
        try:
            tmp.write(response.content)
            return tmp.name
        finally:
            tmp.close()


def _extract_text_excerpt(file_path: str, max_pages: int = 5, max_chars: int = 12000) -> str:
    if Path(file_path).suffix.lower() != ".pdf":
        return ""
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        chunks = []
        for page in reader.pages[:max_pages]:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                continue
        return "\n".join(chunks)[:max_chars]
    except Exception:
        return ""


async def hydrate_accounting_label(
    label: Dict[str, Any],
    *,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Turn one Accounting placement into an evidence-rich supervised example.

    Hydration intentionally uses the same primary-document guard proven by the
    V115 Tumalo golden. A raw nested Accounting placement is retained for audit,
    but its supervised route label is the contract-valid queue boundary. A
    one-level dynamic route is retained only when the hydrated BC context makes
    that exact route contract-valid.
    """
    file_name = str(label["file_name"])
    suffix = Path(file_name).suffix or ".bin"
    local_path = await _download_graph_file(label["drive_id"], label["item_id"], suffix)
    try:
        primary = await classify_primary_document(local_path, file_name)
        primary_type = primary.get("suggested_job_type") or primary.get("document_type") or "Unknown_Document"
        primary_fields = dict(primary.get("extracted_fields") or {})
        bundle = await extract_supporting_references(
            local_path,
            file_name,
            primary_document_type=primary_type,
            primary_fields=primary_fields,
        )
        document = {
            "id": f"accounting-temp:{label['item_id']}",
            "file_name": file_name,
            "document_type": primary_type,
            "suggested_job_type": primary_type,
            "confidence": primary.get("confidence"),
            "extracted_fields": primary_fields,
            "raw_text": _extract_text_excerpt(local_path),
        }
        bc_context = await resolve_ap_routing_context(document, bundle_refs=bundle)
        vendor_name = (
            primary_fields.get("vendor")
            or primary_fields.get("vendor_name")
            or bc_context.get("bc_vendor_name")
            or ((bc_context.get("live_bc_context") or {}).get("bc_vendor_name"))
            or ""
        )

        queue_route = normalize_route_path(label.get("route_path"))
        source_route = normalize_route_path(label.get("source_route_path") or queue_route)
        label_resolution = str(label.get("route_label_resolution") or "raw_accounting_placement")
        if (
            routing_contract
            and source_route
            and source_route != queue_route
            and not _learning_exclusion_for_route(source_route, routing_contract)
            and route_is_allowed(source_route, routing_contract, bc_context)
        ):
            queue_route = source_route
            label_resolution = "verified_dynamic_route"

        return prepare_routing_example(
            {
                "label_source": LABEL_SOURCE_ACCOUNTING_TEMP,
                "source_item_id": label["item_id"],
                "source_drive_id": label["drive_id"],
                "source_web_url": label.get("web_url"),
                "source_route_path": source_route,
                "route_label_resolution": label_resolution,
                "file_name": file_name,
                "route_path": queue_route,
                "vendor_name": vendor_name,
                "document_type": primary_type,
                "classification_confidence": primary.get("confidence"),
                "extracted_fields": primary_fields,
                "bundle_references": bundle,
                "bc_context": bc_context,
                "key_evidence": {
                    "invoice_number": primary_fields.get("invoice_number"),
                    "po_number": bc_context.get("po_number"),
                    "location_code": bc_context.get("location_code"),
                    "supporting_references": bundle.get("references"),
                },
                "created_at": label.get("created_at"),
                "modified_at": label.get("modified_at"),
            }
        )
    finally:
        try:
            os.remove(local_path)
        except OSError:
            pass


def _balanced_sample(
    labels: List[Dict[str, Any]],
    *,
    max_per_route: int,
    max_total: int,
) -> List[Dict[str, Any]]:
    by_route: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for label in labels:
        by_route[label["route_path"]].append(label)

    selected: List[Dict[str, Any]] = []
    # Round-robin across routable queues to prevent giant queues from dominating.
    ordered_routes = sorted(by_route, key=lambda r: len(by_route[r]), reverse=True)
    indices = {route: 0 for route in ordered_routes}
    while len(selected) < max_total:
        progressed = False
        for route in ordered_routes:
            idx = indices[route]
            if idx >= min(len(by_route[route]), max_per_route):
                continue
            selected.append(by_route[route][idx])
            indices[route] += 1
            progressed = True
            if len(selected) >= max_total:
                break
        if not progressed:
            break
    return selected


async def build_supervised_routing_corpus(
    db=None,
    *,
    discovery_max_files: int = 50000,
    max_per_route: int = 30,
    max_total: int = 500,
    concurrency: int = 2,
    persist: bool = False,
    routing_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a balanced evidence-rich corpus; persistence is explicit opt-in.

    When a routing contract is supplied, raw live folder placements are first
    resolved to their nearest routable queue so nested work/archive structure is
    not accidentally learned as an intake destination. Contract-declared
    downstream processed states are excluded from supervised learning while
    remaining visible in raw audit counts. Verified dynamic routes may be
    restored after BC context hydration.
    """
    discovered = await discover_accounting_temp_labels(max_files=discovery_max_files)
    label_resolution = _canonicalize_discovered_labels(discovered["files"], routing_contract)
    selected = _balanced_sample(
        label_resolution["labels"], max_per_route=max_per_route, max_total=max_total
    )
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def hydrate(label):
        async with semaphore:
            try:
                example = await hydrate_accounting_label(
                    label,
                    routing_contract=routing_contract,
                )
                if persist:
                    if db is None:
                        raise ValueError("db is required when persist=True")
                    await upsert_routing_example(db, example)
                return {"ok": True, "example": example}
            except Exception as exc:
                logger.warning("AP corpus hydration failed for %s: %s", label.get("file_name"), str(exc)[:300])
                return {
                    "ok": False,
                    "file_name": label.get("file_name"),
                    "route_path": label.get("route_path"),
                    "source_route_path": label.get("source_route_path") or label.get("route_path"),
                    "error": f"{type(exc).__name__}:{exc}"[:500],
                }

    results = await asyncio.gather(*(hydrate(label) for label in selected))
    examples = [r["example"] for r in results if r.get("ok")]
    failures = [r for r in results if not r.get("ok")]
    return {
        "authority": discovered["authority"],
        "discovered_file_count": discovered["file_count"],
        "discovered_route_counts": discovered["route_counts"],
        "canonical_discovered_route_counts": label_resolution["canonical_route_counts"],
        "collapsed_route_path_count": label_resolution["collapsed_path_count"],
        "unmapped_route_counts": label_resolution["unmapped_route_counts"],
        "excluded_learning_route_counts": label_resolution["excluded_learning_route_counts"],
        "excluded_learning_file_count": label_resolution["excluded_learning_file_count"],
        "selected_count": len(selected),
        "selected_route_counts": dict(Counter(x["route_path"] for x in selected)),
        "hydrated_count": len(examples),
        "hydrated_route_counts": dict(Counter(x.get("route_path") or "" for x in examples)),
        "route_label_resolution_counts": dict(Counter(x.get("route_label_resolution") or "unknown" for x in examples)),
        "failure_count": len(failures),
        "persisted": persist,
        "examples": examples,
        "failures": failures[:100],
    }
