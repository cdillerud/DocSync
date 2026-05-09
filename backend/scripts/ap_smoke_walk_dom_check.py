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
DEFAULT_OUT_SUMMARY_MD = (
    "prod_reports/AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md"
)

RESULT_COLUMNS = [
    "priority", "test_doc_category", "hub_doc_id", "file_name",
    "url", "http_status",
    "page_loaded", "doc_id_in_url", "title_or_filename_visible",
    "document_status_card_present",
    "preview_section_present",
    "ap_review_panel_present",
    "ap_field_vendor_visible", "ap_field_invoice_number_visible",
    "ap_field_invoice_date_visible", "ap_field_total_amount_visible",
    "ap_field_po_number_visible",
    "raw_json_warning_visible", "raw_snake_case_blocker_visible",
    "screenshot_path", "errors", "overall_pass",
]

AP_FIELD_LABELS = (
    ("vendor", ("Vendor",)),
    ("invoice_number", ("Invoice #", "Invoice Number")),
    ("invoice_date", ("Invoice Date",)),
    ("total_amount", ("Total Amount",)),
    ("po_number", ("PO Number",)),
)

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

        # 1. Doc id in URL
        out["doc_id_in_url"] = (
            "yes" if (row.get("hub_doc_id") or "") in page.url else "no")

        # 2. File name / title visibility
        fname = (row.get("file_name") or "").strip()
        body_text = page.inner_text("body", timeout=timeout_ms)
        out["title_or_filename_visible"] = (
            "yes" if fname and fname in body_text else
            "no" if fname else "n/a")

        # 3. Document Status card
        out["document_status_card_present"] = (
            "yes" if "Document Status" in body_text else "no")

        # 4. Document preview section
        preview_present = (
            "Document Preview" in body_text
            or page.locator("[data-testid='pdf-preview-panel']").count() > 0
            or page.locator("iframe").count() > 0
        )
        out["preview_section_present"] = (
            "yes" if preview_present else "no")

        # 5. AP Review panel anchor (we wrap with id="ap-review-panel")
        ap_present = page.locator("#ap-review-panel").count() > 0
        if not ap_present:
            ap_present = "AP Invoice Review" in body_text
        out["ap_review_panel_present"] = (
            "yes" if ap_present else
            "no" if is_ap_invoice else "n/a")

        # 6. Per-field visibility (only when AP panel is present)
        if is_ap_invoice and ap_present:
            # Scope the field search to the AP Review panel container so
            # we don't false-positive on the Extracted Data card etc.
            try:
                panel_text = page.inner_text("#ap-review-panel",
                                             timeout=timeout_ms)
            except Exception:
                panel_text = body_text
            for key, labels in AP_FIELD_LABELS:
                visible = any(label in panel_text for label in labels)
                out[f"ap_field_{key}_visible"] = "yes" if visible else "no"
        else:
            for key, _ in AP_FIELD_LABELS:
                out[f"ap_field_{key}_visible"] = "n/a"

        # 7. Raw JSON warning leakage check
        out["raw_json_warning_visible"] = (
            "yes" if RAW_JSON_WARNING_REGEX.search(body_text) else "no")

        # 8. Raw snake_case blocker leakage check
        out["raw_snake_case_blocker_visible"] = (
            "yes" if RAW_SNAKE_REGEX.search(body_text) else "no")

        # Optional screenshot
        if screenshot_dir:
            os.makedirs(screenshot_dir, exist_ok=True)
            safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_",
                             row.get("hub_doc_id") or "no-id")
            shot_path = os.path.join(screenshot_dir, f"{safe_id}.png")
            page.screenshot(path=shot_path, full_page=True)
            out["screenshot_path"] = shot_path

        # Overall pass calculation
        critical_fail = (
            out["page_loaded"] != "yes"
            or out["raw_json_warning_visible"] == "yes"
            or out["raw_snake_case_blocker_visible"] == "yes"
            or out["document_status_card_present"] != "yes"
            or out["preview_section_present"] != "yes"
            or (is_ap_invoice and out["ap_review_panel_present"] != "yes")
            or (is_ap_invoice and any(
                out[f"ap_field_{k}_visible"] == "no"
                for k, _ in AP_FIELD_LABELS))
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


def _failure_reasons(r: Dict[str, str]) -> List[str]:
    reasons: List[str] = []
    if r.get("page_loaded") != "yes":
        reasons.append("page did not load")
    if r.get("document_status_card_present") == "no":
        reasons.append("Document Status card missing")
    if r.get("preview_section_present") == "no":
        reasons.append("preview section missing")
    if r.get("ap_review_panel_present") == "no":
        reasons.append("AP Review panel missing")
    for key, _ in AP_FIELD_LABELS:
        if r.get(f"ap_field_{key}_visible") == "no":
            reasons.append(f"AP field '{key}' not visible")
    if r.get("raw_json_warning_visible") == "yes":
        reasons.append("raw JSON warning leaked to UI")
    if r.get("raw_snake_case_blocker_visible") == "yes":
        reasons.append("raw snake_case blocker code leaked to UI")
    if r.get("title_or_filename_visible") == "no":
        reasons.append("file name not visible on page")
    if r.get("doc_id_in_url") == "no":
        reasons.append("hub_doc_id missing from final URL")
    if r.get("errors"):
        reasons.append(r["errors"])
    return reasons


def write_summary_md(path: str, results: List[Dict[str, str]],
                     *, hub_origin: str, input_csv: str,
                     priorities_label: str,
                     screenshot_dir: Optional[str]) -> None:
    total = len(results)
    passed = sum(1 for r in results if r.get("overall_pass") == "yes")
    failed = total - passed
    by_priority: Dict[str, Dict[str, int]] = {}
    for r in results:
        bucket = by_priority.setdefault(
            r.get("priority") or "?", {"pass": 0, "fail": 0})
        bucket["pass" if r.get("overall_pass") == "yes" else "fail"] += 1

    lines: List[str] = []
    lines.append("# AP Smoke Walk — Automated DOM Check Summary")
    lines.append("")
    lines.append("> **INTERNAL — IT / Engineering only.** Read-only "
                 "browser pass; no clicks, no saves, no DB writes.")
    lines.append("")
    lines.append(f"- Source: `{input_csv}`")
    lines.append(f"- Hub origin: `{hub_origin}`")
    lines.append(f"- Priorities: `{priorities_label}`")
    lines.append(f"- Total docs checked: **{total}**")
    lines.append(f"- Passed: **{passed}**")
    lines.append(f"- Failed: **{failed}**")
    if screenshot_dir:
        lines.append(f"- Screenshots: `{screenshot_dir}/`")
    lines.append("")
    lines.append("## By priority")
    lines.append("")
    lines.append("| Priority | Pass | Fail |")
    lines.append("| --- | --- | --- |")
    for p in ("P0", "P1", "P2", "P3"):
        if p in by_priority:
            b = by_priority[p]
            lines.append(f"| {p} | {b['pass']} | {b['fail']} |")
    lines.append("")

    if failed:
        lines.append("## Failures")
        lines.append("")
        for r in results:
            if r.get("overall_pass") == "yes":
                continue
            reasons = _failure_reasons(r)
            lines.append(f"### {r.get('priority','?')} · "
                         f"{r.get('file_name') or '(no filename)'}")
            lines.append("")
            lines.append(f"- hub_doc_id: `{r.get('hub_doc_id','')}`")
            lines.append(f"- url: {r.get('url','')}")
            lines.append(f"- http_status: {r.get('http_status','')}")
            if r.get("screenshot_path"):
                lines.append(f"- screenshot: `{r['screenshot_path']}`")
            lines.append("- reasons:")
            for reason in reasons:
                lines.append(f"  - {reason}")
            lines.append("")
    else:
        lines.append("## Failures")
        lines.append("")
        lines.append("_None — every checked document passed the "
                     "structural DOM checks._")
        lines.append("")

    lines.append("## Pass list")
    lines.append("")
    lines.append("| Priority | Hub Doc ID | File Name |")
    lines.append("| --- | --- | --- |")
    for r in results:
        if r.get("overall_pass") == "yes":
            lines.append(f"| {r.get('priority','')} "
                         f"| `{r.get('hub_doc_id','')}` "
                         f"| {r.get('file_name','')} |")
    lines.append("")

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


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
    p.add_argument("--out-summary-md", default=DEFAULT_OUT_SUMMARY_MD)
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
    write_summary_md(
        args.out_summary_md, results,
        hub_origin=args.hub_origin,
        input_csv=args.input_csv,
        priorities_label=(",".join(priorities) if priorities else "ALL"),
        screenshot_dir=screenshot_dir,
    )
    print(render_console(results, args.out_csv, screenshot_dir))
    print(f"  out_summary_md   : {args.out_summary_md}")
    return 0 if all(r.get("overall_pass") == "yes" for r in results) else 4


if __name__ == "__main__":
    raise SystemExit(main())
