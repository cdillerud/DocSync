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

Version `0.2.0.0` adds deterministic Business Central landed-cost logic:

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

## Important semantic choice

The React field `current_price` is used by the existing app as the product's base supplier cost in landed-cost and gross-margin calculations. In this extension it is named **Current Supplier Unit Cost** to avoid confusing supplier cost with customer sell price.

## Deferred until the BC cost foundation is validated

- gross-margin and customer sell-price logic
- customer-specific pricing guardrails
- saved packaging quotes and quote lines
- best-price comparison and route/mileage automation
- bulk import of the real packaging catalog once a non-empty source export is available
- Spiro integration
- Copilot Studio orchestration
