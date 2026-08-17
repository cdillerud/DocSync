# GPI Commercial Guardrail POC

This is the first executable proof-of-concept for the Hawkeye use cases discussed on August 17, 2026.

It deliberately starts **without AI and without write access to Business Central**. The first goal is to prove that Gamer-specific commercial rules and historical transaction patterns can reliably surface exceptions from a small dataset.

## What v0.1 detects

- Gross-profit anomalies relative to a customer's history for an item
- Supplier cost increases where the customer's sell price stayed flat
- Sell prices materially below the customer's historical price
- Items the customer has not previously purchased in the supplied history
- Explicit minimum-GP and minimum-sell rules
- Fixed-price mismatches
- Special-pricing customers/items

## Safety principle

`SPECIAL_PRICING` and `FIXED_PRICE` rules act as a firewall.

The engine may calculate and display margin exposure, but any normal price-change action is replaced with **REVIEW SPECIAL PRICING RULE**. It never automatically decides that a protected customer's price should be increased.

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

Supported rule types in v0.1:

- `SPECIAL_PRICING`
- `FIXED_PRICE`
- `MIN_GP`
- `MIN_SELL`

## Run the sample

From the repository root:

```powershell
python -m poc.commercial_guardrails.cli `
  --transactions poc/commercial_guardrails/sample_transactions.csv `
  --guardrails poc/commercial_guardrails/sample_guardrails.csv `
  --out poc/commercial_guardrails/exceptions.csv
```

The command prints a JSON summary and writes the detailed exception file.

## POC acceptance scenarios

The included synthetic data exercises the same five concepts from the Hawkeye discussion:

1. Supplier cost increases while sell remains flat
2. Protected Giovanni-style pricing
3. Customer orders a previously unseen B64 item instead of its usual CDL
4. GP drops materially below historical behavior
5. Rule-based margin protection

## Next slice

Replace the synthetic transaction CSV with the small 12oz ringneck dataset from Megan/Charlie.

Once the flags are useful, add a **read-only BC adapter** to retrieve the same fields from Sandbox/UAT. Only after that should we add supplier-email/PDF ingestion or rep-facing workflow.
