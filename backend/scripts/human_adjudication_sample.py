"""
scripts/human_adjudication_sample.py
=====================================
Neither the parity report (coverage) nor hub_classification_quality_report.py
(agreement on already-matched docs) can catch Hub's biggest asymmetric risk:
Square9 is a manual filing system, so its failure mode is "slow." Hub
auto-clears and auto-posts, so its failure mode can be "fast, confidently
wrong, and nobody looked." Neither existing report samples THAT population.

This script pulls two small, stratified, human-reviewable samples and writes
them as CSVs an AP person can work through directly, the same handoff-
checklist pattern already used by bucket_C_handoff_doc.py:

  1. autonomous_decisions_sample.csv — documents Hub processed with NO human
     review (auto_cleared=True or routing_status=auto_process or
     automation_state=autonomous). Stratified across doc_type and confidence
     band so the sample isn't dominated by whatever the single most common
     document type happens to be. Question to answer: "did Hub get this
     right without anyone checking?"

  2. excluded_documents_sample.csv — documents Hub filed away as NOT needing
     AP processing (workflow_status in the non-transactional-disposition
     values this session introduced: shipping_filed, excluded,
     archived_from_queue). Question to answer: "was this genuinely not an
     invoice, or did Hub silently drop something it should have processed?"
     This is the mirror image of #1 -- false negatives instead of false
     confidence.

Read-only. Writes two CSVs, no database writes.
"""

import argparse
import asyncio
import csv
import os
import random
import sys
from collections import defaultdict
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

REVIEW_COLUMNS = [
    "doc_id", "file_name", "vendor_canonical", "doc_type", "suggested_job_type",
    "amount_float", "invoice_number_clean", "classification_method",
    "ai_confidence", "routing_status", "auto_cleared", "workflow_status",
    "sharepoint_web_url",
    # Blank columns for the reviewer to fill in:
    "CORRECT (Y/N)", "SHOULD_HAVE_BEEN", "REVIEWER_NOTES",
]


def _confidence_band(conf: Any) -> str:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return "unknown"
    if c >= 0.9:
        return "high"
    if c >= 0.7:
        return "medium"
    return "low"


def stratified_sample(docs: List[Dict[str, Any]], strata_key, per_stratum: int, seed: int) -> List[Dict[str, Any]]:
    """Group docs by strata_key(doc), then take up to per_stratum from each
    group -- so no single dominant doc_type/confidence-band can crowd out
    everything else in a fixed-size random sample."""
    rng = random.Random(seed)
    groups: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for d in docs:
        groups[strata_key(d)].append(d)
    sample: List[Dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda kv: str(kv[0])):
        rng.shuffle(group)
        sample.extend(group[:per_stratum])
    return sample


def cap_total(sample: List[Dict[str, Any]], max_total: int, seed: int) -> List[Dict[str, Any]]:
    """If stratification still produced more than max_total (many strata,
    each contributing a few), take a final random draw down to a size an
    AP reviewer can actually work through in one sitting."""
    if len(sample) <= max_total:
        return sample
    rng = random.Random(seed)
    return rng.sample(sample, max_total)


def _row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": doc.get("id", ""),
        "file_name": doc.get("file_name", ""),
        "vendor_canonical": doc.get("vendor_canonical", ""),
        "doc_type": doc.get("doc_type", ""),
        "suggested_job_type": doc.get("suggested_job_type", ""),
        "amount_float": doc.get("amount_float", ""),
        "invoice_number_clean": doc.get("invoice_number_clean", ""),
        "classification_method": doc.get("classification_method", ""),
        "ai_confidence": doc.get("ai_confidence", ""),
        "routing_status": doc.get("routing_status", ""),
        "auto_cleared": doc.get("auto_cleared", ""),
        "workflow_status": doc.get("workflow_status", ""),
        "sharepoint_web_url": doc.get("sharepoint_web_url", ""),
        "CORRECT (Y/N)": "",
        "SHOULD_HAVE_BEEN": "",
        "REVIEWER_NOTES": "",
    }


def write_sample_csv(path: str, rows: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVIEW_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


PROJECTION = {
    "_id": 0, "id": 1, "file_name": 1, "vendor_canonical": 1, "doc_type": 1,
    "suggested_job_type": 1, "amount_float": 1, "invoice_number_clean": 1,
    "classification_method": 1, "ai_confidence": 1, "routing_status": 1,
    "auto_cleared": 1, "workflow_status": 1, "sharepoint_web_url": 1,
}


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-stratum", type=int, default=5,
                     help="Max docs sampled per (doc_type, confidence-band) group.")
    ap.add_argument("--max-total", type=int, default=40,
                     help="Hard cap on final sample size per pool, after stratification.")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out-dir", default="prod_reports")
    args = ap.parse_args()

    db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]

    # Pool 1: autonomous decisions -- no human ever looked at these.
    autonomous_query = {
        "$or": [
            {"auto_cleared": True},
            {"routing_status": "auto_process"},
            {"automation_state": "autonomous"},
        ]
    }
    autonomous_docs = await db.hub_documents.find(autonomous_query, PROJECTION).to_list(length=None)
    autonomous_sample = stratified_sample(
        autonomous_docs,
        strata_key=lambda d: (d.get("doc_type") or "OTHER", _confidence_band(d.get("ai_confidence"))),
        per_stratum=args.per_stratum,
        seed=args.seed,
    )
    autonomous_sample = cap_total(autonomous_sample, args.max_total, args.seed)
    out1 = os.path.join(args.out_dir, "autonomous_decisions_sample.csv")
    write_sample_csv(out1, [_row(d) for d in autonomous_sample])

    # Pool 2: excluded / dispositioned-as-non-transactional documents.
    excluded_query = {
        "workflow_status": {"$in": ["shipping_filed", "excluded", "archived_from_queue"]}
    }
    excluded_docs = await db.hub_documents.find(excluded_query, PROJECTION).to_list(length=None)
    excluded_sample = stratified_sample(
        excluded_docs,
        strata_key=lambda d: d.get("workflow_status") or "unknown",
        per_stratum=args.per_stratum,
        seed=args.seed,
    )
    excluded_sample = cap_total(excluded_sample, args.max_total, args.seed)
    out2 = os.path.join(args.out_dir, "excluded_documents_sample.csv")
    write_sample_csv(out2, [_row(d) for d in excluded_sample])

    result = {
        "autonomous_pool_size": len(autonomous_docs),
        "autonomous_sample_size": len(autonomous_sample),
        "autonomous_sample_csv": out1,
        "excluded_pool_size": len(excluded_docs),
        "excluded_sample_size": len(excluded_sample),
        "excluded_sample_csv": out2,
    }
    print(
        f"[adjudication-sample] autonomous: {len(autonomous_sample)} sampled from "
        f"{len(autonomous_docs)}-doc pool -> {out1}",
        file=sys.stderr,
    )
    print(
        f"[adjudication-sample] excluded: {len(excluded_sample)} sampled from "
        f"{len(excluded_docs)}-doc pool -> {out2}",
        file=sys.stderr,
    )
    import json
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
