# GPI Commercial Guardrail POC

This is the first executable proof-of-concept for the Hawkeye use cases discussed on August 17, 2026.

It deliberately starts **without AI and without write access to Business Central**. The first goal is to prove that Gamer-specific commercial rules and historical transaction patterns can reliably surface exceptions from a small dataset.

## What v0.2 detects

- Gross-profit anomalies relative to a customer's history for an item
- Supplier cost increases where the customer's sell price stayed flat
- Sell prices materially below the customer's historical price
- Items the customer has not previously purchased in the supplied history
- Explicit minimum-GP and minimum-sell rules
- Fixed-price mismatches
- Special-pricing customers/items
- Read-only ingestion of posted Business Central sales history

## Safety principle

`SPECIAL_PRICING` and `FIXED_PRICE` rules act as a firewall.

The engine may calculate and display margin exposure, but any normal price-change action is replaced with **REVIEW SPECIAL PRICING RULE**. It never automatically decides that a protected customer's price should be increased.

The BC adapter performs data GET requests only. The only POST request it can make is the Microsoft Entra OAuth token exchange. It contains no BC create, update, post, release, or delete operation.

## CSV inputs

### Transactions

Required columns:

`transaction_id, order_no, transaction_date, customer_no, customer_name, item_no, item_description, quantity, uom, unit_cost, unit_sell_price`

Optional columns:

`sales_rep, special_pricing`

### Guardrails

Columns:

`customer_no, item_no, rule_type, min_gp_pct, min_sell_price, locked_sell_price, approver, notes`

`customer_no` and `item_no` may use `*` as a wildcard.

Supported rule types:

- `SPECIAL_PRICING`
- `FIXED_PRICE`
- `MIN_GP`
- `MIN_SELL`

## Run the synthetic sample

From the repository root:

```powershell
python -m poc.commercial_guardrails.cli `
  --transactions poc/commercial_guardrails/sample_transactions.csv `
  --guardrails poc/commercial_guardrails/sample_guardrails.csv `
  --out poc/commercial_guardrails/exceptions.csv
```

## Business Central read-only ingestion

### Preferred source: GPI custom API query

The folder `bc_extension` contains a standalone POC AL extension with one API query:

`gpi/commercialGuardrails/v1.0/historicalSalesLines`

It joins posted Sales Invoice Header and Sales Invoice Line data and exposes:

- invoice number
- source order number
- posting date
- customer number/name
- salesperson
- item number/description
- sales quantity
- quantity base
- unit of measure
- Unit Cost (LCY)
- unit price
- net line amount

Because it is an `API` query and `DataAccessIntent = ReadOnly`, it does not expose BC write operations.

The extension also defines assignable permission set `GPI COMM GUARD POC`. It grants only read access to posted Sales Invoice Header/Line data plus execute permission to the API query. Assign that permission set to the BC Entra application used for the POC rather than granting a broad functional role.

### Fallback source: Microsoft Analytics API

The adapter can also read:

`microsoft/analytics/v1.0/salesInvoiceLines`

This is useful before the POC extension is published. It exposes posted invoice amount and Unit Cost (LCY), but only `quantityBase`, not the original sales UOM. Treat results from this path as exploratory when items can be sold in multiple units of measure.

### Environment variables

Use a dedicated Entra application with only the BC permissions required for read access.

```powershell
$env:BC_ENVIRONMENT = "Sandbox_NoZetadocs_UAT"
$env:BC_TENANT_ID = "<tenant-guid>"
$env:BC_CLIENT_ID = "<app-client-id>"
$env:BC_CLIENT_SECRET = "<secret>"
$env:BC_COMPANY_NAME = "<exact BC company display name>"
```

Instead of client credentials, a temporary access token can be supplied as:

```powershell
$env:BC_ACCESS_TOKEN = "<token>"
```

Never commit these values.

### Run against BC

Preferred UOM-aware custom endpoint:

```powershell
python -m poc.commercial_guardrails.bc_cli `
  --source custom `
  --start-date 2025-01-01 `
  --end-date 2026-08-17 `
  --item "<12OZ-RINGNECK-ITEM-NO>" `
  --guardrails poc/commercial_guardrails/sample_guardrails.csv
```

Quick fallback using the Microsoft Analytics API:

```powershell
python -m poc.commercial_guardrails.bc_cli `
  --source analytics `
  --start-date 2025-01-01 `
  --end-date 2026-08-17 `
  --item "<12OZ-RINGNECK-ITEM-NO>"
```

The command writes both normalized BC transactions and the resulting exceptions to CSV so the calculations can be audited.

## POC acceptance scenarios

The included synthetic data exercises the same five concepts from the Hawkeye discussion:

1. Supplier cost increases while sell remains flat
2. Protected Giovanni-style pricing
3. Customer orders a previously unseen B64 item instead of its usual CDL
4. GP drops materially below historical behavior
5. Rule-based margin protection

## Next slice

1. Publish the standalone POC API query to `Sandbox_NoZetadocs_UAT`.
2. Run the adapter against one known 12oz ringneck item.
3. Compare the normalized output to Megan's existing analysis.
4. Tune thresholds only after verifying BC quantity, UOM, cost, and net sell calculations.
5. Add customer-specific pricing rules before any broader customer population is analyzed.

Supplier-email/PDF ingestion and rep-facing workflow remain out of scope until the historical margin signals are proven useful.
