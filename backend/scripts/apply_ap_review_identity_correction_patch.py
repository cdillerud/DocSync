"""One-time exact patch for fail-closed AP identity corrections."""

from pathlib import Path

path = Path("backend/routers/ap_review.py")
text = path.read_text(encoding="utf-8")

old = '''    # Update document\n    await db.hub_documents.update_one(\n        {"id": doc_id},\n        {"$set": update_data}\n    )\n'''
new = '''    # Material vendor/PO corrections invalidate any previously derived BC\n    # identity/readiness. Preserve the prior identity in append-only audit.\n    identity_change = {"changed": False, "set": {}, "audit": None}\n    try:\n        from services.operator_identity_correction_service import (\n            build_identity_invalidation,\n        )\n        identity_change = build_identity_invalidation(\n            doc,\n            vendor_id=data.vendor_id,\n            po_number=data.po_number,\n        )\n    except ValueError as e:\n        raise HTTPException(status_code=409, detail=str(e))\n\n    if identity_change["changed"]:\n        update_data.update(identity_change["set"])\n\n    mongo_update = {"$set": update_data}\n    if identity_change["changed"]:\n        mongo_update["$push"] = {\n            "identity_correction_history": identity_change["audit"]\n        }\n\n    # Update corrected evidence + invalidated identity atomically.\n    await db.hub_documents.update_one(\n        {"id": doc_id},\n        mongo_update\n    )\n'''
count = text.count(old)
if count != 1:
    raise SystemExit(f"AP review update block: expected 1 match, found {count}")
text = text.replace(old, new, 1)

for needle in (
    "build_identity_invalidation(",
    'identity_change["changed"]',
    '"identity_correction_history": identity_change["audit"]',
    "raise HTTPException(status_code=409, detail=str(e))",
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: AP review identity correction patch applied")
