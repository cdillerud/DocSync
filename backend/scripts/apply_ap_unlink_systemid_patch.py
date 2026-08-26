"""One-time exact patch for AP FactBox unlink SystemId binding."""

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one anchor, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


router = Path("backend/routers/gpi_integration.py")
replace_once(
    router,
    '  const API = "{api_path}";\n  const LIST_API = API + "{identity_query}";\n',
    '  const API = "{api_path}";\n  const IDENTITY_QUERY = "{identity_query}";\n  const LIST_API = API + IDENTITY_QUERY;\n',
)
replace_once(
    router,
    '            const resp = await fetch(API + "/" + encodeURIComponent(id), {{ method: "DELETE" }});\n',
    '            const resp = await fetch(API + "/" + encodeURIComponent(id) + IDENTITY_QUERY, {{ method: "DELETE" }});\n',
)
replace_once(
    router,
    '''@router.delete("/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}")\nasync def delete_document_link(bc_entity: str, bc_document_no: str, doc_id_or_sp_item: str):\n    """Soft-delete a document link. The SharePoint file remains for audit."""\n    db = get_db()\n    now = datetime.now(timezone.utc).isoformat()\n\n    # Find only within the exact BC entity + document number.\n    from services.document_link_visibility_service import build_bc_identity_clause\n    doc = await db.hub_documents.find_one(\n        {\n            "bc_document_no": bc_document_no,\n            "$and": [\n                build_bc_identity_clause(bc_entity),\n                {"$or": [\n                    {"id": doc_id_or_sp_item},\n                    {"sharepoint_item_id": doc_id_or_sp_item},\n                ]},\n            ],\n        },\n        {"_id": 0}\n    )\n''',
    '''@router.delete("/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}")\nasync def delete_document_link(\n    bc_entity: str,\n    bc_document_no: str,\n    doc_id_or_sp_item: str,\n    bc_system_id: str = "",\n):\n    """Soft-delete a document link. The SharePoint file remains for audit."""\n    db = get_db()\n    now = datetime.now(timezone.utc).isoformat()\n\n    # Upgraded AP FactBoxes carry the immutable SystemId used for the read.\n    # Legacy callers retain typed entity + number + link-id behavior.\n    from services.document_link_visibility_service import build_hub_document_unlink_query\n    doc = await db.hub_documents.find_one(\n        build_hub_document_unlink_query(\n            bc_entity, bc_document_no, doc_id_or_sp_item, bc_system_id\n        ),\n        {"_id": 0}\n    )\n''',
)

print("PASS: AP unlink SystemId router patch applied")
