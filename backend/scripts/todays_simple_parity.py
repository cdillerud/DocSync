"""
Simple parity check scoped to TODAY's documents only - reuses the same
proven matching logic as the full cutover report, but filtered to just
today's real activity for a fast, current read on how things are going
right now.
"""
import asyncio
import os
import sys
sys.path.insert(0, '.')
sys.path.insert(0, 'scripts')

MATCH_BUCKETS_TRUSTED = {"exact_match", "strong_evidence_match"}
TODAY = "2026-07-13"


async def main():
    from scripts.square9_hub_ap_parity_report import best_match, load_hub_ap_docs, pull_expanded_ap_corpus
    from scripts.sharepoint_ap_compare import (
        acquire_graph_token, PROD_DEFAULT_SITE_PATH, PROD_DEFAULT_LIBRARY,
    )

    print("Acquiring Square9 Graph token...")
    tenant = os.environ.get("TENANT_ID")
    cid = os.environ.get("GRAPH_CLIENT_ID")
    csec = os.environ.get("GRAPH_CLIENT_SECRET")
    token = acquire_graph_token(tenant, cid, csec)
    host = os.environ.get(
        "SHAREPOINT_HOST",
        f"{(os.environ.get('SHAREPOINT_TENANT_NAME') or 'gamerpackaging1')}.sharepoint.com",
    )

    print("Pulling real Square9 AP corpus...")
    all_sq_docs = pull_expanded_ap_corpus(
        token=token, host=host, site_path=PROD_DEFAULT_SITE_PATH, library=PROD_DEFAULT_LIBRARY,
    )
    sq_docs_today = [d for d in all_sq_docs if str(d.modified or "").startswith(TODAY)]
    print(f"Square9 docs total: {len(all_sq_docs)}  |  from today ({TODAY}): {len(sq_docs_today)}")

    print("Pulling Hub AP documents (last 48h, to safely cover today regardless of timezone edges)...")
    hub_docs = load_hub_ap_docs(since_hours=48, limit=2000)
    print(f"Hub docs available to match against: {len(hub_docs)}")
    print()

    matched = 0
    unmatched = []

    for sq in sq_docs_today:
        hub_doc, result = best_match(sq, hub_docs)
        if hub_doc and result.bucket in MATCH_BUCKETS_TRUSTED:
            matched += 1
        else:
            unmatched.append(sq.name)

    total = len(sq_docs_today)
    rate = (matched / total * 100) if total else 0

    print("=== TODAY'S PARITY (7/13/2026) ===")
    print(f"Square9 documents from today: {total}")
    print(f"Confidently matched to a Hub document: {matched}")
    print(f"Match rate: {rate:.1f}%")
    if unmatched:
        print()
        print(f"Unmatched Square9 documents ({len(unmatched)}):")
        for fn in unmatched[:20]:
            print(f"  {fn}")


asyncio.run(main())
