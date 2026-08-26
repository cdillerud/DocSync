"""One-time exact patch to preserve parent mailbox provenance on split children."""
# Triggered only after the workflow existed on the branch.
from pathlib import Path

path = Path("backend/services/batch_po_splitter.py")
text = path.read_text(encoding="utf-8")

old_projection = '''            "customer_canonical": 1,\n            "customer_id": 1,\n            "mailbox_category": 1,\n'''
new_projection = '''            "customer_canonical": 1,\n            "customer_id": 1,\n            "mailbox_category": 1,\n            "source_mailbox_address": 1,\n            "source_mailbox_id": 1,\n            "source_mailbox_category": 1,\n            "source_graph_message_id": 1,\n            "source_internet_message_id": 1,\n            "source_attachment_id": 1,\n'''
if text.count(old_projection) != 1:
    raise SystemExit(f"parent projection anchor count={text.count(old_projection)}")
text = text.replace(old_projection, new_projection, 1)

anchor = '''            await _record_child_parent_link(\n                db=db,\n                child_doc_id=child_doc_id,\n                parent_doc_id=parent_doc_id,\n                parent_filename=parent_filename,\n                pages=pages,\n                total_pages=total_pages,\n                split_mode=split_mode,\n                group_num=unit_index + 1,\n                reused_existing=reused_existing,\n            )\n\n            if not reused_existing:\n'''
replacement = '''            await _record_child_parent_link(\n                db=db,\n                child_doc_id=child_doc_id,\n                parent_doc_id=parent_doc_id,\n                parent_filename=parent_filename,\n                pages=pages,\n                total_pages=total_pages,\n                split_mode=split_mode,\n                group_num=unit_index + 1,\n                reused_existing=reused_existing,\n            )\n\n            # Preserve the exact receiving mailbox/message provenance through the\n            # split boundary. New children inherit the parent as first-seen source;\n            # reused canonical children only append this parent observation.\n            if (\n                parent_doc.get("source_mailbox_address")\n                or parent_doc.get("source_mailbox_id")\n                or parent_doc.get("source_graph_message_id")\n                or parent_doc.get("source_internet_message_id")\n            ):\n                from services.mailbox_provenance_service import persist_mailbox_provenance\n\n                await persist_mailbox_provenance(\n                    db,\n                    child_doc_id,\n                    mailbox_address=parent_doc.get("source_mailbox_address"),\n                    mailbox_id=parent_doc.get("source_mailbox_id"),\n                    mailbox_category=(\n                        parent_doc.get("source_mailbox_category")\n                        or parent_doc.get("mailbox_category")\n                    ),\n                    graph_message_id=parent_doc.get("source_graph_message_id"),\n                    internet_message_id=parent_doc.get("source_internet_message_id"),\n                    attachment_id=parent_doc.get("source_attachment_id"),\n                    source="batch_split_parent",\n                    set_first_seen=not reused_existing,\n                )\n\n            if not reused_existing:\n'''
if text.count(anchor) != 1:
    raise SystemExit(f"child link anchor count={text.count(anchor)}")
text = text.replace(anchor, replacement, 1)

required = (
    '"source_mailbox_address": 1',
    'persist_mailbox_provenance(',
    'source="batch_split_parent"',
    'set_first_seen=not reused_existing',
)
for token in required:
    if token not in text:
        raise SystemExit(f"missing post-patch token: {token}")

path.write_text(text, encoding="utf-8")
print("PASS: split mailbox provenance patch applied")
