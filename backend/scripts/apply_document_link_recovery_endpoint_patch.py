"""One-time exact patch for idempotent BC link recovery and entity-safe unlink."""

from pathlib import Path

path = Path("backend/routers/gpi_integration.py")
text = path.read_text(encoding="utf-8")

anchor = '''\n\n# --- STEP 3: DELETE a document link (soft delete) ---\n\n@router.delete("/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}")\n'''
insert = '''\n\n# --- STEP 3: RECOVER a failed BC document link without re-uploading ---\n\n@router.post("/document-links/recover/{doc_id}")\nasync def recover_document_link(doc_id: str):\n    """Retry only the missing BC link for an existing SharePoint document.\n\n    This path is intentionally re-link-only: it never uploads file bytes or\n    creates a replacement SharePoint item.\n    """\n    try:\n        from services.bc_document_link_recovery_service import recover_bc_document_link\n        result = await recover_bc_document_link(doc_id)\n    except LookupError as e:\n        raise HTTPException(status_code=404, detail=str(e))\n    except ValueError as e:\n        raise HTTPException(status_code=409, detail=str(e))\n    except Exception as e:\n        logger.error("[DocLinks] BC link recovery failed for %s: %s", doc_id, e)\n        raise HTTPException(status_code=502, detail=f"BC link recovery failed: {str(e)}")\n\n    if not result.get("success"):\n        raise HTTPException(\n            status_code=502,\n            detail={\n                "message": "BC link recovery failed; SharePoint file was not re-uploaded",\n                "doc_id": doc_id,\n                "delivery_status": "bc_link_failed",\n                "error": result.get("error", "Unknown BC link recovery error"),\n            },\n        )\n    return result\n\n\n# --- STEP 4: DELETE a document link (soft delete) ---\n\n@router.delete("/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}")\n'''
if text.count(anchor) != 1:
    raise SystemExit(f"recovery endpoint anchor: expected 1 match, found {text.count(anchor)}")
text = text.replace(anchor, insert, 1)

old_query = '''    # Find by id or sharepoint_item_id\n    doc = await db.hub_documents.find_one(\n        {"$or": [\n            {"id": doc_id_or_sp_item, "bc_document_no": bc_document_no},\n            {"sharepoint_item_id": doc_id_or_sp_item, "bc_document_no": bc_document_no},\n        ]},\n        {"_id": 0}\n    )\n'''
new_query = '''    # Find only within the exact BC entity + document number.\n    from services.document_link_visibility_service import build_bc_identity_clause\n    doc = await db.hub_documents.find_one(\n        {\n            "bc_document_no": bc_document_no,\n            "$and": [\n                build_bc_identity_clause(bc_entity),\n                {"$or": [\n                    {"id": doc_id_or_sp_item},\n                    {"sharepoint_item_id": doc_id_or_sp_item},\n                ]},\n            ],\n        },\n        {"_id": 0}\n    )\n'''
if text.count(old_query) != 1:
    raise SystemExit(f"entity-safe unlink query: expected 1 match, found {text.count(old_query)}")
text = text.replace(old_query, new_query, 1)

for needle in (
    '@router.post("/document-links/recover/{doc_id}")',
    'recover_bc_document_link(doc_id)',
    'SharePoint file was not re-uploaded',
    'build_bc_identity_clause(bc_entity)',
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: document-link recovery endpoint and entity-safe unlink patched")
