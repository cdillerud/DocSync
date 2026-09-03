# Phase 0 Status

- Branch: `feature/order-intake-agent-phase0`
- Certified Business Central target: tenant `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc`, sandbox `PRE_GAMERDOCS_CUTOVER_20260831`, company `Gamer Packaging` (`7d84c6d5-81e2-eb11-86df-00224822baa7`).
- Production: hard blocked.
- Release/ship/invoice/post: not exposed.
- Models: added.
- CanPack deterministic parser: added; BC sell-to/customer-item/UOM profile remains unresolved, so no CanPack write test is authorized.
- Giovanni deterministic parser: added.

## Giovanni live BC profile

- 16oz Vinegar `C-8808-12026443`: normal load `78.166 M` confirmed.
- 14oz Pizza `C-8479-10000229`: normal full load `89.775 M`; partial/nonstandard quantity evidence also exists and must REVIEW.
- 16oz Salsa `C-503004-12033478`: normal load `78.12 M` confirmed.
- 24oz Salsa current normal item `C-503003-12033922`: normal load `56.42 M` confirmed; exact location context matters for price.
- 24oz Pasta `C-9874-10001833`: both `62.062 M` and `56.42 M` repeat in authoritative history; quantity rule remains REVIEW until the business distinction is resolved.
- 24oz Salsa mixed/exception item `C-8682-12013925`: exception context confirmed and explicitly excluded from normal-row automatic resolution.

## Boyer pricing-source proof

Boyer table `Customer Item Sales` (table 50006) is keyed only by sell-to customer + item and is refreshed from posted Sales Invoice Line values. The Boyer Customer Item Sales List copies last sold UOM, quantity, and Unit Price to a new Sales Line. The table is therefore a rolling workflow cache, not an independent pricing authority.

For Giovanni `C-503003-12033922`, nine open `56.42 M @ 277.99 / Location 00` lines were created while posted invoice `303756` was the latest qualifying posted state. All nine matched the prior Boyer-carried quantity/UOM/price state. Later `289.49 / 082` postings changed the single rolling cache row, proving that the cache can oscillate with the most recently posted context.

## Deterministic BC resolver

`GPI Order Intake 0.1.0.7` replaces the unsuccessful synthetic `Sales Line.UpdateUnitPrice(...)` path for approved Giovanni Phase-0 contexts with a deterministic posted-history resolver.

Resolver rules:

- pricing key: customer + item + quantity + UOM + location;
- two most recent exact-context posted Sales Invoice Lines must both exist, both be nonzero, and agree on Unit Price;
- price resolution occurs before any Sales Header or Sales Line insert;
- Boyer `Customer Item Sales` is corroboration only and cannot override the historical decision;
- Pasta ambiguity, mixed/exception Salsa, wrong quantities, unsupported UOMs/items, missing history, or conflicting latest prices raise REVIEW/error before draft creation.

Compile-only proof for `0.1.0.7`:

- AL compiler `17.0.34.45391`;
- 12 AL files compiled;
- only expected `Sales Price` deprecation warning;
- package `Gamer Packaging Inc_GPI Order Intake_0.1.0.7.app`;
- SHA256 `3B4AAA38CDB3937E046CC5A0E10CA60BBAF87CA1ABCF72BCB86F4CA7FC710C63`.

## PRE 0.1.0.7 live authority proof

`GPI Order Intake 0.1.0.7` deployment reached `Completed` in the certified PRE sandbox and subsequently became visible as installed.

A resume-only, no-publish authority test then executed exactly one tagged case:

- customer `GIOVANN`;
- item `C-503003-12033922`;
- quantity/UOM `56.42 M`;
- Location `00` (`53ec399a-c4e1-eb11-abff-7c05070e4047`);
- client did **not** send Unit Price;
- created Draft Sales Order `118850`;
- read-back Unit Price `277.99`;
- pricing result `MATCHED_HISTORICAL_LOCATION_PRICE`;
- exact tagged Draft was deleted;
- cleanup PASS with zero intended residual;
- no release, ship, invoice, or post operation was exposed or called;
- Production remained hard blocked.

This proves the Phase-0 BC authority can resolve and apply a deterministic Giovanni price from authoritative posted-history context rather than relying on the standard API pricing path or blindly copying Boyer's current rolling row.

## Next gates

1. Prove fail-closed behavior for Pasta ambiguity, mixed/exception Salsa, wrong quantity/UOM, and insufficient/conflicting price evidence with zero residual orders.
2. Run positive read/write/cleanup proofs only for additional normal Giovanni contexts whose resolver evidence meets the two-latest agreement rule.
3. Resolve the 24oz Pasta business distinction before allowing either repeated quantity automatically.
4. Discover CanPack sell-to identity and customer-item/UOM mappings before any CanPack write test.
5. Keep Production and all release/ship/invoice/post behaviors blocked throughout Phase 0.
