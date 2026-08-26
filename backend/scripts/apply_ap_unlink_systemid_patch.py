"""One-time exact patch for AP FactBox unlink SystemId binding and CI guards."""

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

parity = Path(".github/workflows/square9-parity-gate.yml")
replace_once(
    parity,
    '            tests/test_document_link_visibility_service.py \\\n            tests/test_mailbox_provenance_service.py \\\n',
    '            tests/test_document_link_visibility_service.py \\\n            tests/test_document_link_systemid_visibility.py \\\n            tests/test_mailbox_provenance_service.py \\\n',
)
replace_once(
    parity,
    '''      - name: Guardrail - Gamer Documents lookup binds BC entity and number\n        run: |\n          grep -q 'build_hub_document_link_query(bc_entity, bc_document_no)' backend/routers/gpi_integration.py || {\n            echo "::error::Hub FactBox lookup is not bound to BC entity"\n            exit 1\n          }\n          grep -q '_fetch_bc_document_links(bc_entity, bc_document_no)' backend/routers/gpi_integration.py || {\n            echo "::error::BC documentLinks lookup is not bound to BC entity"\n            exit 1\n          }\n          grep -q 'build_folder_match_query(bc_entity, bc_document_no)' backend/routers/gpi_integration.py || {\n            echo "::error::BC-drop folder reuse is not bound to BC entity"\n            exit 1\n          }\n          grep -q 'build_bc_identity_clause(bc_entity)' backend/routers/gpi_integration.py || {\n            echo "::error::Document unlink is not bound to BC entity"\n            exit 1\n          }\n''',
    '''      - name: Guardrail - Gamer Documents lookup and unlink bind exact BC identity\n        run: |\n          grep -q 'build_hub_document_link_query(bc_entity, bc_document_no, bc_system_id)' backend/routers/gpi_integration.py || {\n            echo "::error::Hub FactBox lookup does not carry BC SystemId"\n            exit 1\n          }\n          grep -q 'bc_entity, bc_document_no, bc_system_id' backend/routers/gpi_integration.py || {\n            echo "::error::BC documentLinks lookup does not carry BC SystemId"\n            exit 1\n          }\n          grep -q 'build_folder_match_query(bc_entity, bc_document_no, bc_system_id)' backend/routers/gpi_integration.py || {\n            echo "::error::BC-drop folder reuse does not carry BC SystemId"\n            exit 1\n          }\n          grep -q 'build_hub_document_unlink_query' backend/routers/gpi_integration.py || {\n            echo "::error::Document unlink does not use exact-record selector"\n            exit 1\n          }\n          grep -q 'doc_id_or_sp_item, bc_system_id' backend/routers/gpi_integration.py || {\n            echo "::error::Document unlink drops BC SystemId"\n            exit 1\n          }\n''',
)

factbox = Path(".github/workflows/square9-ap-factbox-systemid-gate.yml")
replace_once(
    factbox,
    '''          grep -q 'build_folder_match_query(bc_entity, bc_document_no, bc_system_id)' backend/routers/gpi_integration.py || {\n            echo "::error::BC Drop folder reuse is not bound to resolved BC SystemId"\n            exit 1\n          }\n''',
    '''          grep -q 'build_folder_match_query(bc_entity, bc_document_no, bc_system_id)' backend/routers/gpi_integration.py || {\n            echo "::error::BC Drop folder reuse is not bound to resolved BC SystemId"\n            exit 1\n          }\n          grep -q 'build_hub_document_unlink_query' backend/routers/gpi_integration.py || {\n            echo "::error::FactBox delete is not bound to the exact BC record"\n            exit 1\n          }\n          grep -q 'IDENTITY_QUERY' backend/routers/gpi_integration.py || {\n            echo "::error::FactBox browser delete drops BC SystemId"\n            exit 1\n          }\n''',
)

print("PASS: AP unlink SystemId patch applied")
