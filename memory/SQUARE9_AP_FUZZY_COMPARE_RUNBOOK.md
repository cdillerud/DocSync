# Square9 Cutover — SharePoint AP Folder Fuzzy Comparison

- Owner: Operations / Engineering.
- Generated: 2026-05-02 (UTC); updated to add `--graph-pull` mode.
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

## Two execution modes

### Preferred: `--graph-pull` (one command, no manual export)

The script pulls both folder listings live from SharePoint via
Microsoft Graph using the same env vars the backend already uses
for Graph API. No CSV export step. Read-only.

Required env vars (already present on the prod VM):

- `TENANT_ID`
- `GRAPH_CLIENT_ID`
- `GRAPH_CLIENT_SECRET`
- `SHAREPOINT_SITE_HOSTNAME` (defaults to `gamerpackaging.sharepoint.com`)
- `DEMO_MODE=false` (the script refuses to run with `DEMO_MODE=true`)

Required Graph permission on the app registration:
**`Sites.Read.All` (Application)** with admin consent. Read-only;
no write permissions needed.

Defaults are anchored on the locked production AP destination, so
typically only the test side needs to be specified.

### Fallback: CSV mode

Pre-export both folder listings to CSV (`name,size,modified`
required; `web_url,id` optional) using whatever existing tooling
you already have, then point the script at the two files. Use
this mode only when Graph creds are unavailable.

## Operator runbook (run on prod VM, single SSH session)

### Mode A — `--graph-pull` (preferred)

Bare line. Replace the test site path and folder path with the
real test-environment counterpart of the AP Temp Folder:

    docker compose exec -T backend python -m backend.scripts.sharepoint_ap_compare --graph-pull --test-site-path "/sites/GPI-DocumentHub-Test" --test-folder-path "Accounts Payable/Temp Folder" --out-csv prod_reports/sp_ap_compare_fuzzy.csv --top 25

Optional: pass `--prior-strict-csv prod_reports/sp_strict_match_prev.csv`
to surface "previously missed" rows in the stdout summary.

Optional overrides (only if your setup deviates from the locked
production AP destination):

- `--prod-site-path "/sites/GamerAccounting"` (default)
- `--prod-library "Shared Documents"` (default)
- `--prod-folder-path "General/Accounting/Accounts Payable/Temp Folder"` (default)
- `--test-library "Shared Documents"` (default)

### Mode B — CSV fallback

Bare line:

    docker compose exec -T backend python -m backend.scripts.sharepoint_ap_compare --prod-csv prod_reports/sp_prod_ap_temp_listing.csv --test-csv prod_reports/sp_test_ap_temp_listing.csv --prior-strict-csv prod_reports/sp_strict_match_prev.csv --out-csv prod_reports/sp_ap_compare_fuzzy.csv --top 25

CSVs must have `name,size,modified` columns at minimum.

## What you get

Both modes produce identical artifacts:

1. `prod_reports/sp_ap_compare_fuzzy.csv` — every prod row, with
   the best test-side candidate, confidence bucket, and a score
   breakdown (`norm_ratio`, `inv_po_overlap`, `vendor_overlap`,
   `size_signal`, `modified_day_distance`, `previously_missed`).
2. Stdout summary — counts per bucket and the top-N
   `likely_match` rows that were `previously_missed` by the
   strict matcher.

## How to read the result

| Outcome | Meaning |
|---|---|
| Non-zero `exact_match` + `likely_match` counts | Real overlap exists. The earlier "0 matches" result was a matcher artifact. Proceed to evidence E5b on the acceptance checklist. |
| Zero `exact + likely + possible_match` | Genuine red flag — prod and test really do not share documents. Investigate destination paths first (#1), file-renaming pipelines (#2), and ingestion subset (#3) before drawing conclusions about the matcher (#4). |
| Many `no_match` in addition to matches | Expected — test typically lags prod on volume. Volume gap is not a blocker by itself; pair-level coverage of recently-ingested AP docs is what matters. |

## Tuning

If you need to tighten or loosen buckets in a future iteration,
the only places to edit in `sharepoint_ap_compare.py` are:

- `_SUFFIX_NOISE` — add observed suffixes that should be
  scrubbed before normalized-equality comparison.
- `_INVOICE_PO_PATTERNS` — add vendor-specific reference patterns
  (e.g., a vendor that prefixes invoices with a 3-letter code).
- `score_pair()` — bucket cutoffs (ratio thresholds, size %
  bands, day-distance bands).

No schema, API, or DB changes. The script is read-only against
SharePoint and MongoDB. `--graph-pull` mode adds a runtime
dependency on `httpx`, which is already installed in the backend
image.
