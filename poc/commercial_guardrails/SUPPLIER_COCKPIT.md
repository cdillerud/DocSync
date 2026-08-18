# GPI Supplier Cost Review Cockpit

The cockpit is a local Streamlit review UI layered on top of the validated supplier-price POC outputs.

It does not query or write Business Central directly. Generate the queue and margin-impact CSVs with the existing read-only CLI flow, then launch the cockpit.

## Install

```powershell
python -m pip install -r poc/commercial_guardrails/requirements.txt
```

## Launch

From the repository root:

```powershell
python -m streamlit run poc/commercial_guardrails/supplier_cockpit.py
```

Default inputs:

- `poc/commercial_guardrails/live_supplier_approval_queue.csv`
- `poc/commercial_guardrails/live_supplier_margin_impact.csv`

Default decision output:

- `poc/commercial_guardrails/live_supplier_approval_decisions.csv`

The paths can be changed in the cockpit sidebar.

## What the cockpit shows

- approval item count
- protected item count
- affected and protected customer counts
- actionable margin erosion
- supplier/item/effective-date filters
- editable human decision, reviewer, and notes fields
- item-level cost-change and exposure summary
- customer-level margin drill-down when the margin-impact CSV is available
- local save and CSV download for completed decisions

## Decision safety

Allowed decision values are:

- `APPROVE`
- `HOLD`
- `REJECT`

A reviewer name is required whenever a decision is entered.

`PROTECTED_REVIEW` rows cannot be approved in the generic cockpit. The active Business Central pricing guardrail must be resolved or reviewed through the protected-pricing process first.

Saving a cockpit decision writes only the local decision CSV. No Business Central item, vendor price, purchase price, sales price, or pricing guardrail record is created or changed.
