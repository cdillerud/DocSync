# Phase 0 Status

- Branch: `feature/order-intake-agent-phase0`
- Certified Business Central target: tenant `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc`, sandbox `PRE_GAMERDOCS_CUTOVER_20260831`, company `Gamer Packaging` (`7d84c6d5-81e2-eb11-86df-00224822baa7`).
- Production: hard blocked.
- Release/ship/invoice/post: not exposed.
- Models: added. Source facts and BC transaction values are intentionally separate.
- CanPack deterministic parser: added. It preserves each incoming PO line's actual quantity/UOM; BC sell-to/customer-item/UOM profile remains unresolved, so no CanPack write test is authorized.
- Giovanni deterministic parser: added for the current monthly blanket workbook format.

## Core variable-PO architecture

Order Intake is not a replay engine for fixture quantities. Every incoming PO can differ.

- The incoming PO/source owns its stated quantity, UOM, dates, item reference, ship-to and other source facts.
- Parsers preserve those source values; they do not normalize a new PO by copying a previous PO's quantity.
- Business Central validates that the requested item/UOM/location/quantity are structurally valid.
- Historical quantities are evidence and anomaly signals, not universal requirements.
- Pricing is resolved independently from authoritative BC context. A new legitimate quantity must not fail merely because no invoice exists with that exact quantity.
- Mixed, cancelled, rerouted, ambiguous, unsupported, or otherwise explicitly exceptional source lines remain REVIEW.

The Giovanni blanket workbook is a special source format because its normal release rows do not contain an explicit quantity column. For that format only, a customer/item profile may derive a normal per-load BC quantity. This fixture-specific derivation must never become a generic rule for other POs.

## Giovanni live BC profile

- 16oz Vinegar `C-8808-12026443`: repeated `78.166 M` full-load evidence.
- 14oz Pizza `C-8479-10000229`: repeated normal/full-load evidence exists; partial/nonstandard quantities also exist and are legitimate historical evidence, not proof that every future PO must equal one fixed quantity.
- 16oz Salsa `C-503004-12033478`: repeated `78.12 M` evidence.
- 24oz Salsa current item `C-503003-12033922`: `56.42 M` is common, but other quantities occur. Location context materially correlates with price.
- 24oz Pasta `C-9874-10001833`: both `62.062 M` and `56.42 M` repeat. The current blanket workbook does not state quantity, so this source format remains REVIEW until the business distinction or another explicit quantity source is available.
- 24oz Salsa mixed/exception item `C-8682-12013925`: exception context confirmed and explicitly excluded from normal-row automatic resolution.

## Boyer pricing-source proof

Boyer table `Customer Item Sales` (table 50006) is keyed only by sell-to customer + item and is refreshed from posted Sales Invoice Line values. The Boyer Customer Item Sales List copies last sold UOM, quantity, and Unit Price to a new Sales Line. The table is therefore a rolling workflow cache, not an independent pricing authority.

For Giovanni `C-503003-12033922`, nine open `56.42 M @ 277.99 / Location 00` lines were created while posted invoice `303756` was the latest qualifying posted state. All nine matched the prior Boyer-carried quantity/UOM/price state. Later `289.49 / 082` postings changed the single rolling cache row, proving that the cache can oscillate with the most recently posted context.

## Deterministic BC resolver evolution

`GPI Order Intake 0.1.0.7` produced the first successful live pricing authority proof. It required exact customer + item + quantity + UOM + location history and therefore intentionally overfit the first controlled fixture.

`GPI Order Intake 0.1.0.8` corrects that overfit:

- incoming quantity is accepted as variable when positive;
- requested UOM must exist for the item in BC;
- pricing key is customer + item + UOM + location, not quantity;
- the two most recent pricing-context posted Sales Invoice Lines must both exist, both be nonzero, and agree on Unit Price;
- price resolution occurs before any Sales Header or Sales Line insert;
- Boyer `Customer Item Sales` is corroboration only and cannot override the historical decision;
- Pasta from the current quantity-less blanket format, explicit mixed/exception Salsa, unsupported items/UOMs, missing history, or conflicting latest prices raise REVIEW/error before draft creation.

## PRE 0.1.0.7 live authority proof

`GPI Order Intake 0.1.0.7` deployment reached `Completed` in the certified PRE sandbox and subsequently became visible as installed.

A resume-only, no-publish authority test executed exactly one tagged case:

- customer `GIOVANN`;
- item `C-503003-12033922`;
- quantity/UOM `56.42 M`;
- Location `00`;
- client did **not** send Unit Price;
- created Draft Sales Order `118850`;
- read-back Unit Price `277.99`;
- pricing result `MATCHED_HISTORICAL_LOCATION_PRICE`;
- exact tagged Draft was deleted;
- cleanup PASS;
- no release, ship, invoice, or post operation was exposed or called;
- Production remained hard blocked.

This proved the BC authority mechanism but did not establish that `56.42 M` is the only valid future quantity.

## PRE 0.1.0.8 variable-quantity live authority proof

`GPI Order Intake 0.1.0.8` compiled from 12 AL files with only the expected `Sales Price` deprecation warning.

- package: `Gamer Packaging Inc_GPI Order Intake_0.1.0.8.app`;
- SHA256: `6C8E9AA69685622073294B21B54F92032887DDE66D49018075D88E624D22389A`;
- deployment reached `Completed` in PRE;
- exact installed-version verification passed.

A controlled test then deliberately used a quantity different from the original proof fixture:

- customer `GIOVANN`;
- item `C-503003-12033922`;
- incoming quantity/UOM `56.357 M`;
- Location `00` (`53ec399a-c4e1-eb11-abff-7c05070e4047`);
- client did **not** send Unit Price;
- created Draft Sales Order `118852`;
- read-back quantity remained exactly `56.357 M`;
- read-back Unit Price was `277.99`;
- pricing result `MATCHED_HISTORICAL_LOCATION_PRICE`;
- exact tagged Draft was deleted;
- cleanup PASS;
- no release, ship, invoice, or post operation was exposed or called;
- Production remained hard blocked.

This proves that incoming quantity can vary independently from the historical pricing key. The resolver is therefore validating and pricing a new order, not replaying a sample PO.

## PRE 0.1.0.8 pricing-context profile

A GET-only profiler evaluated the known Giovanni pricing contexts using the production candidate key `customer + item + UOM + location`, with quantity excluded from the price key.

- pricing contexts total: `12`;
- latest-two agreement contexts: `11`;
- review contexts: `1`;
- the only live pricing-evidence conflict is 14oz Pizza `C-8479-10000229`, UOM `M`, Location `082`;
- that context has 28 posted invoice rows but the two newest Unit Prices disagree, so it is a real fail-closed pricing case;
- no one-observation pricing context exists among the current 12 known Giovanni contexts.

Stable pricing does not override source semantics. 24oz Pasta remains source REVIEW because the current blanket workbook does not state quantity, and mixed Salsa remains exception REVIEW even where latest-two prices agree.

## PRE 0.1.0.8 fail-closed live proof

A no-publish fail-closed gate exercised four independent REVIEW paths against the already-installed `0.1.0.8`. Every action returned a controlled resolver rejection with `residualTaggedOrders = 0`; no Draft Sales Order survived any case.

1. `REAL_PRICE_CONFLICT_PIZZA_082`
   - item `C-8479-10000229` / `89.775 M` / Location `082`;
   - rejected because the two most recent pricing-context posted invoices disagree on Unit Price.
2. `PASTA_QUANTITY_SOURCE_AMBIGUITY`
   - item `C-9874-10001833` / `62.062 M` / Location `00`;
   - rejected because the current Giovanni blanket source does not state quantity and historical repetition cannot establish source intent.
3. `MIXED_SALSA_SOURCE_EXCEPTION`
   - item `C-8682-12013925` / `5.642 M` / Location `082`;
   - rejected because explicit mixed/exception source semantics are never eligible for normal automatic resolution.
4. `INVALID_BC_UOM`
   - item `C-503003-12033922` / `56.357 BOX` / Location `00`;
   - rejected because `BOX` is not configured for the item in Business Central.

The gate ended `GPI ORDER INTAKE 0.1.0.8 FAIL-CLOSED RESOLVER GATE: PASS` with zero residual tagged orders. This confirms that `different quantity = bad` is not a rule; REVIEW is driven by unsafe pricing evidence, source ambiguity/exception semantics, or invalid BC structure.

## Next gates

1. Produce a concise GET-only matrix of the 11 latest-two-agreement Giovanni pricing contexts with exact current Unit Price and observed quantity range/evidence.
2. Run a small positive breadth matrix across multiple normal Giovanni items/locations, preserving incoming quantities and requiring exact context price read-back plus mandatory cleanup for each case.
3. Keep Pizza Location `082`, Pasta quantity-less blanket rows, and mixed/exception Salsa fail-closed until their respective evidence/source issues are resolved.
4. Resolve the 24oz Pasta quantity-source distinction for the current blanket format.
5. Discover CanPack sell-to identity and customer-item/UOM mappings before any CanPack write test.
6. Keep Production and all release/ship/invoice/post behaviors blocked throughout Phase 0.
