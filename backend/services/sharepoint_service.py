"""GPI Document Hub SharePoint operations and pre-upload routing guard."""

import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import httpx
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
SHAREPOINT_TARGET = os.environ.get("SHAREPOINT_TARGET", "test").strip().lower()

_SHAREPOINT_TARGETS = {
    "test": {
        "hostname": "gamerpackaging1.sharepoint.com",
        "site_path": "/sites/GPI-DocumentHub-Test",
        "library_name": "Shared Documents",
        "base_folder": "",
    },
    "production": {
        "hostname": "gamerpackaging1.sharepoint.com",
        "site_path": "/sites/GamerAccounting",
        "library_name": "Shared Documents",
        "base_folder": "General/Accounting/Accounts Payable/Temp Folder",
    },
}

if SHAREPOINT_TARGET not in _SHAREPOINT_TARGETS:
    logger.warning(
        "[SharePoint] Unrecognized SHAREPOINT_TARGET=%r; using test for safety",
        SHAREPOINT_TARGET,
    )
    SHAREPOINT_TARGET = "test"

_target = _SHAREPOINT_TARGETS[SHAREPOINT_TARGET]
SHAREPOINT_SITE_HOSTNAME = os.environ.get("SHAREPOINT_SITE_HOSTNAME") or _target["hostname"]
SHAREPOINT_SITE_PATH = os.environ.get("SHAREPOINT_SITE_PATH") or _target["site_path"]
SHAREPOINT_LIBRARY_NAME = os.environ.get("SHAREPOINT_LIBRARY_NAME") or _target["library_name"]
SHAREPOINT_BASE_FOLDER = os.environ.get("SHAREPOINT_BASE_FOLDER")
if SHAREPOINT_BASE_FOLDER is None:
    SHAREPOINT_BASE_FOLDER = _target["base_folder"]

logger.warning(
    "[SharePoint] ACTIVE TARGET: %s -> %s%s (base folder: %r)",
    SHAREPOINT_TARGET.upper(),
    SHAREPOINT_SITE_HOSTNAME,
    SHAREPOINT_SITE_PATH,
    SHAREPOINT_BASE_FOLDER,
)


async def _get_graph_token():
    from services.config_service import get_graph_token
    return await get_graph_token()


async def _resolve_site_and_drive(client: httpx.AsyncClient, token: str) -> Tuple[str, str]:
    site_resp = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
        headers={"Authorization": f"Bearer {token}"},
    )
    site_data = site_resp.json()
    if site_resp.status_code in (401, 403):
        raise Exception(
            f"Graph API permission denied (HTTP {site_resp.status_code}). "
            "The app registration needs Sites.ReadWrite.All with admin consent."
        )
    if site_resp.status_code == 404 or "id" not in site_data:
        error = site_data.get("error", {})
        raise Exception(
            f"SharePoint site not found (HTTP {site_resp.status_code}). "
            f"Check hostname={SHAREPOINT_SITE_HOSTNAME!r}, path={SHAREPOINT_SITE_PATH!r}. "
            f"Detail: {error.get('message', error.get('code', 'unknown'))}"
        )
    site_id = site_data["id"]

    drives_resp = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers={"Authorization": f"Bearer {token}"},
    )
    drives_data = drives_resp.json()
    if drives_resp.status_code in (401, 403):
        raise Exception(
            f"Graph permission denied listing drives (HTTP {drives_resp.status_code})"
        )
    if "error" in drives_data:
        raise Exception(
            f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}"
        )

    drives = drives_data.get("value", [])
    library = SHAREPOINT_LIBRARY_NAME.lower()
    drive = next((d for d in drives if str(d.get("name", "")).lower() == library), None)
    if not drive:
        alternate = {"documents": "shared documents", "shared documents": "documents"}.get(library)
        if alternate:
            drive = next(
                (d for d in drives if str(d.get("name", "")).lower() == alternate),
                None,
            )
    if not drive:
        drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), None)
    if not drive:
        raise Exception(
            f"Document library {SHAREPOINT_LIBRARY_NAME!r} not found. "
            f"Available: {[d.get('name') for d in drives]}"
        )
    return site_id, drive["id"]


async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):
    folder_for_url = str(folder or "").strip("/")
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id,
            "item_id": item_id,
            "web_url": (
                f"https://{SHAREPOINT_SITE_HOSTNAME}{SHAREPOINT_SITE_PATH}/"
                f"{SHAREPOINT_LIBRARY_NAME}/{folder_for_url}/{file_name}"
            ),
            "name": file_name,
        }

    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        _, drive_id = await _resolve_site_and_drive(client, token)
        from urllib.parse import quote

        safe_folder = quote(folder_for_url, safe="/")
        safe_name = quote(file_name, safe="")
        destination = f"{safe_folder}/{safe_name}" if safe_folder else safe_name
        upload_resp = await client.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{destination}:/content",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/octet-stream",
            },
            content=file_content,
        )
        item = upload_resp.json()
        if upload_resp.status_code in (401, 403):
            raise Exception(
                f"Upload permission denied (HTTP {upload_resp.status_code}). "
                "Ensure Files.ReadWrite.All or Sites.ReadWrite.All is granted."
            )
        if "id" not in item:
            error = item.get("error", {})
            raise Exception(
                f"Upload failed (HTTP {upload_resp.status_code}): "
                f"{error.get('message', error.get('code', item))}"
            )
        return {
            "drive_id": drive_id,
            "item_id": item["id"],
            "web_url": item.get("webUrl", ""),
            "name": file_name,
        }


async def create_sharing_link(drive_id: str, item_id: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return f"https://{SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/createLink",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json={"type": "view", "scope": "organization"},
        )
        data = resp.json()
        if "error" in data:
            raise Exception(
                f"Sharing link error: {data['error'].get('message', data['error'])}"
            )
        return data.get("link", {}).get("webUrl", "")


async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:
    """Create the requested folder hierarchy when it does not already exist."""
    normalized_path = str(folder_path or "").strip("/")
    if not normalized_path or DEMO_MODE or not GRAPH_CLIENT_ID:
        return True

    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        _, drive_id = await _resolve_site_and_drive(client, token)
        from urllib.parse import quote

        current_parts = []
        for part in [p for p in normalized_path.split("/") if p]:
            parent_path = "/".join(current_parts)
            current_parts.append(part)
            current_path = "/".join(current_parts)
            safe_current = quote(current_path, safe="/")
            check_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_current}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if check_resp.status_code != 404:
                continue

            if parent_path:
                safe_parent = quote(parent_path, safe="/")
                create_url = (
                    f"https://graph.microsoft.com/v1.0/drives/{drive_id}/"
                    f"root:/{safe_parent}:/children"
                )
            else:
                create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
            create_resp = await client.post(
                create_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={
                    "name": part,
                    "folder": {},
                    "@microsoft.graph.conflictBehavior": "fail",
                },
            )
            if create_resp.status_code not in (200, 201, 409):
                logger.warning(
                    "Failed to create folder %s: %s",
                    current_path,
                    create_resp.text[:200],
                )
            else:
                logger.info("Created SharePoint folder: %s", current_path)
    return True


def _sanitize_filename_part(value: Optional[str], max_len: int = 40) -> str:
    if not value:
        return ""
    cleaned = re.sub(r'[<>:"/\\|?*\n\r\t]', "", str(value).strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:max_len].strip()


def _best_of_clean_and_raw(raw: Optional[str], clean: Optional[str]) -> Optional[str]:
    if raw and "," in raw:
        first = raw.split(",")[0].strip()
        if first:
            return first
    return clean or raw


def _extract_reference_number(doc: Dict[str, Any]) -> str:
    extracted = doc.get("extracted_fields") or {}
    for candidate in (
        _best_of_clean_and_raw(doc.get("invoice_number_raw"), doc.get("invoice_number_clean")),
        _best_of_clean_and_raw(doc.get("po_number_raw"), doc.get("po_number_clean")),
        extracted.get("order_number"),
        extracted.get("tracking_number"),
        extracted.get("bol_number"),
    ):
        if candidate:
            return _sanitize_filename_part(str(candidate), max_len=20)
    return ""


def _extract_vendor_name(doc: Dict[str, Any]) -> str:
    extracted = doc.get("extracted_fields") or {}
    for candidate in (
        doc.get("vendor_canonical"),
        doc.get("bc_vendor_number"),
        extracted.get("vendor"),
        extracted.get("shipper"),
        doc.get("vendor_raw"),
    ):
        if candidate:
            return _sanitize_filename_part(str(candidate), max_len=25)
    return "Unknown"


def _extract_document_date(doc: Dict[str, Any]) -> str:
    extracted = doc.get("extracted_fields") or {}
    for candidate in (
        doc.get("invoice_date_iso"),
        doc.get("invoice_date"),
        extracted.get("invoice_date"),
        extracted.get("ship_date"),
        extracted.get("order_date"),
        doc.get("created_utc"),
    ):
        if not candidate:
            continue
        try:
            return datetime.strptime(str(candidate)[:10], "%Y-%m-%d").strftime("%m%d%Y")
        except (ValueError, TypeError):
            continue
    return ""


def generate_square9_style_filename(doc: Dict[str, Any], original_filename: str) -> str:
    ext = "." + original_filename.rsplit(".", 1)[-1] if "." in original_filename else ""
    reference = _extract_reference_number(doc)
    vendor = _extract_vendor_name(doc)
    date_string = _extract_document_date(doc)
    if sum((bool(reference), vendor != "Unknown", bool(date_string))) < 2:
        return original_filename

    base_name = " ".join(value for value in (reference, vendor, date_string) if value)
    batch_pages = doc.get("batch_pages")
    if batch_pages:
        base_name += " p" + "-".join(str(page) for page in batch_pages)
    return base_name + ext


def _merge_routing_document(fresh: Dict[str, Any], supplied: Dict[str, Any]) -> Dict[str, Any]:
    """Merge the DB record with the in-memory pipeline document.

    The supplied document wins because classification/extraction may have completed
    in memory immediately before the DB update. Nested evidence dictionaries are
    merged rather than replaced.
    """
    merged = dict(fresh or {})
    merged.update(supplied or {})
    for field in (
        "extracted_fields",
        "normalized_fields",
        "canonical_fields",
        "validation_results",
    ):
        nested = dict((fresh or {}).get(field) or {})
        nested.update((supplied or {}).get(field) or {})
        if nested:
            merged[field] = nested
    return merged


def _structured_po_number(doc: Dict[str, Any]) -> str:
    extracted = doc.get("extracted_fields") or {}
    normalized = doc.get("normalized_fields") or {}
    canonical = doc.get("canonical_fields") or {}
    for value in (
        doc.get("po_number_clean"),
        doc.get("po_number_extracted"),
        canonical.get("po_number_clean"),
        canonical.get("po_number"),
        normalized.get("po_number_clean"),
        normalized.get("po_number"),
        extracted.get("po_number"),
        extracted.get("purchase_order_number"),
    ):
        if value and str(value).strip():
            try:
                from services.po_resolution_service import normalize_po
                normalized_value = normalize_po(str(value))
            except Exception:
                normalized_value = str(value).strip().upper()
            if normalized_value:
                return normalized_value
    return ""


async def _prepare_routing_document(doc: Dict[str, Any]):
    """Refresh evidence and resolve a structured PO before a file is routed."""
    routing_doc = dict(doc or {})
    db = None
    try:
        from deps import get_db
        db = get_db()
        doc_id = routing_doc.get("id")
        if db is not None and doc_id:
            fresh = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            routing_doc = _merge_routing_document(fresh or {}, routing_doc)
    except Exception as error:
        logger.warning("[PreUpload] Could not refresh document: %s", error)

    structured_po = _structured_po_number(routing_doc)
    if structured_po:
        routing_doc["po_number_clean"] = structured_po
        routing_doc["po_number_extracted"] = structured_po
        routing_doc.setdefault("extracted_fields", {})["po_number"] = structured_po

    po_result = None
    doc_type = str(
        routing_doc.get("document_type")
        or routing_doc.get("doc_type")
        or routing_doc.get("suggested_job_type")
        or ""
    ).upper().replace(" ", "_")
    should_resolve = structured_po and any(
        token in doc_type
        for token in ("AP_INVOICE", "PURCHASE_INVOICE", "WAREHOUSE", "SHIPPING", "FREIGHT")
    )

    if should_resolve:
        try:
            from services.po_resolution_service import resolve_po_from_document
            po_result = await resolve_po_from_document(routing_doc)
            routing_doc["po_resolution"] = po_result
            best = po_result.get("best_match") or {}
            resolved_po = po_result.get("po_number") or best.get("bc_document_no")
            status = str(po_result.get("status") or "")
            miss_reason = str(po_result.get("miss_reason") or "")
            if resolved_po:
                routing_doc["po_number_clean"] = str(resolved_po)
                routing_doc["po_number_extracted"] = str(resolved_po)
            if status.startswith("resolved"):
                routing_doc["bc_po_resolved"] = True
                for source_key, target_key in (
                    ("location_code", "resolved_location_code"),
                    ("bc_location_code", "resolved_location_code"),
                    ("locationCode", "resolved_location_code"),
                ):
                    value = best.get(source_key) or po_result.get(source_key)
                    if value:
                        routing_doc[target_key] = value
                        routing_doc.setdefault("location_code", value)
                        break
            elif status == "not_found" and miss_reason != "bc_lookup_error":
                routing_doc["bc_po_resolved"] = False

            if db is not None and routing_doc.get("id"):
                update = {
                    "po_resolution": po_result,
                    "po_candidates": po_result.get("candidates_raw", []),
                    "po_number_clean": routing_doc.get("po_number_clean"),
                    "po_number_extracted": routing_doc.get("po_number_extracted"),
                    "routing_preupload_po_checked_at": datetime.now(timezone.utc).isoformat(),
                }
                if "bc_po_resolved" in routing_doc:
                    update["bc_po_resolved"] = routing_doc["bc_po_resolved"]
                if routing_doc.get("resolved_location_code"):
                    update["resolved_location_code"] = routing_doc["resolved_location_code"]
                    update["location_code"] = routing_doc.get("location_code")
                await db.hub_documents.update_one(
                    {"id": routing_doc["id"]},
                    {"$set": update},
                )
        except Exception as error:
            logger.warning(
                "[PreUpload] Structured PO resolution failed for doc=%s po=%s: %s",
                routing_doc.get("id", "unknown"),
                structured_po,
                error,
            )

    return routing_doc, db, po_result


async def _persist_preupload_snapshot(
    db,
    routing_doc: Dict[str, Any],
    folder_path: str,
    reason: str,
    details: Dict[str, Any],
) -> Dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    snapshot = {
        "folder_path": folder_path,
        "reason": reason,
        "source": str((details or {}).get("source") or "folder_routing_service"),
        "suggested_at": now,
        "capture_type": "pre_filing_routing",
        "details": details or {},
    }
    doc_id = routing_doc.get("id")
    if db is None or not doc_id:
        return snapshot

    existing = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "routing_suggestion_snapshot": 1},
    ) or {}
    previous = existing.get("routing_suggestion_snapshot") or {}
    if not previous.get("folder_path"):
        result = await db.hub_documents.update_one(
            {
                "id": doc_id,
                "$or": [
                    {"routing_suggestion_snapshot": {"$exists": False}},
                    {"routing_suggestion_snapshot": None},
                    {"routing_suggestion_snapshot": {}},
                ],
            },
            {"$set": {
                "routing_suggestion_snapshot": snapshot,
                "initial_suggested_folder": folder_path,
                "initial_routing_reason": reason,
                "initial_routing_source": snapshot["source"],
                "initial_routing_suggested_at": now,
                "routing_reason": reason,
                "routing_details": details or {},
                "routing_preupload_checked_at": now,
            }},
        )
        if getattr(result, "modified_count", 0):
            routing_doc["routing_suggestion_snapshot"] = snapshot
            return snapshot

    previous_folder = str(previous.get("folder_path") or "").strip("/").casefold()
    new_folder = str(folder_path or "").strip("/").casefold()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "routing_preupload_checked_at": now,
            "routing_preupload_recheck": {
                "folder_path": folder_path,
                "reason": reason,
                "source": snapshot["source"],
                "checked_at": now,
                "matches_initial": bool(previous_folder and previous_folder == new_folder),
            },
        }},
    )
    return previous or snapshot


async def upload_to_sharepoint_with_routing(
    file_content: bytes,
    file_name: str,
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False,
) -> Dict[str, Any]:
    """Resolve, route, snapshot, and only then upload the document."""
    from services.folder_routing_service import route_with_feedback

    routing_doc, db, po_result = await _prepare_routing_document(doc)
    extracted = routing_doc.get("extracted_fields") or {}
    resolved_direction = (
        freight_direction
        or routing_doc.get("freight_direction")
        or extracted.get("freight_direction")
    )
    resolved_international = bool(
        is_international
        or routing_doc.get("is_international")
        or extracted.get("is_international") is True
        or str(extracted.get("is_international") or "").lower() == "true"
    )

    folder_path, routing_reason, routing_details = await route_with_feedback(
        routing_doc,
        freight_direction=resolved_direction,
        is_international=resolved_international,
        location_code=(
            routing_doc.get("resolved_location_code")
            or routing_doc.get("location_code")
            or extracted.get("location_code")
        ),
    )

    snapshot = await _persist_preupload_snapshot(
        db,
        routing_doc,
        folder_path,
        routing_reason,
        routing_details,
    )

    base = str(SHAREPOINT_BASE_FOLDER or "").strip("/")
    relative = str(folder_path or "").strip("/")
    if base:
        full_folder_path = f"{base}/{relative}" if relative else base
    else:
        full_folder_path = f"/{relative}" if relative else ""

    logger.info(
        "[Folder Routing] Doc %s -> %s (reason=%s source=%s po_status=%s)",
        routing_doc.get("id", "unknown"),
        full_folder_path,
        routing_reason,
        (routing_details or {}).get("source", "folder_routing_service"),
        (po_result or {}).get("status", "not_run"),
    )

    await ensure_sharepoint_folder_exists(full_folder_path)
    upload_file_name = generate_square9_style_filename(routing_doc, file_name)
    if upload_file_name != file_name:
        logger.info(
            "[Filename] Doc %s: %r -> %r",
            routing_doc.get("id", "unknown"),
            file_name,
            upload_file_name,
        )

    result = await upload_to_sharepoint(
        file_content,
        upload_file_name,
        full_folder_path,
    )
    result.update({
        "folder_path": full_folder_path,
        "routing_reason": routing_reason,
        "routing_details": routing_details,
        "routing_snapshot": snapshot,
        "po_resolution_status": (po_result or {}).get("status", "not_run"),
        "uploaded_file_name": upload_file_name,
        "original_file_name": file_name,
    })
    return result
