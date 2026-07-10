import asyncio
import base64
import os
import sys
sys.path.insert(0, '.')

import httpx

TEST_HOSTNAME = "gamerpackaging1.sharepoint.com"
TEST_PATH = "/sites/GPI-DocumentHub-Test"

# Maps the human-readable Folder tag values (as typed by Accounting) to the
# canonical folder path strings Hub's own routing logic actually uses.
FOLDER_TAG_TO_CANONICAL = {
    "DS NOT International": "Dropship Not International",
    "DS International": "Dropship International",
    "DS Internanational": "Dropship International",  # observed typo variant
    "WH NOT International": "Warehouse Not International",
    "WH International": "Warehouse International",
    "Vendor Credit memo": "Vendor Credit Memos",
    "Vendor Credit Memo": "Vendor Credit Memos",
}


async def fetch_folder_tags(token: str) -> list:
    async with httpx.AsyncClient(timeout=30.0) as c:
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{TEST_HOSTNAME}:{TEST_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        site_id = site_resp.json()["id"]

        lists_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists",
            headers={"Authorization": f"Bearer {token}"})
        lists = lists_resp.json().get("value", [])
        doc_list = next(
            (l for l in lists if l.get("list", {}).get("template") == "documentLibrary"
             and l.get("displayName") == "Documents"),
            None,
        )
        list_id = doc_list["id"]

        all_items = []
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items?expand=fields&$top=200"
        while url:
            resp = await c.get(url, headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
            all_items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

        return [
            (i["fields"]["FileLeafRef"], i["fields"]["Folder"])
            for i in all_items
            if i.get("fields", {}).get("Folder")
        ]


async def main():
    from services.sharepoint_service import _get_graph_token
    from services.folder_routing_service import route_with_feedback
    from services.document_intel_helpers import _call_llm_for_extraction
    from services.feedback_loop_service import record_feedback
    from motor.motor_asyncio import AsyncIOMotorClient

    token = await _get_graph_token()
    tags = await fetch_folder_tags(token)
    print(f"Found {len(tags)} tagged documents in the test site.")
    print()

    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]

    recorded = 0
    skipped_no_doc = 0
    skipped_unknown_tag = 0
    skipped_no_vendor = 0

    for file_name, raw_tag in tags:
        canonical_folder = FOLDER_TAG_TO_CANONICAL.get(raw_tag)
        if not canonical_folder:
            print(f"  SKIP (unrecognized tag {raw_tag!r}): {file_name}")
            skipped_unknown_tag += 1
            continue

        doc = await db.hub_documents.find_one({"file_name": file_name})
        if not doc or not doc.get("file_content_b64"):
            print(f"  SKIP (not found in Hub / no content): {file_name}")
            skipped_no_doc += 1
            continue

        # Fresh extraction, since most of these were processed during the
        # model-retirement outage and likely have stale/empty stored fields.
        content = base64.b64decode(doc["file_content_b64"])
        tmp_path = f"/tmp/ingest_{doc['id']}.pdf"
        with open(tmp_path, "wb") as f:
            f.write(content)
        extraction = await _call_llm_for_extraction(tmp_path, file_name)
        extracted_fields = extraction.get("extracted_fields", {})
        vendor_id = (extracted_fields.get("vendor") or "").strip()

        if not vendor_id:
            print(f"  SKIP (no vendor extracted): {file_name}")
            skipped_no_vendor += 1
            continue

        # What Hub's CURRENT rule-based logic would compute, for comparison
        doc_for_routing = dict(doc)
        doc_for_routing["extracted_fields"] = extracted_fields
        original_path, reason, details = await route_with_feedback(
            doc_for_routing,
            freight_direction=extracted_fields.get("freight_direction"),
            is_international=extracted_fields.get("is_international", False),
        )
        original_folder = (original_path or "").split("/")[0]

        await record_feedback(
            db,
            event_type="folder_correction",
            document_id=doc["id"],
            vendor_id=vendor_id,
            before={"folder": original_folder},
            after={"folder": canonical_folder},
            source="bulk_review",
            user_id="meghan_folder_tags",
            metadata={"file_name": file_name, "raw_tag": raw_tag, "extracted_fields": extracted_fields},
        )
        match_note = "(already agreed)" if original_folder == canonical_folder else "(real correction)"
        print(f"  RECORDED: {file_name} :: vendor={vendor_id!r} :: {original_folder!r} -> {canonical_folder!r} {match_note}")
        recorded += 1

    print()
    print("=== SUMMARY ===")
    print(f"Recorded: {recorded}")
    print(f"Skipped (unrecognized tag): {skipped_unknown_tag}")
    print(f"Skipped (not found in Hub): {skipped_no_doc}")
    print(f"Skipped (no vendor extracted): {skipped_no_vendor}")


asyncio.run(main())
