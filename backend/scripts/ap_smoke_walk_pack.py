"""
ap_smoke_walk_pack.py
=====================
READ-ONLY harness: turn the curated smoke-test CSV into a browser-
friendly checklist + an empty findings CSV so Chad/Alani can walk
documents without hand-rebuilding rows every time.

Inputs (from the existing smoke set):
    prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv

Outputs:
    prod_reports/AP_SMOKE_WALK_PACKET.html   ← main tester artifact
    prod_reports/AP_SMOKE_WALK_PACKET.md     ← markdown mirror
    prod_reports/AP_SMOKE_WALK_FINDINGS.csv  ← empty-but-typed findings file

Strict guarantees:
- Read-only. No Mongo. No matcher / classifier / routing /
  Square9 / cutover / DocuSign / HTTPS work.
- No AP-facing communication artifacts. The packet is internal IT/Eng
  only and carries an INTERNAL banner at the top.

CLI:
    --input-csv PATH          Default: prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv
    --hub-origin URL          Optional. If set, hub_document_url is
                              prepended with this origin; else relative
                              /documents/{id} links remain.
    --priorities P0,P1,P2     CSV of priorities to include. Default: all.
    --out-html PATH           Default: prod_reports/AP_SMOKE_WALK_PACKET.html
    --out-md PATH             Default: prod_reports/AP_SMOKE_WALK_PACKET.md
    --out-findings-csv PATH   Default: prod_reports/AP_SMOKE_WALK_FINDINGS.csv
"""
from __future__ import annotations

import argparse
import csv
import html as _html
import os
import sys
from collections import OrderedDict
from typing import Dict, Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_INPUT_CSV = (
    "prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv"
)
DEFAULT_OUT_HTML = "prod_reports/AP_SMOKE_WALK_PACKET.html"
DEFAULT_OUT_MD = "prod_reports/AP_SMOKE_WALK_PACKET.md"
DEFAULT_OUT_FINDINGS_CSV = "prod_reports/AP_SMOKE_WALK_FINDINGS.csv"

PRIORITY_ORDER = ("P0", "P1", "P2", "P3")

FINDINGS_COLUMNS = [
    "Tester", "Date", "Priority", "Category",
    "Hub Doc ID", "File Name", "Hub URL",
    "Opened?", "Preview loaded?", "AP panel visible?",
    "Fields visible?", "Status understandable?",
    "Problem notes", "Severity", "Follow-Up Owner",
]


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------

def read_smoke_csv(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Smoke-test CSV not found at {path!r}. Generate it first "
            f"with build_ap_smoke_test_set.py.")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def parse_priorities(raw: Optional[str]) -> Optional[List[str]]:
    if not raw:
        return None
    out = [p.strip().upper() for p in raw.split(",") if p.strip()]
    return out or None


def filter_rows(rows: List[Dict[str, str]],
                priorities: Optional[List[str]]
                ) -> List[Dict[str, str]]:
    if not priorities:
        return list(rows)
    wanted = set(priorities)
    return [r for r in rows if (r.get("priority") or "").upper() in wanted]


def group_by_priority(rows: List[Dict[str, str]]
                      ) -> "OrderedDict[str, List[Dict[str, str]]]":
    grouped: "OrderedDict[str, List[Dict[str, str]]]" = OrderedDict()
    for p in PRIORITY_ORDER:
        grouped[p] = []
    for r in rows:
        p = (r.get("priority") or "").upper()
        grouped.setdefault(p, []).append(r)
    # Drop empty buckets so the output isn't padded with empty sections.
    return OrderedDict((k, v) for k, v in grouped.items() if v)


def resolve_link(row: Dict[str, str], hub_origin: str) -> str:
    """Resolve the per-doc Hub link. Prefer the smoke CSV's
    ``hub_document_url`` column when populated; otherwise fall back
    to ``/documents/{hub_doc_id}``. When ``hub_origin`` is provided,
    relative links are prepended with the origin."""
    raw_url = (row.get("hub_document_url") or "").strip()
    doc_id = (row.get("hub_doc_id") or "").strip()
    if raw_url.startswith(("http://", "https://")):
        return raw_url
    if not raw_url and not doc_id:
        return ""
    rel = raw_url or f"/documents/{doc_id}"
    if hub_origin:
        return hub_origin.rstrip("/") + (
            rel if rel.startswith("/") else "/" + rel)
    return rel


# ---------------------------------------------------------------------------
# Findings CSV
# ---------------------------------------------------------------------------

def write_findings_csv(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FINDINGS_COLUMNS)
        w.writeheader()


def prefilled_findings_row(row: Dict[str, str], link: str) -> str:
    """Build a CSV-formatted single line with the per-doc fields
    pre-populated. Tester / Date / yes-no boxes / notes / severity /
    owner are left blank for the tester to fill in."""
    values = {
        "Tester": "",
        "Date": "",
        "Priority": row.get("priority") or "",
        "Category": row.get("test_doc_category") or "",
        "Hub Doc ID": row.get("hub_doc_id") or "",
        "File Name": row.get("file_name") or "",
        "Hub URL": link,
        "Opened?": "",
        "Preview loaded?": "",
        "AP panel visible?": "",
        "Fields visible?": "",
        "Status understandable?": "",
        "Problem notes": "",
        "Severity": "",
        "Follow-Up Owner": "",
    }
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FINDINGS_COLUMNS,
                       quoting=csv.QUOTE_MINIMAL)
    w.writerow(values)
    return buf.getvalue().rstrip("\r\n")


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

HTML_HEAD = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>AP Smoke Walk — INTERNAL</title>
<style>
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; max-width: 980px; margin: 0 auto; padding: 16px 22px 64px; line-height: 1.45; }
  header { border-bottom: 2px solid #000; margin-bottom: 16px; padding-bottom: 8px; }
  h1 { margin: 0 0 4px; font-size: 22px; }
  .banner { background: #fee; color: #900; border: 1px solid #f99; padding: 8px 12px; border-radius: 6px; font-weight: 600; margin: 12px 0; }
  .meta { color: #666; font-size: 13px; }
  h2 { margin-top: 28px; padding-top: 8px; border-top: 1px solid #ddd; font-size: 17px; }
  .priority-badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-weight: 700; font-size: 12px; vertical-align: 2px; margin-right: 8px; }
  .p-P0 { background: #c00; color: #fff; }
  .p-P1 { background: #d80; color: #fff; }
  .p-P2 { background: #888; color: #fff; }
  .p-P3 { background: #aaa; color: #fff; }
  .card { border: 1px solid #ccc; border-radius: 8px; padding: 14px 16px; margin: 14px 0; background: #fafafa; }
  .card h3 { margin: 0 0 6px; font-size: 15px; word-break: break-all; }
  .card .id { color: #666; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
  .card .link { display: inline-block; margin: 6px 0 10px; }
  .card .link a { word-break: break-all; }
  .check-row { display: flex; flex-wrap: wrap; gap: 14px; padding: 8px 0; }
  .check-row label { font-size: 13px; user-select: none; }
  .field-row { display: grid; grid-template-columns: 130px 1fr; gap: 6px 12px; margin: 6px 0; font-size: 13px; }
  .field-row .k { color: #555; font-weight: 600; }
  .notes textarea, .findings textarea { width: 100%; box-sizing: border-box; font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; padding: 6px 8px; border: 1px solid #bbb; border-radius: 4px; }
  .notes textarea { min-height: 56px; }
  .findings textarea { min-height: 38px; background: #f3f3f3; color: #222; }
  .findings .head { display: flex; align-items: center; justify-content: space-between; margin-top: 10px; gap: 8px; }
  .findings button { font-size: 12px; padding: 4px 8px; cursor: pointer; }
  .severity, .owner { display: inline-block; }
  .severity select, .owner input { font-size: 12px; padding: 2px 6px; }
  .checked-yes { background: #efe; }
  details { margin-top: 8px; }
  summary { cursor: pointer; font-size: 12px; color: #555; }
  .legend { font-size: 12px; color: #555; margin: 8px 0 0; }
  @media print {
    .findings button { display: none; }
    body { max-width: none; }
    .card { page-break-inside: avoid; }
  }
</style>
</head>
<body>
"""

HTML_TAIL = """
<script>
  // One-click copy for prefilled findings rows.
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('button.copy-btn');
    if (!btn) return;
    var ta = document.getElementById(btn.dataset.target);
    if (!ta) return;
    ta.select();
    try {
      navigator.clipboard.writeText(ta.value).then(function () {
        btn.textContent = 'Copied';
        setTimeout(function () { btn.textContent = 'Copy row'; }, 1200);
      });
    } catch (err) {
      document.execCommand('copy');
      btn.textContent = 'Copied';
      setTimeout(function () { btn.textContent = 'Copy row'; }, 1200);
    }
  });
</script>
</body>
</html>
"""


def _esc(s: Optional[str]) -> str:
    return _html.escape("" if s is None else str(s))


def render_html(grouped: "OrderedDict[str, List[Dict[str, str]]]",
                hub_origin: str,
                priorities_label: str,
                input_csv_path: str,
                total_rows: int) -> str:
    parts: List[str] = [HTML_HEAD]
    parts.append("<header>")
    parts.append("<h1>AP Smoke Walk — INTERNAL</h1>")
    parts.append("<div class=\"meta\">"
                 f"Source: <code>{_esc(input_csv_path)}</code>"
                 f" · Rows: {total_rows}"
                 f" · Priorities: {_esc(priorities_label)}"
                 + (f" · Hub origin: <code>{_esc(hub_origin)}</code>"
                    if hub_origin else
                    " · Hub origin: <em>(not set — links are relative; "
                    "paste behind your Hub origin)</em>")
                 + "</div>"
                 "<div class=\"banner\">INTERNAL — IT / Engineering only. "
                 "Do not send to AP. Observation walk; do not save "
                 "corrections during this pass.</div>"
                 "<div class=\"legend\">For each card: open the link, "
                 "answer the five yes/no questions, write a one-line "
                 "<strong>Problem notes</strong> if anything was off, "
                 "set <strong>Severity</strong>, then click "
                 "<em>Copy row</em> and paste into "
                 "<code>AP_SMOKE_WALK_FINDINGS.csv</code>.</div>")
    parts.append("</header>")

    card_idx = 0
    for priority, rows in grouped.items():
        parts.append(f"<h2><span class=\"priority-badge p-{_esc(priority)}\">"
                     f"{_esc(priority)}</span>{len(rows)} document(s)</h2>")
        for row in rows:
            card_idx += 1
            link = resolve_link(row, hub_origin)
            findings_id = f"findings-{card_idx}"
            parts.append("<div class=\"card\">")
            parts.append(f"<span class=\"priority-badge p-{_esc(priority)}\">"
                         f"{_esc(priority)}</span>")
            parts.append("<h3>"
                         f"{_esc(row.get('file_name') or '(no file name)')}"
                         "</h3>")
            parts.append(f"<div class=\"id\">"
                         f"category={_esc(row.get('test_doc_category') or '')} "
                         f"· hub_doc_id={_esc(row.get('hub_doc_id') or '')}</div>")
            if link:
                parts.append("<div class=\"link\">"
                             f"<a href=\"{_esc(link)}\" target=\"_blank\" rel=\"noopener\">"
                             f"{_esc(link)}</a></div>")
            else:
                parts.append("<div class=\"link\"><em>(no link — "
                             "doc id missing in source row)</em></div>")

            # Field rows from the smoke CSV
            for field in (
                ("vendor_canonical", "Vendor"),
                ("invoice_number_clean", "Invoice #"),
                ("invoice_date", "Invoice Date"),
                ("amount_float", "Amount"),
                ("po_number_clean", "PO Number"),
                ("doc_type", "Doc Type"),
                ("routing_status", "Routing"),
            ):
                v = row.get(field[0]) or ""
                if v:
                    parts.append(
                        "<div class=\"field-row\">"
                        f"<span class=\"k\">{_esc(field[1])}</span>"
                        f"<span>{_esc(v)}</span></div>")

            # What to check / expected / notes
            for field in (
                ("why_this_doc_is_in_the_test_set", "Why"),
                ("what_tester_should_check", "Check"),
                ("expected_result", "Expected"),
                ("notes", "Notes"),
            ):
                v = row.get(field[0]) or ""
                if v:
                    parts.append(
                        "<div class=\"field-row\">"
                        f"<span class=\"k\">{_esc(field[1])}</span>"
                        f"<span>{_esc(v)}</span></div>")

            # Checkboxes
            parts.append("<div class=\"check-row\">")
            for label in ("Opened", "Preview loaded",
                          "AP panel visible / N/A", "Fields visible",
                          "Status understandable", "Problem found"):
                parts.append(f"<label><input type=\"checkbox\"> "
                             f"{_esc(label)}</label>")
            parts.append("</div>")

            # Problem notes / Severity / Owner
            parts.append("<div class=\"notes\">"
                         "<label style=\"font-size:12px;color:#555\">"
                         "Problem notes</label>"
                         "<textarea placeholder=\"One sentence in your own "
                         "words; leave blank if Pass.\"></textarea>"
                         "</div>")
            parts.append("<div class=\"check-row\">")
            parts.append("<span class=\"severity\">"
                         "<label style=\"font-size:12px;color:#555\">"
                         "Severity</label> "
                         "<select>"
                         "<option value=\"\">(blank if Pass)</option>"
                         "<option>Blocker</option>"
                         "<option>Critical</option>"
                         "<option>High</option>"
                         "<option>Medium</option>"
                         "<option>Low</option>"
                         "</select></span>")
            parts.append("<span class=\"owner\">"
                         "<label style=\"font-size:12px;color:#555\">"
                         "Follow-Up Owner</label> "
                         "<input type=\"text\" placeholder=\"Eng owner\">"
                         "</span>")
            parts.append("</div>")

            # Prefilled findings row
            parts.append("<div class=\"findings\">")
            parts.append("<div class=\"head\">"
                         "<label style=\"font-size:12px;color:#555\">"
                         "Prefilled findings row "
                         "(copy → paste into AP_SMOKE_WALK_FINDINGS.csv):"
                         "</label>"
                         f"<button type=\"button\" class=\"copy-btn\" "
                         f"data-target=\"{findings_id}\">Copy row</button>"
                         "</div>")
            prefilled = prefilled_findings_row(row, link)
            parts.append(f"<textarea id=\"{findings_id}\" readonly>"
                         f"{_esc(prefilled)}</textarea>")
            parts.append("</div>")

            parts.append("</div>")  # /.card

    parts.append(HTML_TAIL)
    return "".join(parts)


# ---------------------------------------------------------------------------
# Markdown rendering (mirror of HTML, for readers who prefer text)
# ---------------------------------------------------------------------------

def render_md(grouped: "OrderedDict[str, List[Dict[str, str]]]",
              hub_origin: str,
              priorities_label: str,
              input_csv_path: str,
              total_rows: int) -> str:
    out: List[str] = []
    out.append("# AP Smoke Walk — INTERNAL")
    out.append("")
    out.append("> **INTERNAL — IT / Engineering only.** Do not send "
               "to AP. Observation walk; no corrections saved.")
    out.append("")
    out.append(f"- Source: `{input_csv_path}`")
    out.append(f"- Rows: **{total_rows}**")
    out.append(f"- Priorities: **{priorities_label}**")
    out.append("- Hub origin: "
               + (f"`{hub_origin}`" if hub_origin
                  else "*(not set — links are relative)*"))
    out.append("")
    out.append("Walk each card top-to-bottom. After each doc, copy "
               "the prefilled findings row from the HTML packet into "
               "`AP_SMOKE_WALK_FINDINGS.csv`.")
    out.append("")

    for priority, rows in grouped.items():
        out.append(f"## {priority} — {len(rows)} document(s)")
        out.append("")
        for row in rows:
            link = resolve_link(row, hub_origin)
            out.append(f"### {row.get('file_name') or '(no file name)'}")
            out.append("")
            out.append(f"- **Priority:** {priority}")
            out.append(f"- **Category:** `{row.get('test_doc_category') or ''}`")
            out.append(f"- **Hub doc id:** `{row.get('hub_doc_id') or ''}`")
            if link:
                out.append(f"- **Link:** {link}")
            for k, label in (
                ("vendor_canonical", "Vendor"),
                ("invoice_number_clean", "Invoice #"),
                ("invoice_date", "Invoice Date"),
                ("amount_float", "Amount"),
                ("po_number_clean", "PO Number"),
                ("routing_status", "Routing"),
            ):
                v = row.get(k) or ""
                if v:
                    out.append(f"- **{label}:** {v}")
            for k, label in (
                ("why_this_doc_is_in_the_test_set", "Why"),
                ("what_tester_should_check", "Check"),
                ("expected_result", "Expected"),
                ("notes", "Notes"),
            ):
                v = row.get(k) or ""
                if v:
                    out.append(f"- **{label}:** {v}")
            out.append("")
            out.append("Checks: ☐ Opened · ☐ Preview loaded · "
                       "☐ AP panel visible / N/A · ☐ Fields visible · "
                       "☐ Status understandable · ☐ Problem found")
            out.append("")
            out.append("Severity: Blocker / Critical / High / Medium / "
                       "Low / (blank if Pass)")
            out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def render_console(*, grouped: "OrderedDict[str, List[Dict[str, str]]]",
                   total_rows: int, priorities_label: str,
                   out_html: str, out_md: str,
                   out_findings_csv: str,
                   input_csv_path: str,
                   hub_origin: str) -> str:
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(" ap_smoke_walk_pack")
    lines.append("=" * 72)
    lines.append(f"  source CSV       : {input_csv_path}")
    lines.append(f"  total rows       : {total_rows}")
    lines.append(f"  priorities       : {priorities_label}")
    lines.append(f"  hub origin       : {hub_origin or '(relative links)'}")
    lines.append("")
    lines.append("  rows by priority:")
    for p in PRIORITY_ORDER:
        if p in grouped:
            lines.append(f"    {p:5s} {len(grouped[p]):3d}")
    lines.append("")
    lines.append(f"  out_html         : {out_html}")
    lines.append(f"  out_md           : {out_md}")
    lines.append(f"  out_findings_csv : {out_findings_csv}")
    lines.append("")
    lines.append("  READ-ONLY. No DB writes. Do not send to AP.")
    lines.append("=" * 72)
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Generate a tester-friendly AP smoke-walk packet "
                    "(HTML + MD + findings CSV) from the curated "
                    "smoke-test document set.")
    p.add_argument("--input-csv", default=DEFAULT_INPUT_CSV)
    p.add_argument("--hub-origin", default="",
                   help="Optional. Prepended to relative /documents/ links.")
    p.add_argument("--priorities", default="",
                   help="Comma-separated priorities to include "
                        "(e.g. 'P0,P1'). Default: all.")
    p.add_argument("--out-html", default=DEFAULT_OUT_HTML)
    p.add_argument("--out-md", default=DEFAULT_OUT_MD)
    p.add_argument("--out-findings-csv", default=DEFAULT_OUT_FINDINGS_CSV)
    args = p.parse_args(argv)

    try:
        rows = read_smoke_csv(args.input_csv)
    except FileNotFoundError as e:
        print(f"ap_smoke_walk_pack: {e}", file=sys.stderr)
        return 2

    priorities = parse_priorities(args.priorities)
    filtered = filter_rows(rows, priorities)
    if not filtered:
        print(
            "ap_smoke_walk_pack: 0 rows matched after filtering "
            f"(priorities={priorities!r}). Nothing to write.",
            file=sys.stderr,
        )
        return 3

    grouped = group_by_priority(filtered)
    priorities_label = (",".join(priorities) if priorities
                        else "ALL")
    total_rows = len(filtered)

    html_text = render_html(grouped, args.hub_origin, priorities_label,
                            args.input_csv, total_rows)
    md_text = render_md(grouped, args.hub_origin, priorities_label,
                        args.input_csv, total_rows)

    os.makedirs(os.path.dirname(args.out_html) or ".", exist_ok=True)
    with open(args.out_html, "w", encoding="utf-8") as f:
        f.write(html_text)
    os.makedirs(os.path.dirname(args.out_md) or ".", exist_ok=True)
    with open(args.out_md, "w", encoding="utf-8") as f:
        f.write(md_text)
    write_findings_csv(args.out_findings_csv)

    print(render_console(
        grouped=grouped, total_rows=total_rows,
        priorities_label=priorities_label,
        out_html=args.out_html, out_md=args.out_md,
        out_findings_csv=args.out_findings_csv,
        input_csv_path=args.input_csv,
        hub_origin=args.hub_origin,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
