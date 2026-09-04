# PRE Event Subscription Diagnostics — 2026-09-03

Target: `PRE_GAMERDOCS_CUTOVER_20260831` / `Gamer Packaging`.

## Safety

All event diagnostics were GET-only after `GPI Order Intake 0.1.0.3` was installed. No Sales Order action was called, no business data was written, Release/Ship/Invoice/Post remained unimplemented/blocked, and Production remained hard blocked.

## Broad-scan limitation

The first Event Subscription API scan returned exactly 1,000 rows and no `@odata.nextLink`. That result was treated as capped/ambiguous and was not used to infer that custom subscribers were absent.

## Exact-app targeted scan

Server-side exact `originatingAppName` filters proved:

- `Boyer And Associates Custom Package 25.0.0.13`: 72 active subscriptions, including 18 Sales Header/Line subscriptions.
- `Gamer Spiro Integration 24.0.0.2`: 3 active subscriptions, including 2 Sales Header/Line subscriptions.
- `GPI Packaging Catalog 0.48.0.0`: 5 active subscriptions, including 3 Sales Line subscriptions.

The targeted summary originally labeled 14 Boyer rows as pricing-related because its regex also included generic terms such as `validate`, `sales line`, and context fields. That label is too broad for pricing attribution.

A local PowerShell aggregation defect also caused the detailed arrays (`boyerCustomPackageSubscriptions`, `customSalesHeaderLineSubscriptions`, etc.) to serialize as null even though the per-app summary counts were correct. Independent single-field Sales Header/Line queries still returned the underlying Boyer rows.

Visible Boyer Sales Line subscribers include codeunit 50500 `OnCopyFromItemOnAfterCheck`, plus VAT/item availability/status hooks, and codeunit 50001 `OnBeforeValidateUnitCostLCYOnGetUnitCost`. None of the visible Sales Line subscriber names explicitly target `Unit Price`.

## Next diagnostic

Use `scripts/Read-GPIOrderIntakeBoyerEventDetails-PRE.ps1`, which:

- performs exact Boyer, Spiro, and GPI Packaging Catalog queries independently;
- emits every returned row for each app;
- separates strict pricing names (`price|pricing|discount`) from general order-context names;
- performs GET only and requires no AL compile, publish, or extension mutation.

Pricing remains unresolved. Do not inject historical price and do not run another Sales Order write until the custom-pricing path is understood.
