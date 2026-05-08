"""
matcher_miss_vendor_diagnostic.py
=================================
READ-ONLY diagnostic that looks at a single ``--sender`` cohort of
``hub_only`` docs and tries to find their counterparts among the
``no_match`` (Square9-only) rows in the same parity CSV.

The goal is binary: does Square9 actually hold this vendor's invoices
under a different naming convention (``matcher fix``), or are they
genuinely absent from the Square9 corpus (``scope gap``)?

Inputs
------
- ``--parity-csv``  Latest ``square9_hub_ap_parity*.csv``. Auto-discovers
                    the most recent ``prod_reports/cutover_proof_*/`` if
                    omitted, falling back to ``prod_reports/square9_hub_ap_parity.csv``.
- ``--sender``      Hub email_sender to investigate (default
                    ``billing@tumalocreek.us``).
- ``--fragments``   Comma-separated, case-insensitive substrings to match
                    against Square9 ``name`` / ``parent_path`` / ``web_url``
                    (default: ``tumalo,tumalocreek,tumalo creek``).

Per Hub doc the script computes a 0..1 ``score`` against each Square9
candidate using four signals (weights sum to 1.0):

  - invoice_number_match   (0.55) digits-only invoice number found in
                                  digits-only of Square9 name+path
  - filename_token_overlap (0.25) Jaccard of normalized filename tokens
  - vendor_token_overlap   (0.10) Jaccard of normalized vendor tokens
                                  (hub vendor_canonical + sender root)
                                  vs Square9 name+path tokens
  - date_proximity         (0.10) abs(hub_created_utc - square9_modified)
                                  -> 1.0 within 7 days, linear decay
                                  to 0.0 at 90 days

Score ``>= 0.85`` is "strong".

Outputs (three artifacts)
-------------------------
- ``prod_reports/matcher_miss_vendor_diagnostic.csv``
- ``prod_reports/matcher_miss_vendor_diagnostic.json``
- ``prod_reports/matcher_miss_vendor_diagnostic.md``

Exit codes
----------
- ``0``  >= 80% of Hub docs found a strong Square9 candidate
         (likely matcher fix, not data gap)
- ``1``  30..80% found a strong candidate (mixed)
- ``2``  < 30% found a strong candidate
         (likely Square9 scope gap, not matcher bug)

This script writes nothing to Mongo and never calls a remote service.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import glob
import json
import os
import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_SENDER = "billing@tumalocreek.us"
DEFAULT_FRAGMENTS = ("tumalo", "tumalocreek", "tumalo creek")

STRONG_SCORE_THRESHOLD = 0.85
EXIT_LIKELY_MATCHER_FIX = 0
EXIT_MIXED = 1
EXIT_LIKELY_SCOPE_GAP = 2

# Tunable bands.
STRONG_RATE_HIGH = 0.80   # >=80% strong  -> exit 0
STRONG_RATE_LOW = 0.30    # <30% strong   -> exit 2

WEIGHTS = {
    "invoice_number_match": 0.85,
    "filename_token_overlap": 0.07,
    "vendor_token_overlap": 0.04,
    "date_proximity": 0.04,
}
assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9

DATE_NEAR_DAYS = 7
DATE_FAR_DAYS = 90

STOP_TOKENS = {
    "the", "and", "of", "for", "to", "by", "in", "on",
    "invoice", "inv", "doc", "ap", "pdf", "tif", "tiff",
}


# ---------------------------------------------------------------------------
# IO helpers (shared shape with hub_only_audit)
# ---------------------------------------------------------------------------

def find_latest_parity_csv(base_dir: str = "prod_reports") -> Optional[str]:
    candidates = sorted(
        glob.glob(os.path.join(
            base_dir, "cutover_proof_*", "square9_hub_ap_parity*.csv")),
        reverse=True,
    )
    if candidates:
        return candidates[0]
    fallback = os.path.join(base_dir, "square9_hub_ap_parity.csv")
    return fallback if os.path.exists(fallback) else None


def read_parity_rows(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def filter_hub_for_sender(rows: Iterable[Dict[str, str]],
                          sender: str) -> List[Dict[str, str]]:
    needle = (sender or "").strip().lower()
    out = []
    for r in rows:
        if (r.get("match_bucket") or "").strip() != "hub_only":
            continue
        if (r.get("hub_email_sender") or "").strip().lower() == needle:
            out.append(r)
    return out


def filter_square9_by_fragments(rows: Iterable[Dict[str, str]],
                                fragments: Iterable[str]
                                ) -> List[Dict[str, str]]:
    frags = [f.strip().lower() for f in fragments if f and f.strip()]
    if not frags:
        return []
    out = []
    for r in rows:
        if (r.get("match_bucket") or "").strip() != "no_match":
            continue
        haystack = " ".join((
            r.get("square9_name") or "",
            r.get("square9_parent_path") or "",
            r.get("square9_web_url") or "",
        )).lower()
        if any(f in haystack for f in frags):
            out.append(r)
    return out


# ---------------------------------------------------------------------------
# Normalizers (pure)
# ---------------------------------------------------------------------------

_DIGIT_RE = re.compile(r"\D+")


def digits_only(s: str) -> str:
    """Return only the digit characters of ``s``."""
    if not s:
        return ""
    return _DIGIT_RE.sub("", s).lstrip("0") or _DIGIT_RE.sub("", s)


def normalize_filename(s: str) -> str:
    """Lowercase, strip extension, replace separators with spaces."""
    if not s:
        return ""
    s = s.lower()
    s = re.sub(r"\.(pdf|tif|tiff|png|jpg|jpeg)$", "", s)
    s = re.sub(r"[\\/_\-]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def tokenize(s: str) -> List[str]:
    if not s:
        return []
    norm = re.sub(r"[^a-z0-9]+", " ", s.lower())
    return [t for t in norm.split() if t and t not in STOP_TOKENS]


def vendor_root_from_sender(sender: str) -> str:
    """``billing@tumalocreek.us`` -> ``tumalocreek``."""
    if not sender or "@" not in sender:
        return ""
    domain = sender.split("@", 1)[1].split(".")[0]
    return domain.lower()


def jaccard(a: List[str], b: List[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def parse_iso_utc(s: str) -> Optional[dt.datetime]:
    if not s:
        return None
    try:
        v = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        if v.tzinfo is None:
            v = v.replace(tzinfo=dt.timezone.utc)
        return v
    except (ValueError, AttributeError):
        return None


def date_proximity_score(hub_iso: str, sq_iso: str) -> float:
    h = parse_iso_utc(hub_iso)
    s = parse_iso_utc(sq_iso)
    if h is None or s is None:
        return 0.0
    days = abs((h - s).total_seconds()) / 86400.0
    if days <= DATE_NEAR_DAYS:
        return 1.0
    if days >= DATE_FAR_DAYS:
        return 0.0
    return 1.0 - (days - DATE_NEAR_DAYS) / (DATE_FAR_DAYS - DATE_NEAR_DAYS)


# ---------------------------------------------------------------------------
# Scoring (pure)
# ---------------------------------------------------------------------------

def score_pair(hub: Dict[str, str], sq: Dict[str, str], sender: str
               ) -> Tuple[float, Dict[str, float], List[str]]:
    """Return (score, breakdown, signals_won) for a single Hub-Square9
    pair. signals_won is the list of weight keys that contributed
    positively (>0) to the score; used for downstream rule attribution.
    """
    breakdown: Dict[str, float] = {}
    signals_won: List[str] = []

    hub_inv_digits = digits_only(hub.get("hub_invoice_number_clean", ""))
    sq_haystack_digits = digits_only(
        (sq.get("square9_name") or "") + " " + (sq.get("square9_parent_path") or ""))

    inv_match = 0.0
    if hub_inv_digits and sq_haystack_digits and hub_inv_digits in sq_haystack_digits:
        inv_match = 1.0
    breakdown["invoice_number_match"] = inv_match
    if inv_match > 0:
        signals_won.append("invoice_number_match")

    hub_fname_tokens = tokenize(normalize_filename(hub.get("hub_file_name", "")))
    sq_fname_tokens = tokenize(normalize_filename(sq.get("square9_name", "")))
    fname_overlap = jaccard(hub_fname_tokens, sq_fname_tokens)
    breakdown["filename_token_overlap"] = fname_overlap
    if fname_overlap > 0:
        signals_won.append("filename_token_overlap")

    vendor_tokens = tokenize(hub.get("hub_vendor_canonical", ""))
    root = vendor_root_from_sender(sender)
    if root:
        vendor_tokens.append(root)
    sq_text_tokens = (
        tokenize(sq.get("square9_name", ""))
        + tokenize(sq.get("square9_parent_path", ""))
    )
    vendor_overlap = jaccard(vendor_tokens, sq_text_tokens)
    breakdown["vendor_token_overlap"] = vendor_overlap
    if vendor_overlap > 0:
        signals_won.append("vendor_token_overlap")

    date_score = date_proximity_score(
        hub.get("hub_created_utc", ""),
        sq.get("square9_modified", ""),
    )
    breakdown["date_proximity"] = date_score
    if date_score > 0:
        signals_won.append("date_proximity")

    score = sum(breakdown[k] * WEIGHTS[k] for k in WEIGHTS)
    return score, breakdown, signals_won


def best_candidate(hub: Dict[str, str],
                   candidates: List[Dict[str, str]],
                   sender: str
                   ) -> Tuple[Optional[Dict[str, str]], float,
                              Dict[str, float], List[str]]:
    best_sq: Optional[Dict[str, str]] = None
    best_score: float = 0.0
    best_breakdown: Dict[str, float] = {}
    best_signals: List[str] = []
    for sq in candidates:
        score, breakdown, signals = score_pair(hub, sq, sender)
        if score > best_score:
            best_sq = sq
            best_score = score
            best_breakdown = breakdown
            best_signals = signals
    return best_sq, best_score, best_breakdown, best_signals


# ---------------------------------------------------------------------------
# Per-row reasoning + suggested rule
# ---------------------------------------------------------------------------

def candidate_match_reason(score: float,
                           breakdown: Dict[str, float]) -> str:
    if not breakdown:
        return "no_candidates_in_corpus"
    drivers = sorted(
        ((k, v * WEIGHTS[k]) for k, v in breakdown.items()),
        key=lambda kv: -kv[1],
    )
    label = "strong" if score >= STRONG_SCORE_THRESHOLD else (
        "weak" if score >= 0.5 else "none")
    return f"{label}:" + ",".join(
        f"{k}={breakdown.get(k, 0):.2f}" for k, _ in drivers
    )


def suggested_rule_for_pair(score: float, signals: List[str]) -> str:
    if score < STRONG_SCORE_THRESHOLD or not signals:
        return ""
    if "invoice_number_match" in signals:
        return ("digits_only_invoice_in_square9_name_or_path"
                ":exact_match_tier")
    if "filename_token_overlap" in signals:
        return ("normalized_filename_token_jaccard>=0.5"
                ":strong_evidence_match_tier")
    if "vendor_token_overlap" in signals:
        return ("vendor_token_overlap_with_sender_domain_root"
                ":likely_match_tier")
    if "date_proximity" in signals:
        return "date_proximity_within_7d:possible_match_tier"
    return ""


# ---------------------------------------------------------------------------
# Diagnostic core
# ---------------------------------------------------------------------------

def run_diagnostic(parity_rows: List[Dict[str, str]],
                   sender: str,
                   fragments: List[str],
                   ) -> Dict[str, Any]:
    hub_rows = filter_hub_for_sender(parity_rows, sender)
    sq_rows = filter_square9_by_fragments(parity_rows, fragments)

    per_hub: List[Dict[str, Any]] = []
    score_buckets: Counter = Counter()
    rule_winners: Counter = Counter()
    mismatch_reasons: Counter = Counter()
    strong_count = 0

    for hub in hub_rows:
        sq, score, breakdown, signals = best_candidate(hub, sq_rows, sender)
        is_strong = score >= STRONG_SCORE_THRESHOLD
        if is_strong:
            strong_count += 1
            rule = suggested_rule_for_pair(score, signals)
            if rule:
                rule_winners[rule] += 1
        else:
            mismatch_reasons[
                _summarize_breakdown_gap(breakdown, len(sq_rows))] += 1
        score_buckets[_bucket_score(score)] += 1
        per_hub.append({
            "hub_doc_id": hub.get("hub_doc_id", ""),
            "hub_file_name": hub.get("hub_file_name", ""),
            "hub_email_sender": hub.get("hub_email_sender", ""),
            "hub_vendor_canonical": hub.get("hub_vendor_canonical", ""),
            "hub_invoice_number_clean": hub.get("hub_invoice_number_clean", ""),
            "hub_amount_float": hub.get("hub_amount_float", ""),
            "hub_created_utc": hub.get("hub_created_utc", ""),
            "hub_sharepoint_folder_path":
                hub.get("hub_sharepoint_folder_path", ""),
            "best_square9_name": (sq or {}).get("square9_name", ""),
            "best_square9_parent_path":
                (sq or {}).get("square9_parent_path", ""),
            "best_square9_modified":
                (sq or {}).get("square9_modified", ""),
            "score": round(score, 3),
            "score_breakdown": json.dumps(
                {k: round(v, 3) for k, v in breakdown.items()},
                separators=(",", ":")),
            "candidate_match_reason": candidate_match_reason(score, breakdown),
            "suggested_matcher_rule":
                suggested_rule_for_pair(score, signals) if is_strong else "",
        })

    rate = (strong_count / len(hub_rows)) if hub_rows else 0.0
    exit_code = decide_exit_code(rate, len(hub_rows))
    recommended_rule, rule_count = (
        rule_winners.most_common(1)[0] if rule_winners else ("", 0)
    )

    return {
        "sender": sender,
        "fragments": fragments,
        "hub_docs_considered": len(hub_rows),
        "square9_candidates_considered": len(sq_rows),
        "strong_candidate_count": strong_count,
        "strong_candidate_rate": round(rate, 4),
        "score_histogram": {k: score_buckets.get(k, 0) for k in
                            ("0.0-0.2", "0.2-0.5", "0.5-0.7",
                             "0.7-0.85", "0.85-1.0")},
        "rule_winner_counts": dict(rule_winners),
        "top_mismatch_reasons": mismatch_reasons.most_common(5),
        "recommended_matcher_rule": recommended_rule,
        "recommended_matcher_rule_support": rule_count,
        "conclusion": _conclusion_for_exit(exit_code),
        "exit_code": exit_code,
        "per_hub": per_hub,
    }


def decide_exit_code(rate: float, hub_count: int) -> int:
    if hub_count == 0:
        # No work to evaluate; treat as scope-gap signal so we don't
        # claim a matcher fix that was never tested.
        return EXIT_LIKELY_SCOPE_GAP
    if rate >= STRONG_RATE_HIGH:
        return EXIT_LIKELY_MATCHER_FIX
    if rate < STRONG_RATE_LOW:
        return EXIT_LIKELY_SCOPE_GAP
    return EXIT_MIXED


def _bucket_score(s: float) -> str:
    if s < 0.2:
        return "0.0-0.2"
    if s < 0.5:
        return "0.2-0.5"
    if s < 0.7:
        return "0.5-0.7"
    if s < STRONG_SCORE_THRESHOLD:
        return "0.7-0.85"
    return "0.85-1.0"


def _summarize_breakdown_gap(breakdown: Dict[str, float],
                             corpus_size: int) -> str:
    if corpus_size == 0:
        return "no_square9_corpus_after_fragment_filter"
    if not breakdown:
        return "no_corpus_evaluated"
    if breakdown.get("invoice_number_match", 0) == 0:
        return "invoice_number_not_found_in_square9_name_or_path"
    if (breakdown.get("filename_token_overlap", 0) < 0.2
            and breakdown.get("vendor_token_overlap", 0) < 0.2):
        return "low_filename_and_vendor_token_overlap"
    if breakdown.get("date_proximity", 0) == 0:
        return "no_date_proximity_within_window"
    return "weak_combined_score_below_strong_threshold"


def _conclusion_for_exit(exit_code: int) -> str:
    return {
        EXIT_LIKELY_MATCHER_FIX: (
            "Square9 likely DOES hold this vendor's invoices under a "
            "different naming convention. The matcher needs the "
            "recommended rule. Not a Square9 scope gap."),
        EXIT_MIXED: (
            "Mixed signal. Some Hub docs have strong Square9 candidates "
            "but a meaningful chunk do not. Inspect "
            "top_mismatch_reasons before changing the matcher."),
        EXIT_LIKELY_SCOPE_GAP: (
            "Square9 likely does NOT hold this vendor's invoices. "
            "Treat this cohort as square9_scope_gap and exclude it "
            "from the parity denominator instead of changing the "
            "matcher."),
    }[exit_code]


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

OUTPUT_CSV_COLUMNS = [
    "hub_doc_id", "hub_file_name", "hub_email_sender",
    "hub_vendor_canonical", "hub_invoice_number_clean", "hub_amount_float",
    "hub_created_utc", "hub_sharepoint_folder_path",
    "best_square9_name", "best_square9_parent_path", "best_square9_modified",
    "score", "score_breakdown", "candidate_match_reason",
    "suggested_matcher_rule",
]


def write_csv(path: str, per_hub: List[Dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_CSV_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in per_hub:
            w.writerow(r)


def write_json(path: str, result: Dict[str, Any], source_csv: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {k: v for k, v in result.items() if k != "per_hub"}
    payload["source_csv"] = source_csv
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, default=str, indent=2)


def write_md(path: str, result: Dict[str, Any], source_csv: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rate_pct = result["strong_candidate_rate"] * 100
    lines: List[str] = []
    lines.append("# Matcher-miss vendor diagnostic")
    lines.append("")
    lines.append(f"- source_csv: `{source_csv}`")
    lines.append(f"- sender: `{result['sender']}`")
    lines.append(f"- fragments: `{', '.join(result['fragments'])}`")
    lines.append(f"- hub_docs_considered: **{result['hub_docs_considered']}**")
    lines.append(f"- square9_candidates_considered: "
                 f"**{result['square9_candidates_considered']}**")
    lines.append(f"- strong_candidate_count: "
                 f"**{result['strong_candidate_count']}**")
    lines.append(f"- strong_candidate_rate: **{rate_pct:.1f}%** "
                 f"(threshold {STRONG_SCORE_THRESHOLD})")
    lines.append(f"- exit_code: **{result['exit_code']}**")
    lines.append(f"- recommended_matcher_rule: "
                 f"`{result['recommended_matcher_rule'] or '(none)'}` "
                 f"(support={result['recommended_matcher_rule_support']})")
    lines.append("")
    lines.append("## Conclusion")
    lines.append("")
    lines.append(result["conclusion"])
    lines.append("")
    lines.append("## Score histogram")
    lines.append("")
    lines.append("| range | count |")
    lines.append("| --- | ---: |")
    for k, v in result["score_histogram"].items():
        lines.append(f"| {k} | {v} |")
    lines.append("")
    if result["rule_winner_counts"]:
        lines.append("## Rule-winner counts (strong matches only)")
        lines.append("")
        lines.append("| rule | count |")
        lines.append("| --- | ---: |")
        for k, v in sorted(result["rule_winner_counts"].items(),
                           key=lambda kv: -kv[1]):
            lines.append(f"| {k} | {v} |")
        lines.append("")
    if result["top_mismatch_reasons"]:
        lines.append("## Top mismatch reasons (weak matches)")
        lines.append("")
        lines.append("| reason | count |")
        lines.append("| --- | ---: |")
        for reason, n in result["top_mismatch_reasons"]:
            lines.append(f"| {reason} | {n} |")
        lines.append("")
    lines.append("## Side-by-side examples")
    lines.append("")
    lines.append(
        "| hub_vendor | hub_invoice | hub_amount | hub_file_name | "
        "square9_name | square9_parent_path | score | reason |")
    lines.append("| --- | --- | ---: | --- | --- | --- | ---: | --- |")
    for r in result["per_hub"][:25]:
        lines.append(
            f"| {r['hub_vendor_canonical'] or '<unknown>'} "
            f"| {r['hub_invoice_number_clean'] or '<unknown>'} "
            f"| {r['hub_amount_float'] or ''} "
            f"| {r['hub_file_name'] or ''} "
            f"| {r['best_square9_name'] or ''} "
            f"| {r['best_square9_parent_path'] or ''} "
            f"| {r['score']} "
            f"| {r['candidate_match_reason']} |"
        )
    lines.append("")
    lines.append("_READ-ONLY diagnostic. No DB writes, no cutover._")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Console renderer
# ---------------------------------------------------------------------------

def render_console(result: Dict[str, Any], source_csv: str,
                   csv_out: str, json_out: str, md_out: str) -> str:
    rate_pct = result["strong_candidate_rate"] * 100
    rc = result["exit_code"]
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(f" matcher_miss_vendor_diagnostic — exit_code={rc}")
    lines.append("=" * 72)
    lines.append(f"  source_csv                    : {source_csv}")
    lines.append(f"  sender                        : {result['sender']}")
    lines.append(f"  fragments                     : "
                 f"{', '.join(result['fragments'])}")
    lines.append(f"  hub_docs_considered           : "
                 f"{result['hub_docs_considered']}")
    lines.append(f"  square9_candidates_considered : "
                 f"{result['square9_candidates_considered']}")
    lines.append(f"  strong_candidate_count        : "
                 f"{result['strong_candidate_count']}")
    lines.append(f"  strong_candidate_rate         : {rate_pct:.1f}%  "
                 f"(threshold {STRONG_SCORE_THRESHOLD})")
    lines.append("")
    lines.append("  score_histogram:")
    for k, v in result["score_histogram"].items():
        lines.append(f"    {k:10s}  {v}")
    lines.append("")
    if result["rule_winner_counts"]:
        lines.append("  rule_winner_counts:")
        for k, v in sorted(result["rule_winner_counts"].items(),
                           key=lambda kv: -kv[1]):
            lines.append(f"    {v:5d}  {k}")
        lines.append("")
    if result["top_mismatch_reasons"]:
        lines.append("  top_mismatch_reasons:")
        for reason, n in result["top_mismatch_reasons"]:
            lines.append(f"    {n:5d}  {reason}")
        lines.append("")
    lines.append(f"  recommended_matcher_rule      : "
                 f"{result['recommended_matcher_rule'] or '(none)'}  "
                 f"(support={result['recommended_matcher_rule_support']})")
    lines.append("")
    lines.append("  conclusion:")
    for chunk in _wrap(result["conclusion"], 66):
        lines.append(f"    {chunk}")
    lines.append("")
    lines.append(f"  csv_out  : {csv_out}")
    lines.append(f"  json_out : {json_out}")
    lines.append(f"  md_out   : {md_out}")
    lines.append("")
    lines.append("  READ-ONLY diagnostic. No DB writes, no cutover, "
                 "no Square9 archive.")
    lines.append("=" * 72)
    return "\n".join(lines)


def _wrap(s: str, width: int) -> List[str]:
    out, line, cur = [], [], 0
    for w in s.split():
        if cur + len(w) + 1 > width and line:
            out.append(" ".join(line))
            line, cur = [w], len(w)
        else:
            line.append(w); cur += len(w) + 1
    if line:
        out.append(" ".join(line))
    return out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser(
        description="Read-only matcher-miss vendor diagnostic.")
    p.add_argument("--parity-csv", default=None)
    p.add_argument("--sender", default=DEFAULT_SENDER)
    p.add_argument("--fragments", default=",".join(DEFAULT_FRAGMENTS),
                   help=("Comma-separated case-insensitive substrings "
                         "to match against Square9 name/parent_path/"
                         "web_url. Default: tumalo,tumalocreek,tumalo creek"))
    p.add_argument("--csv-out",
                   default="prod_reports/matcher_miss_vendor_diagnostic.csv")
    p.add_argument("--json-out",
                   default="prod_reports/matcher_miss_vendor_diagnostic.json")
    p.add_argument("--md-out",
                   default="prod_reports/matcher_miss_vendor_diagnostic.md")
    args = p.parse_args()

    csv_path = args.parity_csv or find_latest_parity_csv()
    if not csv_path or not os.path.exists(csv_path):
        print("matcher_miss_vendor_diagnostic: no parity CSV found.")
        return EXIT_LIKELY_SCOPE_GAP

    parity_rows = read_parity_rows(csv_path)
    fragments = [f.strip() for f in args.fragments.split(",") if f.strip()]
    result = run_diagnostic(parity_rows, args.sender, fragments)

    write_csv(args.csv_out, result["per_hub"])
    write_json(args.json_out, result, csv_path)
    write_md(args.md_out, result, csv_path)

    print(render_console(result, csv_path,
                         args.csv_out, args.json_out, args.md_out))
    return result["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
