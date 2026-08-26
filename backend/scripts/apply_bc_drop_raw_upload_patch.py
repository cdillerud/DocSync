"""One-time exact patch for BC Drop binary upload + parity metadata boundary."""

from pathlib import Path

path = Path("backend/routers/gpi_integration.py")
text = path.read_text(encoding="utf-8")

start_marker = 'from fastapi import UploadFile, File, Form\n\n@router.post("/document-links/{bc_entity}/{bc_document_no}/upload")'
end_marker = '\n\n# --- STEP 3: RECOVER a failed BC document link without re-uploading ---'

start = text.find(start_marker)
end = text.find(end_marker, start + 1)
if start < 0 or end < 0:
    raise SystemExit(f"upload block anchors not found exactly: start={start}, end={end}")
if text.find(start_marker, start + 1) >= 0:
    raise SystemExit("upload block start marker is not unique")

replacement = r'''from fastapi import UploadFile, File, Form


async def _deliver_bc_drop_content(
    *,
    bc_entity: str,
    bc_document_no: str,
    bc_system_id: str,
    source_table_id: int,
    source_document_type: str,
    file_content: bytes,
    file_name: str,
    uploaded_by: str,
    vendor_context: str,
):
    """Deliver one exact-record BC FactBox upload without identity or metadata bypasses."""
    db = get_db()

    from services.bc_drop_parity_metadata_service import (
        build_bc_drop_parity_metadata,
        normalize_system_id,
        validate_bc_drop_source_contract,
        write_bc_drop_parity_metadata,
    )

    try:
        validate_bc_drop_source_contract(bc_entity, source_table_id, source_document_type)
        bc_system_id = normalize_system_id(bc_system_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    file_name = str(file_name or "").strip()
    if not file_name:
        raise HTTPException(status_code=400, detail="BC Drop upload requires file_name")
    if not file_content:
        raise HTTPException(status_code=400, detail="BC Drop upload body is empty")
    if len(file_content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds 25MB limit ({len(file_content) / (1024*1024):.1f}MB)",
        )

    # Resolve folder using exact entity + number + immutable SystemId.
    folder_source = "routing_rules"
    folder_path = ""
    from services.document_link_visibility_service import build_folder_match_query
    existing = await db.hub_documents.find_one(
        build_folder_match_query(bc_entity, bc_document_no, bc_system_id),
        {"sharepoint_folder_path": 1, "sharepoint_drive_id": 1, "_id": 0},
        sort=[("created_utc", -1)],
    )

    if existing and existing.get("sharepoint_folder_path"):
        folder_path = existing["sharepoint_folder_path"]
        folder_source = "matched"
        logger.info("[DocLinks] Folder matched from exact existing doc for %s: %s", bc_document_no, folder_path)
    else:
        try:
            from services.folder_routing_service import determine_folder_path
            doc_type = bc_entity_to_doc_type(bc_entity)
            fake_doc = {
                "document_type": doc_type,
                "extracted_fields": {"vendor": vendor_context},
                "normalized_fields": {},
            }
            folder_path, _reason, _details = determine_folder_path(fake_doc)
            logger.info("[DocLinks] Folder from routing rules for %s: %s (%s)", bc_document_no, folder_path, _reason)
        except Exception as exc:
            logger.warning("[DocLinks] Folder routing failed, using default: %s", exc)
            folder_path = f"BC_Drops/{bc_entity}/{bc_document_no}"

    # Upload original bytes once. Production SharePoint remains protected by the
    # central write interlock inside upload_to_sharepoint.
    try:
        from services.sharepoint_service import upload_to_sharepoint
        sp_result = await upload_to_sharepoint(file_content, file_name, folder_path)
    except Exception as exc:
        logger.error("[DocLinks] SharePoint upload failed for %s: %s", bc_document_no, exc)
        raise HTTPException(status_code=502, detail=f"SharePoint upload failed: {str(exc)}") from exc

    now = datetime.now(timezone.utc).isoformat()
    new_doc_id = str(uuid.uuid4())
    staged_metadata = build_bc_drop_parity_metadata(
        bc_entity=bc_entity,
        bc_document_no=bc_document_no,
        bc_system_id=bc_system_id,
        source_table_id=source_table_id,
        source_document_type=source_document_type,
        original_file_name=file_name,
        sharepoint_file_name=sp_result.get("name", file_name),
        sharepoint_path=folder_path,
        sharepoint_url=sp_result.get("web_url", ""),
        ready=False,
    )

    # Persist SharePoint identity immediately so every post-upload failure can be
    # recovered against the same item rather than uploading a duplicate.
    hub_record = {
        "id": new_doc_id,
        "file_name": file_name,
        "original_file_name": file_name,
        "sharepoint_file_name": sp_result.get("name", file_name),
        "bc_document_no": bc_document_no,
        "bc_entity_type": bc_entity,
        "bc_entity": bc_entity,
        "bc_system_id": bc_system_id,
        "bc_record_id": bc_system_id,
        "bc_source_table_id": int(source_table_id),
        "bc_source_document_type": source_document_type,
        "sharepoint_folder_path": folder_path,
        "sharepoint_web_url": sp_result.get("web_url", ""),
        "sharepoint_drive_id": sp_result.get("drive_id", ""),
        "sharepoint_item_id": sp_result.get("item_id", ""),
        "source": "bc_drop",
        "uploaded_by": uploaded_by,
        "created_utc": now,
        "updated_utc": now,
        "document_type": bc_entity_to_doc_type(bc_entity),
        "folder_source": folder_source,
        "file_size_bytes": len(file_content),
        "bc_link_created": False,
        "bc_link_error": "",
        "delivery_status": "sharepoint_uploaded_pending_metadata",
        "import_ready": False,
        **staged_metadata,
    }
    await db.hub_documents.insert_one(hub_record)
    hub_record.pop("_id", None)

    # Stage normalized metadata before attempting the BC link. ImportReady stays
    # false until both sides have succeeded.
    try:
        await write_bc_drop_parity_metadata(hub_record, ready=False)
    except Exception as exc:
        error = str(exc)
        await db.hub_documents.update_one(
            {"id": new_doc_id},
            {"$set": {
                "delivery_status": "sharepoint_metadata_failed",
                "import_ready": False,
                "ImportReady": False,
                "GPI_Status": "NeedsMetadata",
                "last_error": error,
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "SharePoint upload completed but parity metadata failed",
                "doc_id": new_doc_id,
                "delivery_status": "sharepoint_metadata_failed",
                "error": error,
            },
        ) from exc

    # Create the BC document link using the exact SystemId supplied by BC.
    try:
        link_result = await create_gpi_document_link(
            bc_system_id=bc_system_id,
            bc_document_no=bc_document_no,
            document_type=source_document_type,
            sharepoint_url=sp_result.get("web_url", ""),
            sharepoint_drive_id=sp_result.get("drive_id", ""),
            sharepoint_item_id=sp_result.get("item_id", ""),
            uploaded_by=uploaded_by,
            source="BCDrop",
        )
        bc_link_created = bool(link_result.get("success", False))
        bc_link_error = "" if bc_link_created else link_result.get("error", "BC document link creation failed")
    except Exception as exc:
        bc_link_created = False
        bc_link_error = str(exc)
        logger.error("[DocLinks] BC link creation failed: %s", exc)

    if not bc_link_created:
        await db.hub_documents.update_one(
            {"id": new_doc_id},
            {"$set": {
                "bc_link_created": False,
                "bc_link_error": bc_link_error,
                "delivery_status": "bc_link_failed",
                "import_ready": False,
                "ImportReady": False,
                "GPI_Status": "NeedsBCLink",
                "last_error": bc_link_error,
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "SharePoint upload completed but BC link creation failed",
                "doc_id": new_doc_id,
                "delivery_status": "bc_link_failed",
                "error": bc_link_error,
            },
        )

    # Finalize the same SharePoint item only after the exact BC link exists.
    try:
        final_metadata = await write_bc_drop_parity_metadata(hub_record, ready=True)
    except Exception as exc:
        error = str(exc)
        await db.hub_documents.update_one(
            {"id": new_doc_id},
            {"$set": {
                "bc_link_created": True,
                "bc_link_error": "",
                "delivery_status": "sharepoint_metadata_failed",
                "import_ready": False,
                "ImportReady": False,
                "GPI_Status": "NeedsMetadata",
                "last_error": error,
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }},
        )
        raise HTTPException(
            status_code=502,
            detail={
                "message": "BC link created but final SharePoint parity metadata failed",
                "doc_id": new_doc_id,
                "delivery_status": "sharepoint_metadata_failed",
                "error": error,
            },
        ) from exc

    delivered_at = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": new_doc_id},
        {"$set": {
            **final_metadata,
            "bc_link_created": True,
            "bc_link_error": "",
            "delivery_status": "delivered",
            "import_ready": True,
            "last_error": "",
            "updated_utc": delivered_at,
            "delivered_at": delivered_at,
        }},
    )

    logger.info(
        "[DocLinks] Delivered %s to %s for exact %s/%s/%s (folder_source=%s)",
        file_name,
        folder_path,
        bc_entity,
        bc_document_no,
        bc_system_id,
        folder_source,
    )
    return {
        "success": True,
        "doc_id": new_doc_id,
        "file_name": file_name,
        "sharepoint_url": sp_result.get("web_url", ""),
        "folder_path": folder_path,
        "folder_source": folder_source,
        "bc_link_created": True,
        "import_ready": True,
    }


@router.post("/document-links/{bc_entity}/{bc_document_no}/upload")
async def upload_document_to_bc_record(
    bc_entity: str,
    bc_document_no: str,
    file: UploadFile = File(...),
    uploaded_by: str = Form("BC Drop"),
    vendor_context: str = Form(""),
    bc_system_id: str = Query(""),
    source_table_id: int = Query(0),
    source_document_type: str = Query(""),
):
    """Browser/multipart upload using the exact-record delivery boundary."""
    return await _deliver_bc_drop_content(
        bc_entity=bc_entity,
        bc_document_no=bc_document_no,
        bc_system_id=bc_system_id,
        source_table_id=source_table_id,
        source_document_type=source_document_type,
        file_content=await file.read(),
        file_name=file.filename or "",
        uploaded_by=uploaded_by,
        vendor_context=vendor_context,
    )


@router.post("/document-links/{bc_entity}/{bc_document_no}/upload-raw")
async def upload_document_to_bc_record_raw(
    bc_entity: str,
    bc_document_no: str,
    request: Request,
    bc_system_id: str = Query(""),
    source_table_id: int = Query(0),
    source_document_type: str = Query(""),
    file_name: str = Query(""),
    uploaded_by: str = Query("BC Drop"),
    vendor_context: str = Query(""),
):
    """Business Central native binary upload; the body is the original file bytes."""
    content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    if content_type != "application/octet-stream":
        raise HTTPException(status_code=415, detail="BC raw upload requires application/octet-stream")

    return await _deliver_bc_drop_content(
        bc_entity=bc_entity,
        bc_document_no=bc_document_no,
        bc_system_id=bc_system_id,
        source_table_id=source_table_id,
        source_document_type=source_document_type,
        file_content=await request.body(),
        file_name=file_name,
        uploaded_by=uploaded_by,
        vendor_context=vendor_context,
    )
'''

patched = text[:start] + replacement + text[end:]

required = (
    'async def _deliver_bc_drop_content(',
    '@router.post("/document-links/{bc_entity}/{bc_document_no}/upload-raw")',
    'content_type != "application/octet-stream"',
    'write_bc_drop_parity_metadata(hub_record, ready=False)',
    'write_bc_drop_parity_metadata(hub_record, ready=True)',
    'validate_bc_drop_source_contract(bc_entity, source_table_id, source_document_type)',
    'bc_system_id: str = Query("")',
)
for token in required:
    if token not in patched:
        raise SystemExit(f"missing post-patch safety token: {token}")

old_corruption_markers = (
    'file_content = await file.read()\n    if len(file_content) > MAX_UPLOAD_SIZE:',
    'identity = await resolve_bc_document_system_id(bc_entity, bc_document_no)',
)
for token in old_corruption_markers:
    if token in patched[start:patched.find(end_marker, start)]:
        raise SystemExit(f"legacy upload boundary remains after patch: {token}")

path.write_text(patched, encoding="utf-8")
print("PASS: BC Drop exact-record binary/parity upload boundary patched")
