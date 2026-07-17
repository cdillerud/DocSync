"""
backfill_xml_invoice_extraction.py — re-runs invoice extraction for
existing hub_documents whose file is an XML e-invoice that was
processed before the CFDI parser fix landed (2026-07-17), and so still
has no invoice_number_clean/amount_float in Mongo.

Why this exists: extract_invoice_data() silently skipped every .xml
file for as long as the pipeline has existed - .xml was never in its
supported-extension list. The fix (_try_extract_cfdi_invoice) only
helps documents processed FROM NOW ON; it does nothing for the 42
XML documents already sitting in hub_documents with incomplete
extraction. This script closes that gap for the existing backlog.

Deliberately narrow in scope: only backfills invoice_number_clean and
amount_float (via compute_ap_normalized_fields - the exact function
the live pipeline itself uses, imported directly rather than
reimplemented, so the normalization logic - comma/whitespace
stripping, uppercasing, amount cleaning - is guaranteed identical to
what a freshly-processed document would get). Deliberately does NOT
touch vendor_canonical: that field goes through a separate, multi-step
process in the real pipeline (sender-email lookup, text-based vendor
alias lookup, an LLM vendor-ranking gate) that this script does not
attempt to replicate - partially reimplementing that safely would need
much more care than a single-session fix, and getting it wrong risks
silently mis-attributing a vendor, which is worse than leaving the
field as-is for a human/the normal reprocess path to resolve.

Dry-run by default, matching every other data-modifying script from
tonight's session - requires explicit --confirm to write to Mongo.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import tempfile
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def find_candidates(db) -> List[Dict[str, Any]]:
    cursor = db.hub_documents.find(
        {
            "file_name": {"$regex": r"\.xml$", "$options": "i"},
            "$or": [
                {"invoice_number_clean": {"$in": [None, ""]}},
                {"invoice_number_clean": {"$exists": False}},
            ],
        },
        {"_id": 0, "id": 1, "file_name": 1, "sharepoint_web_url": 1,
         "extracted_fields": 1},
    )
    return await cursor.to_list(length=None)


async def download_via_share_url(client, token: str, share_url: str) -> Optional[bytes]:
    """Resolves a SharePoint web URL to its driveItem via the Graph
    shares API and downloads the raw content. Returns None on any
    failure - a single document's download problem should not abort
    the whole backfill run."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        encoded = base64.urlsafe_b64encode(share_url.encode()).decode().rstrip("=")
        r = await client.get(
            f"https://graph.microsoft.com/v1.0/shares/u!{encoded}/driveItem",
            headers=headers,
        )
        if r.status_code != 200:
            return None
        download_url = r.json().get("@microsoft.graph.downloadUrl")
        if not download_url:
            return None
        content_resp = await client.get(download_url)
        if content_resp.status_code != 200:
            return None
        return content_resp.content
    except Exception:
        return None


async def run(confirm: bool) -> Dict[str, Any]:
    import httpx
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.config_service import get_graph_token
    from services.invoice_extractor import extract_invoice_data
    from services.document_intel_helpers import compute_ap_normalized_fields

    client_db = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client_db[os.environ["DB_NAME"]]

    candidates = await find_candidates(db)
    token = await get_graph_token()

    results = {
        "total_candidates": len(candidates),
        "downloaded": 0,
        "download_failed": 0,
        "extracted": 0,
        "extraction_failed": 0,
        "updated": 0,
        "confirm": confirm,
        "details": [],
    }

    async with httpx.AsyncClient(timeout=30.0) as http_client:
        for doc in candidates:
            file_name = doc.get("file_name", "")
            web_url = doc.get("sharepoint_web_url", "")
            entry = {"file_name": file_name, "status": None}

            if not web_url:
                entry["status"] = "no_sharepoint_url"
                results["details"].append(entry)
                continue

            content = await download_via_share_url(http_client, token, web_url)
            if content is None:
                results["download_failed"] += 1
                entry["status"] = "download_failed"
                results["details"].append(entry)
                continue
            results["downloaded"] += 1

            with tempfile.NamedTemporaryFile(suffix=".xml", delete=False) as f:
                f.write(content)
                tmp_path = f.name

            try:
                extraction = await extract_invoice_data(tmp_path)
            finally:
                os.unlink(tmp_path)

            if not extraction.success:
                results["extraction_failed"] += 1
                entry["status"] = "extraction_failed"
                entry["error"] = extraction.error
                results["details"].append(entry)
                continue
            results["extracted"] += 1

            # Map InvoiceExtractionResult's field names onto the shape
            # compute_ap_normalized_fields() and the rest of the
            # pipeline actually expect in Mongo (vendor/invoice_number/
            # amount, not vendor_name/invoice_number/total_amount) -
            # confirmed directly by reading a real, already-processed
            # document's stored extracted_fields before writing this.
            mapped_fields = {
                "vendor": extraction.vendor_name,
                "invoice_number": extraction.invoice_number,
                "amount": extraction.total_amount,
                "invoice_date": extraction.invoice_date,
                "po_number": extraction.po_number,
                "line_items": extraction.line_items,
            }
            normalized = compute_ap_normalized_fields(mapped_fields)

            entry["status"] = "would_update" if not confirm else "updated"
            entry["invoice_number_clean"] = normalized.get("invoice_number_clean")
            entry["amount_float"] = normalized.get("amount_float")
            entry["vendor_raw"] = normalized.get("vendor_raw")

            if confirm:
                # Merge into existing extracted_fields (preserves
                # _po_all_candidates and anything else already there)
                # rather than overwriting it outright.
                existing_ef = doc.get("extracted_fields") or {}
                merged_ef = {**existing_ef, **mapped_fields}
                await db.hub_documents.update_one(
                    {"id": doc["id"]},
                    {"$set": {
                        "invoice_number_clean": normalized.get("invoice_number_clean"),
                        "amount_float": normalized.get("amount_float"),
                        "extracted_fields": merged_ef,
                    }},
                )
                results["updated"] += 1

            results["details"].append(entry)

    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill invoice_number_clean/amount_float for "
                     "already-processed XML e-invoices, using the "
                     "now-fixed CFDI parser. Dry-run by default."
    )
    ap.add_argument(
        "--confirm", action="store_true",
        help="Actually write to hub_documents. Without this flag, "
             "prints what WOULD be written and makes no changes.",
    )
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = asyncio.run(run(args.confirm))

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== backfill_xml_invoice_extraction ===")
    print(f"  mode:               {'CONFIRM (writing)' if result['confirm'] else 'DRY RUN (no writes)'}")
    print(f"  total_candidates:   {result['total_candidates']}")
    print(f"  downloaded:         {result['downloaded']}")
    print(f"  download_failed:    {result['download_failed']}")
    print(f"  extracted:          {result['extracted']}")
    print(f"  extraction_failed:  {result['extraction_failed']}")
    if result["confirm"]:
        print(f"  updated:            {result['updated']}")
    print()
    print("  DETAIL:")
    for d in result["details"]:
        if d["status"] in ("would_update", "updated"):
            print(f"    [{d['status']}] {d['file_name']}  "
                  f"inv#={d.get('invoice_number_clean')!r}  "
                  f"amount={d.get('amount_float')}  "
                  f"vendor={d.get('vendor_raw')!r}")
        else:
            print(f"    [{d['status']}] {d['file_name']}  {d.get('error', '')}")

    if not result["confirm"] and result["extracted"] > 0:
        print()
        print("  Re-run with --confirm to actually write these updates.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
