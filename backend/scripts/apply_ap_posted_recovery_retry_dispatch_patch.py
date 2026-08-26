"""One-time exact patch: intercept AP post-success recovery states before generic retry."""

from pathlib import Path

path = Path("backend/services/document_retry_service.py")
text = path.read_text(encoding="utf-8")

old = '''    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})\n    if not doc:\n        raise HTTPException(status_code=404, detail="Document not found")\n\n    if not should_retry(doc):\n'''
new = '''    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})\n    if not doc:\n        raise HTTPException(status_code=404, detail="Document not found")\n\n    # AP post-success recovery states must be intercepted before ordinary retry\n    # bookkeeping. BC is already posted in both states, so generic retry must\n    # never rewrite them to Retrying, refresh PO identity, repost, or reupload.\n    from services.ap_posted_recovery_dispatch_service import (\n        dispatch_ap_posted_recovery_if_needed,\n    )\n    posted_recovery = await dispatch_ap_posted_recovery_if_needed(doc_id, db, doc)\n    if posted_recovery is not None:\n        return posted_recovery\n\n    if not should_retry(doc):\n'''

if text.count(old) != 1:
    raise SystemExit(f"retry dispatch anchor: expected 1 match, found {text.count(old)}")
text = text.replace(old, new, 1)

needles = (
    "dispatch_ap_posted_recovery_if_needed(doc_id, db, doc)",
    "if posted_recovery is not None:",
    "return posted_recovery",
)
for needle in needles:
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

if text.index("dispatch_ap_posted_recovery_if_needed(doc_id, db, doc)") > text.index("if not should_retry(doc):"):
    raise SystemExit("AP posted recovery dispatch must precede should_retry")
if text.index("dispatch_ap_posted_recovery_if_needed(doc_id, db, doc)") > text.index('"status": "Retrying"'):
    raise SystemExit("AP posted recovery dispatch must precede Retrying state write")

path.write_text(text, encoding="utf-8")
print("PASS: AP post-success retry dispatch patch applied")
