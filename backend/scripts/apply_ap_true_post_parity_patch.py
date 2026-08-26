"""One-time exact patch for AP true-post semantics and FactBox identity handoff."""

from pathlib import Path

router_path = Path("backend/routers/gpi_integration.py")
router = router_path.read_text(encoding="utf-8")

old_router_writeback = '''    await db.hub_documents.update_one(\n        {"id": doc_id},\n        {"$set": {\n            "bc_purchase_invoice": bc_purchase_invoice,\n            "bc_purchase_invoice_no": result.get("bc_record_no", ""),\n            "updated_utc": now,\n        }}\n    )\n'''
new_router_writeback = '''    pi_writeback = {\n        "bc_purchase_invoice": bc_purchase_invoice,\n        "bc_purchase_invoice_no": result.get("bc_record_no", ""),\n        "updated_utc": now,\n    }\n    if result.get("success") and result.get("bc_record_no"):\n        from services.ap_purchase_invoice_identity_service import (\n            build_ap_purchase_invoice_identity_update,\n        )\n        pi_writeback.update(\n            build_ap_purchase_invoice_identity_update(\n                result.get("bc_record_no", ""),\n                result.get("bc_system_id", ""),\n                posted=False,\n            )\n        )\n    await db.hub_documents.update_one(\n        {"id": doc_id},\n        {"$set": pi_writeback}\n    )\n'''
if router.count(old_router_writeback) != 1:
    raise SystemExit(f"router PI writeback: expected 1 match, found {router.count(old_router_writeback)}")
router = router.replace(old_router_writeback, new_router_writeback, 1)
router_path.write_text(router, encoding="utf-8")

ap_path = Path("backend/services/ap_auto_post_service.py")
ap = ap_path.read_text(encoding="utf-8")

old_success_head = '''        if result.get("success") or result.get("already_exists"):\n            now = datetime.now(timezone.utc).isoformat()\n            bc_record_no = result.get("bc_record_no", "")\n            attempt = build_attempt(\n'''
new_success_head = '''        if result.get("success") or result.get("already_exists"):\n            bc_record_no = result.get("bc_record_no", "")\n            bc_system_id = result.get("bc_system_id", "")\n            if not bc_system_id:\n                raise ValueError(\n                    f"BC Purchase Invoice {bc_record_no or '?'} was created/reused without a SystemId; cannot post safely"\n                )\n\n            # Creating a purchaseInvoices resource only creates/reuses the BC\n            # invoice document. The explicit bound action is the proof that BC\n            # actually posted it. A retry reuses the existing draft above and\n            # calls this action again; it never creates a duplicate invoice.\n            from services.bc_purchase_invoice_posting_service import (\n                post_purchase_invoice_system_id,\n            )\n            post_result = await post_purchase_invoice_system_id(bc_system_id)\n            if not post_result.get("posted"):\n                raise RuntimeError(\n                    f"BC Purchase Invoice {bc_record_no or '?'} was not confirmed posted"\n                )\n\n            from services.ap_purchase_invoice_identity_service import (\n                build_ap_purchase_invoice_identity_update,\n            )\n            posted_identity = build_ap_purchase_invoice_identity_update(\n                bc_record_no, bc_system_id, posted=True\n            )\n            now = datetime.now(timezone.utc).isoformat()\n            attempt = build_attempt(\n'''
if ap.count(old_success_head) != 1:
    raise SystemExit(f"AP success head: expected 1 match, found {ap.count(old_success_head)}")
ap = ap.replace(old_success_head, new_success_head, 1)

old_attempt_id = '''                bc_record_no=bc_record_no,\n                bc_document_id=result.get("bc_system_id", ""),\n            )\n            await record_standalone_attempt(db, doc_id, attempt, also_set={\n'''
new_attempt_id = '''                bc_record_no=bc_record_no,\n                bc_document_id=bc_system_id,\n            )\n            await record_standalone_attempt(db, doc_id, attempt, also_set={\n'''
if ap.count(old_attempt_id) != 1:
    raise SystemExit(f"AP attempt identity: expected 1 match, found {ap.count(old_attempt_id)}")
ap = ap.replace(old_attempt_id, new_attempt_id, 1)

old_also_set_tail = '''                "bc_purchase_invoice_no": bc_record_no,\n                "bc_system_id": result.get("bc_system_id", ""),\n                "posted_to_bc_at": now,\n                "bc_posting_error": None,\n            })\n'''
new_also_set_tail = '''                "bc_purchase_invoice_no": bc_record_no,\n                "bc_system_id": bc_system_id,\n                "posted_to_bc_at": now,\n                "bc_posting_error": None,\n                "bc_true_post_confirmed": True,\n                "bc_true_post_http_status": post_result.get("http_status"),\n                **posted_identity,\n            })\n'''
if ap.count(old_also_set_tail) != 1:
    raise SystemExit(f"AP posted writeback: expected 1 match, found {ap.count(old_also_set_tail)}")
ap = ap.replace(old_also_set_tail, new_also_set_tail, 1)

ap = ap.replace('''                "bc_record_no": result.get("bc_record_no"),\n                "bc_system_id": result.get("bc_system_id"),\n''', '''                "bc_record_no": bc_record_no,\n                "bc_system_id": bc_system_id,\n''', 1)

for needle in (
    "post_purchase_invoice_system_id(bc_system_id)",
    "bc_true_post_confirmed",
    "**posted_identity",
):
    if needle not in ap:
        raise SystemExit(f"AP post-patch verification missing: {needle}")

ap_path.write_text(ap, encoding="utf-8")
print("PASS: AP true-post + Purchase Invoice identity patch applied")

# Triggered after workflow creation so GitHub evaluates this exact patch.
