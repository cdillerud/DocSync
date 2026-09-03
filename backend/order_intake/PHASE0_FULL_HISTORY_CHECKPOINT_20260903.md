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

Newly visible real REVIEW contexts:

- 14oz Pizza `C-8479-10000229` / `M` / Location `082`: latest two disagree.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `001`: 2 rows; latest two disagree.
- 16oz Vinegar `C-8808-12026443` / `M` / Location `002`: 1 row; one observation only.
- 24oz Pasta `C-9874-10001833` / `M` / Location `000`: 1 row; one observation only, though current blanket Pasta remains source REVIEW before pricing anyway.

Stable pricing still does not override source semantics: Pasta from the quantity-less blanket format and explicit mixed/exception Salsa remain REVIEW even when their pricing context itself is stable.

## Live positive breadth state

The first positive breadth run progressed through the Pizza/00 and Salsa16/00 cases before reaching Vinegar/082. Salsa16/00 explicitly proved `85.932 M -> 217.67` with Draft creation and cleanup PASS. Progression to Vinegar means the prior Pizza/00 case satisfied the matrix's exact item/quantity/UOM/location/price/cleanup assertions as well.

Vinegar/082 was then independently diagnosed after the stale `188.01` expectation failed:

- incoming quantity: `49.742 M`
- Location: `082`
- resolver/read-back price: `212.60`
- Draft only
- cleanup PASS

The corrected full-history GET evidence independently corroborates `212.60 / 212.60` as the latest-two Vinegar/082 price context.

The only original four-case breadth item not yet executed is:

- 24oz Salsa `C-503003-12033922` / `33.852 M` / Location `082` / expected full-history price `289.49`.

Use `scripts/Resume-GPIOrderIntakePositiveBreadth-FullHistory-0.1.0.8-PRE.ps1` to run only that remaining tagged Draft with mandatory cleanup; do not rerun the stale original breadth matrix.

## Next gates

1. Complete the one remaining Salsa24/082 positive breadth case.
2. Add full-history fail-closed pricing-evidence coverage for Vinegar Location `001` (latest-two conflict) and Location `002` (one observation), with zero residual AITEST orders.
3. Keep Pizza/082, Pasta source ambiguity, mixed/exception Salsa, and invalid UOM fail-closed.
4. Do not use capped pricing-profile evidence for authority decisions.
5. Keep Production and all release/ship/invoice/post behavior blocked throughout Phase 0.
