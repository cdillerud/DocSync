import asyncio
import base64
import os
import sys
sys.path.insert(0, '.')

import httpx

TEST_HOSTNAME = "gamerpackaging1.sharepoint.com"
TEST_PATH = "/sites/GPI-DocumentHub-Test"

# Maps the human-readable Folder tag values (as typed by Accounting) to the
# canonical folder path strings folder_routing_service.py actually uses
# TODAY (post the 2026-07-09 fix removing the "Documents" suffix). This
# matters a lot: route_with_feedback() uses whatever string is stored here
# VERBATIM as the final routing destination, with zero reformatting.
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
    from services.document_intel_helpers import _call_llm_for_extraction
    from services.routing_feedback_service import init_feedback_db, record_correction, lookup_feedback
    from motor.motor_asyncio import AsyncIOMotorClient

    token = await _get_graph_token()
    tags = await fetch_folder_tags(token)
    print(f"Found {len(tags)} tagged documents in the test site.")
    print()

    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    init_feedback_db(db)

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

        content = base64.b64decode(doc["file_content_b64"])
        tmp_path = f"/tmp/ingest2_{doc['id']}.pdf"
        with open(tmp_path, "wb") as f:
            f.write(content)
        extraction = await _call_llm_for_extraction(tmp_path, file_name)
        extracted_fields = extraction.get("extracted_fields", {})
        vendor = (extracted_fields.get("vendor") or "").strip()
        doc_type = extraction.get("suggested_job_type") or "Unknown"

        if not vendor:
            print(f"  SKIP (no vendor extracted): {file_name}")
            skipped_no_vendor += 1
            continue

        po = (extracted_fields.get("po_number") or extracted_fields.get("order_number") or "").strip()
        has_po = bool(po)
        is_international = bool(extracted_fields.get("is_international", False))

        result = await record_correction(
            vendor=vendor,
            doc_type=doc_type,
            has_po=has_po,
            is_international=is_international,
            correct_folder=canonical_folder,
            file_name=file_name,
            source="meghan_manual_review",
        )
        print(f"  {result['status'].upper()}: {file_name} :: vendor={vendor!r} doc_type={doc_type!r} "
              f"has_po={has_po} intl={is_international} -> {canonical_folder!r}")
        recorded += 1

    print()
    print("=== SUMMARY ===")
    print(f"Recorded: {recorded}")
    print(f"Skipped (unrecognized tag): {skipped_unknown_tag}")
    print(f"Skipped (not found in Hub): {skipped_no_doc}")
    print(f"Skipped (no vendor extracted): {skipped_no_vendor}")

    print()
    print("=== Verifying: rules now live in the real feedback system ===")
    all_rules = await db["routing_feedback"].find({"source": "meghan_manual_review"}).to_list(50)
    print(f"Rules with source=meghan_manual_review: {len(all_rules)}")
    for r in all_rules:
        print(f"  {r['routing_key']} -> {r['correct_folder']} (confidence={r['confidence']})")


asyncio.run(main())
