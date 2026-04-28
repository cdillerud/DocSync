"""
Vendor-Mismatch Sweep — read-only diagnostic of the systematic AP vendor-resolution
defect surfaced during Tier 1 Batch 2 dry-run.

Scope (per signed declaration, 2026-04-28):
  - AP_Invoice docs only.
  - Reuses the live `_vendor_match_likely` heuristic from `tier1_batch_runner.py`
    (imported, NOT duplicated — single source of truth).
  - Read-only: no Mongo writes, no BC calls, no remediation changes.

For each AP_Invoice doc:
  1. Read extracted vendor name (`extracted_fields.vendor`).
  2. Resolve canonical vendor identity:
       - prefer `validation_results.bc_record_info.displayName` (human name from BC)
       - fallback: `vendor_invoice_profiles.vendor_name` looked up by vendor_no
       - fallback: `vendor_aliases.vendor_name` looked up by vendor_no
       - last resort: the raw vendor code itself
     The vendor code is `vendor_canonical` on the doc.
  3. Run `_vendor_match_likely(extracted, canonical_name)` — if False, classify as MISMATCH.
  4. Bucket by (extracted, canonical_name, vendor_code) tuple.

Output: `/app/memory/VENDOR_MISMATCH_SWEEP.md` (markdown report) + a sibling
`.json` with the same data for downstream tooling.

Per-pair report fields:
  - extracted vendor (verbatim)
  - canonical vendor (human name)
  - canonical vendor code (BC vendor_no)
  - affected doc count
  - 3–5 sample doc IDs
  - implicated alias / profile rule (the record that produced the mapping, if traceable)
  - recommended remediation type:
      alias_retire | alias_edit | profile_correction | doc_re_resolve | manual_review

Final section: "Batch 2 impact" — recommendation for the held Batch 2 candidates.

Usage:
  python /app/backend/scripts/vendor_mismatch_sweep.py
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from collections import Counter, defaultdict
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

# Import the LIVE heuristic — single source of truth (signed guardrail).
from scripts.tier1_batch_runner import _vendor_match_likely, _vendor_tokens  # noqa: E402


REPORT_MD = Path("/app/memory/VENDOR_MISMATCH_SWEEP.md")
REPORT_JSON = Path("/app/memory/VENDOR_MISMATCH_SWEEP.json")
TOP_N_PAIRS = 25
SAMPLE_IDS_PER_PAIR = 5


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _norm(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"[^\w\s]", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


def _has_meaningful_tokens(s: str) -> bool:
    """True iff `s` produces at least one token the heuristic considers signal-bearing."""
    return bool(_vendor_tokens(s or ""))


def _db():
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    return AsyncIOMotorClient(url)[name]


# ---------------------------------------------------------------------------
# Vendor-name resolution from canonical code
# ---------------------------------------------------------------------------


async def _build_vendor_name_lookup(db) -> Dict[str, str]:
    """vendor_no (BC code) → best human-readable name we can find."""
    lookup: Dict[str, str] = {}
    # Prefer profile names (they include the "vendor_card" pull from BC)
    async for p in db.vendor_invoice_profiles.find(
        {"vendor_no": {"$nin": [None, ""]}},
        {"_id": 0, "vendor_no": 1, "vendor_name": 1},
    ):
        if p.get("vendor_name"):
            lookup[p["vendor_no"]] = p["vendor_name"]
    # Fill gaps from aliases
    async for a in db.vendor_aliases.find(
        {"vendor_no": {"$nin": [None, ""]}},
        {"_id": 0, "vendor_no": 1, "vendor_name": 1},
    ):
        if a.get("vendor_no") and a["vendor_no"] not in lookup and a.get("vendor_name"):
            lookup[a["vendor_no"]] = a["vendor_name"]
    # Fill gaps from BC reference cache (vendor type)
    async for v in db.bc_reference_cache.find(
        {"type": "vendor"},
        {"_id": 0, "data.number": 1, "data.displayName": 1, "data.name": 1},
    ):
        d = v.get("data") or {}
        no = d.get("number")
        nm = d.get("displayName") or d.get("name")
        if no and nm and no not in lookup:
            lookup[no] = nm
    return lookup


# ---------------------------------------------------------------------------
# Implicated-rule tracing
# ---------------------------------------------------------------------------


async def _trace_implicated_rule(
    db,
    extracted_name: str,
    vendor_code: str,
) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Return (rule_type, rule_record) for the alias/profile that produced this mapping.

    rule_type ∈ {"alias", "profile", None}. None means we couldn't trace it
    (might be a doc-level pre-stamp or learned-at-extraction-time mapping).
    """
    norm = _norm(extracted_name)
    if not norm or not vendor_code:
        return (None, None)

    # 1) alias hit pointing at this code
    a = await db.vendor_aliases.find_one(
        {
            "vendor_no": vendor_code,
            "$or": [
                {"alias_string": extracted_name},
                {"normalized_alias": norm},
                {"alias": extracted_name},  # legacy field name
                {"alias_normalized": norm},  # legacy field name
            ],
        },
        {"_id": 0},
    )
    if a:
        return ("alias", a)

    # 2) profile hit pointing at this code, where the extracted name matches
    #    one of the recognized variants
    p = await db.vendor_invoice_profiles.find_one(
        {
            "vendor_no": vendor_code,
            "$or": [
                {"vendor_name": extracted_name},
                {"vendor_name_variants": extracted_name},
            ],
        },
        {"_id": 0, "vendor_no": 1, "vendor_name": 1, "vendor_name_variants": 1, "source": 1},
    )
    if p:
        return ("profile", p)

    return (None, None)


def _recommend_remediation(rule_type: Optional[str], rule: Optional[Dict[str, Any]]) -> str:
    """Map traced rule → remediation recommendation."""
    if rule_type == "alias":
        # Alias rules are user-correction or learned. Default = retire.
        # If correction_count is high, prefer edit (review what should it actually point to).
        cc = (rule or {}).get("correction_count", 0)
        if cc and cc >= 5:
            return "alias_edit"
        return "alias_retire"
    if rule_type == "profile":
        # Profile name carries variants. The fix is to remove the bad variant
        # / correct the canonical vendor_name on the profile.
        return "profile_correction"
    return "doc_re_resolve"


# ---------------------------------------------------------------------------
# Sweep
# ---------------------------------------------------------------------------


async def sweep() -> Dict[str, Any]:
    db = _db()
    name_lookup = await _build_vendor_name_lookup(db)

    cursor = db.hub_documents.find(
        {"document_type": "AP_Invoice"},
        {
            "_id": 0,
            "id": 1,
            "extracted_fields.vendor": 1,
            "vendor_canonical": 1,
            "validation_results.bc_record_info": 1,
            "status": 1,
            "workflow_status": 1,
            "bc_purchase_invoice": 1,
        },
    )

    total = 0
    no_extracted = 0
    no_canonical = 0
    matches = 0
    mismatches = 0
    already_posted = 0
    # Per-axis counters (a doc can fail one or both)
    name_axis_fail = 0  # extracted vs canonical_name (BC displayName / profile name)
    code_axis_fail = 0  # extracted vs vendor_canonical (the code that will post)
    both_axes_fail = 0
    code_unresolved = 0  # vendor_canonical has no meaningful tokens (e.g., "112522")

    pair_buckets: Dict[Tuple[str, str, str], List[str]] = defaultdict(list)
    pair_axes: Dict[Tuple[str, str, str], Counter] = defaultdict(Counter)
    pair_code_unresolved: Dict[Tuple[str, str, str], int] = defaultdict(int)

    async for d in cursor:
        total += 1
        ef = d.get("extracted_fields") or {}
        extracted = (ef.get("vendor") or "").strip()
        code = (d.get("vendor_canonical") or "").strip()
        bc_info = ((d.get("validation_results") or {}).get("bc_record_info") or {}) if d.get("validation_results") else {}
        canonical_name = (
            (bc_info.get("displayName") if isinstance(bc_info, dict) else None)
            or name_lookup.get(code, "")
            or code  # last-resort: fall back to the code itself
        )

        if not extracted:
            no_extracted += 1
            continue
        if not code:
            no_canonical += 1
            continue
        if d.get("bc_purchase_invoice"):
            already_posted += 1

        # Two-axis comparison — a doc is mismatched if EITHER axis fails.
        name_ok = _vendor_match_likely(extracted, canonical_name)
        code_ok = _vendor_match_likely(extracted, code)
        # Track when the code itself is too thin to compare against (e.g., bare numbers)
        code_thin = not _has_meaningful_tokens(code)

        if name_ok and code_ok:
            matches += 1
            continue

        mismatches += 1
        if not name_ok:
            name_axis_fail += 1
        if not code_ok:
            code_axis_fail += 1
        if not name_ok and not code_ok:
            both_axes_fail += 1
        if code_thin:
            code_unresolved += 1

        key = (extracted, canonical_name, code)
        pair_buckets[key].append(d["id"])
        if not name_ok:
            pair_axes[key]["name"] += 1
        if not code_ok:
            pair_axes[key]["code"] += 1
        if code_thin:
            pair_code_unresolved[key] += 1

    # Build top-N pair report — also classify each pair
    pairs = sorted(pair_buckets.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_pairs: List[Dict[str, Any]] = []
    class_counts: Counter = Counter()  # mismatch-class breakdown across ALL pairs
    doc_id_to_class: Dict[str, str] = {}  # FULL coverage, not just top-5 samples

    for (extracted, canonical_name, code), doc_ids in pairs:
        rule_type, rule = await _trace_implicated_rule(db, extracted, code)
        rec = _recommend_remediation(rule_type, rule)
        axes = pair_axes[(extracted, canonical_name, code)]
        code_thin_count = pair_code_unresolved[(extracted, canonical_name, code)]
        if code_thin_count == len(doc_ids):
            mismatch_class = "unresolved_or_ambiguous"
        elif rule_type == "alias":
            mismatch_class = "alias_driven"
        elif rule_type == "profile":
            mismatch_class = "profile_driven"
        else:
            mismatch_class = "doc_prestamp_or_fallback"
        class_counts[mismatch_class] += len(doc_ids)
        for did in doc_ids:
            doc_id_to_class[did] = mismatch_class

        # Strip rule down to the fields we care about for the report
        rule_summary: Optional[Dict[str, Any]] = None
        if rule:
            if rule_type == "alias":
                rule_summary = {
                    "kind": "alias",
                    "alias_id": rule.get("alias_id"),
                    "alias_string": rule.get("alias_string") or rule.get("alias"),
                    "normalized_alias": rule.get("normalized_alias") or rule.get("alias_normalized"),
                    "vendor_no": rule.get("vendor_no"),
                    "vendor_name": rule.get("vendor_name"),
                    "source": rule.get("source"),
                    "correction_count": rule.get("correction_count"),
                    "learned_at": rule.get("learned_at"),
                }
            else:
                rule_summary = {
                    "kind": "profile",
                    "vendor_no": rule.get("vendor_no"),
                    "vendor_name": rule.get("vendor_name"),
                    "vendor_name_variants": rule.get("vendor_name_variants"),
                    "source": rule.get("source"),
                }
        top_pairs.append({
            "extracted_vendor": extracted,
            "canonical_vendor": canonical_name,
            "canonical_vendor_code": code,
            "affected_doc_count": len(doc_ids),
            "sample_doc_ids": doc_ids[:SAMPLE_IDS_PER_PAIR],
            "axis_fail": dict(axes),  # which axis caught it (and how many)
            "code_unresolved_count": code_thin_count,
            "mismatch_class": mismatch_class,
            "implicated_rule": rule_summary,
            "recommended_remediation": rec,
        })

    return {
        "generated_at": _utc_iso(),
        "scope": "AP_Invoice (signed: 1a)",
        "heuristic": "live tier1_batch_runner._vendor_match_likely (signed: 2a, two-axis)",
        "axes": {
            "name_axis": "extracted vendor name vs BC displayName / profile / alias name",
            "code_axis": "extracted vendor name vs vendor_canonical (the value that actually posts)",
        },
        "totals": {
            "ap_invoice_docs_scanned": total,
            "matches": matches,
            "mismatches": mismatches,
            "skipped_no_extracted_vendor": no_extracted,
            "skipped_no_canonical_code": no_canonical,
            "already_posted_to_bc": already_posted,
            "name_axis_failures": name_axis_fail,
            "code_axis_failures": code_axis_fail,
            "both_axes_failures": both_axes_fail,
            "code_unresolved_or_thin": code_unresolved,
        },
        "mismatch_class_breakdown": dict(class_counts),
        "distinct_mismatch_pairs": len(pair_buckets),
        "top_pairs": top_pairs[:TOP_N_PAIRS],
        "all_pairs": top_pairs,  # full list for downstream tooling
        "all_mismatch_doc_ids": [doc_id for ids in pair_buckets.values() for doc_id in ids],
        "doc_id_to_class": doc_id_to_class,  # FULL per-doc class lookup
    }


# ---------------------------------------------------------------------------
# Batch 2 impact analysis
# ---------------------------------------------------------------------------


async def _batch2_impact(report: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run the tier1 candidate selection logic and decide which are at risk."""
    from scripts.tier1_batch_runner import _select_candidates  # local import — avoids
    db = _db()
    cands = await _select_candidates(db)
    # Full per-doc class lookup (covers all mismatched docs, not just top-5 samples)
    doc_class: Dict[str, str] = dict(report.get("doc_id_to_class") or {})
    mismatch_ids = set(report["all_mismatch_doc_ids"])

    at_risk: List[Dict[str, Any]] = []
    safe: List[Dict[str, Any]] = []
    for c in cands:
        entry = {
            "doc_id": c.doc_id,
            "extracted_vendor": c.vendor_name,
            "vendor_no": c.vendor_no,
        }
        if c.doc_id in mismatch_ids:
            entry["mismatch_class"] = doc_class.get(c.doc_id, "unknown_class")
            at_risk.append(entry)
        else:
            safe.append(entry)

    # Per-class action mapping for at-risk candidates
    action_by_class = {
        "alias_driven": "stays_excluded — alias rule must be retired/edited first",
        "profile_driven": "stays_excluded — profile must be corrected first",
        "doc_prestamp_or_fallback": "blocked_pending_root_cause — fallback/extraction bug; do not post",
        "unresolved_or_ambiguous": "stays_excluded — vendor_canonical is non-meaningful (e.g., bare numbers)",
        "unknown_class": "stays_excluded — out of top-N pair sample; class undetermined",
    }
    for e in at_risk:
        e["action"] = action_by_class.get(e["mismatch_class"], "stays_excluded")

    if at_risk and len(at_risk) == len(cands):
        recommendation = "stay_excluded — every Batch-2 candidate is mismatched; do not post any."
    elif at_risk:
        recommendation = (
            f"re_resolve_and_reconsider — {len(at_risk)} candidate(s) MUST be excluded "
            f"(see per-class action below); the {len(safe)} clean candidate(s) MAY proceed "
            "only after the doc_prestamp_or_fallback root-cause investigation completes "
            "(otherwise the same defect could re-stamp them silently)."
        )
    else:
        recommendation = (
            "no_action — none of the current Batch-2 candidates appear in the "
            "mismatch set."
        )

    return {
        "candidates_total": len(cands),
        "at_risk": at_risk,
        "safe": safe,
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_md(report: Dict[str, Any], batch2: Dict[str, Any]) -> str:
    t = report["totals"]
    lines: List[str] = []
    lines.append("# Vendor-Mismatch Sweep")
    lines.append("")
    lines.append(f"- Generated: `{report['generated_at']}`")
    lines.append(f"- Scope: {report['scope']}")
    lines.append(f"- Heuristic: {report['heuristic']}")
    lines.append("- Mode: **read-only**, no Mongo writes, no BC calls.")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| metric | count |")
    lines.append("|---|---|")
    lines.append(f"| AP_Invoice docs scanned | {t['ap_invoice_docs_scanned']} |")
    lines.append(f"| matches (both axes pass) | {t['matches']} |")
    lines.append(f"| **mismatches (either axis fails)** | **{t['mismatches']}** |")
    lines.append(f"| ↳ name-axis failures (extracted vs displayName/profile) | {t['name_axis_failures']} |")
    lines.append(f"| ↳ code-axis failures (extracted vs `vendor_canonical`) | {t['code_axis_failures']} |")
    lines.append(f"| ↳ both axes failed | {t['both_axes_failures']} |")
    lines.append(f"| ↳ `vendor_canonical` lacks meaningful tokens (e.g. bare numbers) | {t['code_unresolved_or_thin']} |")
    lines.append(f"| skipped — no extracted vendor name | {t['skipped_no_extracted_vendor']} |")
    lines.append(f"| skipped — no `vendor_canonical` code | {t['skipped_no_canonical_code']} |")
    lines.append(f"| already posted to BC | {t['already_posted_to_bc']} |")
    lines.append(f"| distinct mismatch (extracted → canonical) pairs | {report['distinct_mismatch_pairs']} |")
    lines.append("")
    lines.append("## Mismatch class breakdown (doc counts)")
    lines.append("")
    lines.append("| class | docs | meaning |")
    lines.append("|---|---|---|")
    cb = report.get("mismatch_class_breakdown") or {}
    classes_meta = [
        ("alias_driven", "Traceable to a `vendor_aliases` row — alias_retire / alias_edit"),
        ("profile_driven", "Traceable to a `vendor_invoice_profiles` row — profile_correction"),
        ("doc_prestamp_or_fallback", "Not traceable to alias/profile — extraction-time pre-stamp or fallback bug"),
        ("unresolved_or_ambiguous", "`vendor_canonical` is non-meaningful (bare digits, empty tokens) — manual review"),
    ]
    for cls, desc in classes_meta:
        lines.append(f"| `{cls}` | {cb.get(cls, 0)} | {desc} |")
    lines.append("")

    if not report["top_pairs"]:
        lines.append("## Top mismatch pairs")
        lines.append("")
        lines.append("_No mismatches detected._")
    else:
        lines.append(f"## Top {min(TOP_N_PAIRS, len(report['top_pairs']))} mismatch pairs")
        lines.append("")
        for i, p in enumerate(report["top_pairs"], 1):
            lines.append(f"### {i}. `{p['extracted_vendor']}` → `{p['canonical_vendor']}` (`{p['canonical_vendor_code']}`)")
            lines.append("")
            lines.append(f"- Affected docs: **{p['affected_doc_count']}**  ·  "
                         f"class: **`{p['mismatch_class']}`**  ·  "
                         f"axis fail: `{p.get('axis_fail') or {}}`"
                         + (f"  ·  code-thin: `{p['code_unresolved_count']}`" if p.get('code_unresolved_count') else ""))
            lines.append(f"- Sample doc IDs: {', '.join(f'`{did}`' for did in p['sample_doc_ids'])}")
            rule = p["implicated_rule"]
            if rule is None:
                lines.append("- Implicated rule: **not traceable** via aliases or profiles "
                             "(may be a doc-level pre-stamp or extraction-time mapping)")
            elif rule["kind"] == "alias":
                lines.append("- Implicated rule (alias):")
                lines.append(f"  - `alias_id`: `{rule.get('alias_id')}`")
                lines.append(f"  - `alias_string`: `{rule.get('alias_string')}`")
                lines.append(f"  - `vendor_no`: `{rule.get('vendor_no')}`  ·  `vendor_name`: `{rule.get('vendor_name')}`")
                lines.append(f"  - `source`: `{rule.get('source')}`  ·  `correction_count`: `{rule.get('correction_count')}`")
                lines.append(f"  - `learned_at`: `{rule.get('learned_at')}`")
            else:
                lines.append("- Implicated rule (profile):")
                lines.append(f"  - `vendor_no`: `{rule.get('vendor_no')}`  ·  `vendor_name`: `{rule.get('vendor_name')}`")
                lines.append(f"  - `vendor_name_variants`: `{rule.get('vendor_name_variants')}`")
                lines.append(f"  - `source`: `{rule.get('source')}`")
            lines.append(f"- **Recommended remediation: `{p['recommended_remediation']}`**")
            lines.append("")

    lines.append("## Remediation legend")
    lines.append("")
    lines.append("- `alias_retire` — delete or deactivate the bad `vendor_aliases` row.")
    lines.append("- `alias_edit` — keep the alias but redirect `vendor_no` to the correct vendor (used when the alias has been corrected ≥5 times — high signal).")
    lines.append("- `profile_correction` — remove the bad name variant from `vendor_invoice_profiles.vendor_name_variants`, or correct `vendor_name`.")
    lines.append("- `doc_re_resolve` — no traceable rule; re-run vendor resolution on the doc with current alias/profile state.")
    lines.append("- `manual_review` — escalate to a human; signal too ambiguous to auto-fix.")
    lines.append("")

    lines.append("## Batch 2 impact")
    lines.append("")
    lines.append(f"- Candidates the tier1 selector currently picks: **{batch2['candidates_total']}**")
    lines.append(f"- At risk (mismatch detected): **{len(batch2['at_risk'])}**")
    lines.append(f"- Safe (no mismatch): **{len(batch2['safe'])}**")
    lines.append("")
    if batch2["at_risk"]:
        lines.append("### At-risk candidates")
        lines.append("")
        lines.append("| doc_id | extracted vendor | resolved vendor_no | mismatch class | action |")
        lines.append("|---|---|---|---|---|")
        for c in batch2["at_risk"]:
            lines.append(
                f"| `{c['doc_id']}` | {c['extracted_vendor']} | `{c['vendor_no']}` | "
                f"`{c.get('mismatch_class','-')}` | {c.get('action','-')} |"
            )
        lines.append("")
    if batch2["safe"]:
        lines.append("### Safe candidates")
        lines.append("")
        lines.append("| doc_id | extracted vendor | resolved vendor_no |")
        lines.append("|---|---|---|")
        for c in batch2["safe"]:
            lines.append(f"| `{c['doc_id']}` | {c['extracted_vendor']} | `{c['vendor_no']}` |")
        lines.append("")
    lines.append(f"**Recommendation:** {batch2['recommendation']}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _amain() -> int:
    print(f"[{_utc_iso()}] vendor-mismatch sweep — read-only, AP_Invoice scope")
    report = await sweep()
    batch2 = await _batch2_impact(report)
    md = _render_md(report, batch2)

    REPORT_MD.parent.mkdir(parents=True, exist_ok=True)
    REPORT_MD.write_text(md)
    REPORT_JSON.write_text(json.dumps({"sweep": report, "batch2_impact": batch2}, indent=2, default=str))

    t = report["totals"]
    print(f"  scanned={t['ap_invoice_docs_scanned']}  matches={t['matches']}  "
          f"mismatches={t['mismatches']}  pairs={report['distinct_mismatch_pairs']}")
    print(f"  Batch-2 candidates total={batch2['candidates_total']} "
          f"at_risk={len(batch2['at_risk'])} safe={len(batch2['safe'])}")
    print("  Reports written:")
    print(f"    {REPORT_MD}")
    print(f"    {REPORT_JSON}")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
