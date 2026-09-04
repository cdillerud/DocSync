# Phase 0 Customer-PDF Corpus Checkpoint — 2026-09-03

## Safety state

- Certified BC target remains tenant `c7b2de14-71d9-4c49-a0b9-2bec103a6fdc`, sandbox `PRE_GAMERDOCS_CUTOVER_20260831`, company `Gamer Packaging` (`7d84c6d5-81e2-eb11-86df-00224822baa7`).
- Production remains hard blocked.
- Release/ship/invoice/post remains not exposed.
- This checkpoint does not authorize a new Business Central write path.

## Giovanni authority status

`GPI Order Intake 0.1.0.8` has completed both positive breadth and fail-closed pricing-evidence breadth in PRE.

Positive proof includes variable incoming quantities across multiple Giovanni items/locations with exact quantity read-back, resolver-owned context price, Draft/Open only, and mandatory cleanup.

Fail-closed proof includes:

- conflicting latest-two context prices;
- only one posted pricing observation;
- source quantity ambiguity for the current Pasta blanket format;
- mixed/exception source semantics;
- invalid BC UOM;
- zero residual tagged orders after every rejected case.

Quantity is not a pricing key. Incoming customer quantity is allowed to vary when structurally valid.

## CanPack role correction

The profiled CanPack workbook is a supplier/manufacturer schedule, not a customer PO whose sell-to customer is CanPack.

Confirmed PRE / operating evidence:

- `CANPUSA` = CanPack Olyphant;
- `NEW` = New Glarus Brewing Company;
- CanPack supplier/material codes are not guaranteed to equal Gamer item numbers;
- source plant `US50` remains a supplier facility reference, not a BC Location by assumption;
- source UOM `TS` remains supplier-side evidence and is not automatically a BC Sales Order UOM.

The historical 2022 Spotted Cow source reference `3286_NH01` aligns with historical New Glarus item `3286-NH01`, `194.5 M`, Location `00`. Full New Glarus history shows the NH-family lifecycle:

1. `3286-NH01` — active historical context through 2023;
2. `3286-NH01-CPNEW` — 2023 CPNEW/Location 012 context;
3. `3286-NH02` — late-2023 context;
4. `3286-NH02-PFASNI` — current 2026 context, latest two posted prices `130.96`, Location `00`.

The newest family member must **not** be substituted for an older supplier reference merely because it is newest. A current explicit customer/supplier cross-reference or another deterministic effective-dated mapping is required.

**CanPack Sales Order write authorization remains NOT GRANTED.**

## Real customer-PO corpus expansion

Phase 0 now includes actual customer-Purchase-Order examples rather than treating the CanPack supplier schedule as a customer format.

### Berner Food & Beverage LLC — PO 241355

Profiled archive document is an image/scanned PDF.

Source facts observed:

- customer: Berner Food & Beverage LLC;
- PO: `241355`;
- order date: `2026-05-14`;
- required/delivery date: `2026-07-20`;
- Gamer vendor reference: `7050`;
- customer item/reference: `811476`;
- quantity/UOM: `68,000 EA`;
- source unit price: `243.4300 THOU`;
- source line/order total: `16,553.24 USD`.

Standard PDF text extraction returned no body. Therefore this format requires a document-vision/OCR evidence extraction path before deterministic normalization.

### Herdez Group — PO 4500063632

Profiled archive document is a digital Coupa PDF with embedded text.

Source facts observed:

- customer: Herdez Group;
- Gamer supplier account: `50001644`;
- PO: `4500063632`;
- PO date: `2026-07-30`;
- currency: `USD`;
- ship-to: SLP Industries Plant, Mexico;
- line: `0001`;
- customer/source material: `000000000004003467`;
- description: `EP.HE.PP.80202.9OZ.`;
- requested delivery: `2026-09-01`;
- displayed quantity/UOM: `195,888 THOUSAND`;
- source unit price: `225.75`;
- source line total: `44,221.72`.

For this profiled Herdez/Coupa format, the comma in `195,888 THOUSAND` is a decimal comma. The normalized customer transaction quantity is `195.888 M`; `195.888 × 225.75 = 44,221.72` corroborates the interpretation.

This is a format-specific semantic rule, not a global comma rule.

## PDF extraction architecture

PDF byte/text extraction and business interpretation are separate layers.

- Digital PDF → text extraction → deterministic customer-format parser.
- Image/scanned PDF → document vision/OCR → structured evidence → deterministic evidence normalizer.
- Both paths emit the same normalized order contract.
- Source PO price is retained as evidence only. Business Central remains pricing authority.

## Code added

- `backend/order_intake/parsers/customer_pdf.py`
  - `CustomerPoLineEvidence`
  - `CustomerPoEvidence`
  - `CustomerPoEvidenceNormalizer`
  - `BernerPdfEvidenceParser`
  - `HerdezCoupaPdfTextParser`
- normalized model extended with customer PO number/date/currency and source line/price evidence fields;
- parser exports updated;
- offline regressions added under `backend/tests/test_order_intake_customer_pdf.py`;
- offline runner added as `scripts/Test-GPIOrderIntakeCustomerPdfParsers.ps1`.

## Next gate

1. Run the offline customer-PDF parser regression.
2. If it passes, perform GET-only Business Central discovery for the Berner and Herdez customer/item/UOM/ship-to contexts.
3. Do not send the source PO price to the BC authority; use it only as comparison evidence.
4. Do not authorize any Draft Sales Order until customer, item/customer-item reference, UOM, ship-to/location, duplicate state, and BC pricing context are independently proven.
