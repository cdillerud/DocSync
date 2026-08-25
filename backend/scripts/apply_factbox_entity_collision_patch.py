"""One-time exact patch for BC Gamer Documents entity-safe lookups.

Fails closed unless each expected source shape appears exactly once.
"""

from pathlib import Path

path = Path("backend/routers/gpi_integration.py")
text = path.read_text(encoding="utf-8")

replacements = [
    (
'''async def _fetch_bc_document_links(bc_document_no: str) -> list:
    """Fetch documentLinks from BC gpi/documents/v1.0 API for a given document number.
    Returns list of dicts. In DEMO_MODE returns empty list."""
''',
'''async def _fetch_bc_document_links(bc_entity: str, bc_document_no: str) -> list:
    """Fetch BC document links for one entity + document number.

    Document numbers are not globally unique across BC entities, so this read
    is intentionally type-bound and fails closed for unsupported entities.
    """
''',
        "BC link helper signature",
    ),
    (
'''        doc_link_api = "gpi/documents/v1.0"
        url = (f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/{doc_link_api}/"
               f"companies({company_id})/documentLinks"
               f"?$filter=bcDocumentNo eq '{bc_document_no}'")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            })
''',
'''        from services.document_link_visibility_service import build_bc_document_link_filter
        doc_link_api = "gpi/documents/v1.0"
        url = (f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/{doc_link_api}/"
               f"companies({company_id})/documentLinks")
        odata_filter = build_bc_document_link_filter(bc_entity, bc_document_no)

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            }, params={"$filter": odata_filter})
''',
        "BC OData type filter",
    ),
    (
'''    # 1) Query hub_documents for docs linked to this BC document
    hub_docs = await db.hub_documents.find(
        {
            "bc_document_no": bc_document_no,
            "sharepoint_web_url": {"$nin": [None, ""]},
            "$or": [{"deleted": {"$exists": False}}, {"deleted": False}],
        },
        {"_id": 0}
    ).sort("created_utc", -1).to_list(200)
''',
'''    # 1) Query hub_documents for docs proven to belong to this BC entity + number
    from services.document_link_visibility_service import build_hub_document_link_query
    hub_docs = await db.hub_documents.find(
        build_hub_document_link_query(bc_entity, bc_document_no),
        {"_id": 0}
    ).sort("created_utc", -1).to_list(200)
''',
        "Hub type-safe selector",
    ),
    (
'''    # 2) Query BC documentLinks API for this document number
    bc_links = await _fetch_bc_document_links(bc_document_no)
''',
'''    # 2) Query BC documentLinks API for this exact entity + document number
    bc_links = await _fetch_bc_document_links(bc_entity, bc_document_no)
''',
        "BC helper call",
    ),
    (
'''    # Try to find existing folder from hub_documents for this BC record
    existing = await db.hub_documents.find_one(
        {
            "bc_document_no": bc_document_no,
            "sharepoint_folder_path": {"$nin": [None, ""]},
        },
        {"sharepoint_folder_path": 1, "sharepoint_drive_id": 1, "_id": 0},
        sort=[("created_utc", -1)],
    )
''',
'''    # Try to find an existing folder from the same BC entity + record only.
    from services.document_link_visibility_service import build_folder_match_query
    existing = await db.hub_documents.find_one(
        build_folder_match_query(bc_entity, bc_document_no),
        {"sharepoint_folder_path": 1, "sharepoint_drive_id": 1, "_id": 0},
        sort=[("created_utc", -1)],
    )
''',
        "BC-drop folder selector",
    ),
]

for old, new, label in replacements:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 match, found {count}")
    text = text.replace(old, new, 1)

for needle in (
    "build_hub_document_link_query(bc_entity, bc_document_no)",
    "build_bc_document_link_filter(bc_entity, bc_document_no)",
    "_fetch_bc_document_links(bc_entity, bc_document_no)",
    "build_folder_match_query(bc_entity, bc_document_no)",
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: FactBox entity collision paths patched")
