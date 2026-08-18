# GPI Commercial Guardrail POC

This is the executable proof-of-concept for the Hawkeye use cases discussed on August 17, 2026.

It deliberately starts **without AI and without write access from the Python guardrail client to Business Central**. The goal is to prove that Gamer-specific commercial rules and historical transaction patterns can reliably surface exceptions before any automated write-back is considered.

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

Family-level special pricing is intentionally **not inferred** from description similarity. Protected pricing must match an exact item or an explicit wildcard maintained in the authoritative rule table.

## Business Central integration

### Historical sales

The standalone POC extension exposes:

`gpi/commercialGuardrails/v1.0/historicalSalesLines`

It joins posted Sales Invoice Header and Sales Invoice Line data and exposes invoice/order/date/customer/item/UOM/quantity/cost/sell information through a read-only API query.

The live proposal checker also uses standard Business Central v2 APIs for posted invoice/customer/item history and automatic related-item discovery.

### Authoritative pricing guardrails

The POC extension now includes Business Central table:

`GPI Pricing Guardrail`

Fields include:

- Enabled
- Customer No. (blank = all customers)
- Item No. (blank = all items)
- Rule Type: Special Pricing or Fixed Price
- Locked Sell Price
- Effective From / Effective To
- Approver
- Notes

Business Central users maintain these records through the `GPI Pricing Guardrails` page.

The Python client reads enabled rules through:

`gpi/commercialGuardrails/v1.0/pricingGuardrails`

That API page has `InsertAllowed = false`, `ModifyAllowed = false`, and `DeleteAllowed = false`. The Python client therefore treats Business Central as the authoritative rule source but cannot change pricing guardrails through the API.

The assignable permission set `GPI COMM GUARD POC` grants the Entra application read access to posted Sales Invoice Header/Line data and `GPI Pricing Guardrail`, plus execute access to the two read-only API objects.

## Authentication

Environment variables:

```powershell
$env:BC_ENVIRONMENT = "Sandbox_NoZetadocs_UAT"
$env:BC_TENANT_ID = "<tenant-guid>"
$env:BC_CLIENT_ID = "<app-client-id>"
$env:BC_CLIENT_SECRET = "<secret>"
$env:BC_COMPANY_NAME = "<exact BC company display name>"
```

A temporary token may be supplied instead:

```powershell
$env:BC_ACCESS_TOKEN = "<token>"
```

Never commit credentials. Temporary tokens expire and must be refreshed when BC returns `401 Unauthorized`.

## Historical BC analysis

```powershell
python -m poc.commercial_guardrails.bc_cli `
  --source custom `
  --start-date 2024-01-01 `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>"
```

## Pricing-rule probe

Use this to prove the rule maintained in Business Central can be read and matched:

```powershell
python -m poc.commercial_guardrails.bc_pricing_rule_probe `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>" `
  --proposal-date 2026-08-17
```

Business Central may encode enum captions over OData, for example `Special_x0020_Pricing`. The adapter decodes those values before applying the firewall.

## Live proposal check

Business Central pricing rules are now loaded **automatically by default**:

```powershell
python -m poc.commercial_guardrails.bc_proposal_cli `
  --customer "<CUSTOMER-NO>" `
  --item "<ITEM-NO>" `
  --price 195.00 `
  --quantity 10 `
  --uom "M" `
  --start-date 2024-01-01 `
  --proposal-date 2026-08-17
```

The output shows:

- `Pricing rule source: BUSINESS CENTRAL`
- count of enabled rules read from BC
- whether the exact proposal is protected
- matching rule type, approver, and notes
- historical price evidence
- historical GP evidence
- item-family/substitution evidence

If the Business Central pricing-rule API cannot be read, the command **fails closed** rather than returning a false `PASS` without the special-pricing protection layer.

### Explicit troubleshooting overrides

`--guardrails <file.csv>` remains available only as a local CSV override for testing/offline development.

`--no-special-pricing` explicitly disables the firewall and should be used only for intentional troubleshooting. It cannot be combined with `--guardrails`.

## POC validations completed

Using real posted BC history in `Sandbox_NoZetadocs_UAT`:

1. TRIPLEH at `$195/M` produced both `SELL_BELOW_CUSTOMER_HISTORY` and `LOW_GP_ANOMALY`.
2. The same TRIPLEH item at its established `$224.81/M` price passed with no proposal exceptions.
3. GRUMPY proposed on a related hot-fill ringneck item with no exact-item history produced `SIMILAR_ITEM_SUBSTITUTION` while refusing to invent a margin baseline.
4. Historical TRIPLEH transactions themselves produced zero margin exceptions, demonstrating a stable baseline rather than a noisy detector.
5. A synthetic protected TRIPLEH rule correctly redirected both price and GP actions to the configured approver.
6. The same synthetic rule was moved into Business Central and successfully read back through the read-only `pricingGuardrails` API.

## Current next slice

1. Validate the live proposal checker with **Business Central**, not CSV, as the special-pricing source.
2. Remove the synthetic TRIPLEH rule after that proof.
3. Do not enter real Bragg, Giovanni, or other protected agreements until ownership and authoritative pricing data are reviewed.
4. Then move to quote/extras guidance and supplier-price ingestion.

Supplier-email/PDF ingestion and rep-facing workflow remain out of scope until these core commercial safety controls are accepted.
