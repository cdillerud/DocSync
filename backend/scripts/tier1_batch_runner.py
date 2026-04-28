"""
Tier 1 Batch Runner — controlled AP-to-BC-Sandbox posting harness.

Phases (CLI subcommands):
  preflight   — run 5 pre-batch verification checks; abort on any miss
  select      — select up to 10 candidate AP_Invoice docs and print summary
  dry-run     — for each candidate, show vendor re-resolve + dup-check + line completeness
  post        — sequentially POST each candidate; classify pass/fail buckets
                ⚠️  REQUIRES --confirm flag; refuses to write without it

Safety fences:
  - All writes target BC_WRITE_ENVIRONMENT (currently Sandbox_11_3_2025).
  - BC_BLOCK_PRODUCTION_WRITES=true is observed at every step.
  - Hard cap: 10 documents per run. Sequential. 60s per-doc timeout.
  - Auto-stop on first F-BUG OR repeatable malformed posting behavior
    (defined: 2 consecutive identical 4xx/5xx response shapes).
  - Single new file: appends to /app/memory/TIER1_BATCH_RESULTS.md.

Usage:
  python /app/backend/scripts/tier1_batch_runner.py preflight
  python /app/backend/scripts/tier1_batch_runner.py select
  python /app/backend/scripts/tier1_batch_runner.py dry-run
  python /app/backend/scripts/tier1_batch_runner.py post --confirm
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure we can import backend modules and that .env is loaded
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass

import httpx
from motor.motor_asyncio import AsyncIOMotorClient


WORKSHEET_PATH = Path("/app/memory/TIER1_BATCH_RESULTS.md")
BATCH_LIMIT = 10
PER_DOC_TIMEOUT_SECONDS = 60
INTER_DOC_PAUSE_SECONDS = 2
LOCAL_API = "http://localhost:8001"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short(s: Any, n: int = 60) -> str:
    txt = str(s) if s is not None else ""
    return txt if len(txt) <= n else txt[: n - 1] + "…"


# ---------------------------------------------------------------------------
# Shared infra
# ---------------------------------------------------------------------------


def _db():
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    return AsyncIOMotorClient(url)[name]


@dataclass
class Candidate:
    doc_id: str
    vendor_name: str
    vendor_no: Optional[str]
    invoice_number: str
    invoice_date: str
    total_amount: Any
    line_count: int
    status: str
    workflow_status: str
    document_type: str
    risks: List[str] = field(default_factory=list)
    duplicate_check: str = "unchecked"
    duplicate_detail: str = ""


@dataclass
class PostResult:
    doc_id: str
    bucket: str  # P1 / P2 / F-CONFIG / F-AUTH / F-REF / F-DATA / F-DUP / F-RULE / F-NETWORK / F-BUG
    bc_invoice_number: Optional[str]
    http_status: Optional[int]
    elapsed_ms: int
    detail: str
    raw_response_shape: Optional[str] = None  # used for repeatable-malformed detection


# ---------------------------------------------------------------------------
# Phase 1 — preflight
# ---------------------------------------------------------------------------


async def phase_preflight() -> bool:
    print("=" * 72)
    print(f"[{_utc_iso()}] PHASE 1 — PRE-BATCH VERIFICATION")
    print("=" * 72)

    checks: List[Dict[str, Any]] = []

    sandbox_config: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=10) as client:
        # 1. Basic backend health
        try:
            r = await client.get(f"{LOCAL_API}/api/health")
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            ok = r.status_code == 200 and j.get("status") == "healthy"
            checks.append({"name": "1. Backend /api/health", "ok": ok, "status": r.status_code, "body": _short(j, 220)})
        except Exception as e:
            checks.append({"name": "1. Backend /api/health", "ok": False, "status": None, "body": f"ERR {e}"})

        # 2. BC sandbox status (write target + block_prod confirmation)
        try:
            r = await client.get(f"{LOCAL_API}/api/bc-sandbox/status")
            j = r.json() if r.status_code == 200 else {}
            sandbox_config = (j.get("config") or {}) if isinstance(j, dict) else {}
            ok = (
                r.status_code == 200
                and str(sandbox_config.get("write_environment", "")).startswith("Sandbox")
                and sandbox_config.get("block_production_writes") is True
            )
            checks.append({
                "name": "2. BC sandbox status (write→Sandbox, block_prod=true)",
                "ok": ok,
                "status": r.status_code,
                "body": f"write_env={sandbox_config.get('write_environment')}, block_prod={sandbox_config.get('block_production_writes')}, "
                        f"pilot_mode={j.get('pilot_mode')}, read_only={j.get('read_only')}",
            })
        except Exception as e:
            checks.append({"name": "2. BC sandbox status", "ok": False, "status": None, "body": f"ERR {e}"})

        # 3. BC catalog freshness (advisory — 168h ≈ 7 days is the soft limit)
        try:
            r = await client.get(f"{LOCAL_API}/api/gpi-integration/catalog/health")
            j = r.json() if r.status_code == 200 else {}
            age = j.get("sync_age_hours")
            ok = r.status_code == 200 and isinstance(age, (int, float)) and age < 24 * 7
            checks.append({
                "name": "3. BC catalog freshness (<7d)",
                "ok": ok,
                "status": r.status_code,
                "body": f"item_count={j.get('item_count')}, gl_account_count={j.get('gl_account_count')}, "
                        f"sync_age_hours={age}, is_stale={j.get('is_stale')}",
            })
        except Exception as e:
            checks.append({"name": "3. BC catalog freshness", "ok": False, "status": None, "body": f"ERR {e}"})

        # 4. AP metrics dashboard
        try:
            r = await client.get(f"{LOCAL_API}/api/dashboard/ap-metrics")
            checks.append({
                "name": "4. AP metrics dashboard",
                "ok": r.status_code == 200,
                "status": r.status_code,
                "body": "200 OK" if r.status_code == 200 else _short(r.text, 220),
            })
        except Exception as e:
            checks.append({"name": "4. AP metrics dashboard", "ok": False, "status": None, "body": f"ERR {e}"})

    # 5. Resolved-config sanity (read from /api/bc-sandbox/status response — uses the
    #    same fallback chain the production code uses, so no drift across env-var
    #    naming conventions: BC_WRITE_ENVIRONMENT → BC_SANDBOX_ENVIRONMENT → BC_ENVIRONMENT, etc.)
    write_env = str(sandbox_config.get("write_environment") or "")
    block_prod = sandbox_config.get("block_production_writes")
    config_issues = []
    if not write_env.lower().startswith("sandbox"):
        config_issues.append(f"resolved write_environment={write_env!r} does not start with 'Sandbox'")
    if block_prod is not True:
        config_issues.append(f"resolved block_production_writes={block_prod!r}, expected True")
    checks.append({
        "name": "5. Resolved BC config (write→Sandbox, block_prod=True)",
        "ok": not config_issues,
        "status": None,
        "body": "OK" if not config_issues else "; ".join(config_issues),
    })

    # 6. BC credential plausibility (read from /api/bc-sandbox/status — the resolved
    #    runtime values, not raw env vars, so naming differences across envs don't
    #    cause false negatives.)
    import re
    GUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
    PLACEHOLDER_HINTS = ("test", "example", "placeholder", "demo", "doc-workflow", "order-ledger", "your-")
    cred_issues = []
    for label, key in (("client_id", "client_id"), ("tenant_id", "tenant_id")):
        v = str(sandbox_config.get(key) or "").strip()
        if not v:
            cred_issues.append(f"resolved {label} is missing from /api/bc-sandbox/status")
            continue
        if not GUID_RE.match(v):
            hint = next((h for h in PLACEHOLDER_HINTS if h in v.lower()), None)
            if hint:
                cred_issues.append(f"resolved {label}={v!r} contains placeholder hint {hint!r} — not a real GUID")
            else:
                cred_issues.append(f"resolved {label}={v!r} is not a GUID — likely a placeholder")
    checks.append({
        "name": "6. BC credential plausibility (real GUIDs in resolved config?)",
        "ok": not cred_issues,
        "status": None,
        "body": "OK — resolved client_id and tenant_id look like real Azure GUIDs"
                if not cred_issues
                else "PLACEHOLDER DETECTED: " + "; ".join(cred_issues)
                     + ". This environment cannot reach BC; run Tier 1 on the production VM instead.",
    })

    for c in checks:
        marker = "✅" if c["ok"] else "❌"
        print(f"  {marker} {c['name']:60s} status={c['status']}  body={c['body']}")

    all_ok = all(c["ok"] for c in checks)
    print("-" * 72)
    print(f"  RESULT: {'PASS' if all_ok else 'FAIL'} — preflight {'allows' if all_ok else 'blocks'} batch.")
    return all_ok


# ---------------------------------------------------------------------------
# Phase 2 — candidate selection
# ---------------------------------------------------------------------------


async def _select_candidates(db, limit: int = BATCH_LIMIT) -> List[Candidate]:
    """Pull up to `limit` AP_Invoice docs ordered by posting-readiness.

    Tier 1 selection priority (highest first):
      1. status=ReadyForPost  ← gold tier (already approved for posting)
      2. status in {Validated, ValidationPassed, NeedsReview}
      3. status=Completed but workflow_status in {approved, ready_for_post}

    Selection is read-only and deliberately tolerant: docs without a pre-stamped
    vendor_no are accepted because the dry-run does vendor re-resolution against
    aliases + invoice profiles. Field name is `amount` on the live VM dataset
    (preview env used `total`), so we read both with `amount` first.
    """
    base_match = {
        "document_type": "AP_Invoice",
        "$or": [
            {"vendor_canonical": {"$nin": [None, ""]}},
            {"validation_results.bc_record_info.number": {"$nin": [None, ""]}},
            {"extracted_fields.vendor": {"$nin": [None, ""]}},
            {"normalized_fields.vendor": {"$nin": [None, ""]}},
        ],
        # Not already posted to BC
        "$and": [{"$or": [
            {"bc_purchase_invoice": {"$exists": False}},
            {"bc_purchase_invoice": None},
            {"bc_purchase_invoice": ""},
        ]}],
    }
    add_fields = {
        "_inv_no": {"$ifNull": [
            "$extracted_fields.invoice_number",
            "$normalized_fields.invoice_number",
        ]},
        "_total": {"$ifNull": [
            "$extracted_fields.amount",
            "$extracted_fields.total",
            "$normalized_fields.amount",
            "$normalized_fields.total",
        ]},
        "_lines": {"$size": {"$ifNull": ["$extracted_fields.line_items", []]}},
    }
    have_data_match = {
        "_inv_no": {"$nin": [None, ""]},
        "_total": {"$nin": [None, 0, "0", ""]},
    }

    # Ordered status tiers; query each until we hit `limit`.
    tiers = [
        ("ReadyForPost (gold)", {"status": "ReadyForPost"}),
        ("Validated/ValidationPassed/NeedsReview",
         {"status": {"$in": ["Validated", "ValidationPassed", "NeedsReview"]}}),
        ("Completed + workflow approved/ready_for_post",
         {"status": "Completed", "workflow_status": {"$in": ["approved", "ready_for_post"]}}),
    ]

    seen_ids: set = set()
    docs: List[Dict[str, Any]] = []
    for label, status_filter in tiers:
        if len(docs) >= limit:
            break
        pipe = [
            {"$match": {**base_match, **status_filter}},
            {"$addFields": add_fields},
            {"$match": have_data_match},
            {"$sort": {"created_utc": -1}},
            {"$limit": limit - len(docs)},
        ]
        async for d in db.hub_documents.aggregate(pipe):
            if d["id"] in seen_ids:
                continue
            seen_ids.add(d["id"])
            d["_tier"] = label
            docs.append(d)
            if len(docs) >= limit:
                break

    candidates: List[Candidate] = []
    for d in docs:
        ef = d.get("extracted_fields") or {}
        nf = d.get("normalized_fields") or {}
        vr = d.get("validation_results") or {}
        bc_info = (vr.get("bc_record_info") or {}) if isinstance(vr, dict) else {}
        line_items = ef.get("line_items") or []
        vendor_no = (
            d.get("vendor_canonical")
            or bc_info.get("number")
            or d.get("vendor_no")
            or ""
        )
        total_value = (
            ef.get("amount")
            or ef.get("total")
            or nf.get("amount")
            or nf.get("total")
        )
        candidates.append(Candidate(
            doc_id=d["id"],
            vendor_name=ef.get("vendor") or nf.get("vendor") or bc_info.get("displayName") or "",
            vendor_no=vendor_no or None,
            invoice_number=ef.get("invoice_number") or nf.get("invoice_number") or "",
            invoice_date=ef.get("invoice_date") or nf.get("invoice_date") or "",
            total_amount=total_value,
            line_count=len(line_items) if isinstance(line_items, list) else 0,
            status=d.get("status", ""),
            workflow_status=d.get("workflow_status", ""),
            document_type=d.get("document_type", ""),
        ))
    return candidates


async def phase_select() -> List[Candidate]:
    print("=" * 72)
    print(f"[{_utc_iso()}] PHASE 2 — CANDIDATE SELECTION (limit {BATCH_LIMIT})")
    print("=" * 72)
    db = _db()
    cands = await _select_candidates(db)
    print(f"  Selected {len(cands)} candidates.\n")
    if not cands:
        print("  ⚠️  No candidates matched. Running diagnostic to surface why.\n")
        # Show what AP-ish data actually looks like on this DB
        ap_like = await db.hub_documents.count_documents({
            "$or": [
                {"document_type": {"$regex": "^AP", "$options": "i"}},
                {"doc_type": {"$regex": "^AP", "$options": "i"}},
            ]
        })
        print(f"  AP-ish docs (document_type|doc_type starts with 'AP'): {ap_like}")

        for fld in ("document_type", "doc_type", "status", "workflow_status"):
            print(f"\n  distinct {fld}:")
            pipe = [
                {"$match": {"$or": [
                    {"document_type": {"$regex": "^AP", "$options": "i"}},
                    {"doc_type": {"$regex": "^AP", "$options": "i"}},
                ]}},
                {"$group": {"_id": f"${fld}", "n": {"$sum": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 10},
            ]
            async for r in db.hub_documents.aggregate(pipe):
                print(f"    {str(r['_id']):40s} {r['n']}")

        already_posted = await db.hub_documents.count_documents({
            "$or": [
                {"document_type": {"$regex": "^AP", "$options": "i"}},
                {"doc_type": {"$regex": "^AP", "$options": "i"}},
            ],
            "bc_purchase_invoice": {"$exists": True},
        })
        print(f"\n  AP-ish docs already posted (bc_purchase_invoice exists): {already_posted}")

        # Check filter components individually so we know which one is too strict
        base = {"$or": [
            {"document_type": {"$regex": "^AP", "$options": "i"}},
            {"doc_type": {"$regex": "^AP", "$options": "i"}},
        ]}
        c_status = await db.hub_documents.count_documents({**base, "status": {"$in": ["NeedsReview", "ReadyForPost", "Completed"]}})
        c_vendor = await db.hub_documents.count_documents({**base, "$and": [{"$or": [
            {"vendor_canonical": {"$nin": [None, ""]}},
            {"validation_results.bc_record_info.number": {"$nin": [None, ""]}},
            {"extracted_fields.vendor": {"$nin": [None, ""]}},
            {"normalized_fields.vendor": {"$nin": [None, ""]}},
        ]}]})
        c_inv = await db.hub_documents.count_documents({**base, "$or": [
            {"extracted_fields.invoice_number": {"$nin": [None, ""]}},
            {"normalized_fields.invoice_number": {"$nin": [None, ""]}},
        ]})
        c_total = await db.hub_documents.count_documents({**base, "$or": [
            {"extracted_fields.total": {"$nin": [None, 0, "0", ""]}},
            {"normalized_fields.total": {"$nin": [None, 0, "0", ""]}},
        ]})
        print("\n  Per-criterion candidate counts (AP-ish base):")
        print(f"    status in {{NeedsReview, ReadyForPost, Completed}}: {c_status}")
        print(f"    has vendor signal:                                   {c_vendor}")
        print(f"    has invoice_number:                                  {c_inv}")
        print(f"    has non-zero total:                                  {c_total}")

        # Sample one AP-ish doc to see field layout
        sample = await db.hub_documents.find_one({"$or": [
            {"document_type": {"$regex": "^AP", "$options": "i"}},
            {"doc_type": {"$regex": "^AP", "$options": "i"}},
        ]}, {"_id": 0, "id": 1, "document_type": 1, "doc_type": 1, "status": 1, "workflow_status": 1,
              "extracted_fields": 1, "normalized_fields": 1, "vendor_canonical": 1,
              "bc_purchase_invoice": 1})
        if sample:
            print("\n  Sample AP-ish doc shape (first match):")
            for k in ("id", "document_type", "doc_type", "status", "workflow_status", "vendor_canonical", "bc_purchase_invoice"):
                print(f"    {k}: {sample.get(k)}")
            ef = sample.get("extracted_fields") or {}
            print(f"    extracted_fields keys: {sorted(ef.keys())[:15]}")
            for fk in ("vendor", "invoice_number", "total", "invoice_date"):
                print(f"      extracted_fields.{fk}: {ef.get(fk)}")

        print("\n  → Bring this output back to me. I'll widen the candidate query to match your actual data shape.")
        return cands

    print(f"  {'#':<3} {'tier':<32} {'doc_id':<38} {'vendor':<28} {'inv #':<14} {'total':<12} {'lines':<5}")
    print("  " + "-" * 137)
    for i, c in enumerate(cands, 1):
        tier = c.workflow_status or c.status
        print(f"  {i:<3} {_short(tier, 30):<32} {c.doc_id:<38} {_short(c.vendor_name, 26):<28} {_short(c.invoice_number, 12):<14} "
              f"{str(c.total_amount):<12} {c.line_count:<5}")
    return cands


# ---------------------------------------------------------------------------
# Phase 3 — dry-run normalization (vendor + dup + line completeness + risks)
# ---------------------------------------------------------------------------


async def _dup_check(db, candidate: Candidate) -> tuple[str, str]:
    """Return (status, detail) for a duplicate check against bc_reference_cache."""
    if not candidate.invoice_number:
        return ("skip", "no invoice number to check")
    q = {
        "type": "purchase_invoice",
        "data.vendorInvoiceNumber": candidate.invoice_number,
    }
    if candidate.vendor_no:
        q["data.vendorNumber"] = candidate.vendor_no
    hit = await db.bc_reference_cache.find_one(q, {"_id": 0, "data.number": 1, "data.vendorNumber": 1})
    if hit:
        return ("HIT", f"BC already has PI {hit.get('data',{}).get('number','?')} for vendor {hit.get('data',{}).get('vendorNumber','?')}")
    return ("clean", "")


async def _vendor_resolve(db, candidate: Candidate) -> tuple[str, str]:
    """Try to resolve a vendor by name through aliases + invoice profiles. Read-only."""
    if candidate.vendor_no:
        return (candidate.vendor_no, "pre-stamped on doc")
    name = (candidate.vendor_name or "").strip()
    if not name:
        return ("", "no vendor name available")
    # 1) alias hit
    a = await db.vendor_aliases.find_one(
        {"$or": [{"alias": name}, {"alias_normalized": name.lower()}]},
        {"_id": 0, "vendor_no": 1, "alias": 1},
    )
    if a and a.get("vendor_no"):
        return (a["vendor_no"], f"alias '{a.get('alias','')}'")
    # 2) profile hit
    p = await db.vendor_invoice_profiles.find_one(
        {"$or": [{"vendor_name": name}, {"vendor_name_normalized": name.lower()}]},
        {"_id": 0, "vendor_no": 1, "vendor_name": 1},
    )
    if p and p.get("vendor_no"):
        return (p["vendor_no"], f"profile '{p.get('vendor_name','')}'")
    return ("", f"no alias or profile match for {name!r}")


async def phase_dry_run(candidates: List[Candidate]) -> List[Candidate]:
    print("=" * 72)
    print(f"[{_utc_iso()}] PHASE 3 — DRY-RUN NORMALIZATION")
    print("=" * 72)
    if not candidates:
        return candidates
    db = _db()
    for c in candidates:
        # vendor re-resolve
        v_no, v_method = await _vendor_resolve(db, c)
        if v_no and v_no != c.vendor_no:
            c.vendor_no = v_no
            c.risks.append(f"vendor will be resolved at post via {v_method}")
        elif not v_no:
            c.risks.append(f"NO VENDOR — cannot post until resolved ({v_method})")

        # dup check
        dup_status, dup_detail = await _dup_check(db, c)
        c.duplicate_check = dup_status
        c.duplicate_detail = dup_detail
        if dup_status == "HIT":
            c.risks.append(f"DUPLICATE in BC: {dup_detail}")

        # line completeness
        if c.line_count == 0:
            c.risks.append("zero line items extracted — endpoint may post a header-only PI")

        # invoice basics
        if not c.invoice_number:
            c.risks.append("missing invoice_number")
        if not c.total_amount or c.total_amount == 0:
            c.risks.append("missing or zero total amount")
        if not c.invoice_date:
            c.risks.append("missing invoice_date — will default to today")

        # cap to top 2 risks for display
        c.risks = c.risks[:2]

    # Print the per-candidate report exactly as the user requested
    print("  Per-candidate review (top 1–2 risks each):\n")
    for i, c in enumerate(candidates, 1):
        print(f"  [{i}] doc_id={c.doc_id}")
        print(f"      vendor:       {c.vendor_name or '(none)'}  ({c.vendor_no or 'unresolved'})")
        print(f"      invoice_no:   {c.invoice_number or '(missing)'}")
        print(f"      total:        {c.total_amount}")
        print(f"      duplicate:    {c.duplicate_check}  {('— ' + c.duplicate_detail) if c.duplicate_detail else ''}")
        if c.risks:
            print("      risks:        " + "; ".join(c.risks))
        else:
            print("      risks:        none")
        print()
    return candidates


# ---------------------------------------------------------------------------
# Phase 4 — post (requires --confirm)
# ---------------------------------------------------------------------------


def _classify(http_status: Optional[int], body: Dict[str, Any] | str, exc: Optional[Exception]) -> str:
    """Map an HTTP response (or exception) to a Tier 1 bucket."""
    if exc is not None:
        msg = str(exc).lower()
        if "timeout" in msg or "connect" in msg:
            return "F-NETWORK"
        return "F-BUG"
    if http_status is None:
        return "F-NETWORK"
    if isinstance(body, dict):
        # success path
        if http_status == 200 and (body.get("success") or body.get("bc_record_no") or body.get("already_exists")):
            if body.get("already_exists"):
                return "F-DUP"
            return "P1"
        detail = ""
        if isinstance(body.get("detail"), dict):
            detail = json.dumps(body["detail"]).lower()
        elif isinstance(body.get("detail"), str):
            detail = body["detail"].lower()
        elif isinstance(body, dict):
            detail = json.dumps(body).lower()
        if http_status in (401, 403):
            return "F-AUTH"
        if http_status == 422:
            if "missing_vendor" in detail or "vendor" in detail:
                return "F-REF"
            if "duplicate" in detail or "already" in detail:
                return "F-DUP"
            return "F-DATA"
        if http_status == 404:
            return "F-DATA"
        if http_status == 503:
            return "F-CONFIG"
        if 500 <= http_status < 600:
            if "rule" in detail or "period" in detail or "closed" in detail or "on hold" in detail:
                return "F-RULE"
            return "F-BUG"
        if 400 <= http_status < 500:
            return "F-DATA"
    return "F-BUG"


def _shape_signature(http_status: Optional[int], body: Any) -> str:
    """Compact signature used to detect repeatable malformed posting behavior."""
    if isinstance(body, dict):
        keys = sorted(list(body.keys()))[:6]
        detail = body.get("detail") or body.get("error") or body.get("message") or ""
        if isinstance(detail, dict):
            detail = json.dumps(detail, sort_keys=True)
        return f"{http_status}|{','.join(keys)}|{_short(detail, 80)}"
    return f"{http_status}|str|{_short(body, 80)}"


async def phase_post(candidates: List[Candidate]) -> List[PostResult]:
    print("=" * 72)
    print(f"[{_utc_iso()}] PHASE 4 — SEQUENTIAL SANDBOX POST (cap {BATCH_LIMIT}, timeout {PER_DOC_TIMEOUT_SECONDS}s/doc)")
    print("=" * 72)
    if not candidates:
        return []

    # Initialize worksheet with a header for this run
    WORKSHEET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with WORKSHEET_PATH.open("a") as fh:
        fh.write(f"\n## Batch run @ {_utc_iso()}  (write_env={os.environ.get('BC_WRITE_ENVIRONMENT')})\n\n")
        fh.write("| # | doc_id | vendor | inv# | total | dup | bucket | bc_invoice_no | http | ms | detail |\n")
        fh.write("|---|---|---|---|---|---|---|---|---|---|---|\n")

    results: List[PostResult] = []
    last_signature: Optional[str] = None
    consecutive_same = 0
    # Track which doc_ids had 0 line items going into the post — used for the
    # "policy decision" annotation on successful posts.
    zero_line_doc_ids = {c.doc_id for c in candidates if c.line_count == 0}

    async with httpx.AsyncClient(timeout=PER_DOC_TIMEOUT_SECONDS) as client:
        for i, c in enumerate(candidates, 1):
            print(f"  [{i}/{len(candidates)}] POST doc {c.doc_id} (vendor={_short(c.vendor_name,30)}  inv={c.invoice_number}) ...")
            t0 = time.time()
            url = f"{LOCAL_API}/api/gpi-integration/purchase-invoices/from-document/{c.doc_id}"
            http_status: Optional[int] = None
            body: Any = None
            exc: Optional[Exception] = None
            try:
                r = await client.post(url)
                http_status = r.status_code
                try:
                    body = r.json()
                except Exception:
                    body = r.text
            except Exception as e:
                exc = e

            elapsed_ms = int((time.time() - t0) * 1000)
            bucket = _classify(http_status, body, exc)
            bc_no = ""
            if isinstance(body, dict):
                bc_no = body.get("bc_record_no") or body.get("bc_invoice_number") or ""
            sig = _shape_signature(http_status, body)
            detail = _short(body, 200) if exc is None else f"EXC {exc}"
            # Policy-decision annotation: a successful post of a 0-line doc
            # means BC accepted a header-only PI. That is *technically* a P1,
            # but the operator needs to decide whether to allow it.
            if bucket in ("P1", "P2") and c.doc_id in zero_line_doc_ids:
                bucket = f"{bucket}-POLICY"
                detail = f"[POLICY DECISION: header-only PI accepted by BC] {detail}"
            res = PostResult(
                doc_id=c.doc_id,
                bucket=bucket,
                bc_invoice_number=bc_no or None,
                http_status=http_status,
                elapsed_ms=elapsed_ms,
                detail=detail,
                raw_response_shape=sig,
            )
            results.append(res)

            # Worksheet append
            with WORKSHEET_PATH.open("a") as fh:
                fh.write(
                    f"| {i} | `{c.doc_id}` | {_short(c.vendor_name,28)} | {_short(c.invoice_number,12)} | "
                    f"{c.total_amount} | {c.duplicate_check} | **{bucket}** | {bc_no or '-'} | "
                    f"{http_status if http_status is not None else 'EXC'} | {elapsed_ms} | {_short(detail,80)} |\n"
                )

            print(f"      → bucket={bucket}  http={http_status}  bc_no={bc_no or '-'}  ({elapsed_ms} ms)")

            # Hard stop on F-BUG
            if bucket == "F-BUG":
                print("      🛑 F-BUG detected — aborting batch.")
                break

            # Stop on repeatable malformed posting behavior:
            # 2 consecutive identical 4xx/5xx response shapes that aren't success buckets
            success_buckets = ("P1", "P2", "P1-POLICY", "P2-POLICY", "F-DUP")
            if bucket not in success_buckets:
                if sig == last_signature:
                    consecutive_same += 1
                else:
                    consecutive_same = 1
                last_signature = sig
                if consecutive_same >= 2:
                    print(f"      🛑 Repeatable malformed posting behavior detected (sig={sig!r}); aborting batch.")
                    break
            else:
                last_signature = None
                consecutive_same = 0

            await asyncio.sleep(INTER_DOC_PAUSE_SECONDS)

    return results


# ---------------------------------------------------------------------------
# Phase 5 — summary
# ---------------------------------------------------------------------------


def phase_summary(results: List[PostResult]) -> None:
    print("=" * 72)
    print(f"[{_utc_iso()}] PHASE 5 — BATCH SUMMARY")
    print("=" * 72)
    if not results:
        print("  No posting results to summarize.")
        return
    import math
    counts = Counter(r.bucket for r in results)
    n = len(results)
    print(f"  Posted: {n}")
    for bucket in (
        "P1", "P2", "P1-POLICY", "P2-POLICY",
        "F-DUP", "F-CONFIG", "F-AUTH", "F-REF",
        "F-DATA", "F-RULE", "F-NETWORK", "F-BUG",
    ):
        if counts.get(bucket):
            print(f"    {bucket:12s} {counts[bucket]}")
    pass_count = sum(counts.get(b, 0) for b in ("P1", "P2", "P1-POLICY", "P2-POLICY"))
    threshold = max(1, math.ceil(n * 0.7))
    print()
    if any(b.endswith("-POLICY") for b in counts):
        print("  ⚠️  POLICY DECISION items present — header-only PIs were accepted by BC.")
        print("      Review whether to allow header-only PIs operationally before promoting this path.")
        print()
    print(f"  PASS criterion: ≥{threshold}/{n} in (P1+P2+POLICY) with zero F-BUG.")
    viable = (pass_count >= threshold) and (counts.get("F-BUG", 0) == 0)
    print(f"  RESULT: {'✅ TIER 1 VIABLE' if viable else '❌ NOT YET — see worksheet for fix targets'}")
    print(f"  Worksheet: {WORKSHEET_PATH}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> int:
    if args.cmd == "preflight":
        ok = await phase_preflight()
        return 0 if ok else 2

    if args.cmd == "select":
        await phase_select()
        return 0

    if args.cmd == "dry-run":
        ok = await phase_preflight()
        if not ok:
            print("\n  Aborting dry-run: preflight failed.")
            return 2
        cands = await phase_select()
        await phase_dry_run(cands)
        return 0

    if args.cmd == "post":
        if not args.confirm:
            print("ERROR: --confirm flag is required to perform sandbox writes.")
            return 2
        ok = await phase_preflight()
        if not ok:
            print("\n  Aborting post: preflight failed.")
            return 2
        cands = await phase_select()
        cands = await phase_dry_run(cands)

        # Apply --exclude-ids filter (operator-driven; exact doc_id substring match)
        exclude_tokens = [t.strip() for t in (args.exclude_ids or "").split(",") if t.strip()]
        if exclude_tokens:
            kept: List[Candidate] = []
            for c in cands:
                if any(tok in c.doc_id for tok in exclude_tokens):
                    print(f"  ⊖ excluding doc {c.doc_id} (matched --exclude-ids)")
                else:
                    kept.append(c)
            cands = kept
            print(f"  After --exclude-ids: {len(cands)} candidate(s) remain.\n")

        if not cands:
            print("\n  🛑 No candidates remain after exclusions; nothing to post.")
            return 3

        # Hard guard: if any remaining candidate has no resolvable vendor, refuse.
        unresolved = [c for c in cands if not c.vendor_no]
        if unresolved:
            print(f"\n  🛑 {len(unresolved)} candidate(s) lack a resolvable vendor; refusing to post the batch.")
            print("     Remediation: stamp vendor_canonical or fix vendor aliases before retry.")
            return 3
        results = await phase_post(cands)
        phase_summary(results)
        return 0 if any(r.bucket.startswith("P") for r in results) else 1

    return 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight")
    sub.add_parser("select")
    sub.add_parser("dry-run")
    pp = sub.add_parser("post")
    pp.add_argument("--confirm", action="store_true", help="Required to actually POST to BC sandbox")
    pp.add_argument("--exclude-ids", default="", help="Comma-separated doc_id substrings to exclude from this batch")
    args = p.parse_args()
    return asyncio.run(_amain(args))


if __name__ == "__main__":
    sys.exit(main())
