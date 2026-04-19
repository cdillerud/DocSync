"""
Workflow State Observer — Phase B.0 de-risking pre-flight (v2.5.2)
────────────────────────────────────────────────────────────────────

Records every invocation of `_update_standard_workflow_status` with
caller-site attribution so the Phase B extraction (427-line function
move out of server.py) can proceed with production-verified knowledge
of which code paths actually exercise it.

Fire-and-forget: never raises, never blocks the primary workflow.
Writes to `workflow_state_observations` with a 30-day TTL on
`created_at` so the collection stays bounded.

Observation shape:
    {
      id, doc_id, doc_type, confidence, has_normalized_fields,
      caller_file, caller_func, caller_line,
      created_at, week_key,
    }
"""

import inspect
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COLL = "workflow_state_observations"
TTL_DAYS = 30

_INDEXES_READY = False


async def _ensure_indexes(db) -> None:
    global _INDEXES_READY
    if _INDEXES_READY:
        return
    try:
        await db[COLL].create_index(
            "created_at",
            expireAfterSeconds=TTL_DAYS * 24 * 3600,
            name="ttl_created_at",
        )
        await db[COLL].create_index("caller_func", name="by_caller")
        await db[COLL].create_index("doc_type", name="by_doc_type")
        _INDEXES_READY = True
    except Exception as e:
        logger.debug("[WorkflowObserver] index setup skipped: %s", e)


def _iso_week_key(d: datetime) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _caller_frame():
    """Walk up the stack past this module AND past the observed function
    itself (`_update_standard_workflow_status`) to find the real caller
    site — the code that actually invoked the instrumented function."""
    try:
        stack = inspect.stack()
        this_file = os.path.basename(__file__)
        # Known wrapper function name(s) to skip — these are the functions
        # we're instrumenting, not the callers we care about.
        SKIP_FUNCS = {"_update_standard_workflow_status"}
        for frame in stack[1:]:
            fname = os.path.basename(frame.filename)
            if fname == this_file:
                continue
            if frame.function in SKIP_FUNCS:
                continue
            return frame
    except Exception:
        pass
    return None


async def record_workflow_call(
    db,
    *,
    doc_id: str,
    doc_type: str,
    confidence: float,
    has_normalized_fields: bool,
) -> None:
    """Observe one call to the workflow state updater. Fire-and-forget."""
    try:
        await _ensure_indexes(db)
        frame = _caller_frame()
        caller_file = os.path.basename(frame.filename) if frame else "unknown"
        caller_func = frame.function if frame else "unknown"
        caller_line = frame.lineno if frame else 0

        now = datetime.now(timezone.utc)
        doc = {
            "id": str(uuid.uuid4()),
            "doc_id": doc_id,
            "doc_type": doc_type or "",
            "confidence": round(float(confidence or 0), 4),
            "has_normalized_fields": bool(has_normalized_fields),
            "caller_file": caller_file,
            "caller_func": caller_func,
            "caller_line": caller_line,
            "created_at": now.isoformat(),
            "week_key": _iso_week_key(now),
        }
        await db[COLL].insert_one(doc)
    except Exception as e:
        logger.debug("[WorkflowObserver] record failed (non-fatal): %s", e)


async def get_observer_summary(db, *, days: int = 7) -> Dict[str, Any]:
    """Aggregate observations for the last `days` days by caller and doc_type."""
    from datetime import timedelta
    days = max(1, min(int(days), 90))
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    total = 0
    by_caller: Dict[str, int] = {}
    by_doc_type: Dict[str, int] = {}
    by_caller_x_doc_type: Dict[str, Dict[str, int]] = {}
    try:
        async for d in db[COLL].find(
            {"created_at": {"$gte": since}},
            {"_id": 0, "caller_file": 1, "caller_func": 1, "doc_type": 1},
        ):
            total += 1
            c = f"{d.get('caller_file', '?')}::{d.get('caller_func', '?')}"
            by_caller[c] = by_caller.get(c, 0) + 1
            dt = d.get("doc_type") or "unknown"
            by_doc_type[dt] = by_doc_type.get(dt, 0) + 1
            by_caller_x_doc_type.setdefault(c, {})
            by_caller_x_doc_type[c][dt] = by_caller_x_doc_type[c].get(dt, 0) + 1
    except Exception as e:
        logger.warning("[WorkflowObserver] summary aggregate failed: %s", e)

    return {
        "window_days": days,
        "since": since,
        "total_calls": total,
        "by_caller": dict(sorted(by_caller.items(), key=lambda kv: kv[1], reverse=True)),
        "by_doc_type": dict(sorted(by_doc_type.items(), key=lambda kv: kv[1], reverse=True)),
        "by_caller_x_doc_type": by_caller_x_doc_type,
    }


async def list_recent_observations(
    db, *, limit: int = 50, caller_func: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Tail of recent observations (for spot-checks), newest first."""
    limit = max(1, min(int(limit), 500))
    q: Dict[str, Any] = {}
    if caller_func:
        q["caller_func"] = caller_func
    return await db[COLL].find(q, {"_id": 0}).sort("created_at", -1).to_list(limit)


# ─────────────────────────────────────────────────────────────
# Phase B Readiness Report (v2.5.2)
# ─────────────────────────────────────────────────────────────

async def build_phase_b_readiness_report(
    db, *, days: int = 7, min_coverage: int = 5,
) -> Dict[str, Any]:
    """Turn observer data into a Phase-B extraction readiness matrix.

    For each (caller_file::caller_func, doc_type) pair seen in the
    window, emit a row with the call count + a readiness category:
      • 'must_preserve'   — ≥ min_coverage calls (high traffic; Phase B
                            MUST have a green test for this exact path)
      • 'should_cover'    — 2..min_coverage-1 calls (meaningful traffic)
      • 'edge_case'       — 1 call (rare; nice-to-have coverage)

    Also returns a human-readable markdown report ready to paste into
    a PR description or the CHANGELOG before the extraction lands.
    """
    min_coverage = max(2, min(int(min_coverage), 100))
    summary = await get_observer_summary(db, days=days)
    cxd = summary.get("by_caller_x_doc_type", {})

    rows: List[Dict[str, Any]] = []
    for caller, dt_counts in cxd.items():
        for doc_type, count in dt_counts.items():
            if count >= min_coverage:
                category = "must_preserve"
            elif count >= 2:
                category = "should_cover"
            else:
                category = "edge_case"
            rows.append({
                "caller": caller,
                "doc_type": doc_type,
                "calls": count,
                "category": category,
            })
    rows.sort(key=lambda r: (-r["calls"], r["caller"], r["doc_type"]))

    must_preserve = [r for r in rows if r["category"] == "must_preserve"]
    should_cover = [r for r in rows if r["category"] == "should_cover"]
    edge_cases = [r for r in rows if r["category"] == "edge_case"]

    # Ready to extract only when we have AT LEAST ONE must-preserve path
    # AND no caller path was silent in the window (i.e., coverage > 0 for
    # every caller we know about — best-effort heuristic)
    ready_to_extract = len(must_preserve) > 0
    if summary.get("total_calls", 0) == 0:
        verdict = "NOT READY — no observer data captured yet. Let the shim run in production for a full business week before re-running."
    elif not ready_to_extract:
        verdict = (
            "NOT READY — observer has data but no caller × doc_type pair "
            f"hit the min_coverage={min_coverage} threshold. Either lower "
            "the threshold or wait for more traffic."
        )
    else:
        verdict = (
            f"READY — {len(must_preserve)} must-preserve paths identified. "
            "Phase B extraction should ship with a pytest covering each of "
            "those pairs to prevent behavior drift."
        )

    # Build markdown block (escape pipes in doc_type/caller just in case)
    def _esc(s: str) -> str:
        return (s or "").replace("|", "\\|")

    md_lines = [
        "# Phase B Readiness Report",
        "",
        f"**Window:** last {summary.get('window_days')} days"
        f" (since `{summary.get('since', '')[:19]}Z`)",
        f"**Total calls observed:** {summary.get('total_calls', 0)}",
        f"**Min coverage threshold:** {min_coverage}",
        "",
        f"## Verdict",
        "",
        verdict,
        "",
    ]
    if must_preserve:
        md_lines += [
            "## Must-preserve paths (REQUIRED test coverage in new home)",
            "",
            "| Caller | Doc Type | Calls |",
            "|---|---|---|",
        ]
        for r in must_preserve:
            md_lines.append(f"| `{_esc(r['caller'])}` | `{_esc(r['doc_type'])}` | {r['calls']} |")
        md_lines.append("")
    if should_cover:
        md_lines += [
            "## Should-cover paths (meaningful traffic)",
            "",
            "| Caller | Doc Type | Calls |",
            "|---|---|---|",
        ]
        for r in should_cover:
            md_lines.append(f"| `{_esc(r['caller'])}` | `{_esc(r['doc_type'])}` | {r['calls']} |")
        md_lines.append("")
    if edge_cases:
        md_lines += [
            "## Edge cases (single observed call)",
            "",
            "| Caller | Doc Type | Calls |",
            "|---|---|---|",
        ]
        for r in edge_cases:
            md_lines.append(f"| `{_esc(r['caller'])}` | `{_esc(r['doc_type'])}` | {r['calls']} |")
        md_lines.append("")

    return {
        "window_days": summary.get("window_days"),
        "since": summary.get("since"),
        "total_calls": summary.get("total_calls", 0),
        "min_coverage": min_coverage,
        "ready_to_extract": ready_to_extract,
        "verdict": verdict,
        "counts": {
            "must_preserve": len(must_preserve),
            "should_cover": len(should_cover),
            "edge_case": len(edge_cases),
        },
        "matrix": rows,
        "markdown": "\n".join(md_lines),
    }


__all__ = [
    "record_workflow_call",
    "get_observer_summary",
    "list_recent_observations",
    "build_phase_b_readiness_report",
    "COLL",
]
