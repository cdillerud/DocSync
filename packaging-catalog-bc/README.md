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

Version `0.6.0.0` adds the commercial decision and audit layer on top of the validated quote workflow.

New approval controls:

- explicit Approve Quote and Reject Quote actions from Ready for Review
- Rejected quote status
- approval/rejection note, decision timestamp, and actual Business Central decision user
- pricing-exception approvals require a decision note
- all rejections require a decision note
- Approved, Rejected, and Expired quotes block pricing, customer, quote-date, expiration-date, and description changes until explicitly reopened to Draft
- Reopen Draft clears the current evaluation and requires a fresh guardrail evaluation before review
- quote-date changes invalidate effective-dated guardrail results

Durable audit records capture:

- evaluation, Ready for Review, approval, rejection, reopen, pricing-change, customer-change, and quote-date-change events
- event timestamp and Business Central user
- quote status, customer, quote date, expiration date, description, and decision note at the time of the event
- line product, BC item, UOM, quantity, landed cost, proposed sell, target margin, calculated GP, guardrail state, approver, fixed-price policy value, and pricing rule entry
- previous pricing values and previous guardrail state when pricing inputs change after evaluation or review

The quote card embeds read-only Approval and Audit History. A read-only `packagingQuoteAudits` API is exposed under `gpi/packagingQuotes/v1.0`.

The quote API now also exposes bound actions for approve, reject, and reopen. The automated UAT runner verifies approval-note enforcement, approval and rejection snapshots, decision-user/timestamp capture, post-decision edit locks, reopen behavior, and pricing-change audit values in addition to the Milestone 5 guardrail matrix.

## Important semantic choice

The React field `current_price` is used by the existing app as the product's base supplier cost in landed-cost and gross-margin calculations. In this extension it is named **Current Supplier Unit Cost** to avoid confusing supplier cost with customer sell price.

## Next BC-only work

- compile and publish Packaging Catalog `0.6.0.0` to UAT
- run `scripts/Test-GPIPackagingQuoteAPIUAT.ps1` and validate the expanded approval/audit matrix
- port customer-specific posted-price-history anomaly checks into the BC quote workflow without allowing history to become an automatic replacement-price recommendation
- best-price comparison and route/mileage automation
- bulk import of the real packaging catalog once a non-empty source export is available

Spiro integration and Copilot Studio orchestration remain deferred until the Business Central commercial rules, quote workflow, and approval controls are validated.
