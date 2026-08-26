"""One-time exact patch: sync SharePoint metadata after BC draft Purchase Invoice identity promotion."""

from pathlib import Path

path = Path("backend/routers/gpi_integration.py")
text = path.read_text(encoding="utf-8")

old = '''    pi_writeback = {\n        "bc_purchase_invoice": bc_purchase_invoice,\n        "bc_purchase_invoice_no": result.get("bc_record_no", ""),\n        "updated_utc": now,\n    }\n    if result.get("success") and result.get("bc_record_no"):\n        from services.ap_purchase_invoice_identity_service import (\n            build_ap_purchase_invoice_identity_update,\n        )\n        pi_writeback.update(\n            build_ap_purchase_invoice_identity_update(\n                result.get("bc_record_no", ""),\n                result.get("bc_system_id", ""),\n                posted=False,\n            )\n        )\n    await db.hub_documents.update_one(\n        {"id": doc_id},\n        {"$set": pi_writeback}\n    )\n\n    # Emit event\n'''
new = '''    pi_writeback = {\n        "bc_purchase_invoice": bc_purchase_invoice,\n        "bc_purchase_invoice_no": result.get("bc_record_no", ""),\n        "updated_utc": now,\n    }\n    draft_identity = None\n    if result.get("success") and result.get("bc_record_no"):\n        from services.ap_purchase_invoice_identity_service import (\n            build_ap_purchase_invoice_identity_update,\n        )\n        draft_identity = build_ap_purchase_invoice_identity_update(\n            result.get("bc_record_no", ""),\n            result.get("bc_system_id", ""),\n            posted=False,\n        )\n        pi_writeback.update(draft_identity)\n    await db.hub_documents.update_one(\n        {"id": doc_id},\n        {"$set": pi_writeback}\n    )\n\n    # A BC draft is not a complete parity transition until the already-uploaded\n    # SharePoint item carries the same Purchase Invoice identity. Patch metadata\n    # only after preserving the BC draft/SystemId in Mongo so a Graph failure can\n    # never cause a later retry to create a second draft.\n    if draft_identity:\n        from services.sharepoint_parity_resync_service import (\n            resync_existing_sharepoint_parity_metadata,\n        )\n        try:\n            await resync_existing_sharepoint_parity_metadata(\n                doc_id, db, identity_update=draft_identity\n            )\n            result["metadata_synced"] = True\n            result["metadata_pending"] = False\n        except Exception as metadata_exc:\n            metadata_error = str(metadata_exc)\n            blocked_identity = dict(draft_identity)\n            blocked_identity.update({\n                "GPI_Status": "DraftNeedsMetadata",\n                "ImportReady": False,\n                "import_ready": False,\n                "delivery_status": "DraftNeedsMetadata",\n            })\n            await db.hub_documents.update_one(\n                {"id": doc_id},\n                {"$set": {\n                    **blocked_identity,\n                    "status": "DraftNeedsMetadata",\n                    "workflow_status": "draft_needs_metadata",\n                    "sharepoint_metadata_error": metadata_error,\n                    "draft_metadata_pending_since": datetime.now(timezone.utc).isoformat(),\n                    "updated_utc": datetime.now(timezone.utc).isoformat(),\n                }}\n            )\n            # BC draft creation remains a success. Surface a distinct recoverable\n            # metadata state so no caller interprets this as permission to create\n            # another Purchase Invoice.\n            result["metadata_synced"] = False\n            result["metadata_pending"] = True\n            result["metadata_error"] = metadata_error\n            result["document_status"] = "DraftNeedsMetadata"\n            logger.error(\n                "[GPI Integration] Draft PI %s created/reused but SharePoint metadata sync failed for %s: %s",\n                result.get("bc_record_no", "?"), doc_id[:8], metadata_error\n            )\n\n    # Emit event\n'''

if text.count(old) != 1:
    raise SystemExit(f"draft PI writeback anchor: expected 1 match, found {text.count(old)}")
text = text.replace(old, new, 1)

for needle in (
    "draft_identity = build_ap_purchase_invoice_identity_update(",
    "resync_existing_sharepoint_parity_metadata(",
    '"status": "DraftNeedsMetadata"',
    'result["metadata_pending"] = True',
    '"ImportReady": False',
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: AP draft metadata completion patch applied")
