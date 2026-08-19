# GPI Packaging Catalog

This is the isolated Business Central foundation for the replacement of `my-packaging-app`.

## Safety boundaries

- GitHub branch: `agent/gpi-packaging-catalog`
- BC target: `Sandbox_NoZetadocs_UAT`
- Object range: `71000..71199`
- No dependency on the Zetadocs replacement extension
- No Production deployment without explicit approval
- Do not merge to `main` without explicit approval

## Milestone 1: catalog foundation

Validated in UAT:

- packaging product master
- vendor/FOB locations
- current supplier unit cost
- metric-ton cost calculation
- supplier cost history
- freight-rate master data
- product list and card pages
- vendor-location and freight-rate maintenance pages

## Milestone 2: landed cost foundation

Validated in UAT:

- immediate Vendor Name and FOB FlowField refresh on the product card
- persistent landed-cost worksheets
- product defaults for vendor, FOB, mode, quantity, gram weight, pallets, and supplier unit cost
- manual domestic freight input
- CWT freight-rate lookup using vendor, FOB, destination state, mode, effective date, and controlled fallbacks
- minimum-charge and fuel-surcharge handling
- pallet cost per unit
- tariff per unit
- international freight, customs, and delivery allocations per unit
- calculated landed cost per unit

Freight-rate matching prioritizes the most specific active rate and then falls back through vendor/location scope, `Any` mode, and default-destination rates. Blank origin vendor/location values are used for broader fallback rows.

## Milestone 3: deterministic margin guidance

Validated in UAT:

- target gross margin percent
- suggested sell price per unit calculated as landed cost divided by one minus target gross margin
- extended landed cost
- extended sell
- gross profit per unit
- gross profit total

These calculations remain Business Central logic. AI is not allowed to invent, override, or independently determine pricing.

## Milestone 4: commercial guardrail integration

Version `0.4.1.0` absorbed the useful Business Central portion of the former `GPI Commercial Guardrails POC` into this extension rather than creating a competing pricing-rule design.

Validated in UAT:

- enabled customer/item pricing guardrails
- special-pricing and fixed-price rule types
- effective dating
- configured approver and notes
- historical posted sales-line API
- item cost and UOM context API
- in-BC guardrail maintenance page
- blank customer + blank item protection
- live `TRIPLEH` special-pricing rule read through the preserved API contract
- supplier-margin regression using pricing rules, historical sales, and item/UOM context together
- Python commercial-guardrail regression suite: 102 tests passing

The standalone `GPI Commercial Guardrails POC` Business Central extension has been retired from the sandbox. The Python project remains useful as a regression/UAT oracle.

The read-only API contract remains under `gpi/commercialGuardrails/v1.0`.

### Guardrail scope safety

A guardrail may leave Customer No. blank to apply the rule to all customers for a specific item, or leave Item No. blank to apply the rule to all items for a specific customer. Customer No. and Item No. cannot both be blank. This prevents an accidentally saved empty line from becoming a global special-pricing rule.

## Milestone 5: packaging quote workflow

Version `0.5.2.0` added the saved packaging quote workflow plus controlled APIs for automated UAT and future integration work.

Validated in UAT with 22 of 22 API checks passing:

- saved packaging quote header and lines
- product-to-BC-item mapping
- optional saved landed-cost worksheet linkage
- proposed sell, target gross margin, suggested sell, calculated GP, extended cost, extended sell, and gross profit
- deterministic Special Pricing, Fixed Price Match, Fixed Price Conflict, Below Target Margin, Within Policy, Approval Required, and Missing Cost states
- Ready for Review transition for legitimate commercial exceptions
- pricing edits invalidate stale guardrail evaluations
- temporary UAT quote and fixed-price rule cleanup

### Quote APIs

Custom quote header and quote-line APIs are exposed under `gpi/packagingQuotes/v1.0`. The quote API exposes bound actions for deterministic evaluation and Ready for Review.

A separate `gpi/packagingQuoteUAT/v1.0` pricing-rule endpoint exists only to create and remove temporary UAT pricing rules. Its page enforces `Environment Information`.IsSandbox(), so it rejects access outside a Business Central sandbox.

## Milestone 6: approval decisions and durable audit history

Version `0.6.0.0` added the commercial decision and audit layer on top of the validated quote workflow.

Validated in `Sandbox_NoZetadocs_UAT` with 48 of 48 API checks passing on 2026-08-19:

- explicit Approve Quote and Reject Quote actions from Ready for Review
- Rejected quote status
- approval/rejection note, decision timestamp, and Business Central decision user
- pricing-exception approvals require a decision note
- all rejections require a decision note
- Approved, Rejected, and Expired quotes block pricing and consequential quote changes until explicitly reopened to Draft
- Reopen Draft clears current guardrail evaluation and requires a fresh evaluation before review
- quote-date changes invalidate effective-dated guardrail results
- approval and rejection create durable header and line audit snapshots
- post-decision pricing edits and decision-note edits are blocked
- pricing changes after evaluation preserve previous and new sell values plus the previous guardrail state
- audit API returns the decision snapshots used by the automated regression
- temporary UAT quotes, audit rows, and fixed-price rule are removed during cleanup

Durable audit records capture:

- evaluation, Ready for Review, approval, rejection, reopen, pricing-change, customer-change, and quote-date-change events
- event timestamp and Business Central user
- quote status, customer, quote date, expiration date, description, and decision note at the time of the event
- line product, BC item, UOM, quantity, landed cost, proposed sell, target margin, calculated GP, guardrail state, approver, fixed-price policy value, and pricing rule entry
- previous pricing values and previous guardrail state when pricing inputs change after evaluation or review

The quote card embeds read-only Approval and Audit History. A read-only `packagingQuoteAudits` API is exposed under `gpi/packagingQuotes/v1.0`.

The quote API also exposes bound actions for approve, reject, and reopen. `scripts/Test-GPIPackagingQuoteAPIUAT.ps1` is the regression harness for Milestones 5 and 6.

## Milestone 7: customer historical pricing guardrails

Version `0.7.0.0` added Business Central-native customer price-history evaluation to quote lines.

Validated in `Sandbox_NoZetadocs_UAT` on 2026-08-19:

- the existing quote/approval regression remained clean at 48 of 48 checks
- customer-history UAT passed 21 of 21 checks
- exact customer + BC item + UOM posted history is the only history that can trigger a review
- at least 3 matching posted sales lines are required before customer history can trigger review
- the median of up to the 5 most recent matching posted sales lines is the customer baseline
- a proposed sell price 7.5% or more below that median becomes `Below Customer History`
- a proposed sell price 15% or more above that median becomes `Above Customer History`
- both history states require human approval
- all-customer item + UOM history is calculated and displayed as context only and never creates an approval by itself
- posted history is limited through the quote date so future transactions cannot affect an earlier quote
- historical evidence never writes or infers a replacement sell price
- history evidence is preserved in the quote approval/audit snapshot
- temporary history UAT quotes and audit rows are removed during cleanup

The validated customer-history case used 6 exact posted lines, a recent customer median of `190.16`, and an independently matched all-customer recent median of `224.81`.

## Milestone 8: deterministic sourcing comparison

Version `0.8.0.2` is the validated Business Central-native best-price and sourcing comparison workflow.

Validated in `Sandbox_NoZetadocs_UAT` on 2026-08-19 with 23 of 23 comparison checks passing. The final full regression set is 92 of 92 checks passing across quote/approval/audit, customer-history pricing, and sourcing comparison.

Validated comparison behavior:

- a saved sourcing-comparison header stores reference product, destination state, comparison date, target margin, and default cost assumptions
- `Add Exact Spec Matches` adds nonblocked products matching the reference product on Material, Style, Capacity, Capacity UOM, and Color
- specific candidate products can also be added manually
- each candidate snapshots its current BC item, vendor, FOB, transport mode, gram weight, supplier unit cost, load quantity, and pallet count
- the existing landed-cost engine is reused instead of duplicating freight or margin formulas
- stored freight rates retain the existing vendor/FOB/destination/mode/effective-date fallback logic
- delivered cost includes supplier cost, pallet cost, domestic freight, tariff, international freight, customs, and delivery allocations
- suggested sell price remains deterministic from landed cost and target margin
- complete candidates are ranked by landed cost per unit, lowest first
- each ranked line shows cost above the best option per unit
- a missing vendor, quantity, gram weight, supplier cost, or freight rate makes the option incomplete and unranked
- missing freight never becomes zero freight and can never make an option appear artificially cheapest
- bulk exact-spec candidate creation works through the comparison API without stale-header write failures
- temporary comparison, candidate products, freight rate, and vendor location are removed during UAT cleanup

The validated comparison case ranked the lower-cost candidate first at `0.23941` landed cost per unit. The higher-cost candidate remained above it, and the no-rate candidate stayed unranked with rank `0` and no landed cost presented.

Comparison APIs are exposed under `gpi/packagingComparisons/v1.0`. Bound actions add exact spec matches, apply header defaults, and calculate/rank the comparison.

Sandbox-only `gpi/packagingCompareUAT/v1.0` product, freight, and vendor-location endpoints support controlled automated UAT setup and cleanup. They reject access outside a Business Central sandbox.

`scripts/Test-GPIPackagingCompareAPIUAT.ps1` is the regression harness for Milestone 8.

## Important semantic choice

The React field `current_price` is used by the existing app as the product's base supplier cost in landed-cost and gross-margin calculations. In this extension it is named **Current Supplier Unit Cost** to avoid confusing supplier cost with customer sell price.

## Current automated UAT baseline

- quote, approval, and audit regression: 48 of 48 passing
- customer historical pricing regression: 21 of 21 passing
- sourcing comparison regression: 23 of 23 passing
- combined current regression baseline: 92 of 92 passing

## Next BC-only work

- route/mileage automation for freight-aware sourcing comparison
- bulk import the real packaging catalog once a non-empty source export is available
- keep all commercial pricing, freight, comparison, guardrail, and approval logic deterministic in Business Central

Spiro integration and Copilot Studio orchestration remain deferred until the remaining Business Central sourcing and catalog data work is ready.
