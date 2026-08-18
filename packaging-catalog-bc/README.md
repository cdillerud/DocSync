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

Version `0.4.1.0` absorbs the useful Business Central portion of the existing `GPI Commercial Guardrails POC` into this extension rather than creating a competing pricing-rule design.

Integrated objects preserve the existing read-only API contract under `gpi/commercialGuardrails/v1.0`:

- enabled customer/item pricing guardrails
- special-pricing and fixed-price rule types
- effective dating
- configured approver and notes
- historical posted sales-line API
- item cost and UOM context API
- in-BC guardrail maintenance page

The uploaded Commercial Guardrail Python source remains the behavioral regression oracle. Its 102 unit tests pass as supplied. Important retained behaviors include exact item/UOM matching, customer-specific history, protected special pricing, fixed-price mismatch detection, supplier-cost margin impact, and explicit review/reject states rather than invented replacement prices.

The standalone `GPI Commercial Guardrails POC` BC app should only be retired from the sandbox after this integrated version compiles and the preserved API endpoints are validated. Both apps should not remain installed with the same API entity routes.

### Guardrail scope safety

A guardrail may leave Customer No. blank to apply the rule to all customers for a specific item, or leave Item No. blank to apply the rule to all items for a specific customer. Customer No. and Item No. cannot both be blank. This prevents an accidentally saved empty line from becoming a global special-pricing rule.

The current POC export contained one enabled Special Pricing row with both Customer No. and Item No. blank and no other commercial values. That row is treated as an accidental blank record and is not intended for migration into the integrated extension.

## Important semantic choice

The React field `current_price` is used by the existing app as the product's base supplier cost in landed-cost and gross-margin calculations. In this extension it is named **Current Supplier Unit Cost** to avoid confusing supplier cost with customer sell price.

## Next BC-only work

- connect packaging products to authoritative BC item/customer pricing history where applicable
- evaluate proposed packaging sell prices through the ported guardrail semantics
- add saved packaging quote header and lines
- add auditable quote approval state and consequential pricing history
- best-price comparison and route/mileage automation
- bulk import of the real packaging catalog once a non-empty source export is available

Spiro integration and Copilot Studio orchestration remain deferred until the Business Central commercial rules and quote workflow are validated.
