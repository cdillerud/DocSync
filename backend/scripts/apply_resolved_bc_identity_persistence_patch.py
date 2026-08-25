"""One-time exact patch: promote exact PO/shipment identity to top-level Hub fields."""

from pathlib import Path

path = Path("backend/services/document_bytes_intake_service.py")
text = path.read_text(encoding="utf-8")

old_import = '''        from services.po_resolution_service import resolve_po_from_document, attempt_bc_link\n'''
new_import = '''        from services.po_resolution_service import resolve_po_from_document, attempt_bc_link\n        from services.resolved_bc_identity_persistence_service import build_resolved_bc_identity_update\n'''
if text.count(old_import) != 1:
    raise SystemExit(f"PO resolution import: expected 1 match, found {text.count(old_import)}")
text = text.replace(old_import, new_import, 1)

old_update = '''            po_result["bc_link"] = bc_link_result\n            await db.hub_documents.update_one(\n                {"id": doc_id},\n                {"$set": {\n                    "po_resolution": po_result,\n                    "po_candidates": po_result.get("candidates_raw", []),\n                }}\n            )\n'''
new_update = '''            po_result["bc_link"] = bc_link_result\n            po_persist_update = {\n                "po_resolution": po_result,\n                "po_candidates": po_result.get("candidates_raw", []),\n            }\n            # The FactBox visibility contract queries durable top-level BC\n            # identity, not only nested resolution audit evidence. Promote only\n            # exact, SystemId-bearing PO/shipment matches; ambiguous/not-found\n            # and local-staging results remain fail-closed.\n            po_persist_update.update(build_resolved_bc_identity_update(po_result))\n            await db.hub_documents.update_one(\n                {"id": doc_id},\n                {"$set": po_persist_update}\n            )\n'''
if text.count(old_update) != 1:
    raise SystemExit(f"PO resolution persistence block: expected 1 match, found {text.count(old_update)}")
text = text.replace(old_update, new_update, 1)

for needle in (
    "build_resolved_bc_identity_update",
    "po_persist_update.update(build_resolved_bc_identity_update(po_result))",
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: resolved BC identity persistence patch applied")

# trigger: workflow exists on branch
