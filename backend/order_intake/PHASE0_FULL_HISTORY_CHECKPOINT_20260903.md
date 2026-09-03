# Phase 0 Full-History Pricing Checkpoint — 2026-09-03

## Certified target

- Tenant: `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc`
- Environment: `PRE_GAMERDOCS_CUTOVER_20260831`
- Environment type: `sandbox`
- Company: `Gamer Packaging`
- Company ID: `7d84c6d5-81e2-eb11-86df-00224822baa7`
- Installed app: `GPI Order Intake 0.1.0.8`
- Package SHA256: `6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A`
- Production: hard blocked
- Release/ship/invoice/post: not implemented / blocked

## Variable-PO rule

Incoming PO quantity is preserved when positive and structurally valid. Quantity is not part of the pricing key. Pricing key is:

`customer + item + UOM + location`

Historical quantities are evidence/anomaly context only; they are not fixed requirements for a new PO.

## Full-history profiler correction

The first pricing-context profiler used `$top=500` on each customer/item Sales Invoice Line history request. For high-volume items this acted as a total-result cap before local `systemCreatedAt` sorting, so it could omit newer records.

The issue became visible on 16oz Vinegar because the capped profile returned exactly 500 rows (`462` at Location `00` + `38` at Location `082`) and reported `188.01` at Location `082`.

A controlled no-publish AL authority diagnostic for `GIOVANN / C-8808-12026443 / 49.742 M / Location 082` then created a Draft at `212.60`, read it back at `212.60`, and deleted it with cleanup PASS. The authority applies the resolver price last and immediately `TestField`s Unit Price against that resolved price, so this demonstrated that the resolver itself selected `212.60`; the Standard API did not overwrite it afterward.

The corrected GET-only profiler removed the total-result cap and followed OData `nextLink` pagination to exhaustion before grouping and sorting history.

## Corrected full-history results

Full-history context totals:

- pricing contexts: `15`
- latest-two agreement contexts: `11`
- review contexts: `4`

Normal positive contexts:

- 14oz Pizza `C-8479-10000229` / `M` / Location `00`: latest two `196.43 / 196.43`, 92 rows.
- 16oz Salsa `C-503004-12033478` / `M` / Location `00`: latest two `217.67 / 217.67`, 18 rows.
- 16oz Salsa `C-503004-12033478` / `M` / Location `082`: latest two `228.24 / 228.24`, 8 rows.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `00`: latest two `201.09 / 201.09`, 717 rows.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `082`: latest two `212.60 / 212.60`, 73 rows.
- 24oz Salsa `C-503003-12033922` / `M` / Location `00`: latest two `277.99 / 277.99`, 32 rows.
- 24oz Salsa `C-503003-12033922` / `M` / Location `082`: latest two `289.49 / 289.49`, 7 rows.

Real REVIEW pricing contexts:

- 14oz Pizza `C-8479-10000229` / `M` / Location `082`: latest two disagree.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `001`: 2 rows; latest two disagree.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `002`: 1 row; one observation only.
- 24oz Pasta `C-9874-10001833` / `M` / Location `000`: 1 row; one observation only, though current blanket Pasta remains source REVIEW before pricing anyway.

Stable pricing still does not override source semantics: Pasta from the quantity-less blanket format and explicit mixed/exception Salsa remain REVIEW even when their pricing context itself is stable.

## Completed live positive breadth proof

Four different normal Giovanni contexts independently created a tagged Draft, preserved the requested PO quantity, read back the full-history context price, and deleted the exact tagged Draft with cleanup PASS:

1. 14oz Pizza `C-8479-10000229` / `61.425 M` / Location `00` / `196.43`.
2. 16oz Salsa `C-503004-12033478` / `85.932 M` / Location `00` / `217.67`.
3. 16oz Vinegar `C-8808-12026443` / `49.742 M` / Location `082` / `212.60`.
4. 24oz Salsa `C-503003-12033922` / `33.852 M` / Location `082` / `289.49`.

The Vinegar case was re-proven independently after retiring the stale capped-profiler expectation. The final Salsa24/082 resume test created Draft Sales Order `118857`, read back `33.852 M @ 289.49`, and deleted it with cleanup PASS.

This breadth proof establishes that the order-intake authority is not replaying one fixture quantity. Different requested quantities survive exactly while Unit Price is resolved independently from `customer + item + UOM + location` evidence.

## Completed fail-closed coverage

The installed `0.1.0.8` has rejected the following with zero residual AITEST orders and no surviving Draft:

- Pizza / Location `082`: latest-two price conflict.
- Pasta current blanket source: quantity-source ambiguity.
- mixed/exception Salsa: explicit exception semantics.
- invalid BC UOM (`BOX`): structural rejection.
- Vinegar / Location `001`: full-history latest-two conflict. Live rejection proved document `294879 = 193.90` versus `285035 = 191.77`, HTTP 400, `residualTaggedOrders = 0`.
- Vinegar / Location `002`: exactly one posted invoice observation. Live rejection proved latest document `298460 @ 201.09`, HTTP 400, `residualTaggedOrders = 0`.

The full-history pricing-evidence rejection gate ended:

`GPI ORDER INTAKE 0.1.0.8 FULL-HISTORY PRICING-EVIDENCE REJECTION GATE: PASS`

This completes live coverage for both missing pricing-evidence branches: conflicting recent evidence and insufficient evidence.

## Giovanni Phase-0 authority conclusion

For the currently supported Giovanni normal-item allow-list, `0.1.0.8` now has live PRE proof for:

- variable incoming quantity preservation;
- BC item/UOM structural validation;
- location-sensitive pricing context;
- repeated latest-two price agreement -> tagged Draft creation;
- latest-two conflict -> REVIEW / rollback;
- one observation -> REVIEW / rollback;
- source ambiguity/exception semantics -> REVIEW / rollback;
- mandatory exact AITEST cleanup;
- zero Production, release, ship, invoice, or post exposure.

## Next gates

1. Move back up the pipeline and prove another customer format without assuming it resembles Giovanni.
2. CanPack remains GET-only until sell-to customer identity, customer-item mapping, BC item/UOM, location/ship-to semantics, and pricing context are independently proven.
3. Treat CanPack source quantity/UOM as PO-owned facts (`Call-off quantity`, source UOM); do not normalize them to Giovanni-style `M` quantities.
4. Resolve the 24oz Pasta quantity-source distinction for the current Giovanni blanket format separately; do not generalize that fixture-specific ambiguity to other POs.
5. Do not use capped pricing-profile evidence for authority decisions.
6. Keep Production and all release/ship/invoice/post behavior blocked throughout Phase 0.
