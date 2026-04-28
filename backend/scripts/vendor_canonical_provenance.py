"""
Vendor-Canonical Provenance Tracer — read-only diagnostic for ONE doc.

Goal:
  Given a single AP_Invoice doc_id (default: first CARGOMO sample from the
  vendor-mismatch sweep), dump every system-recorded source that could have
  stamped `vendor_canonical` on it. Read-only. No DB writes.

What it inspects:
  §A Doc snapshot — id, type, status, extracted vendor, vendor_canonical,
     bc_record_info, intake / source / created timestamps.
  §B Doc-internal trail — full key listing + search for any embedded field
     whose VALUE contains the canonical code or canonical name (catches
     workflow_history, validation_history, notes, events arrays).
  §C vendor_aliases — any alias that points at this doc's vendor_canonical,
     and any alias whose alias_string matches the extracted vendor name.
  §D vendor_invoice_profiles — the profile keyed by vendor_canonical, with
     full variant list + source.
  §E bc_reference_cache — vendor record for the canonical code (if present).
  §F learning_events_v2 — any event tied to this doc_id.
  §G workflow_events / audit_log / intake_events / vendor_corrections /
     auto_resolve_* / gap_closer_* collections — any record tied to this
     doc_id, surfaced from a runtime collection scan (so we don't miss
     deployment-specific telemetry).
  §H Determination — best guess at which path stamped the canonical.

Usage:
  python /app/backend/scripts/vendor_canonical_provenance.py
  python /app/backend/scripts/vendor_canonical_provenance.py --doc-id <uuid>

Output:
  Prints a markdown report to stdout AND writes:
    /app/memory/CARGOMO_PROVENANCE_<doc_id>.md
    /app/memory/CARGOMO_PROVENANCE_<doc_id>.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BACKEND_DIR / ".env")
except Exception:
    pass

from motor.motor_asyncio import AsyncIOMotorClient


REPORT_DIR = Path("/app/memory")
DEFAULT_DOC_ID = "b2a9d129-bf74-4882-b744-93fa1e76eadd"  # first CARGOMO sample, pair #3 (MKC CUSTOMS BROKERS)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    url = os.environ["MONGO_URL"]
    name = os.environ["DB_NAME"]
    return AsyncIOMotorClient(url)[name]


def _strip_id(d: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not d:
        return d
    d.pop("_id", None)
    return d


def _has_token(value: Any, token: str) -> bool:
    """Recursively search a JSON-ish value for `token` (case-insensitive substring)."""
    tok = token.lower()
    if isinstance(value, str):
        return tok in value.lower()
    if isinstance(value, dict):
        return any(_has_token(v, token) for v in value.values())
    if isinstance(value, list):
        return any(_has_token(v, token) for v in value)
    return False


def _find_paths_with_token(
    obj: Any, token: str, prefix: str = "", max_paths: int = 40,
) -> List[str]:
    """Return JSON-ish paths whose leaf value (string) contains `token` (case-insensitive).

    Truncates at `max_paths` to keep output reasonable.
    """
    out: List[str] = []
    tok = token.lower()

    def walk(v: Any, p: str):
        if len(out) >= max_paths:
            return
        if isinstance(v, str):
            if tok in v.lower():
                out.append(f"{p} = {v!r}")
        elif isinstance(v, dict):
            for k, vv in v.items():
                walk(vv, f"{p}.{k}" if p else k)
        elif isinstance(v, list):
            for i, vv in enumerate(v):
                walk(vv, f"{p}[{i}]")

    walk(obj, prefix)
    return out


# ---------------------------------------------------------------------------
# Section gatherers
# ---------------------------------------------------------------------------


async def section_a_doc_snapshot(db, doc_id: str) -> Dict[str, Any]:
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not d:
        return {"found": False}
    ef = d.get("extracted_fields") or {}
    vr = d.get("validation_results") or {}
    bc_info = (vr.get("bc_record_info") or {}) if isinstance(vr, dict) else {}
    return {
        "found": True,
        "id": d.get("id"),
        "document_type": d.get("document_type"),
        "doc_type": d.get("doc_type"),
        "status": d.get("status"),
        "workflow_status": d.get("workflow_status"),
        "extracted_vendor": ef.get("vendor"),
        "vendor_canonical": d.get("vendor_canonical"),
        "vendor_no": d.get("vendor_no"),
        "bc_record_info": bc_info,
        "bc_purchase_invoice": d.get("bc_purchase_invoice"),
        "source": d.get("source"),
        "source_email": d.get("source_email"),
        "source_path": d.get("source_path"),
        "capture_channel": d.get("capture_channel"),
        "created_utc": d.get("created_utc"),
        "intake_at": d.get("intake_at"),
        "updated_utc": d.get("updated_utc"),
        "all_top_level_keys": sorted(d.keys()),
        # keep the full doc for §B
        "_full": d,
    }


def section_b_doc_internal_trail(snap: Dict[str, Any]) -> Dict[str, Any]:
    if not snap.get("found"):
        return {"applicable": False}
    full = snap["_full"]
    code = (snap.get("vendor_canonical") or "").strip()
    name = ((snap.get("bc_record_info") or {}).get("displayName") or "").strip()
    extracted = (snap.get("extracted_vendor") or "").strip()

    findings: Dict[str, List[str]] = {
        "paths_referencing_canonical_code": _find_paths_with_token(full, code) if code else [],
        "paths_referencing_canonical_name": _find_paths_with_token(full, name) if name else [],
        "paths_referencing_extracted_vendor": _find_paths_with_token(full, extracted) if extracted else [],
    }

    # Surface any obvious history-shaped fields
    history_like = {
        k: full.get(k)
        for k in full.keys()
        if any(tok in k.lower() for tok in ("history", "events", "audit", "trail", "stamps", "log"))
    }
    return {
        "applicable": True,
        "canonical_code": code,
        "canonical_name": name,
        "extracted_vendor": extracted,
        "findings": findings,
        "history_shaped_fields": {k: v for k, v in history_like.items() if v},
    }


async def section_c_aliases(db, code: str, extracted: str) -> Dict[str, Any]:
    aliases_to_code: List[Dict[str, Any]] = []
    if code:
        async for a in db.vendor_aliases.find({"vendor_no": code}, {"_id": 0}):
            aliases_to_code.append(a)
    aliases_matching_extracted: List[Dict[str, Any]] = []
    if extracted:
        norm = re.sub(r"\s+", " ", extracted.lower()).strip()
        cursor = db.vendor_aliases.find(
            {
                "$or": [
                    {"alias_string": extracted},
                    {"alias": extracted},  # legacy
                    {"normalized_alias": norm},
                    {"alias_normalized": norm},  # legacy
                ]
            },
            {"_id": 0},
        )
        async for a in cursor:
            aliases_matching_extracted.append(a)
    return {
        "aliases_pointing_at_canonical_code": aliases_to_code,
        "aliases_matching_extracted_name": aliases_matching_extracted,
    }


async def section_d_profile(db, code: str) -> Dict[str, Any]:
    if not code:
        return {"applicable": False}
    p = await db.vendor_invoice_profiles.find_one({"vendor_no": code}, {"_id": 0})
    return {"applicable": True, "profile": p}


async def section_e_bc_cache(db, code: str) -> Dict[str, Any]:
    if not code:
        return {"applicable": False}
    rows: List[Dict[str, Any]] = []
    cursor = db.bc_reference_cache.find(
        {
            "$or": [
                {"type": "vendor", "data.number": code},
                {"data.number": code},
                {"data.no": code},
                {"vendor_no": code},
            ]
        },
        {"_id": 0},
    )
    async for r in cursor:
        rows.append(r)
    return {"applicable": True, "matches": rows[:10], "match_count": len(rows)}


async def section_f_learning_events(db, doc_id: str) -> Dict[str, Any]:
    if "learning_events_v2" not in await db.list_collection_names():
        return {"applicable": False, "reason": "collection not present"}
    rows: List[Dict[str, Any]] = []
    cursor = db.learning_events_v2.find(
        {"$or": [{"doc_id": doc_id}, {"document_id": doc_id}, {"context.doc_id": doc_id}]},
        {"_id": 0},
    ).limit(50)
    async for r in cursor:
        rows.append(r)
    return {"applicable": True, "events": rows, "event_count": len(rows)}


async def section_g_other_collections(db, doc_id: str, code: str) -> Dict[str, Any]:
    """Scan all collections whose name suggests vendor / event / audit / resolution
    history, and return any documents tied to this doc_id (or to the canonical code
    if doc_id reference is absent)."""
    collections = await db.list_collection_names()
    interesting = [
        c for c in collections
        if any(tok in c.lower() for tok in (
            "vendor", "alias", "profile", "event", "audit", "cache",
            "learning", "resolution", "correction", "gap", "stamp", "history",
        ))
    ]
    # exclude collections we already covered explicitly
    explicit = {
        "vendor_aliases", "vendor_invoice_profiles", "bc_reference_cache",
        "learning_events_v2", "hub_documents",
    }
    interesting = [c for c in interesting if c not in explicit]

    out: Dict[str, Any] = {"collections_scanned": interesting, "hits": {}}
    for c in interesting:
        # search by doc_id first
        q_doc = {
            "$or": [
                {"doc_id": doc_id},
                {"document_id": doc_id},
                {"id": doc_id},
                {"context.doc_id": doc_id},
                {"target_id": doc_id},
            ]
        }
        rows: List[Dict[str, Any]] = []
        try:
            cursor = db[c].find(q_doc, {"_id": 0}).limit(20)
            async for r in cursor:
                rows.append(r)
        except Exception as e:
            out["hits"][c] = {"error": str(e)}
            continue
        # If no hits and we have a code, also try by canonical code (catches
        # collections keyed by vendor rather than doc)
        if not rows and code:
            try:
                cursor = db[c].find(
                    {"$or": [
                        {"vendor_no": code},
                        {"vendor_canonical": code},
                        {"canonical": code},
                        {"to_vendor_no": code},
                    ]},
                    {"_id": 0},
                ).limit(5)
                async for r in cursor:
                    rows.append(r)
                if rows:
                    out["hits"][c] = {"by_canonical_code_only": True, "rows": rows}
                    continue
            except Exception:
                pass
        if rows:
            out["hits"][c] = {"rows": rows}
    return out


def section_h_determination(
    snap: Dict[str, Any],
    sec_b: Dict[str, Any],
    sec_c: Dict[str, Any],
    sec_d: Dict[str, Any],
    sec_e: Dict[str, Any],
    sec_g: Dict[str, Any],
) -> Dict[str, Any]:
    """Heuristic verdict on which path most likely stamped vendor_canonical."""
    code = sec_b.get("canonical_code", "")
    extracted = sec_b.get("extracted_vendor", "")
    candidates: List[str] = []

    # 1. Did an alias map the extracted name → this code?
    matched_aliases = sec_c.get("aliases_matching_extracted_name") or []
    matched_to_this_code = [a for a in matched_aliases if a.get("vendor_no") == code]
    if matched_to_this_code:
        candidates.append(
            f"ALIAS — `vendor_aliases` row maps extracted name "
            f"{extracted!r} → vendor_no {code!r} "
            f"(alias_id={matched_to_this_code[0].get('alias_id')})"
        )

    # 2. Does the profile recognize the extracted name as a variant?
    prof = (sec_d.get("profile") or {}) if sec_d.get("applicable") else {}
    variants = prof.get("vendor_name_variants") or []
    if extracted and extracted in variants:
        candidates.append(
            f"PROFILE — `vendor_invoice_profiles[{code}]` lists "
            f"{extracted!r} in vendor_name_variants"
        )

    # 3. BC validation cached this vendor on the doc
    bc_info = snap.get("bc_record_info") or {}
    if bc_info and bc_info.get("number") == code:
        candidates.append(
            f"BC_VALIDATION — `validation_results.bc_record_info.number` already "
            f"== {code!r} (vendor_canonical likely sourced from this BC validation cache)"
        )

    # 4. Other collections referencing this doc + tagging it with the code
    sec_g_hits = sec_g.get("hits") or {}
    for coll, info in sec_g_hits.items():
        if "rows" in info or "by_canonical_code_only" in info:
            candidates.append(f"COLLECTION — `{coll}` carries history rows for this doc/code")

    # 5. No traceable origin → fallback inference
    if not candidates:
        candidates.append(
            "UNTRACEABLE — no alias, profile-variant, BC validation, or auxiliary "
            "collection record explains this canonical. Most likely an extraction-time "
            "default fallback (e.g., a doc-classifier rule that stamps CARGOMO on any "
            "freight-shaped document the LLM cannot resolve)."
        )

    return {
        "ranked_hypotheses": candidates,
        "primary": candidates[0] if candidates else "no signal",
    }


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def _render_md(doc_id: str, sections: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append(f"# Vendor-Canonical Provenance — `{doc_id}`")
    lines.append("")
    lines.append(f"- Generated: `{_utc_iso()}`")
    lines.append("- Mode: **read-only**, no Mongo writes, no BC calls.")
    lines.append("")

    # §A
    snap = sections["A"]
    lines.append("## §A · Doc snapshot")
    lines.append("")
    if not snap.get("found"):
        lines.append(f"_Doc `{doc_id}` not found in `hub_documents`._")
        return "\n".join(lines)
    keys = ("id", "document_type", "doc_type", "status", "workflow_status",
            "extracted_vendor", "vendor_canonical", "vendor_no",
            "bc_purchase_invoice", "source", "source_email", "source_path",
            "capture_channel", "created_utc", "intake_at", "updated_utc")
    lines.append("| field | value |")
    lines.append("|---|---|")
    for k in keys:
        v = snap.get(k)
        lines.append(f"| `{k}` | `{v!r}` |")
    lines.append("")
    lines.append("**`bc_record_info`:**")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(snap.get("bc_record_info") or {}, indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.append("**All top-level keys on this doc:**")
    lines.append("")
    lines.append("`" + "`, `".join(snap.get("all_top_level_keys") or []) + "`")
    lines.append("")

    # §B
    sec_b = sections["B"]
    lines.append("## §B · Doc-internal trail")
    lines.append("")
    lines.append(f"- Searched the full doc for paths whose value contains the canonical code (`{sec_b.get('canonical_code')}`), the canonical name (`{sec_b.get('canonical_name')}`), or the extracted vendor (`{sec_b.get('extracted_vendor')}`).")
    lines.append("")
    f = sec_b.get("findings") or {}
    for label, paths in (
        ("paths referencing canonical code", f.get("paths_referencing_canonical_code") or []),
        ("paths referencing canonical name", f.get("paths_referencing_canonical_name") or []),
        ("paths referencing extracted vendor", f.get("paths_referencing_extracted_vendor") or []),
    ):
        lines.append(f"**{label}** — {len(paths)} hit(s)")
        if paths:
            lines.append("")
            for p in paths:
                lines.append(f"- `{p}`")
        lines.append("")
    hist = sec_b.get("history_shaped_fields") or {}
    if hist:
        lines.append("**History-shaped embedded fields (full content):**")
        lines.append("")
        for k, v in hist.items():
            lines.append(f"- `{k}`:")
            lines.append("")
            lines.append("```json")
            lines.append(json.dumps(v, indent=2, default=str)[:4000])
            lines.append("```")
            lines.append("")

    # §C
    sec_c = sections["C"]
    lines.append("## §C · `vendor_aliases`")
    lines.append("")
    a1 = sec_c.get("aliases_pointing_at_canonical_code") or []
    a2 = sec_c.get("aliases_matching_extracted_name") or []
    lines.append(f"- aliases pointing at canonical code: **{len(a1)}**")
    lines.append(f"- aliases whose alias_string matches extracted name: **{len(a2)}**")
    lines.append("")
    if a2:
        lines.append("**Aliases that map this extracted vendor name (showing first 5):**")
        lines.append("")
        for a in a2[:5]:
            lines.append("```json")
            lines.append(json.dumps(_strip_id(a), indent=2, default=str))
            lines.append("```")
        lines.append("")
    if a1:
        lines.append(f"**Aliases pointing at `{sec_b.get('canonical_code')}` (showing first 5):**")
        lines.append("")
        for a in a1[:5]:
            lines.append("```json")
            lines.append(json.dumps(_strip_id(a), indent=2, default=str))
            lines.append("```")
        lines.append("")

    # §D
    sec_d = sections["D"]
    lines.append("## §D · `vendor_invoice_profiles`")
    lines.append("")
    p = sec_d.get("profile") if sec_d.get("applicable") else None
    if not p:
        lines.append(f"_No profile keyed by vendor_no = `{sec_b.get('canonical_code')}`._")
    else:
        keep = {k: p.get(k) for k in (
            "vendor_no", "vendor_name", "vendor_name_variants",
            "source", "seeded_at", "last_updated", "bc_invoice_count",
        )}
        lines.append("```json")
        lines.append(json.dumps(keep, indent=2, default=str))
        lines.append("```")
    lines.append("")

    # §E
    sec_e = sections["E"]
    lines.append("## §E · `bc_reference_cache`")
    lines.append("")
    if not sec_e.get("applicable"):
        lines.append("_skipped — no canonical code._")
    elif not sec_e.get("matches"):
        lines.append(f"_No bc_reference_cache record matches code `{sec_b.get('canonical_code')}`._")
    else:
        lines.append(f"**{sec_e.get('match_count')} match(es).** First record:")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(sec_e["matches"][0], indent=2, default=str)[:3000])
        lines.append("```")
    lines.append("")

    # §F
    sec_f = sections["F"]
    lines.append("## §F · `learning_events_v2`")
    lines.append("")
    if not sec_f.get("applicable"):
        lines.append(f"_skipped — {sec_f.get('reason', 'unknown')}_")
    elif not sec_f.get("events"):
        lines.append("_No learning_events_v2 rows reference this doc_id._")
    else:
        lines.append(f"**{sec_f.get('event_count')} event(s).** Showing first 5:")
        lines.append("")
        for e in sec_f["events"][:5]:
            lines.append("```json")
            lines.append(json.dumps(e, indent=2, default=str)[:1500])
            lines.append("```")
    lines.append("")

    # §G
    sec_g = sections["G"]
    lines.append("## §G · Other vendor / event / audit collections")
    lines.append("")
    lines.append("**Collections scanned:**")
    lines.append("")
    lines.append(", ".join(f"`{c}`" for c in sec_g.get("collections_scanned") or []))
    lines.append("")
    hits = sec_g.get("hits") or {}
    if not hits:
        lines.append("_No hits in any of the scanned collections._")
    else:
        for coll, info in hits.items():
            lines.append(f"### `{coll}`")
            lines.append("")
            if "error" in info:
                lines.append(f"_query error: {info['error']}_")
            else:
                if info.get("by_canonical_code_only"):
                    lines.append("(no doc-id link — matched on canonical code only)")
                lines.append("")
                for r in (info.get("rows") or [])[:5]:
                    lines.append("```json")
                    lines.append(json.dumps(r, indent=2, default=str)[:2000])
                    lines.append("```")
                lines.append("")

    # §H
    sec_h = sections["H"]
    lines.append("## §H · Determination")
    lines.append("")
    lines.append(f"**Best guess:** {sec_h.get('primary')}")
    lines.append("")
    lines.append("**Ranked hypotheses (highest evidence first):**")
    lines.append("")
    for h in sec_h.get("ranked_hypotheses") or []:
        lines.append(f"- {h}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _amain(args: argparse.Namespace) -> int:
    db = _db()
    print(f"[{_utc_iso()}] vendor_canonical provenance — doc_id={args.doc_id}")

    snap = await section_a_doc_snapshot(db, args.doc_id)
    if not snap.get("found"):
        print(f"  ERROR: doc {args.doc_id} not found in hub_documents.")
        return 2
    code = (snap.get("vendor_canonical") or "").strip()
    extracted = (snap.get("extracted_vendor") or "").strip()
    print(f"  extracted_vendor={extracted!r}  vendor_canonical={code!r}")

    sec_b = section_b_doc_internal_trail(snap)
    sec_c = await section_c_aliases(db, code, extracted)
    sec_d = await section_d_profile(db, code)
    sec_e = await section_e_bc_cache(db, code)
    sec_f = await section_f_learning_events(db, args.doc_id)
    sec_g = await section_g_other_collections(db, args.doc_id, code)
    sec_h = section_h_determination(snap, sec_b, sec_c, sec_d, sec_e, sec_g)

    # Strip the heavy _full doc out of snap before serialization
    snap_for_report = {k: v for k, v in snap.items() if k != "_full"}
    sections = {
        "A": {**snap_for_report, **{"all_top_level_keys": snap.get("all_top_level_keys")}},
        "B": sec_b,
        "C": sec_c,
        "D": sec_d,
        "E": sec_e,
        "F": sec_f,
        "G": sec_g,
        "H": sec_h,
    }
    # Inject canonical info into section A render input
    sections["A"]["bc_record_info"] = snap.get("bc_record_info")
    sections["A"]["found"] = True

    md = _render_md(args.doc_id, sections)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORT_DIR / f"CARGOMO_PROVENANCE_{args.doc_id}.md"
    json_path = REPORT_DIR / f"CARGOMO_PROVENANCE_{args.doc_id}.json"
    md_path.write_text(md)
    json_path.write_text(json.dumps(sections, indent=2, default=str))

    print(f"  determination: {sec_h.get('primary')}")
    print("  reports written:")
    print(f"    {md_path}")
    print(f"    {json_path}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--doc-id", default=DEFAULT_DOC_ID, help="hub_documents.id to trace")
    return asyncio.run(_amain(p.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
