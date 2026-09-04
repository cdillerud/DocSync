# Customer PDF resolved-mapping checkpoint — 2026-09-03

## Safety state

- Target evidence environment: `PRE_GAMERDOCS_CUTOVER_20260831` / sandbox / Gamer Packaging.
- `GPI Order Intake 0.1.0.10` installed.
- Evidence collection was GET-only after the exact diagnostics extension install.
- No Sales Order action was called.
- No business-data write was performed.
- Production remained hard blocked.

## Architecture rule

Customer PO facts remain immutable source evidence. Mapping is a separate deterministic layer. Resolved BC customer/item/ship-to/location/quantity values are stored separately and never overwrite the customer PO facts. Source price remains evidence/corroboration only; Business Central must independently resolve or validate transaction price.

Incoming PO quantity remains authoritative except where a narrowly proven customer/item packout conversion is explicitly required. Historical quantity is never a universal template.

## Berner evidence

Three independent customer-PO / Gamer Sales Order chains were proven:

| Customer PO | Gamer SO | Source part | Source alias in PO description | Source qty | BC item | BC qty | BC UOM | Ship-to | Location | Price |
|---|---|---|---|---:|---|---:|---|---|---|---:|
| 241355 | 114600 | 811476 | 21579-858231 | 68,000 EA | 21759-858231 | 72.2 | M | 78899028 | 00 | 243.43 |
| 241356 | 114601 | 811476 | 21579-858231 | 68,000 EA | 21759-858231 | 72.2 | M | 78899028 | 00 | 243.43 |
| 241357 | 114602 | 811476 | 21579-858231 | 68,000 EA | 21759-858231 | 72.2 | M | 78899028 | 00 | 243.43 |

Additional BC proof:

- `21579-858231` does not exist in the current BC item master.
- `21759-858231` exists, is Inventory, is not blocked, and has base UOM EA.
- Current Item Reference and historical Sales Line Item Reference fields are blank; the mapping is therefore supported by repeated transaction linkage, not an Item Reference master record.

### Berner rule

Only the exact currently proven pattern may resolve automatically:

`BERNER + source part 811476 + source alias 21579-858231 + 5778 Baxter Road + 68,000 EA`

resolves to:

`BERNER + BC item 21759-858231 + Ship-to 78899028 + Location 00 + 72.2 M`

A different incoming Berner quantity/UOM must remain REVIEW. The repeated `72.2 M` result is not a universal quantity template.

## Herdez evidence

Exact current BC Sales Order proof exists for the fixture PO:

- customer PO `4500063632`
- Gamer Sales Order `117357`
- customer `HERDEZ`
- item `20113526`
- quantity `195.888 M`
- price `225.75`
- Location `00`
- status Open.

Ten additional current Herdez Sales Orders use the same item `20113526`, quantity `195.888 M`, price `225.75`, and Location `00` across multiple customer PO numbers and shipment dates.

The linked Gamer Purchase Order `117357` independently carries customer PO `4500063632`, item `20113526`, `195.888 M`, and the SLP factory destination.

Current BC Item Reference and historical posted-line Item Reference fields are blank, so this mapping is also supported by repeated transaction linkage rather than an Item Reference master row.

### Herdez rule

For the proven customer material and SLP destination:

`HERDEZ + source material 000000000004003467 + SLP factory`

resolves to:

`HERDEZ + BC item 20113526 + Ship-to 001 + Location 00 + UOM M`.

The profiled Coupa source uses decimal-comma `THOUSAND` semantics. Once parsed to M, the incoming positive quantity carries through to BC; it is not forced to the historically common `195.888 M` quantity.

## Duplicate rule

Duplicate evidence overrides an otherwise valid mapping. The historical fixture POs must never create new orders:

- Berner `241355` -> existing SO `114600`
- Berner `241356` -> existing SO `114601`
- Berner `241357` -> existing SO `114602`
- Herdez `4500063632` -> existing SO `117357`

A caller must provide current BC duplicate evidence before any create decision.

## Next gate

Run the offline customer-PDF resolved-mapping regression. It must prove:

1. parsing still preserves source facts;
2. exact Berner mapping resolves;
3. different Berner quantity fails closed to REVIEW;
4. Herdez variable incoming quantity carries through after the proven M mapping;
5. exact existing customer PO evidence returns DUPLICATE;
6. no BC call or mutation occurs.

No customer-PDF Draft creation is authorized by this checkpoint.
