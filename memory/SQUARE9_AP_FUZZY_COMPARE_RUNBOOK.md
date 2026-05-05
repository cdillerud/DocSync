# Square9 Cutover — SharePoint AP Folder Fuzzy Comparison

- Owner: Operations / Engineering.
- Generated: 2026-05-02 (UTC).
- Companion to: `SQUARE9_CUTOVER_ACCEPTANCE_CHECKLIST.md` §6 (E5b).
- Script: `backend/scripts/sharepoint_ap_compare.py`.

## Why this exists

The first prod-vs-test comparison of the AP Temp Folder returned
zero matches. That is almost certainly a matcher problem, not a
real-world overlap problem. Filenames diverge between prod and
test for normal reasons:

- Suffixes added or removed (`DO NOT PAY`, `BOL`, `copy`,
  `Final`, `Final Final`, `scan`).
- Underscore vs space vs hyphen separators.
- Vendor-name token order (`Canpack BOL 778899` vs
  `Canpack_778899_BOL`).
- Date-format reshuffles (`03-2026` vs `03_2026`).
- Accents / case differences.

Strict filename equality misses all of those. The fuzzy
comparator now matches on multiple signals and surfaces the
"obviously the same document" pairs the strict matcher missed.

## Authoritative AP destination

Production AP path of record (locked):

    /sites/GamerAccounting/Shared Documents/General/Accounting/Accounts Payable/Temp Folder

Both listings (prod + test) must be pulled from the equivalent
folder in their respective tenants. Test destination must be the
test-environment counterpart of `Accounts Payable/Temp Folder`,
not the parent `Accounts Payable`.

## What the script does

For every prod doc, it picks the best test-side candidate and
classifies the pair into exactly one bucket:

- exact_match     — normalized filenames identical.
- likely_match    — same invoice/PO token + size or date match,
                    OR vendor-token overlap >=2 + size equal,
                    OR normalized fuzzy ratio >= 0.92.
- possible_match  — invoice/PO token alone, OR vendor token + day
                    distance <=7, OR fuzzy ratio >= 0.85.
- no_match        — none of the above.

Outputs a revised CSV with: prod row, best test row, confidence,
score breakdown (norm_ratio, inv_po_overlap, vendor_overlap,
size_signal, modified_day_distance), and a `previously_missed`
flag if a prior strict-match output is supplied.

## Inputs

Two CSV listings, one per folder. Required columns:
`name, size, modified`. Optional: `web_url, id, parent_path`.

If you do not already have a "prior strict-match output", just
omit the `--prior-strict-csv` argument; the script still runs,
it just won't fill the `previously_missed` column.

## Operator runbook (run on prod VM, single SSH session)

Step 1 — pull current listings into CSV. (Use whichever method
your existing tooling already uses to dump SharePoint folder
contents to CSV. The CSV must have `name,size,modified`.)

Save them, by convention, into:

    prod_reports/sp_prod_ap_temp_listing.csv
    prod_reports/sp_test_ap_temp_listing.csv

Step 2 — (optional) keep your prior strict-match CSV at:

    prod_reports/sp_strict_match_prev.csv

with at least columns `name,status` where status is one of
`match` / `no_match`.

Step 3 — run the fuzzy comparator. Bare line:

    docker compose exec -T backend python -m backend.scripts.sharepoint_ap_compare --prod-csv prod_reports/sp_prod_ap_temp_listing.csv --test-csv prod_reports/sp_test_ap_temp_listing.csv --prior-strict-csv prod_reports/sp_strict_match_prev.csv --out-csv prod_reports/sp_ap_compare_fuzzy.csv --top 25

Step 4 — review stdout. The summary block prints counts per
bucket and a top-N list of `likely_match` rows that were
`previously_missed` by the strict matcher.

Step 5 — open `prod_reports/sp_ap_compare_fuzzy.csv` for the
full row-by-row evidence. Sort by confidence to triage.

## How to read the result

| Outcome | Meaning |
|---|---|
| Non-zero exact_match + likely_match counts | Real overlap exists. The earlier "0 matches" result was a matcher artifact. Proceed to evidence E5b on the acceptance checklist. |
| Zero exact + likely + possible_match | Genuine red flag — prod and test really do not share documents. Investigate destination paths first (#1), file-renaming pipelines (#2), and ingestion subset (#3) before drawing conclusions about the matcher (#4). |
| Many no_match in addition to matches | Expected — test typically lags prod on volume. Volume gap is not a blocker by itself; pair-level coverage of recently-ingested AP docs is what matters. |

## Tuning

If you need to tighten or loosen buckets in a future iteration,
the only places to edit in `sharepoint_ap_compare.py` are:

- `_SUFFIX_NOISE` — add observed suffixes that should be
  scrubbed before normalized-equality comparison.
- `_INVOICE_PO_PATTERNS` — add vendor-specific reference patterns
  (e.g., a vendor that prefixes invoices with a 3-letter code).
- `score_pair()` — bucket cutoffs (ratio thresholds, size %
  bands, day-distance bands).

No schema, API, or DB changes. The script is fully read-only and
stdlib-only (no extra Python deps beyond what's already in the
backend image).
