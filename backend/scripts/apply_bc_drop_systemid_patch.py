"""One-time exact patch for BC-drop SystemId/link delivery boundary."""

from pathlib import Path

router_path = Path("backend/routers/gpi_integration.py")
service_path = Path("backend/services/gpi_integration_service.py")
router = router_path.read_text(encoding="utf-8")
service = service_path.read_text(encoding="utf-8")

router_replacements = [
    (
'''    if len(file_content) > MAX_UPLOAD_SIZE:\n        raise HTTPException(\n            status_code=413,\n            detail=f"File exceeds 25MB limit ({len(file_content) / (1024*1024):.1f}MB)"\n        )\n\n    # --- FOLDER RESOLUTION ---\n''',
'''    if len(file_content) > MAX_UPLOAD_SIZE:\n        raise HTTPException(\n            status_code=413,\n            detail=f"File exceeds 25MB limit ({len(file_content) / (1024*1024):.1f}MB)"\n        )\n\n    # Resolve exact BC identity before creating any new SharePoint artifact.\n    # A document number alone is not a safe linkage key.\n    try:\n        from services.bc_document_identity_service import resolve_bc_document_system_id\n        identity = await resolve_bc_document_system_id(bc_entity, bc_document_no)\n        bc_system_id = identity["bc_system_id"]\n    except Exception as e:\n        logger.error("[DocLinks] BC identity resolution failed for %s/%s: %s", bc_entity, bc_document_no, e)\n        raise HTTPException(\n            status_code=409,\n            detail=f"BC record identity could not be resolved; no file was uploaded: {str(e)}",\n        )\n\n    # --- FOLDER RESOLUTION ---\n''',
        "pre-upload SystemId gate",
    ),
    (
'''        link_result = await create_gpi_document_link(\n            bc_system_id="",\n''',
'''        link_result = await create_gpi_document_link(\n            bc_system_id=bc_system_id,\n''',
        "BC link SystemId",
    ),
    (
'''        bc_link_created = link_result.get("success", False)\n    except Exception as e:\n        logger.warning("[DocLinks] BC link creation failed (non-blocking): %s", e)\n\n    # --- CREATE HUB_DOCUMENTS RECORD ---\n''',
'''        bc_link_created = link_result.get("success", False)\n        bc_link_error = "" if bc_link_created else link_result.get("error", "BC document link creation failed")\n    except Exception as e:\n        bc_link_error = str(e)\n        logger.error("[DocLinks] BC link creation failed: %s", e)\n\n    # --- CREATE HUB_DOCUMENTS RECORD ---\n''',
        "blocking BC link state capture",
    ),
    (
'''        "bc_document_no": bc_document_no,\n        "bc_entity_type": bc_entity,\n''',
'''        "bc_document_no": bc_document_no,\n        "bc_entity_type": bc_entity,\n        "bc_system_id": bc_system_id,\n''',
        "persist BC SystemId",
    ),
    (
'''        "folder_source": folder_source,\n        "file_size_bytes": len(file_content),\n    }\n''',
'''        "folder_source": folder_source,\n        "file_size_bytes": len(file_content),\n        "bc_link_created": bc_link_created,\n        "bc_link_error": bc_link_error if not bc_link_created else "",\n        "delivery_status": "delivered" if bc_link_created else "bc_link_failed",\n        "import_ready": bool(bc_link_created and bc_system_id),\n    }\n''',
        "delivery state persistence",
    ),
    (
'''    logger.info("[DocLinks] Uploaded %s to %s for %s/%s (folder_source=%s, bc_link=%s)",\n                file.filename, folder_path, bc_entity, bc_document_no, folder_source, bc_link_created)\n\n    return {\n''',
'''    logger.info("[DocLinks] Uploaded %s to %s for %s/%s (folder_source=%s, bc_link=%s)",\n                file.filename, folder_path, bc_entity, bc_document_no, folder_source, bc_link_created)\n\n    if not bc_link_created:\n        raise HTTPException(\n            status_code=502,\n            detail={\n                "message": "SharePoint upload completed but BC link creation failed",\n                "doc_id": new_doc_id,\n                "delivery_status": "bc_link_failed",\n                "error": bc_link_error,\n            },\n        )\n\n    return {\n''',
        "fail request when BC link fails",
    ),
]

for old, new, label in router_replacements:
    count = router.count(old)
    if count != 1:
        raise SystemExit(f"router {label}: expected 1 match, found {count}")
    router = router.replace(old, new, 1)

service_old = '''    _check_write_protection("create_gpi_document_link")\n    if not HAS_CREDENTIALS:\n        raise ValueError("BC credentials not configured")\n\n    token = await _get_token()\n'''
service_new = '''    _check_write_protection("create_gpi_document_link")\n    if not str(bc_system_id or "").strip():\n        raise ValueError("BC SystemId is required for GPI Document Link creation")\n    if not HAS_CREDENTIALS:\n        raise ValueError("BC credentials not configured")\n\n    token = await _get_token()\n'''
count = service.count(service_old)
if count != 1:
    raise SystemExit(f"service SystemId guard: expected 1 match, found {count}")
service = service.replace(service_old, service_new, 1)

for needle in (
    'resolve_bc_document_system_id(bc_entity, bc_document_no)',
    'bc_system_id=bc_system_id',
    '"delivery_status": "delivered" if bc_link_created else "bc_link_failed"',
    '"import_ready": bool(bc_link_created and bc_system_id)',
):
    if needle not in router:
        raise SystemExit(f"router verification missing: {needle}")
if 'BC SystemId is required for GPI Document Link creation' not in service:
    raise SystemExit("service verification missing SystemId guard")

router_path.write_text(router, encoding="utf-8")
service_path.write_text(service, encoding="utf-8")
print("PASS: BC-drop SystemId/link boundary patched")
