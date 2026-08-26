"""One-time exact patch: thread immutable BC SystemId through FactBox reads and folder reuse."""

from pathlib import Path

path = Path("backend/routers/gpi_integration.py")
text = path.read_text(encoding="utf-8")

repls = []

repls.append((
'''@router.get("/factbox-ui/{bc_entity}/{bc_document_no}", response_class=HTMLResponse)\nasync def factbox_ui(bc_entity: str, bc_document_no: str, request: Request):\n''',
'''@router.get("/factbox-ui/{bc_entity}/{bc_document_no}", response_class=HTMLResponse)\nasync def factbox_ui(\n    bc_entity: str,\n    bc_document_no: str,\n    request: Request,\n    bc_system_id: str = "",\n):\n'''))

repls.append((
'''    # Use relative API path so JS works from any origin\n    api_path = f"/api/gpi-integration/document-links/{bc_entity}/{bc_document_no}"\n\n    html = f"""<!DOCTYPE html>\n''',
'''    # Use a relative base path so JS works from any origin. The exact BC\n    # SystemId is attached only to list reads; upload independently resolves\n    # record identity server-side before creating any SharePoint artifact.\n    api_path = f"/api/gpi-integration/document-links/{bc_entity}/{bc_document_no}"\n    identity_query = f"?bc_system_id={bc_system_id}" if bc_system_id else ""\n\n    html = f"""<!DOCTYPE html>\n'''))

repls.append((
'''  const API = "{api_path}";\n  const listWrap = document.getElementById("docListWrap");\n''',
'''  const API = "{api_path}";\n  const LIST_API = API + "{identity_query}";\n  const listWrap = document.getElementById("docListWrap");\n'''))

repls.append((
'''      const resp = await fetch(API);\n''',
'''      const resp = await fetch(LIST_API);\n'''))

repls.append((
'''async def _fetch_bc_document_links(bc_entity: str, bc_document_no: str) -> list:\n    """Fetch BC document links for one entity + document number.\n''',
'''async def _fetch_bc_document_links(\n    bc_entity: str,\n    bc_document_no: str,\n    bc_system_id: str = "",\n) -> list:\n    """Fetch BC document links for one entity + document number + optional SystemId.\n'''))

repls.append((
'''        odata_filter = build_bc_document_link_filter(bc_entity, bc_document_no)\n''',
'''        odata_filter = build_bc_document_link_filter(\n            bc_entity, bc_document_no, bc_system_id\n        )\n'''))

repls.append((
'''@router.get("/document-links/{bc_entity}/{bc_document_no}")\nasync def get_document_links(bc_entity: str, bc_document_no: str):\n''',
'''@router.get("/document-links/{bc_entity}/{bc_document_no}")\nasync def get_document_links(\n    bc_entity: str,\n    bc_document_no: str,\n    bc_system_id: str = "",\n):\n'''))

repls.append((
'''        build_hub_document_link_query(bc_entity, bc_document_no),\n''',
'''        build_hub_document_link_query(bc_entity, bc_document_no, bc_system_id),\n'''))

repls.append((
'''    bc_links = await _fetch_bc_document_links(bc_entity, bc_document_no)\n''',
'''    bc_links = await _fetch_bc_document_links(\n        bc_entity, bc_document_no, bc_system_id\n    )\n'''))

repls.append((
'''        "bc_document_no": bc_document_no,\n        "documents": results,\n''',
'''        "bc_document_no": bc_document_no,\n        "bc_system_id": bc_system_id,\n        "documents": results,\n'''))

repls.append((
'''        build_folder_match_query(bc_entity, bc_document_no),\n''',
'''        build_folder_match_query(bc_entity, bc_document_no, bc_system_id),\n'''))

for old, new in repls:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one route patch anchor, found {count}: {old[:100]!r}")
    text = text.replace(old, new, 1)

for needle in (
    'bc_system_id: str = ""',
    'const LIST_API = API + "{identity_query}";',
    'fetch(LIST_API)',
    'build_hub_document_link_query(bc_entity, bc_document_no, bc_system_id)',
    'build_bc_document_link_filter(\n            bc_entity, bc_document_no, bc_system_id',
    'build_folder_match_query(bc_entity, bc_document_no, bc_system_id)',
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: FactBox SystemId route patch applied")

# Explicit retrigger after the write-capable workflow exists.
