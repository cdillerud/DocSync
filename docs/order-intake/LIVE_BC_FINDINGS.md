# Live Business Central Findings

Environment: `PRE_GAMERDOCS_CUTOVER_20260831`  
Company: `Gamer Packaging`  
Company ID: `7d84c6d5-81e2-eb11-86df-00224822baa7`

## Safety proof

- Environment server-verified as `sandbox`.
- Production is hard blocked by the test harness.
- Release, ship, invoice, and post operations are not exposed.
- Tagged `AITEST-` Sales Order create/read-back/delete round trip completed successfully and cleanup passed.

## Giovanni customer

- BC customer number: `GIOVANN`
- Name: `Giovanni Food Company., Inc.`

## 16oz Vinegar — C-8808-12026443

Source physical full-load packout: `78,166 EA`.

Live PRE_GAMERDOCS sales history inspected:

- 100 posted invoices scanned.
- 47 open orders scanned.
- 16 matching lines.
- All 16 matching lines transact as `78.166 M`.
- Observed unit-price range: `201.09` to `212.60`.
- Newest evidence date: `2026-08-31`.
- Current open orders also use `78.166 M`.

Earlier document/pick-ticket evidence showed a `22 PALLET` presentation. That evidence is retained as historical/anomalous context but is not the current automation rule because live 2026 BC transaction history is authoritative.

## 14oz Pizza — C-8479-10000229

Source normal full-load packout: `89,775 EA`.

Live PRE_GAMERDOCS sales history inspected:

- `89.775 M` at unit price `196.43`.
- `85.05 M` at unit price `205.40`.
- Both sampled transactions were posted `2026-08-31`, shipped `2026-08-20`, and used the same location ID.

The second quantity is evidence that partial/nonstandard quantities can carry a different sell price. Price must not be inferred from a single customer/item historical value.

## Standard API pricing finding

A controlled `AITEST-` Sales Order round trip created `GIOVANN` + `C-8479-10000229` at `89.775 M` successfully, but the standard Business Central v2.0 line-create call returned `unitPrice = 0` when unit price was omitted.

Therefore:

- a successful standard API line insert is not proof that BC pricing logic ran;
- Copilot must never infer or supply price independently;
- the production create path needs a deterministic BC-side AL pricing/validation authority, or another BC-authoritative path that proves the resolved price before an order can pass validation.

## Date finding

Current Giovanni open orders sampled by the inspector use `requestedDeliveryDate = 0001-01-01` while the line `shipmentDate` carries the operational schedule date. Giovanni workbook `Delivery Date` must not be blindly mapped to header requested-delivery date. Shipment-date mapping needs explicit BC validation.

## Current automation profiles

| Product | BC Item | Physical normal load | Current BC quantity/UOM | Confidence |
|---|---|---:|---:|---|
| 16oz Vinegar | C-8808-12026443 | 78,166 EA | 78.166 M | High |
| 14oz Pizza | C-8479-10000229 | 89,775 EA | 89.775 M normal full load | High for full load; partial loads require review |

Remaining Giovanni products still require live BC profiling before straight-through automation.
