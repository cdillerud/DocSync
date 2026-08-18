# GPI Commercial Guardrail - Manual Supplier Intake

This slice moves the validated supplier-price POC from a single set of `live_*.csv` files to an auditable **one-folder-per-notice** workflow.

It is intentionally manual. It does not monitor Gmail, Outlook, Exchange, Teams, or any other mailbox. A user chooses a local CSV/XLSX/XLSM supplier notice and starts the analysis.

## Why this is the next step

The supplier-price logic is already validated. Before connecting an inbox or automating ingestion, Gamer needs to prove that real supplier notices can be processed repeatably while preserving:

- the exact source notice used for analysis
- the approval queue generated from that notice
- the matching customer-margin detail from the same analysis snapshot
- the eventual human decision log
- a manifest showing the environment and summary counts

Each intake therefore creates a unique local run directory under:

`poc/commercial_guardrails/runs/`

The entire `runs/` tree is gitignored because real notices and Business Central-derived customer data must not be committed.

## Run one supplier notice

From the POC worktree root:

```powershell
python -m poc.commercial_guardrails.bc_supplier_manual_run_cli `
  --input "C:\Path\To\SupplierNotice.xlsx" `
  --start-date 2024-01-01
```

Optional arguments:

```text
--supplier   Default supplier when the file omits supplier name
--sheet      Specific Excel worksheet
--end-date   Optional posted-history end date
--run-root   Alternate root folder for auditable run directories
```

The command uses the same Business Central environment variables and access token as the validated POC.

## Run contents

A successful run creates a directory similar to:

```text
poc/commercial_guardrails/runs/
  20260818T023900Z_SupplierNotice_a1b2c3d4/
    SupplierNotice.xlsx
    approval_queue.csv
    margin_impact.csv
    manifest.json
    decisions.csv        # created later when a cockpit decision is saved
```

`approval_queue.csv` and `margin_impact.csv` are generated from the same in-memory analysis run, so they cannot silently represent different pricing-rule snapshots.

`manifest.json` records the Business Central environment, source filename, summary counts, timestamp, and the safety contract that Business Central writes are disabled and human approval is required.

If analysis fails, the source notice remains in its run directory and a `FAILED.txt` marker is written. This preserves the attempted input for troubleshooting instead of silently deleting it.

## Review the run in the cockpit

Launch the existing cockpit:

```powershell
python -m streamlit run poc/commercial_guardrails/supplier_cockpit.py
```

Open the collapsed **Data sources** sidebar and point it to the run files:

```text
Approval queue CSV      <run folder>\approval_queue.csv
Margin impact detail CSV <run folder>\margin_impact.csv
Decision log CSV         <run folder>\decisions.csv
```

The cockpit continues to validate that queue and detail totals match before permitting a saved decision.

## Safety boundary

This slice does not:

- monitor or search any mailbox
- infer supplier-item mapping from descriptions
- write item costs, vendor prices, purchase prices, sales prices, or guardrail rules to Business Central
- automatically approve a supplier cost change
- automatically change customer sell prices after approval

The next planned step, after this manual intake is proven with a real notice, is to place the intake control directly in the authenticated cockpit so a reviewer can upload a file in the browser. Mailbox ingestion remains a later step and requires explicit authorization.
