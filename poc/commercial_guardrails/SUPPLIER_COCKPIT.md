# GPI Supplier Cost Review Cockpit

The cockpit is a local Streamlit review UI for the validated supplier-price guardrail workflow.

It now supports **manual supplier-notice intake directly in the browser**. A reviewer can upload a CSV, XLSX, or XLSM file, run the same read-only Business Central analysis used by the CLI, and land directly in the human approval workflow.

The cockpit does not monitor email and does not write to Business Central.

## Install

```powershell
python -m pip install -r poc/commercial_guardrails/requirements.txt
```

## Launch

From the repository root:

```powershell
python -m streamlit run poc/commercial_guardrails/supplier_cockpit.py
```

## New supplier notice

Open **New supplier notice** at the top of the cockpit.

Supported uploads:

- `.csv`
- `.xlsx`
- `.xlsm`

The manual upload is limited to 25 MB. Empty or unsupported files are rejected before analysis.

Optional intake fields:

- history start date, default `2024-01-01`
- default supplier when the notice does not carry a supplier name
- Excel worksheet name when a specific sheet must be selected

Click **Analyze and open review**.

The cockpit creates a unique local run folder under:

```text
poc/commercial_guardrails/runs/
```

Each successful run contains:

```text
<run>/
  <original supplier notice>
  approval_queue.csv
  margin_impact.csv
  manifest.json
  decisions.csv        # created when a human decision is saved
```

The manifest records the Business Central environment, source filename, source byte count, SHA-256 hash, queue summary, and the safety contract that Business Central writes are disabled and human approval is required.

If analysis fails after the source has been accepted, the run folder retains the source notice and creates `FAILED.txt` rather than deleting the evidence of what was submitted.

After successful analysis the cockpit automatically switches its queue, detail, and decision paths to the new run. No PowerShell path changes are required.

## Existing local outputs

The cockpit can still open previously generated CSVs through the collapsed **Data sources** sidebar.

Default legacy inputs are:

- `poc/commercial_guardrails/live_supplier_approval_queue.csv`
- `poc/commercial_guardrails/live_supplier_margin_impact.csv`

Default legacy decision output is:

- `poc/commercial_guardrails/live_supplier_approval_decisions.csv`

## What the cockpit shows

- approval item count
- protected item count
- affected and protected customer counts
- actionable margin erosion
- supplier cost change and concentration of exposure
- customer-level sell, cost, projected cost, GP and erosion
- protected-pricing state
- human decision, reviewer, and notes fields
- local decision persistence and CSV download

The approval queue browser remains available in a collapsed section so the selected commercial decision stays above the fold.

## Consistency safety

The queue and customer-margin detail must come from the same analysis snapshot.

The cockpit validates customer count, protected-customer count, erosion, and top exposure. If the detail file is stale or inconsistent with the queue, customer detail is suppressed and **Save decision** is disabled until the run is regenerated.

## Decision safety

Allowed decision values are:

- `APPROVE`
- `HOLD`
- `REJECT`

A reviewer name is required whenever a decision is entered.

`PROTECTED_REVIEW` rows cannot be approved in the generic cockpit. The active Business Central pricing guardrail must be resolved or reviewed through the protected-pricing process first.

Saving a cockpit decision writes only the local `decisions.csv` file for that run. No Business Central item, vendor price, purchase price, sales price, or pricing guardrail record is created or changed.
