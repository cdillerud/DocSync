"""
Workflow-Status Orphan Unstick — targeted promotion of exactly four
§6.2-healed Mid America docs into a (status, workflow_status) pair the
tier1_batch_runner selector recognises.

Read-only by default. `--apply` to write. Idempotent. Per-doc reversible.
Hard-coded to a frozenset of 4 doc_ids — refuses any other id.

See: memory/WORKFLOW_STATUS_ORPHAN_UNSTICK_DECLARATION.md
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


REPORT_DIR = Path("/app/memory")
SCRIPT_VERSION = "workflow_status_orphan_unstick_v1"


# ---------------------------------------------------------------------------
# Hard-coded scope (declaration §3)
# ---------------------------------------------------------------------------

ALLOWED_DOC_IDS = frozenset({
    "c413fe62-7f99-4584-b56f-4d30bf8b173d",
    "d10f5242-0c8a-41fe-b713-e34223de0c52",
    "c10a8b04-a49f-46ac-a78e-a5b448891307",
    "48a153f8-41c0-46bd-bc93-52e2cc8238e5",
})

# Per-doc from→to mapping (§3 criterion 9)
PROMOTION_MAP: Dict[str, Dict[str, Dict[str, str]]] = {
    "c413fe62-7f99-4584-b56f-4d30bf8b173d": {
        "from": {"status": "Completed",    "workflow_status": "processed"},
        "to":   {"status": "ReadyForPost", "workflow_status": "ready_for_post"},
    },
    "d10f5242-0c8a-41fe-b713-e34223de0c52": {
        "from": {"status": "Completed",    "workflow_status": "processed"},
        "to":   {"status": "ReadyForPost", "workflow_status": "ready_for_post"},
    },
    "c10a8b04-a49f-46ac-a78e-a5b448891307": {
        "from": {"status": "batch_parent", "workflow_status": "ready_for_post"},
        "to":   {"status": "ReadyForPost", "workflow_status": "ready_for_post"},
    },
    "48a153f8-41c0-46bd-bc93-52e2cc8238e5": {
        "from": {"status": "batch_parent", "workflow_status": "ready_for_post"},
        "to":   {"status": "ReadyForPost", "workflow_status": "ready_for_post"},
    },
}

EXPECTED_VENDOR_CANONICAL = "Mid America Logistics Group LLC"
EXPECTED_BC_VENDOR_NUMBER = "MIDAMER"
EXPECTED_MATCH_METHOD = "self_healed_bc_validation"


# Buckets
BUCKET_PROMOTED = "promoted"
BUCKET_CLEAN = "clean_already_promoted"
BUCKET_MR_VENDOR_DRIFT = "manual_review_vendor_drift"
BUCKET_MR_POSTED = "manual_review_already_posted"
BUCKET_MR_DUPLICATE = "manual_review_duplicate"
BUCKET_MR_UNEXPECTED = "manual_review_unexpected_state"
BUCKET_REJECTED = "rejected_unknown_doc_id"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    return AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]


# ---------------------------------------------------------------------------
# Classification — pure function (no DB, no I/O), unit-testable
# ---------------------------------------------------------------------------


def _classify_doc(doc: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """Classify a doc into one of the eligibility buckets."""
    did = doc.get("id") or ""
    if did not in ALLOWED_DOC_IDS:
        return (BUCKET_REJECTED, {"doc_id": did})

    mapping = PROMOTION_MAP[did]
    expected_from = mapping["from"]
    target = mapping["to"]

    cur_status = doc.get("status")
    cur_wf = doc.get("workflow_status")
    ctx: Dict[str, Any] = {
        "doc_id": did,
        "current_status": cur_status,
        "current_workflow_status": cur_wf,
        "expected_from": expected_from,
        "target": target,
    }

    # Idempotency check first — already at the target state.
    if cur_status == target["status"] and cur_wf == target["workflow_status"]:
        return (BUCKET_CLEAN, ctx)

    # Criterion 2 — must be AP_Invoice
    if doc.get("document_type") != "AP_Invoice":
        return (BUCKET_MR_UNEXPECTED, {**ctx, "reason": "document_type != AP_Invoice"})

    # Criteria 3, 4, 5 — §6.2 heal must still be in place
    vc = (doc.get("vendor_canonical") or "")
    bcvn = (doc.get("bc_vendor_number") or "")
    vmm = (doc.get("vendor_match_method") or "")
    if vc != EXPECTED_VENDOR_CANONICAL or bcvn != EXPECTED_BC_VENDOR_NUMBER or vmm != EXPECTED_MATCH_METHOD:
        return (BUCKET_MR_VENDOR_DRIFT, {
            **ctx,
            "vendor_canonical": vc,
            "bc_vendor_number": bcvn,
            "vendor_match_method": vmm,
        })

    # Criterion 6 — not posted
    if doc.get("bc_purchase_invoice"):
        return (BUCKET_MR_POSTED, ctx)

    # Criterion 7 — not duplicate
    if doc.get("is_duplicate") or doc.get("duplicate_of_document_id"):
        return (BUCKET_MR_DUPLICATE, ctx)

    # Criterion 8 — current pair must match the declared "from" pair
    if cur_status != expected_from["status"] or cur_wf != expected_from["workflow_status"]:
        return (BUCKET_MR_UNEXPECTED, ctx)

    return (BUCKET_PROMOTED, ctx)


# ---------------------------------------------------------------------------
# Promotion write
# ---------------------------------------------------------------------------


async def _apply_promotion(
    db,
    doc_id: str,
    ctx: Dict[str, Any],
    run_id: str,
) -> Dict[str, Any]:
    """Apply a single promotion + emit telemetry."""
    now = _utc_iso()
    target = ctx["target"]
    history_entry = {
        "promoted_at": now,
        "previous_status": ctx["current_status"],
        "previous_workflow_status": ctx["current_workflow_status"],
        "new_status": target["status"],
        "new_workflow_status": target["workflow_status"],
        "source": SCRIPT_VERSION,
        "run_id": run_id,
    }
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "status": target["status"],
                "workflow_status": target["workflow_status"],
                "promoted_for_batch2_at": now,
                "promoted_for_batch2_source": SCRIPT_VERSION,
            },
            "$push": {"workflow_promotion_history": history_entry},
        },
    )
    event = {
        "event_id": str(uuid.uuid4()),
        "event_type": "workflow.status_promoted_for_batch2",
        "status": "completed",
        "source_service": "workflow_status_orphan_unstick",
        "timestamp": now,
        "actor": None,
        "document_id": doc_id,
        "payload": {
            "from": {
                "status": ctx["current_status"],
                "workflow_status": ctx["current_workflow_status"],
            },
            "to": {
                "status": target["status"],
                "workflow_status": target["workflow_status"],
            },
            "vendor_canonical": EXPECTED_VENDOR_CANONICAL,
            "bc_vendor_number": EXPECTED_BC_VENDOR_NUMBER,
            "source": SCRIPT_VERSION,
            "run_id": run_id,
        },
    }
    try:
        await db.workflow_events.insert_one(event)
    except Exception as e:
        return {"doc_id": doc_id, "promoted": True, "telemetry_failed": str(e)}
    return {"doc_id": doc_id, "promoted": True}


# ---------------------------------------------------------------------------
# Sweep (read or apply)
# ---------------------------------------------------------------------------


async def sweep(
    apply: bool,
    doc_id_filter: Optional[str],
    run_id: str,
) -> Dict[str, Any]:
    db = _db()

    # Determine target ids
    if doc_id_filter is not None:
        if doc_id_filter not in ALLOWED_DOC_IDS:
            # Hard fail before any DB read — declaration §3 rejection rule.
            raise ValueError(
                f"doc_id {doc_id_filter!r} is not in the hard-coded "
                f"ALLOWED_DOC_IDS set; refusing to act"
            )
        target_ids = [doc_id_filter]
    else:
        target_ids = sorted(ALLOWED_DOC_IDS)

    bucket_counts: Dict[str, int] = {}
    per_doc: List[Dict[str, Any]] = []
    promote_results: List[Dict[str, Any]] = []
    promote_failures: List[Dict[str, Any]] = []

    for did in target_ids:
        doc = await db.hub_documents.find_one({"id": did}, {"_id": 0})
        if not doc:
            bucket_counts[BUCKET_MR_UNEXPECTED] = bucket_counts.get(BUCKET_MR_UNEXPECTED, 0) + 1
            per_doc.append({
                "doc_id": did,
                "bucket": BUCKET_MR_UNEXPECTED,
                "reason": "doc_not_found",
            })
            continue

        bucket, ctx = _classify_doc(doc)
        bucket_counts[bucket] = bucket_counts.get(bucket, 0) + 1
        per_doc.append({"doc_id": did, "bucket": bucket, "context": ctx})

        if apply and bucket == BUCKET_PROMOTED:
            try:
                result = await _apply_promotion(db, did, ctx, run_id)
                promote_results.append(result)
            except Exception as e:
                promote_failures.append({"doc_id": did, "error": str(e)})

    return {
        "run_id": run_id,
        "generated_at": _utc_iso(),
        "applied": apply,
        "doc_id_filter": doc_id_filter,
        "bucket_counts": bucket_counts,
        "per_doc": per_doc,
        "promote_results": promote_results,
        "promote_failures": promote_failures,
    }


# ---------------------------------------------------------------------------
# Revert paths
# ---------------------------------------------------------------------------


async def revert_doc(doc_id: str) -> Dict[str, Any]:
    db = _db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"doc_id": doc_id, "reverted": False, "reason": "doc_not_found"}
    history = doc.get("workflow_promotion_history") or []
    if not history:
        return {"doc_id": doc_id, "reverted": False, "reason": "no_promotion_history"}
    most_recent = history[-1]
    now = _utc_iso()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "status": most_recent.get("previous_status"),
                "workflow_status": most_recent.get("previous_workflow_status"),
            },
            "$pop": {"workflow_promotion_history": 1},
        },
    )
    try:
        await db.workflow_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "workflow.status_promoted_for_batch2_reverted",
            "status": "completed",
            "source_service": "workflow_status_orphan_unstick",
            "timestamp": now,
            "actor": None,
            "document_id": doc_id,
            "payload": {
                "reverted_entry": most_recent,
                "source": SCRIPT_VERSION,
            },
        })
    except Exception:
        pass
    return {"doc_id": doc_id, "reverted": True, "restored": most_recent}


async def revert_run(run_id: str) -> Dict[str, Any]:
    db = _db()
    doc_ids: List[str] = []
    cursor = db.workflow_events.find(
        {"event_type": "workflow.status_promoted_for_batch2",
         "payload.run_id": run_id},
        {"_id": 0, "document_id": 1},
    )
    async for e in cursor:
        if e.get("document_id"):
            doc_ids.append(e["document_id"])
    results = []
    for did in doc_ids:
        results.append(await revert_doc(did))
    return {
        "run_id": run_id,
        "reverted_count": sum(1 for r in results if r["reverted"]),
        "results": results,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_md(report: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Workflow-Status Orphan Unstick — `{report['run_id']}`")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Mode: **{'APPLY' if report['applied'] else 'DRY-RUN'}**")
    if report.get("doc_id_filter"):
        lines.append(f"- doc_id_filter: `{report['doc_id_filter']}`")
    lines.append("")
    lines.append("## Bucket counts")
    lines.append("")
    lines.append("| bucket | count |")
    lines.append("|---|---|")
    bucket_order = [
        BUCKET_PROMOTED, BUCKET_CLEAN,
        BUCKET_MR_VENDOR_DRIFT, BUCKET_MR_POSTED,
        BUCKET_MR_DUPLICATE, BUCKET_MR_UNEXPECTED,
        BUCKET_REJECTED,
    ]
    for b in bucket_order:
        n = report["bucket_counts"].get(b, 0)
        lines.append(f"| `{b}` | {n} |")
    lines.append("")
    lines.append("## Per-doc disposition")
    lines.append("")
    for row in report["per_doc"]:
        lines.append(f"### `{row['doc_id']}` → `{row['bucket']}`")
        ctx = row.get("context") or {}
        if ctx:
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(ctx, indent=2, default=str))
            lines.append("```")
        if row.get("reason"):
            lines.append(f"- reason: `{row['reason']}`")
        lines.append("")

    if report["applied"]:
        lines.append("## Promotion results")
        lines.append("")
        lines.append(f"- promoted: **{len([r for r in report['promote_results'] if r.get('promoted')])}**")
        lines.append(f"- failures: **{len(report['promote_failures'])}**")
        for f in report["promote_failures"]:
            lines.append(f"- ⚠ `{f['doc_id']}`: {f['error']}")
    return "\n".join(lines)


def _write_reports(report: Dict[str, Any]) -> Tuple[Path, Path]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    rid = report["run_id"]
    md_path = REPORT_DIR / f"WORKFLOW_STATUS_ORPHAN_UNSTICK_REPORT_{rid}.md"
    json_path = REPORT_DIR / f"WORKFLOW_STATUS_ORPHAN_UNSTICK_REPORT_{rid}.json"
    md_path.write_text(_render_md(report))
    json_path.write_text(json.dumps(report, indent=2, default=str))
    return md_path, json_path


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> int:
    if args.revert:
        result = await revert_doc(args.revert)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("reverted") else 2
    if args.revert_run:
        result = await revert_run(args.revert_run)
        print(json.dumps({"run_id": result["run_id"],
                          "reverted_count": result["reverted_count"]},
                         indent=2, default=str))
        return 0

    # Hard reject unknown --doc-id BEFORE any DB read
    if args.doc_id is not None and args.doc_id not in ALLOWED_DOC_IDS:
        print(f"ERROR: --doc-id {args.doc_id!r} is not in ALLOWED_DOC_IDS; refusing to act.",
              file=sys.stderr)
        return 3

    run_id = str(uuid.uuid4())
    print(f"[{_utc_iso()}] workflow_status orphan unstick — run_id={run_id}")
    print(f"  mode={'APPLY' if args.apply else 'DRY-RUN'}  filter={args.doc_id}")
    report = await sweep(
        apply=args.apply,
        doc_id_filter=args.doc_id,
        run_id=run_id,
    )
    md_path, json_path = _write_reports(report)
    print(f"  bucket_counts={report['bucket_counts']}")
    if args.apply:
        print(f"  promoted={len([r for r in report['promote_results'] if r.get('promoted')])}  "
              f"failures={len(report['promote_failures'])}")
    print("  reports:")
    print(f"    {md_path}")
    print(f"    {json_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--apply", action="store_true",
                   help="actually perform promotion writes (default: dry-run)")
    p.add_argument("--doc-id", default=None,
                   help="restrict to a single doc id (must be in ALLOWED_DOC_IDS)")
    p.add_argument("--revert", default=None,
                   help="revert a single doc's most-recent promotion")
    p.add_argument("--revert-run", default=None,
                   help="revert every doc touched by one run_id")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
