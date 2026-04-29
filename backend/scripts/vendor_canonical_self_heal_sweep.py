"""
Vendor-Canonical Self-Heal Sweep — retroactive correction for stale
`vendor_canonical` on AP_Invoice docs that already have an authoritative
BC resolution cached on them.

Read-only by default. `--apply` to write. Idempotent.

See: memory/VENDOR_CANONICAL_SELF_HEAL_SWEEP_DECLARATION.md
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass

from motor.motor_asyncio import AsyncIOMotorClient

from services.vendor_name_helpers import vendor_match_likely


REPORT_DIR = Path("/app/memory")
SWEEP_VERSION = "vendor_canonical_self_heal_sweep_v1"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------------------------------------------------------------------------
# Classification — pure function (no DB, no I/O), unit-testable
# ---------------------------------------------------------------------------


# Buckets
BUCKET_AUTO_HEAL = "auto_heal"
BUCKET_CLEAN = "clean_no_change_needed"
BUCKET_NA_NO_EXTRACTED = "not_applicable_no_extracted_vendor"
BUCKET_NA_NO_BC = "not_applicable_no_bc_resolution"
BUCKET_MR_EXTRACTION_VS_BC = "manual_review_extraction_vs_bc_disagreement"
BUCKET_MR_POSTED = "manual_review_protected_already_posted"
BUCKET_MR_DUPLICATE = "manual_review_protected_duplicate"
BUCKET_MR_OVERRIDE = "manual_review_protected_manual_override"

_MANUAL_OVERRIDE_METHODS = {"manual", "manual_override", "operator_correction"}


def _classify_doc(doc: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Classify a doc into one of the 8 buckets.

    Returns (bucket, context) where context carries the values used to make
    the decision so the caller can use them when writing the heal.
    """
    ef = doc.get("extracted_fields") or {}
    extracted = (ef.get("vendor") or "").strip()
    vr = doc.get("validation_results") or {}
    bc_info = (vr.get("bc_record_info") or {}) if isinstance(vr, dict) else {}
    bc_number = (bc_info.get("number") or "").strip() if isinstance(bc_info, dict) else ""
    bc_display = (bc_info.get("displayName") or "").strip() if isinstance(bc_info, dict) else ""
    current_canonical = (doc.get("vendor_canonical") or "").strip()
    posted = doc.get("bc_purchase_invoice")
    is_dup = bool(doc.get("is_duplicate")) or bool(doc.get("duplicate_of_document_id"))
    manual_override = bool(doc.get("vendor_canonical_manual_override"))
    match_method = (doc.get("vendor_match_method") or "").lower()

    ctx = {
        "extracted_vendor": extracted,
        "bc_number": bc_number,
        "bc_display": bc_display,
        "current_vendor_canonical": current_canonical,
        "current_vendor_match_method": doc.get("vendor_match_method"),
        "current_bc_vendor_number": doc.get("bc_vendor_number"),
    }

    # Criterion 2
    if not extracted:
        return (BUCKET_NA_NO_EXTRACTED, ctx)
    # Criteria 3 + 4
    if not bc_number or not bc_display:
        return (BUCKET_NA_NO_BC, ctx)
    # Criterion 5 — extraction must agree with BC, else manual review
    if not vendor_match_likely(extracted, bc_display):
        return (BUCKET_MR_EXTRACTION_VS_BC, ctx)
    # Criterion 6 — current canonical must DISAGREE with BC (the contradiction)
    if vendor_match_likely(bc_display, current_canonical):
        return (BUCKET_CLEAN, ctx)
    # Criterion 7 — already posted = protected
    if posted:
        return (BUCKET_MR_POSTED, ctx)
    # Criterion 8 — duplicate = protected
    if is_dup:
        return (BUCKET_MR_DUPLICATE, ctx)
    # Criterion 9 — manual override = protected
    if manual_override or match_method in _MANUAL_OVERRIDE_METHODS:
        return (BUCKET_MR_OVERRIDE, ctx)

    return (BUCKET_AUTO_HEAL, ctx)


# ---------------------------------------------------------------------------
# Heal write
# ---------------------------------------------------------------------------


async def _apply_heal(
    db,
    doc_id: str,
    ctx: Dict[str, Any],
    extracted_vendor: str,
    sweep_run_id: str,
) -> Dict[str, Any]:
    """Apply a single heal write + emit telemetry. Returns a result dict."""
    now = _utc_iso()
    history_entry = {
        "healed_at": now,
        "previous_vendor_canonical": ctx["current_vendor_canonical"],
        "previous_vendor_match_method": ctx["current_vendor_match_method"],
        "previous_bc_vendor_number": ctx["current_bc_vendor_number"],
        "new_vendor_canonical": ctx["bc_display"],
        "new_bc_vendor_number": ctx["bc_number"],
        "source": SWEEP_VERSION,
        "sweep_run_id": sweep_run_id,
    }
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "vendor_canonical": ctx["bc_display"],
                "bc_vendor_number": ctx["bc_number"],
                "vendor_match_method": "self_healed_bc_validation",
                "self_healed_at": now,
                "self_heal_source": SWEEP_VERSION,
            },
            "$push": {"self_heal_history": history_entry},
        },
    )
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "vendor.canonical_self_healed",
        "status": "completed",
        "source_service": "vendor_canonical_self_heal_sweep",
        "timestamp": now,
        "actor": None,
        "document_id": doc_id,
        "payload": {
            "from": {
                "vendor_canonical": ctx["current_vendor_canonical"],
                "vendor_match_method": ctx["current_vendor_match_method"],
                "bc_vendor_number": ctx["current_bc_vendor_number"],
            },
            "to": {
                "vendor_canonical": ctx["bc_display"],
                "vendor_match_method": "self_healed_bc_validation",
                "bc_vendor_number": ctx["bc_number"],
            },
            "extracted_vendor": extracted_vendor,
            "source": SWEEP_VERSION,
            "sweep_run_id": sweep_run_id,
        },
    }
    try:
        await db.workflow_events.insert_one(event)
    except Exception as e:
        # Telemetry best-effort. Heal write already succeeded.
        return {"doc_id": doc_id, "healed": True, "telemetry_failed": str(e)}
    return {"doc_id": doc_id, "healed": True}


# ---------------------------------------------------------------------------
# Sweep (read or apply)
# ---------------------------------------------------------------------------


async def sweep(
    apply: bool,
    max_heals: Optional[int],
    doc_id_filter: Optional[str],
    sweep_run_id: str,
) -> Dict[str, Any]:
    db = _db()

    bucket_counts: Dict[str, int] = {}
    bucket_samples: Dict[str, List[str]] = {}
    auto_heal_doc_ids: List[str] = []
    heal_results: List[Dict[str, Any]] = []
    heal_failures: List[Dict[str, Any]] = []

    query: Dict[str, Any] = {"document_type": "AP_Invoice"}
    if doc_id_filter:
        query["id"] = doc_id_filter

    cursor = db.hub_documents.find(query, {"_id": 0})
    async for doc in cursor:
        bucket, ctx = _classify_doc(doc)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        if bucket not in bucket_samples:
            bucket_samples[bucket] = []
        if len(bucket_samples[bucket]) < 5:
            bucket_samples[bucket].append(doc.get("id"))
        if bucket == BUCKET_AUTO_HEAL:
            auto_heal_doc_ids.append(doc.get("id"))

    if apply:
        targets = auto_heal_doc_ids if max_heals is None else auto_heal_doc_ids[:max_heals]
        for did in targets:
            doc = await db.hub_documents.find_one({"id": did}, {"_id": 0})
            if not doc:
                continue
            bucket, ctx = _classify_doc(doc)
            if bucket != BUCKET_AUTO_HEAL:
                # Lost a race / changed since classification — skip safely.
                continue
            try:
                result = await _apply_heal(
                    db, did, ctx,
                    (doc.get("extracted_fields") or {}).get("vendor", ""),
                    sweep_run_id,
                )
                heal_results.append(result)
            except Exception as e:
                heal_failures.append({"doc_id": did, "error": str(e)})

    return {
        "sweep_run_id": sweep_run_id,
        "generated_at": _utc_iso(),
        "applied": apply,
        "max_heals": max_heals,
        "doc_id_filter": doc_id_filter,
        "bucket_counts": bucket_counts,
        "bucket_samples": bucket_samples,
        "auto_heal_doc_ids": auto_heal_doc_ids,
        "heal_results": heal_results,
        "heal_failures": heal_failures,
    }


# ---------------------------------------------------------------------------
# Revert paths
# ---------------------------------------------------------------------------


async def revert_doc(doc_id: str) -> Dict[str, Any]:
    db = _db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"doc_id": doc_id, "reverted": False, "reason": "doc_not_found"}
    history = doc.get("self_heal_history") or []
    if not history:
        return {"doc_id": doc_id, "reverted": False, "reason": "no_self_heal_history"}
    most_recent = history[-1]
    now = _utc_iso()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "vendor_canonical": most_recent.get("previous_vendor_canonical"),
                "vendor_match_method": most_recent.get("previous_vendor_match_method"),
                "bc_vendor_number": most_recent.get("previous_bc_vendor_number"),
            },
            "$pop": {"self_heal_history": 1},  # remove most-recent entry
        },
    )
    try:
        await db.workflow_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "vendor.canonical_self_heal_reverted",
            "status": "completed",
            "source_service": "vendor_canonical_self_heal_sweep",
            "timestamp": now,
            "actor": None,
            "document_id": doc_id,
            "payload": {
                "reverted_entry": most_recent,
                "source": SWEEP_VERSION,
            },
        })
    except Exception:
        pass
    return {"doc_id": doc_id, "reverted": True, "restored": most_recent}


async def revert_sweep_run(sweep_run_id: str) -> Dict[str, Any]:
    db = _db()
    affected_doc_ids: List[str] = []
    cursor = db.workflow_events.find(
        {"event_type": "vendor.canonical_self_healed",
         "payload.sweep_run_id": sweep_run_id},
        {"_id": 0, "document_id": 1},
    )
    async for e in cursor:
        if e.get("document_id"):
            affected_doc_ids.append(e["document_id"])
    results = []
    for did in affected_doc_ids:
        results.append(await revert_doc(did))
    return {"sweep_run_id": sweep_run_id, "reverted_count": sum(1 for r in results if r["reverted"]),
            "results": results}


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Vendor-Canonical Self-Heal Sweep — `{report['sweep_run_id']}`")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Mode: **{'APPLY' if report['applied'] else 'DRY-RUN'}**")
    if report.get("max_heals") is not None:
        lines.append(f"- max_heals: `{report['max_heals']}`")
    if report.get("doc_id_filter"):
        lines.append(f"- doc_id_filter: `{report['doc_id_filter']}`")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| bucket | count | sample doc_ids |")
    lines.append("|---|---|---|")
    bucket_order = [
        BUCKET_AUTO_HEAL,
        BUCKET_CLEAN,
        BUCKET_NA_NO_EXTRACTED,
        BUCKET_NA_NO_BC,
        BUCKET_MR_EXTRACTION_VS_BC,
        BUCKET_MR_POSTED,
        BUCKET_MR_DUPLICATE,
        BUCKET_MR_OVERRIDE,
    ]
    for b in bucket_order:
        n = report["bucket_counts"].get(b, 0)
        samples = report["bucket_samples"].get(b, [])
        sample_str = ", ".join(f"`{s}`" for s in samples) if samples else "-"
        lines.append(f"| `{b}` | {n} | {sample_str} |")
    lines.append("")
    if report["applied"]:
        lines.append("## Heal results")
        lines.append("")
        lines.append(f"- healed: **{len([r for r in report['heal_results'] if r.get('healed')])}**")
        lines.append(f"- failures: **{len(report['heal_failures'])}**")
        if report["heal_failures"]:
            lines.append("")
            lines.append("### Failures")
            lines.append("")
            for f in report["heal_failures"][:20]:
                lines.append(f"- `{f['doc_id']}`: {f['error']}")
        lines.append("")
    else:
        lines.append("## Auto-heal candidates (would write in --apply mode)")
        lines.append("")
        lines.append(f"Total: **{len(report['auto_heal_doc_ids'])}**")
        if report["auto_heal_doc_ids"]:
            lines.append("")
            for did in report["auto_heal_doc_ids"][:50]:
                lines.append(f"- `{did}`")
        lines.append("")
    return "\n".join(lines)


def _write_reports(report: Dict[str, Any]) -> Tuple[Path, Path, Optional[Path]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rid = report["sweep_run_id"]
    md_path = REPORT_DIR / f"VENDOR_CANONICAL_SELF_HEAL_REPORT_{rid}.md"
    json_path = REPORT_DIR / f"VENDOR_CANONICAL_SELF_HEAL_REPORT_{rid}.json"
    md_path.write_text(_render_md(report))
    json_path.write_text(json.dumps(report, indent=2, default=str))
    mr_path: Optional[Path] = None
    mr_buckets = (BUCKET_MR_EXTRACTION_VS_BC, BUCKET_MR_POSTED,
                  BUCKET_MR_DUPLICATE, BUCKET_MR_OVERRIDE)
    if any(report["bucket_counts"].get(b) for b in mr_buckets):
        mr_path = REPORT_DIR / f"VENDOR_CANONICAL_SELF_HEAL_MANUAL_REVIEW_{rid}.json"
        mr_path.write_text(json.dumps({
            b: report["bucket_samples"].get(b, []) for b in mr_buckets
        }, indent=2, default=str))
    return md_path, json_path, mr_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> int:
    if args.revert:
        result = await revert_doc(args.revert)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("reverted") else 2
    if args.revert_sweep_run:
        result = await revert_sweep_run(args.revert_sweep_run)
        print(json.dumps({"sweep_run_id": result["sweep_run_id"],
                          "reverted_count": result["reverted_count"]},
                         indent=2, default=str))
        return 0

    sweep_run_id = str(uuid.uuid4())
    print(f"[{_utc_iso()}] vendor_canonical self-heal sweep — run_id={sweep_run_id}")
    print(f"  mode={'APPLY' if args.apply else 'DRY-RUN'}  max={args.max}  filter={args.doc_id}")
    report = await sweep(
        apply=args.apply,
        max_heals=args.max,
        doc_id_filter=args.doc_id,
        sweep_run_id=sweep_run_id,
    )
    md_path, json_path, mr_path = _write_reports(report)
    print(f"  bucket_counts={report['bucket_counts']}")
    if args.apply:
        print(f"  healed={len([r for r in report['heal_results'] if r.get('healed')])}  "
              f"failures={len(report['heal_failures'])}")
    print("  reports:")
    print(f"    {md_path}")
    print(f"    {json_path}")
    if mr_path:
        print(f"    {mr_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="actually perform heal writes (default: dry-run)")
    p.add_argument("--max", type=int, default=None,
                   help="cap apply count (e.g. --max 5 for cautious first run)")
    p.add_argument("--doc-id", default=None,
                   help="restrict scan to a single doc id")
    p.add_argument("--revert", default=None,
                   help="revert a single doc's most-recent heal")
    p.add_argument("--revert-sweep-run", default=None,
                   help="revert every doc touched by one sweep_run_id")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
