# GPI Order Intake - Business Central Authority

Dedicated Business Central extension for the GPI Order Intake Agent.

## Phase 0 purpose

Prove that Business Central itself can create a draft Sales Order through normal `Sales Header` / `Sales Line` validation and calculate the authoritative sell price when the complete order context is supplied.

Copilot/parser code interprets source documents. Business Central decides customer, item, UOM, quantity validity, location, dates, discounts and price.

## Hard Phase-0 safety gates

The AL authority refuses execution unless all of the following are true:

- Business Central reports the current environment is a **Sandbox**.
- Environment name is exactly `PRE_GAMERDOCS_CUTOVER_20260831`.
- External Document No. begins with `AITEST-`.
- Customer, item and location exist.
- Item is not blocked.
- Quantity is greater than zero.
- UOM, order date and shipment date are supplied.
- No existing Sales Header has the same customer + external document number.
- No posted Sales Invoice has the same customer + external document number.
- Business Central calculates a Unit Price greater than zero.

The code contains no release, ship, invoice or post action and no explicit `COMMIT`.

If BC price remains zero, the code raises an AL error. Because the transaction has not been committed, the draft header and line are rolled back.

## Objects

| Type | ID | Name |
| --- | ---: | --- |
| Codeunit | 71200 | GPI Order Intake Authority |
| API Page | 71200 | GPI Order Intake Cust API |
| API Page | 71201 | GPI Order Intake Order API |
| API Page | 71202 | GPI Order Intake Line API |
| Permission Set | 71200 | GPI ORDER INTAKE |

Object range: `71200..71299`.

## API

Base route:

`/api/gpi/orderIntake/v1.0/companies({companyId})`

Customer endpoint:

`/orderIntakeCustomers`

Bound action on a resolved customer:

`Microsoft.NAV.createValidatedDraft`

Parameters:

- `itemNumber`
- `quantity`
- `unitOfMeasureCode`
- `locationCode`
- `orderDate`
- `shipmentDate`
- `externalDocumentNumber`

The successful action response points to the read-only `orderIntakeOrders` entity. Order lines are exposed read-only through `orderIntakeLines`.

## Current Giovanni proof target

First AL authority test after compile/publish is intentionally fixed to the already-proven Giovanni profile:

- Customer: `GIOVANN`
- Item: `C-503003-12033922`
- Quantity/UOM: `56.42 M`
- BC Location: `00` / Drop Ship Location
- Shipment date: controlled future test date
- Expected BC price context: live history shows `$277.99` for the Drop Ship location
- External Document No.: generated `AITEST-...`

A successful test order must remain Draft/Open and be deleted immediately after read-back verification.
