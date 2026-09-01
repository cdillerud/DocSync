# Giovanni Live Business Central Profile — 2026-09-01

Target used for discovery: `PRE_GAMERDOCS_CUTOVER_20260831` / `Gamer Packaging`.

This document records live Business Central evidence for the Giovanni monthly blanket-order parser. It is evidence for deterministic validation, not permission to hard-code prices or bypass Business Central pricing.

## Customer

- BC customer: `GIOVANN`
- Name: Giovanni Food Company., Inc.

## Business Central locations

These are BC inventory/fulfillment Location Codes, not customer Ship-to Codes.

| Location ID | Code | Name | Observed Giovanni pricing context |
|---|---|---|---|
| `53ec399a-c4e1-eb11-abff-7c05070e4047` | `00` | Drop Ship Location | normal/lower price pattern on sampled Giovanni lines |
| `8cec399a-c4e1-eb11-abff-7c05070e4047` | `082` | Gamer c/o Rotondo Warehouse | higher price pattern on sampled Giovanni lines |

The normalized order model must keep `ship_to_candidate` and BC location resolution separate.

## Current item / quantity / UOM evidence

### 16oz Vinegar

- Item: `C-8808-12026443`
- Item is unblocked; base UOM `EA`
- Live sampled Giovanni transaction pattern: `78.166 M`
- 16 matching posted/open lines all used `78.166 M`
- Observed price range: `201.09` to `212.60`
- Sampled `00` location price: `201.09`
- Sampled `082` location price: `212.60`
- Earlier `22 PALLET` evidence is historical/anomalous context only and is not the current automation rule.

### 14oz Pizza

- Item: `C-8479-10000229`
- Item is unblocked; base UOM `EA`
- Sampled transactions:
  - `89.775 M` at `196.43`
  - `85.05 M` at `205.40`
- Both sampled lines used location `082`.
- Treat `89.775 M` as strong normal-full-load evidence, but nonstandard quantities must remain reviewable rather than being forced to the normal profile.

### 16oz Salsa

- Item: `C-503004-12033478`
- Item is unblocked; base UOM `EA`
- 6 sampled Giovanni lines all used `78.12 M`
- Sampled unit price: `217.67`
- This is a strong current quantity/UOM profile.

### 24oz Pasta

- Item: `C-9874-10001833`
- Item is unblocked; base UOM `EA`
- 25 sampled Giovanni matches contained two active quantities:
  - `62.062 M` — 19 occurrences
  - `56.42 M` — 6 occurrences
- Observed price range across sampled lines: `234.74` to `243.65`
- Do not hard-code one Pasta quantity until the business rule separating these two packouts is identified.

### 24oz Salsa — standard current pattern

- Current standard candidate: `C-503003-12033922`
- Item is unblocked; base UOM `EA`
- 23 sampled Giovanni matches:
  - `56.42 M` — 22 occurrences
  - `56.357 M` — 1 occurrence
- Same item and `56.42 M` quantity showed location-sensitive pricing:
  - Location `00`: `277.99`
  - Location `082`: `289.49`
- Treat `C-503003-12033922 / 56.42 M` as the normal current 24oz Salsa profile, subject to BC location and pricing validation.

### 24oz Salsa — mixed/exception evidence

- Legacy/referenced item: `C-8682-10001486` is blocked and had no sampled Giovanni matches.
- Replacement reference fragment `12013925` resolves to unblocked item `C-8682-12013925`.
- `C-8682-12013925` appeared only twice, both at `5.642 M` and `289.49`, location `082`.
- Those two occurrences were on the same invoices (`304560` and `304562`) that also contained the sampled 14oz Pizza lines.
- Therefore this pattern is classified as mixed-load/top-off evidence, not the normal 24oz Salsa blanket-release profile.
- The parser must not assign this exception item automatically to a normal 24oz Salsa release.

## Deterministic rules established by live evidence

1. Base Item UOM (`EA`) does not determine Giovanni Sales Order UOM.
2. No global `/1000`, pallet or truckload conversion is allowed.
3. Customer + product/item quantity/UOM profiles are evidence-driven and can have exception quantities.
4. BC Location and customer Ship-to are separate dimensions and must be resolved independently.
5. BC Location is materially associated with sampled Giovanni sell-price differences.
6. Mixed/partial/reroute/cancel/location-question notes stay in `REVIEW` and must not inherit a normal-load quantity blindly.
7. Copilot does not calculate or infer price.
8. The standard BC v2.0 Sales Order line create path accepted item/UOM/quantity but returned `unitPrice = 0` when price was omitted. It remains transport plumbing until a BC-authoritative pricing path is proven.

## Next controlled proof

Run one tagged `AITEST-` create/read-back/delete in PRE with the complete known 24oz Salsa context:

- Customer `GIOVANN`
- Item `C-503003-12033922`
- Quantity `56.42`
- UOM `M`
- Location ID `53ec399a-c4e1-eb11-abff-7c05070e4047` (`00` Drop Ship)
- Representative shipment date
- Do not send `unitPrice`

If price remains zero, the standard API path is conclusively unsuitable as the Business Central pricing authority and the next implementation slice should be BC-side AL validation/pricing/order creation.
