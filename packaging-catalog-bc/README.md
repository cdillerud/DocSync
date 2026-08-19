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

Version `0.5.2.0` contains the saved packaging quote workflow plus controlled APIs for automated UAT and future integration work.

New quote foundation:

- saved packaging quote header and lines
- quote date, expiration date, customer, description, notes, and status
- product-to-BC-item mapping so packaging products can use authoritative BC pricing guardrails
- optional link from a quote line to a saved landed-cost worksheet
- landed cost, quantity, proposed sell price, target gross margin, suggested sell price, calculated GP, extended cost, extended sell, and gross profit
- line-level deterministic guardrail evaluation
- quote-level re-evaluation and Ready for Review action
- automatic return to Draft when pricing inputs are changed after review
- incomplete lines are blocked from Ready for Review
- customer selection on the quote card is saved before page refresh

Current deterministic quote guardrail results:

- Not Evaluated
- Within Policy
- Special Pricing Protected
- Fixed Price Match
- Fixed Price Conflict
- Below Target Margin
- Approval Required
- Missing Landed Cost

Pricing-rule precedence remains deterministic. Active fixed-price rules are evaluated at the most specific customer/item scope. Equally specific conflicting fixed-price rules are treated as a conflict. Active special-pricing rules redirect the line to the configured approver rather than inferring a replacement sell price from broad history.

A quote may move to Ready for Review with a valid commercial exception such as Special Pricing Protected, Fixed Price Conflict, or Below Target Margin because those states require human review. Missing required pricing inputs such as quantity, proposed sell price, or landed cost block the transition.

### Quote APIs and automated UAT

Version `0.5.2.0` adds custom quote header and quote-line APIs under `gpi/packagingQuotes/v1.0`. The quote API exposes bound actions for deterministic evaluation and Ready for Review so UAT can exercise the same Business Central code used by the UI.

A separate `gpi/packagingQuoteUAT/v1.0` pricing-rule endpoint exists only to create and remove temporary UAT pricing rules. Its page enforces `Environment Information`.IsSandbox(), so it rejects access outside a Business Central sandbox.

Run `scripts/Test-GPIPackagingQuoteAPIUAT.ps1` after publishing `0.5.2.0` to `Sandbox_NoZetadocs_UAT`. The script retrieves the existing BC client secret from Azure Key Vault without displaying it, creates temporary quote records, tests Special Pricing, Within Policy, Below Target Margin, stale-evaluation invalidation, Missing Cost, Fixed Price Match, and Fixed Price Conflict, and removes the temporary quote records and fixed-price UAT rule in cleanup.

## Important semantic choice

The React field `current_price` is used by the existing app as the product's base supplier cost in landed-cost and gross-margin calculations. In this extension it is named **Current Supplier Unit Cost** to avoid confusing supplier cost with customer sell price.

## Next BC-only work

- compile and publish Packaging Catalog `0.5.2.0` to UAT
- run the automated packaging quote API UAT matrix
- add auditable quote approval state and consequential pricing history after the basic quote workflow is accepted
- port customer-specific posted-price-history anomaly checks into the BC quote workflow without allowing history to become an automatic replacement-price recommendation
- best-price comparison and route/mileage automation
- bulk import of the real packaging catalog once a non-empty source export is available

Spiro integration and Copilot Studio orchestration remain deferred until the Business Central commercial rules and quote workflow are validated.
