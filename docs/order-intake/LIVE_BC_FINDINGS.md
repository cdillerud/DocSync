# GPI Order Intake - Live Business Central Findings

## Certified test target

- Environment: `PRE_GAMERDOCS_CUTOVER_20260831`
- Environment type: sandbox
- Company: `Gamer Packaging`
- Company ID: `7d84c6d5-81e2-eb11-86df-00224822baa7`
- Production: blocked

## Standard API pricing conclusion

Two guarded standard v2.0 Sales Order line-create round trips proved transport but not pricing authority:

1. Giovanni 14oz Pizza: `C-8479-10000229 / 89.775 M` -> `unitPrice = 0` when price omitted.
2. Giovanni 24oz Salsa: `C-503003-12033922 / 56.42 M / Location 00` -> `unitPrice = 0` when price omitted.

Both tagged test orders were cleaned up successfully. Therefore the standard v2.0 Sales Order line-create path is treated as transport plumbing only for Order Intake.

## Giovanni quantity/UOM profiles

- 16oz Vinegar `C-8808-12026443`: normal current profile `78.166 M`.
- 14oz Pizza `C-8479-10000229`: normal full-load `89.775 M`; `85.05 M` exists as partial/nonstandard evidence.
- 16oz Salsa `C-503004-12033478`: current profile `78.12 M`.
- 24oz Salsa normal current item `C-503003-12033922`: 23 sampled matches, 22 at `56.42 M`; one `56.357 M` exception.
- 24oz Salsa workbook-referenced `C-8682-12013925`: two recent `5.642 M` lines; treated as mixed/exception evidence, not the normal full-load profile.
- 24oz Pasta `C-9874-10001833`: both `62.062 M` and `56.42 M` are current; the deterministic quantity rule remains unresolved.

## Giovanni location evidence

- Location `00`: `Drop Ship Location`.
- Location `082`: `Gamer c/o Rotondo Warehouse`, Liverpool, NY.
- 24oz Salsa `56.42 M` repeatedly shows `277.99` at Location `00` and `289.49` at Location `082` in current history.

This establishes that location correlates with current Giovanni price outcomes, but it does not prove location alone causes the price selection.

## Dedicated AL authority

`GPI Order Intake 0.1.0.0` compiled cleanly and was installed only in the certified PRE sandbox.

The authority:

- is hard-pinned to sandbox + exact PRE environment;
- permits only `AITEST-` external document numbers;
- uses normal Sales Header / Sales Line validation;
- explicitly executes `Sales Line.UpdateUnitPrice(...)`;
- throws when the resulting Unit Price is zero/nonpositive;
- contains no release, ship, invoice, post, or explicit COMMIT path.

### Controlled AL authority result

Test case:

- Customer: `GIOVANN`
- Item: `C-503003-12033922`
- Quantity/UOM: `56.42 M`
- Location: `00`
- Order Date: `2026-09-01`
- Shipment Date: `2026-09-08`
- Historical evidence price: `277.99` (not sent to BC)

Result:

- HTTP status: `400`
- AL message: BC pricing validation returned `Unit Price 0.00`.
- Result classification: `AL_PRICING_RETURNED_ZERO_AND_TRANSACTION_ROLLED_BACK`.
- Residual tagged orders: `0`.
- Cleanup: not needed because the transaction rolled back.
- Production: untouched.

Conclusion: the zero-price behavior is not a standard REST-only artifact. Even normal Sales Line validation plus `UpdateUnitPrice(...)` returns zero for this synthetic Giovanni context. Pricing setup/source/context must be inspected before any further create-path changes.

## Pricing diagnostics next

Version `0.1.0.1` is a diagnostics-only revision. It does not change the write authority. It adds read-only API visibility for:

- Giovanni customer pricing context: Bill-to Customer No., Customer Price Group, Customer Discount Group, Currency Code, Price Calculation Method;
- open Sales Line pricing context: document number, customer price/discount groups, currency, price calculation method, item/UOM/quantity/location/price;
- Price List Line records: source type/no., asset/item, UOM, minimum quantity, dates, currency, amount type, unit price, status.

Offline compile of `0.1.0.1`: PASS

- AL compiler: `17.0.34.45391`
- source files compiled: `6`
- package: `Gamer Packaging Inc_GPI Order Intake_0.1.0.1.app`
- SHA256: `8CC6ED106EFC4FD66BF642DE69DB4D7956157EB8FD5CB322EDD15268369A41AB`
- Business Central contacted: NO
- publish/install: NONE
- BC writes: NONE
- Production: NOT TOUCHED
- Release/Ship/Post source hard gate: PASS

Next gate: publish only `0.1.0.1` to certified PRE and perform GET-only pricing diagnostics. No Sales Order authority action should be invoked in that pass.
