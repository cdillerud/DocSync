"""Hourly AP learning cycle: learn from every incoming document, with BC as truth.

Each cycle (LEARNING_CYCLE_MINUTES, default 60):
  1. bc_reconciliation_service.reconcile_recent: link AP documents to the
     BC purchase invoice they became; correct vendor / document type from
     BC; flag amount mismatches; BC order number feeds routing.
  2. scripts/bc_vendor_learning.py --apply: raw vendor names -> BC vendor
     numbers from exact BC pairs (aliases + document corrections).
  3. scripts/mark_invoice_duplicates.py (last 14 days): repeated copies of
     one invoice (same vendor, number, amount) marked duplicate.
  4. scripts/link_sales_docs_to_bc.py (last 30 days): sales documents
     linked to their BC order and customer; scripts/mark_split_continuations.py
     (last 30 days): split pages that continue an invoice marked.
  5. extraction_retry_service: recent AP documents with nothing extracted
     are re-extracted.
Routing learning from staff Square9 filings also runs hourly on a 72-hour
parity window (in addition to the daily readiness run). Each step is isolated: a
failure is logged and the cycle continues. Cycle summaries are stored in
learning_cycle_runs. LEARNING_CYCLE_ENABLED=false turns it off.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

APP_DIR = "/app"
CYCLE_MINUTES = int(os.environ.get("LEARNING_CYCLE_MINUTES", "60"))
ENABLED = os.environ.get("LEARNING_CYCLE_ENABLED", "true").lower() == "true"


async def _script(*args: str, timeout: int = 900) -> str:
    proc = await asyncio.create_subprocess_exec(
        "python3", *args, cwd=APP_DIR, env={**os.environ, "PYTHONPATH": APP_DIR},
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    lines = [l for l in out.decode("utf-8", "replace").splitlines() if l.strip()]
    return lines[-1] if lines else f"rc={proc.returncode}"


async def run_learning_cycle(db) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    summary: Dict[str, Any] = {"started_at": started.isoformat()}
    try:
        # CFDI XML (Mexican e-invoices) first: exact numbers/amounts for the
        # companion PDFs, so they can link to BC in this same cycle.
        from services.cfdi_service import process_recent as cfdi_process
        summary["cfdi"] = await cfdi_process(db)
    except Exception as e:
        summary["cfdi"] = {"error": repr(e)}
    try:
        # Invoice numbers that do not look like the vendor's numbers in BC
        # ("10" for NBC Packaging 1813556) -> the one in the subject / file name.
        from services.number_shape_service import correct_recent as shape_correct
        summary["number_shape"] = await shape_correct(db)
    except Exception as e:
        summary["number_shape"] = {"error": repr(e)}
    try:
        # The Gamer order when the PO field holds something else (glued
        # text, a vendor reference), confirmed against BC's known orders.
        from services.po_correction_service import correct_recent as po_correct
        summary["po_correction"] = await po_correct(db)
    except Exception as e:
        summary["po_correction"] = {"error": repr(e)}
    try:
        from services.bc_reconciliation_service import reconcile_recent
        summary["bc_reconciliation"] = await reconcile_recent(db)
        from services.bc_reconciliation_service import fetch_ship_to
        summary["bc_location"] = await fetch_ship_to(db)
        from services.lane_profile_service import rebuild_order_lanes
        summary["order_lanes"] = await rebuild_order_lanes(db)
    except Exception as e:
        summary["bc_reconciliation"] = {"error": repr(e)}
    try:
        from services.bc_amount_patterns_service import refresh_amount_patterns_from_bc
        summary["amount_patterns"] = await refresh_amount_patterns_from_bc(db)
    except Exception as e:
        summary["amount_patterns"] = {"error": repr(e)}
    try:
        from services.invoice_number_rules_service import learn_and_apply
        summary["invoice_number_rules"] = await learn_and_apply(db)
    except Exception as e:
        summary["invoice_number_rules"] = {"error": repr(e)}
    for key, args in (
        ("bc_vendor_learning", ("scripts/bc_vendor_learning.py", "--apply")),
        ("invoice_duplicates", ("scripts/mark_invoice_duplicates.py", "--since",
                                (started - timedelta(days=14)).date().isoformat(), "--apply")),
        ("sales_bc_link", ("scripts/link_sales_docs_to_bc.py", "--since",
                           (started - timedelta(days=30)).date().isoformat(), "--apply")),
        ("split_continuations", ("scripts/mark_split_continuations.py", "services/batch_po_splitter.py",
                                 "--since=" + (started - timedelta(days=30)).date().isoformat(), "--apply")),
    ):
        try:
            summary[key] = await _script(*args)
        except Exception as e:
            summary[key] = f"error: {e!r}"
    # Routing learning from staff Square9 filings, hourly: a short parity
    # window (72h, about 2 min, no efficacy writes) feeds the routing
    # learner, which counts each staff filing once (routing_learning_seen).
    try:
        summary["parity_72h"] = await _script(
            "scripts/square9_hub_ap_parity_report.py", "--since-hours", "72", "--hub-lookback-days", "14",
            "--limit", "20000", "--no-record-efficacy", "--out-csv", "prod_reports/parity_hourly.csv", timeout=1200)
        summary["routing_learning"] = await _script(
            "scripts/square9_daily_learning.py", "--csv", "prod_reports/parity_hourly.csv", "--confirm", "APPLY")
        from services.lane_profile_service import learn_from_csv
        summary["lane_profiles"] = await learn_from_csv(db, "/app/prod_reports/parity_hourly.csv")
        from services.lane_profile_service import learn_folders_from_csv
        summary["folder_profiles"] = await learn_folders_from_csv(db, "/app/prod_reports/parity_hourly.csv")
    except Exception as e:
        summary["routing_learning"] = f"error: {e!r}"
    try:
        # Correspondence intake typed AP_Invoice (tax-exemption requests,
        # statements, price notices) -> its real type.
        from services.non_ap_reclassifier import reclassify_recent
        summary["non_ap_reclassified"] = await reclassify_recent(db)
    except Exception as e:
        summary["non_ap_reclassified"] = {"error": repr(e)}
    try:
        # Routing path accuracy from the newest staff filings, then one stage
        # (and, when staff must act, one reason) per AP document.
        from services.ap_workflow_service import learn_people_and_approvers
        summary["ap_people"] = await learn_people_and_approvers(db, ["/app/prod_reports/parity_hourly.csv"])
        from services.ap_stage_service import measure_reason_accuracy, refresh_stages
        summary["routing_outcomes"] = await measure_reason_accuracy(db, "/app/prod_reports/parity_hourly.csv", "hourly")
        summary["ap_stages"] = await refresh_stages(db)
    except Exception as e:
        summary["ap_stages"] = {"error": repr(e)}
    try:
        # BC -> Hub: read the Hub's sandbox drafts back (still there? edited?
        # posted?) before drafting more.
        from services.draft_readback_service import readback
        summary["draft_readback"] = await readback(db)
    except Exception as e:
        summary["draft_readback"] = {"error": repr(e)}
    try:
        # Draft (never post) up to 10 ready AP invoices per hour in the PRE
        # sandbox; refuses unless writes are on and the target is PRE.
        from services.sandbox_draft_service import draft as sandbox_draft
        summary["sandbox_drafts"] = await sandbox_draft(db, limit=10)
        if summary["sandbox_drafts"].get("drafted"):
            summary["ap_stages_after_drafts"] = (await refresh_stages(db)).get("stages")
    except Exception as e:
        summary["sandbox_drafts"] = {"error": repr(e)}
    try:
        # Once a day: replay current intake logic against staff filings and BC.
        from services.learning_metrics_service import record_daily
        summary["learning_metrics"] = await record_daily(db)
    except Exception as e:
        summary["learning_metrics"] = {"error": repr(e)}
    try:
        from services.extraction_retry_service import retry_failed_extractions
        summary["extraction_retry"] = await retry_failed_extractions(db, limit=20)
    except Exception as e:
        summary["extraction_retry"] = {"error": repr(e)}
    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    try:
        await db.learning_cycle_runs.insert_one(dict(summary))
    except Exception:
        pass
    logger.info("[LearningCycle] %s", summary)
    return summary


async def learning_cycle_scheduler() -> None:
    """Run the learning cycle every CYCLE_MINUTES; first run 10 minutes after
    startup so it does not compete with startup work."""
    if not ENABLED:
        logger.info("[LearningCycle] disabled")
        return
    await asyncio.sleep(600)
    while True:
        try:
            from deps import get_db
            await run_learning_cycle(get_db())
        except Exception as e:
            logger.warning("[LearningCycle] cycle failed: %r", e)
        await asyncio.sleep(CYCLE_MINUTES * 60)
