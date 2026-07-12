"""
Continuously learn correct document routing by comparing real Square9
filing locations against Hub's own routing, using the SAME proven
matching logic already used for cutover parity reporting
(scripts/square9_hub_ap_parity_report.py).

SAFETY DESIGN (informed directly by a real mistake caught and fixed
2026-07-10): before ever calling record_correction() for a given
vendor+doc_type+has_po+is_international key, checks whether a rule
ALREADY exists for that key. If it does and DISAGREES with what this
new match says, does NOT auto-apply either answer - flags it as a
conflict for human review instead. Only auto-applies when the existing
rule (if any) agrees, or when there's no existing rule yet.

Defaults to DRY RUN: reports what it would do, writes nothing. Requires
--confirm APPLY to actually call record_correction().
"""
import argparse
import asyncio
import os
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'scripts')

MATCH_BUCKETS_TRUSTED = {"exact_match", "strong_evidence_match"}


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", default=None, help="Pass APPLY to actually write corrections")
    args = p.parse_args()

    from scripts.square9_hub_ap_parity_report import (
        best_match, load_hub_ap_docs, pull_expanded_ap_corpus, _hub_folder_root,
    )
    from scripts.sharepoint_ap_compare import (
        acquire_graph_token, PROD_DEFAULT_SITE_PATH, PROD_DEFAULT_LIBRARY,
    )
    from services.routing_feedback_service import init_feedback_db, record_correction, _make_routing_key
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(os.environ['MONGO_URL'])
    db = client[os.environ['DB_NAME']]
    init_feedback_db(db)

    print("Acquiring Square9 Graph token...")
    tenant = os.environ.get("TENANT_ID")
    cid = os.environ.get("GRAPH_CLIENT_ID")
    csec = os.environ.get("GRAPH_CLIENT_SECRET")
    token = acquire_graph_token(tenant, cid, csec)
    host = os.environ.get(
        "SHAREPOINT_HOST",
        f"{(os.environ.get('SHAREPOINT_TENANT_NAME') or 'gamerpackaging1')}.sharepoint.com",
    )

    print("Pulling real Square9 AP corpus (full, folder-structure-based)...")
    sq_docs = pull_expanded_ap_corpus(
        token=token, host=host, site_path=PROD_DEFAULT_SITE_PATH, library=PROD_DEFAULT_LIBRARY,
    )
    print("Pulling Hub AP documents (last 7 days)...")
    hub_docs = load_hub_ap_docs(since_hours=168, limit=5000)
    print(f"Square9 docs: {len(sq_docs)}  Hub docs: {len(hub_docs)}")
    print()

    applied = 0
    strengthened = 0
    conflicts = []
    skipped_low_confidence = 0
    skipped_no_data = 0

    for sq in sq_docs:
        hub_doc, result = best_match(sq, hub_docs)
        if not hub_doc or result.bucket not in MATCH_BUCKETS_TRUSTED:
            skipped_low_confidence += 1
            continue

        vendor = (hub_doc.vendor_canonical or "").strip()
        doc_type = (hub_doc.doc_type or "Unknown").strip()
        has_po = bool(hub_doc.po_number_clean)
        is_international = bool((hub_doc.raw or {}).get("is_international", False))
        real_folder = _hub_folder_root(sq.raw.get("parent_path", ""))

        if not vendor or not real_folder:
            skipped_no_data += 1
            continue

        key = _make_routing_key(vendor, doc_type, has_po, is_international)
        existing = await db["routing_feedback"].find_one({"routing_key": key})

        if existing and existing.get("correct_folder", "").lower() != real_folder.lower():
            conflicts.append({
                "key": key, "vendor": vendor, "doc_type": doc_type,
                "existing_folder": existing.get("correct_folder"),
                "new_folder": real_folder,
                "square9_file": sq.name, "hub_file": hub_doc.file_name,
            })
            continue

        action = "STRENGTHEN" if existing else "CREATE"
        print(f"  {action}: {key} -> {real_folder!r} (square9={sq.name}, hub={hub_doc.file_name})")

        if args.confirm == "APPLY":
            await record_correction(
                vendor=vendor, doc_type=doc_type, has_po=has_po,
                is_international=is_international, correct_folder=real_folder,
                file_name=hub_doc.file_name, source="square9_continuous_learning",
            )
        if existing:
            strengthened += 1
        else:
            applied += 1

    print()
    print("=== SUMMARY ===")
    print(f"New rules {'created' if args.confirm == 'APPLY' else 'that would be created'}: {applied}")
    print(f"Existing rules {'strengthened' if args.confirm == 'APPLY' else 'that would be strengthened'}: {strengthened}")
    print(f"Skipped (match confidence too low): {skipped_low_confidence}")
    print(f"Skipped (missing vendor/folder data): {skipped_no_data}")
    print(f"CONFLICTS (existing rule disagrees - NOT auto-applied): {len(conflicts)}")
    print()

    if conflicts:
        print("=== CONFLICTS NEEDING HUMAN REVIEW ===")
        for c in conflicts:
            print(f"  {c['key']}")
            print(f"    existing rule says: {c['existing_folder']!r}")
            print(f"    this Square9 match says: {c['new_folder']!r}")
            print(f"    square9_file={c['square9_file']!r} hub_file={c['hub_file']!r}")
            print()

    if args.confirm != "APPLY":
        print("DRY RUN ONLY - no changes made. Re-run with --confirm APPLY to actually write corrections.")


asyncio.run(main())
