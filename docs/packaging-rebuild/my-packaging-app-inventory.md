# `my-packaging-app` inventory and Business Central mapping

Source reviewed: uploaded `my-packaging-app(1).zip`, including `src/App.tsx`, Supabase migrations, import scripts, vendor map/geocoding code, drawing overlay code, and project configuration.

## 1. Current architecture

The application is a Vite + React + TypeScript single-page app backed by Supabase. The main application behavior is concentrated in `src/App.tsx`.

Supabase currently provides authentication, product rows, vendor locations, price history, freight-rate maintenance, and storage for product images/PDFs. Browser `localStorage` holds saved quotes and geocoding cache. OpenStreetMap Nominatim provides geocoding, OSRM provides driving-distance estimates, Leaflet provides the vendor map, and PDF.js is loaded from a CDN for drawing overlays.

This means the current app has four separate state/logic locations: Supabase, browser local storage, third-party map/routing services, and React calculation code. The rebuild should consolidate business data and financial rules in Business Central.

## 2. Product data model found in the React app

The active React `Product` model contains:

- UUID `id`
- Gamer ID
- supplier mold number
- material
- capacity and capacity UOM
- finish and finish type
- color
- style
- packout and packout type
- vendor/supplier
- vendor coordinates in several legacy naming variants
- transport mode (`TL`, `CTR`/`CNTR`, or other)
- full-load quantity
- number of pallets
- pallet quantity
- quantity per layer
- number of layers
- gram weight
- FOB text
- FOB cost, a legacy/import field that is present in the UI/import mapping but is not used by the active landed-cost or comparison formulas
- current price
- metric-ton cost
- product image URL
- product PDF URL

The list page shows Gamer ID, supplier mold number, material, style, capacity/UOM, color, vendor, FOB, transport mode, and current price. The detail drawer adds finish, finish type, packout, quantities, pallet data, gram weight, metric-ton cost, image, PDF, and price history.

### Important semantic finding

`current_price` is not treated as a customer sell price. The quoting logic uses it as the base product/supplier cost before pallet cost, freight, tariffs, customs, delivery charges, and gross-margin markup. In BC this should therefore be named **Current Supplier Unit Cost**.

## 3. Vendor and FOB model

The Supabase `vendors` table is a facility/location table, not just one row per supplier. It contains:

- UUID id
- vendor name
- address
- city
- state
- ZIP/postal code
- country
- latitude
- longitude

A migration explicitly removes the unique constraint on vendor name so a vendor can have multiple locations. The React app presents those locations as FOB choices.

### BC mapping

Use standard BC Vendor as the supplier master and a dedicated `GPI Pack Vendor Location` child table for each plant/FOB. Products reference both `Vendor No.` and `Vendor Location Code`.

## 4. Price history

The React app reads and writes `price_history` with:

- product id
- old unit price
- new unit price
- old metric-ton cost
- new metric-ton cost
- note
- effective/change timestamp

The checked-in migration creates `old_price` and `new_price`, but the React code also expects `old_metric_ton` and `new_metric_ton`. No checked-in migration adding those two columns was found. This is schema drift and should not be copied into BC.

The app also averages price-history points across products to produce vendor-level trend charts.

### BC mapping

Use a dedicated immutable price-history table keyed by entry number, product, effective date, and vendor/location context. Cost changes should be logged by deterministic AL logic.

## 5. Freight-rate model

The Supabase `freight_rates` table contains:

- origin vendor, nullable for any vendor
- destination state or sentinel `DEFAULT`
- mode: `TL`, `CNTR`, or `ANY`
- rate per CWT
- minimum charge
- fuel surcharge percent
- notes
- effective date

The migration comments define a fallback concept:

1. vendor + state + mode
2. state + mode
3. default + mode
4. default + any

However, the current quote calculator does not actually consume this rate table. The UI only maintains and displays the rates. Domestic quote freight is entered as either a total freight amount or cost per mile multiplied by OSRM driving miles.

### BC mapping

Keep freight rates as first-class BC master data, but implement rate-selection and landed-cost rules in a later deterministic AL codeunit. Replace the text sentinel `DEFAULT` with an explicit `Default Destination` Boolean.

## 6. Existing calculations

### Metric-ton cost

The app calculates:

`metric ton cost = (1,000,000 grams / gram weight per unit) * supplier unit cost`

The UI rounds the result to two decimal places.

### Quantity used for a quote

For `TL` or `CNTR`:

`quantity used = product.quantity`

`number of pallets = product.number_of_pallets`

For other modes:

`quantity used = product.pallet_qty * entered number of pallets`

### Pallet cost per unit

`pallet cost per unit = pallet cost per pallet * number of pallets / quantity used`

### Domestic freight

The app geocodes origin and destination, asks OSRM for driving miles, and can derive:

`freight total = driving miles * cost per mile`

or accept a manually entered freight total.

`freight per unit = freight total / quantity used`

### International adders

A vendor location is considered international when its country is not exactly `USA`, `Canada`, or `Mexico`.

Per-unit international additions are:

- tariff = supplier unit cost * tariff percent
- ocean/international freight = total entered freight / quantity
- customs = total customs / quantity
- pallet charge = total pallet charge / quantity
- delivery/drayage charge = total delivery charge / quantity

`international cost per unit = tariff + international freight + customs + pallet charge + delivery`

### Landed cost

`landed cost = supplier unit cost + pallet cost per unit + domestic freight per unit + international cost per unit`

### Gross-margin selling price

For a requested gross margin percentage `GM` expressed as a decimal:

`sell price = cost / (1 - GM)`

The app calculates versions without freight and with freight/landed cost, plus total sell dollars and total gross profit.

### Best-price finder

For selected products, destination ZIP, and an entered cost-per-mile:

1. geocode destination
2. use stored vendor coordinates
3. get OSRM driving miles for each product/vendor
4. calculate freight total from miles * cost per mile
5. calculate freight per unit and pallet cost per unit
6. add those to current supplier unit cost
7. sort ascending by delivered cost

This is deterministic except for the third-party routing result and manually entered cost-per-mile. The BC rebuild should preserve deterministic price/cost logic and treat routing data as an input, not AI reasoning.

## 7. Comparison and purchasing tools

The app contains:

- side-by-side product/spec comparison
- side-by-side quote-cost comparison with per-product freight overrides
- cross-vendor price comparison by capacity and optional style
- same-vendor metric-ton comparison across selected FOBs
- product price-history chart
- vendor price-trend chart using average historical price/metric-ton values
- best delivered-price ranking
- drawing/PDF overlay using first-page PDF rendering
- vendor location map

These should be rebuilt in phases after the BC catalog and cost model are stable. The initial BC milestone does not need to reproduce the map, charting, PDF overlay, or best-price UI.

## 8. Saved quotes

Saved quotes are not stored in Supabase. They are serialized into browser `localStorage` under `saved_quotes_v1` and can be exported to CSV.

Each saved quote contains customer name, product/vendor/FOB, destination ZIP, transport mode, pallet and international inputs, quantities, base supplier cost, freight, landed cost, gross margin, unit sell prices, and total sell prices.

### BC mapping

This must become a real BC Packaging Quote Header/Line model in a later milestone. The browser-local implementation is not an acceptable system of record and should not be migrated as architecture.

## 9. Data-quality and architecture findings to fix in the rebuild

- The active `Glass Products` table creation is not represented by one authoritative migration in the archive.
- React expects metric-ton history columns that are absent from the checked-in price-history migration.
- The repository includes an empty `Glass Products_rows.csv`, so the actual production/test product dataset is not present in the uploaded archive.
- Freight-rate fallback logic is documented in SQL comments but not actually used by quote calculations.
- Product/vendor naming was normalized through many one-off SQL migrations, indicating a need for controlled BC codes/enums/relations rather than free-text normalization after the fact.
- Transport mode is inconsistent in the React app (`CTR` in editing/import UI and `CNTR` in freight calculations). BC normalizes this to `CNTR`.
- The legacy `fob cost` field is captured by import/UI code but is not referenced by the active costing formulas. It should not become an authoritative BC cost field until its business meaning is confirmed.
- Product images and PDFs are currently public Supabase storage URLs with anonymous upload/update policies.
- Saved quotes are browser-local only.
- Geocoding and routing are performed client-side against public services.
- Financial formulas live in React and can therefore diverge from future integrations if not centralized.

## 10. Milestone 1 BC foundation created

The first BC scaffold uses object range `71000..71199`, separate from the Zetadocs replacement objects, and introduces:

- `GPI Packaging Product`
- `GPI Pack Vendor Location`
- `GPI Pack Price History`
- `GPI Pack Freight Rate`
- transport-mode and packout-type enums
- deterministic metric-ton calculation codeunit
- price-change history logging
- Packaging Catalog list page
- Packaging Product card page
- Vendor Locations list
- Freight Rates list
- Price History list part
- dedicated permission set

The extension is targeted only at `Sandbox_NoZetadocs_UAT` for this phase.

## 11. Explicitly deferred

Do not begin these until the BC catalog/data model is validated:

- Spiro API/authentication/integration
- Copilot Studio topics/actions
- customer pricing guardrails
- special pricing approval workflow
- BC Packaging Quote Header/Line implementation
- landed-cost calculation codeunit
- freight-rate lookup/fallback engine
- best-price engine
- customer purchase/price history aggregation
- charts
- vendor map
- PDF drawing overlay
- Production deployment
