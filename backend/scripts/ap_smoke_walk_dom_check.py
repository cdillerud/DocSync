"""
ap_smoke_walk_dom_check.py
==========================
OPTIONAL read-only browser harness that runs structural DOM checks
against the documents in the smoke-test CSV. Pairs with
``ap_smoke_walk_pack.py``: that script produces the human walk packet,
this one produces an automated structural pass/fail per document.

Strict guarantees:
- Read-only. Never clicks Save / Mark Ready / Post / Re-process.
- No network calls beyond loading each Hub page.
- No Mongo. No matcher / classifier / routing changes.
- If Playwright is not installed, the script fails clearly with a
  one-line install hint and does NOT install anything.
- If the Hub redirects to a login page, the script fails clearly and
  defers to the manual HTML packet.

CLI:
    --input-csv PATH          Default: prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv
    --hub-origin URL          REQUIRED for this script (no relative URLs).
    --priorities P0,P1        Comma-separated. Default: all.
    --out-csv PATH            Default: prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv
    --screenshot-dir DIR      Optional. If set, saves one PNG per doc.
    --headed (true|false)     Default: false.
    --timeout-ms N            Default: 15000.
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from typing import Dict, List, Optional, Tuple


DEFAULT_INPUT_CSV = (
    "prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv"
)
DEFAULT_OUT_CSV = (
    "prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv"
)

RESULT_COLUMNS = [
    "priority", "test_doc_category", "hub_doc_id", "file_name",
    "url", "http_status",
    "page_loaded", "title_or_filename_visible",
    "ap_review_panel_present", "preview_section_present",
    "raw_json_warning_visible", "raw_snake_case_blocker_visible",
    "screenshot_path", "errors", "overall_pass",
]

# Snake_case patterns we should never see leak to AP. Bounded with
# word boundaries so we don't false-positive on prose.
RAW_SNAKE_PATTERNS = [
    r"\bvendor_match\b",
    r"\bpo_validation\b",
    r"\bpo_not_found\b",
    r"\bfreight_direction_unknown\b",
    r"\bvendor_unmatched\b",
    r"\bamount_missing\b",
    r"\binvoice_date_missing\b",
    r"\bduplicate_suspect\b",
    r"\bextraction_low_confidence\b",
    r"\bbc_validation_failed\b",
]
RAW_SNAKE_REGEX = re.compile("|".join(RAW_SNAKE_PATTERNS))

# A JSON-stringified warning would look roughly like:
#   {"check_name":"freight_direction_unknown",...}
# Detect that shape rather than any literal "{" since the page may
# legitimately render JSON in debug subsections.
RAW_JSON_WARNING_REGEX = re.compile(
    r'\{\s*[\'"]check_name[\'"]\s*:\s*[\'"][a-z_]+[\'"]')


def _import_playwright_or_die() -> None:
    try:
        import playwright  # noqa: F401
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "ap_smoke_walk_dom_check: Playwright is not installed in "
            "this environment. To enable automated DOM checks:\n"
            "    pip install playwright && python -m playwright install chromium\n"
            "Until then, the manual HTML packet "
            "(prod_reports/AP_SMOKE_WALK_PACKET.html) is the supported "
            "path.\n"
        )
        raise SystemExit(127)


def read_smoke_csv(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Smoke-test CSV not found at {path!r}.")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def filter_rows(rows: List[Dict[str, str]],
                priorities: Optional[List[str]]
                ) -> List[Dict[str, str]]:
    if not priorities:
        return list(rows)
    wanted = set(p.upper() for p in priorities)
    return [r for r in rows if (r.get("priority") or "").upper() in wanted]


def resolve_url(row: Dict[str, str], hub_origin: str) -> str:
    raw = (row.get("hub_document_url") or "").strip()
    if raw.startswith(("http://", "https://")):
        return raw
    doc_id = (row.get("hub_doc_id") or "").strip()
    if not doc_id and not raw:
        return ""
    rel = raw or f"/documents/{doc_id}"
    return hub_origin.rstrip("/") + (
        rel if rel.startswith("/") else "/" + rel)


# ---------------------------------------------------------------------------
# Per-doc check
# ---------------------------------------------------------------------------

def check_doc(page, row: Dict[str, str], url: str,
              *, timeout_ms: int,
              is_ap_invoice: bool,
              screenshot_dir: Optional[str]
              ) -> Dict[str, str]:
    """Run the read-only DOM checks for a single document. Returns a
    flat dict shaped to RESULT_COLUMNS."""
    out: Dict[str, str] = {c: "" for c in RESULT_COLUMNS}
    out.update({
        "priority": row.get("priority") or "",
        "test_doc_category": row.get("test_doc_category") or "",
        "hub_doc_id": row.get("hub_doc_id") or "",
        "file_name": row.get("file_name") or "",
        "url": url,
    })
    errors: List[str] = []

    try:
        resp = page.goto(url, wait_until="networkidle",
                         timeout=timeout_ms)
        out["http_status"] = str(resp.status) if resp else ""
        if resp is None or resp.status >= 400:
            errors.append(f"http_status={out['http_status']}")
            out["page_loaded"] = "no"
            out["overall_pass"] = "no"
            out["errors"] = "; ".join(errors)
            return out

        # Detect login redirect — strong heuristic: if the page lacks
        # any "Document Detail" / "AP Review" / "Document Status"
        # markers AND has a sign-in form, treat as auth wall.
        if page.locator("input[type=password]").count() > 0:
            errors.append("login_redirect_detected")
            out["page_loaded"] = "no"
            out["overall_pass"] = "no"
            out["errors"] = "; ".join(errors)
            return out

        out["page_loaded"] = "yes"

        # 1. File name / title visibility
        fname = (row.get("file_name") or "").strip()
        body_text = page.inner_text("body", timeout=timeout_ms)
        out["title_or_filename_visible"] = (
            "yes" if fname and fname in body_text else
            "no" if fname else "n/a")

        # 2. AP Review panel anchor (we wrap with id="ap-review-panel")
        ap_present = page.locator("#ap-review-panel").count() > 0
        if not ap_present:
            # Fallback: look for the visible heading text the panel renders.
            ap_present = "AP Invoice Review" in body_text
        out["ap_review_panel_present"] = (
            "yes" if ap_present else
            "no" if is_ap_invoice else "n/a")

        # 3. Document preview section
        preview_present = (
            "Document Preview" in body_text
            or page.locator("[data-testid='pdf-preview-panel']").count() > 0
            or page.locator("iframe").count() > 0
        )
        out["preview_section_present"] = (
            "yes" if preview_present else "no")

        # 4. Raw JSON warning leakage check
        out["raw_json_warning_visible"] = (
            "yes" if RAW_JSON_WARNING_REGEX.search(body_text) else "no")

        # 5. Raw snake_case blocker leakage check
        out["raw_snake_case_blocker_visible"] = (
            "yes" if RAW_SNAKE_REGEX.search(body_text) else "no")

        # Optional screenshot
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_",
                             row.get("hub_doc_id") or "no-id")
            shot_path = os.path.join(screenshot_dir, f"{safe_id}.png")
            page.screenshot(path=shot_path, full_page=False)
            out["screenshot_path"] = shot_path

        # Overall pass calculation
        critical_fail = (
            out["page_loaded"] != "yes"
            or out["raw_json_warning_visible"] == "yes"
            or out["raw_snake_case_blocker_visible"] == "yes"
            or (is_ap_invoice and out["ap_review_panel_present"] != "yes")
        )
        out["overall_pass"] = "no" if critical_fail else "yes"

    except Exception as e:
        errors.append(f"{type(e).__name__}: {str(e)[:200]}")
        out["page_loaded"] = out["page_loaded"] or "no"
        out["overall_pass"] = "no"

    out["errors"] = "; ".join(errors)
    return out


def write_results(path: str, rows: List[Dict[str, str]]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RESULT_COLUMNS,
                           extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render_console(results: List[Dict[str, str]], out_csv: str,
                   screenshot_dir: Optional[str]) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.get("overall_pass") == "yes")
    failed = total - passed
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(" ap_smoke_walk_dom_check")
    lines.append("=" * 72)
    lines.append(f"  total docs       : {total}")
    lines.append(f"  passed           : {passed}")
    lines.append(f"  failed           : {failed}")
    lines.append(f"  out_csv          : {out_csv}")
    if screenshot_dir:
        lines.append(f"  screenshots      : {screenshot_dir}")
    if failed:
        lines.append("")
        lines.append("  failing docs:")
        for r in results:
            if r.get("overall_pass") != "yes":
                lines.append(
                    f"    - {r.get('priority','')} "
                    f"{r.get('hub_doc_id','')[:8]}... "
                    f"{r.get('file_name','')[:50]}: "
                    f"{r.get('errors','')}")
    lines.append("")
    lines.append("  READ-ONLY. No clicks, no DB writes.")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Run read-only Playwright DOM checks against the "
                    "smoke-test document set.")
    p.add_argument("--input-csv", default=DEFAULT_INPUT_CSV)
    p.add_argument("--hub-origin", required=True,
                   help="REQUIRED. e.g. http://4.204.41.190:8080")
    p.add_argument("--priorities", default="")
    p.add_argument("--out-csv", default=DEFAULT_OUT_CSV)
    p.add_argument("--screenshot-dir", default="")
    p.add_argument("--headed", default="false")
    p.add_argument("--timeout-ms", type=int, default=15000)
    args = p.parse_args(argv)

    _import_playwright_or_die()
    from playwright.sync_api import sync_playwright  # noqa: WPS433

    try:
        rows = read_smoke_csv(args.input_csv)
    except FileNotFoundError as e:
        print(f"ap_smoke_walk_dom_check: {e}", file=sys.stderr)
        return 2

    priorities = [p.strip() for p in args.priorities.split(",") if p.strip()]
    filtered = filter_rows(rows, priorities or None)
    if not filtered:
        print("ap_smoke_walk_dom_check: 0 rows after filter; nothing to do.",
              file=sys.stderr)
        return 3

    headed = args.headed.lower() in ("1", "true", "yes")
    screenshot_dir = args.screenshot_dir or None

    results: List[Dict[str, str]] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=not headed)
        context = browser.new_context()
        page = context.new_page()
        for row in filtered:
            url = resolve_url(row, args.hub_origin)
            if not url:
                results.append({
                    "priority": row.get("priority") or "",
                    "test_doc_category": row.get("test_doc_category") or "",
                    "hub_doc_id": row.get("hub_doc_id") or "",
                    "file_name": row.get("file_name") or "",
                    "url": "",
                    "errors": "no_url_resolvable",
                    "overall_pass": "no",
                })
                continue
            doc_type = (row.get("doc_type") or "").upper()
            sjt = (row.get("suggested_job_type") or "").upper()
            is_ap_invoice = (
                "AP_INVOICE" in doc_type or "AP_INVOICE" in sjt
                or row.get("test_doc_category", "").startswith(
                    ("clean_ap_invoice", "ap_invoice_",
                     "metadata_cleanup_example"))
            )
            results.append(check_doc(
                page, row, url,
                timeout_ms=args.timeout_ms,
                is_ap_invoice=is_ap_invoice,
                screenshot_dir=screenshot_dir,
            ))
        context.close()
        browser.close()

    write_results(args.out_csv, results)
    print(render_console(results, args.out_csv, screenshot_dir))
    return 0 if all(r.get("overall_pass") == "yes" for r in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
