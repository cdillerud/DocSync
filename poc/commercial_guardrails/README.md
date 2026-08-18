# GPI Commercial Guardrail POC

This is the executable proof-of-concept for the Hawkeye use cases discussed on August 17, 2026.

It deliberately starts **without AI and without write access to Business Central**. The goal is to prove that Gamer-specific commercial rules and historical transaction patterns can reliably surface exceptions before any automated write-back is considered.

## What the current POC detects

- Gross-profit anomalies relative to a customer's exact item/UOM history
- Supplier cost increases where the customer's sell price stayed flat
- Sell prices materially below or above the customer's historical price
- Related items the customer buys when the proposed exact item has no history
- Explicit minimum-GP and minimum-sell rules in the historical engine
- Fixed-price mismatches
- Special-pricing customers/items
- Read-only ingestion of posted Business Central sales history
- Live proposal checks that combine price, item-family, margin, and special-pricing protection

## Safety principle

`SPECIAL_PRICING` and `FIXED_PRICE` rules act as a firewall.

The engine may calculate and display price or margin exposure, but any normal pricing action on a protected proposal is replaced with **REVIEW SPECIAL PRICING RULE** and, when configured, the named approver. The guardrail does not infer or recommend a replacement price from general history for protected pricing.

A `FIXED_PRICE` mismatch is surfaced as `CRITICAL`. If multiple equally specific active fixed-price rules disagree, the POC surfaces a configuration conflict instead of choosing one.

The BC adapter performs data GET requests only. The only POST request it can make is the Microsoft Entra OAuth token exchange. It contains no BC create, update, post, release, or delete operation.

## CSV inputs

### Transactions

Required columns:

`transaction_id, order_no, transaction_date, customer_no, customer_name, item_no, item_description, quantity, uom, unit_cost, unit_sell_price`

Optional columns:

`sales_rep, special_pricing`

### Guardrails

Columns:

`customer_no, item_no, rule_type, min_gp_pct, min_sell_price, locked_sell_price, effective_from, effective_to, approver, notes`

`customer_no` and `item_no` may use `*` as a wildcard. Effective dates are inclusive and optional. The live proposal firewall currently uses `SPECIAL_PRICING` and `FIXED_PRICE`; the historical engine also supports `MIN_GP` and `MIN_SELL`.

The checked-in `sample_guardrails.csv` contains POC examples only. Do not treat those rows as authoritative Gamer pricing agreements.

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

### Standard API usage

The live proposal checker uses standard Business Central v2 APIs for posted sales invoice/customer/item history and the custom read-only query for historical cost/margin data. The standard root `salesInvoiceLines` endpoint is not used directly; invoice lines are expanded from posted sales invoices.

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

Never commit these values. Temporary access tokens expire and must be refreshed when BC returns `401 Unauthorized`.

### Historical BC analysis

```powershell
python -m poc.commercial_guardrails.bc_cli `
  --source custom `
  --start-date 2024-01-01 `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>"
```

The command writes normalized BC transactions and exceptions to CSV when output paths are supplied.

## Live proposal check

Example:

```powershell
python -m poc.commercial_guardrails.bc_proposal_cli `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>" `
  --price 195.00 `
  --quantity 10 `
  --uom "M" `
  --start-date 2024-01-01
```

The checker can combine:

- exact customer/item price history
- automatic related-item discovery
- exact customer/item/UOM GP history
- latest posted historical cost as a clearly labeled proposal-time proxy
- special-pricing/fixed-price protection

### Special-pricing firewall

Pass a reviewed pricing-rule CSV and a proposal date:

```powershell
python -m poc.commercial_guardrails.bc_proposal_cli `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>" `
  --price 195.00 `
  --quantity 10 `
  --uom "M" `
  --start-date 2024-01-01 `
  --guardrails "<reviewed-pricing-rules.csv>" `
  --proposal-date 2026-08-17
```

When an active `SPECIAL_PRICING` or `FIXED_PRICE` rule matches the exact customer/item or a configured wildcard, output includes a `SPECIAL PRICING FIREWALL` section and `SPECIAL_PRICING_PROTECTED`. Price and GP evidence remains visible, but pricing actions are redirected to the configured approver.

Family-level special pricing is intentionally **not inferred** from description similarity. Until Gamer defines an authoritative family mapping/rule source, protected pricing must match an exact item or an explicit `*` wildcard. This avoids silently extending a contract price to related but non-equivalent SKUs.

## POC validations completed

Using real posted BC history in `Sandbox_NoZetadocs_UAT`:

1. TRIPLEH at `$195/M` correctly produced both `SELL_BELOW_CUSTOMER_HISTORY` and `LOW_GP_ANOMALY`.
2. The same TRIPLEH item at its established `$224.81/M` price correctly passed with no proposal exceptions.
3. GRUMPY proposed on a related hot-fill ringneck item with no exact-item history correctly produced `SIMILAR_ITEM_SUBSTITUTION` while refusing to invent a margin baseline.
4. Historical TRIPLEH transactions themselves produced zero margin exceptions, demonstrating a stable baseline rather than a noisy detector.

## Next slice

1. Populate a small **reviewed** special-pricing rule file from authoritative Gamer agreements/ownership, rather than guessing from history.
2. Validate one protected customer/item and one fixed-price mismatch end to end.
3. Decide where the authoritative rule table should live long term, likely Business Central rather than a local CSV.
4. Then move to quote/extras guidance and supplier-price ingestion.

Supplier-email/PDF ingestion and rep-facing workflow remain out of scope until these core commercial safety controls are accepted.
