# Customer PDF Corpus Checkpoint — 2026-09-03

## Scope

This checkpoint records the first real customer-PDF corpus proof for GPI Order Intake. It is intentionally evidence-only and does not authorize any Business Central Sales Order write.

Customer PO families profiled:

1. Berner Foods scanned/image PDF.
2. Herdez Coupa digital PDF.

The initial offline parser regression passed `3 passed` with no Business Central calls, no extension mutation, no business-data writes, and no Production contact.

## Architecture correction: customer source quantity is not automatically BC-ready

The first customer-PDF normalizer populated `NormalizedRelease.quantity/uom` directly from a customer PO. Archive linkage proved that assumption is too broad.

Revised rule:

- the customer PO remains authoritative source evidence for what the customer stated;
- source quantity/UOM are preserved separately from BC transaction quantity/UOM;
- `NormalizedRelease.quantity/uom` remain unresolved until an authoritative customer/item mapping proves either:
  - direct equivalence, or
  - an explicit deterministic conversion/packout rule;
- customer-stated price remains source evidence/corroboration only; Business Central remains pricing authority.

This is the same general architecture used elsewhere in Order Intake: source evidence is immutable, while BC transaction semantics require validated mapping.

## Berner PO 241355

### Customer source evidence

Profiled source:

- customer PO: `241355`;
- customer item reference: `811476`;
- source quantity/UOM: `68,000 EA`;
- source unit-price evidence: `243.43 THOU`;
- requested receive date: `2026-07-20`;
- Gamer vendor reference on customer PO: `7050`.

### Linked Gamer Sales Order archive proof

Gamer Sales Order Confirmation `114600` explicitly references customer PO `241355` and records:

- BC customer: `BERNER`;
- BC item: `21759-858231`;
- BC warehouse/location: `00`;
- BC quantity/UOM: `72.2 M`;
- Unit Price: `243.43`;
- requested receive date: `2026-07-20`.

This is direct proof that a real customer PO quantity can require a customer/item packout conversion rather than literal copying into the BC Sales Order transaction. One archived order is not enough to define the universal Berner conversion rule, so Berner quantity mapping remains REVIEW pending repeated historical evidence.

## Herdez PO 4500063632

### Customer source evidence

Profiled source:

- customer PO: `4500063632`;
- Gamer supplier/vendor reference on Herdez PO: `50001644`;
- customer material reference: `000000000004003467`;
- displayed quantity/UOM: `195,888 THOUSAND`;
- format-specific semantic source normalization: `195.888 M`;
- source unit-price evidence: `225.75`;
- requested delivery date: `2026-09-01`;
- ship-to: Herdez SLP Industries Plant, San Luis Potosi.

The line arithmetic corroborates the decimal-comma interpretation: `195.888 × 225.75 = 44,221.72`.

### Linked Gamer downstream Purchase Order proof

Gamer Purchase Order `117357`, linked by customer PO `4500063632`, records:

- vendor: Amcor Rigid Plastics USA Inc.;
- ship-to: HERDEZ SLP FACTORY;
- BC item: `20113526`;
- quantity/UOM: `195.888 M`;
- expected receipt date: `2026-08-24`.

This strongly corroborates the Herdez source quantity normalization and identifies an item candidate used in the supply chain. It does **not** by itself prove the Herdez Sales Order customer/item mapping or authorize BC-ready Sales Order quantity/UOM.

## PDF extraction boundary

- Berner source PDF is image/scanned in the profiled fixture: document vision/OCR evidence is required before deterministic normalization.
- Herdez Coupa PDF contains extractable text and can use deterministic text parsing.
- Extraction is transport only; format-specific parsing owns interpretation.

## Current write status

- Customer PDF Draft Sales Order writes: **NOT AUTHORIZED**.
- CanPack Draft Sales Order writes: **NOT AUTHORIZED**.
- Production: **HARD BLOCKED**.
- Release/Ship/Invoice/Post: **NOT EXPOSED / BLOCKED**.

## Next gate

Run `scripts/Discover-GPIOrderIntakeCustomerPdfMappings-PRE.ps1` after the corrected offline PDF parser regression passes.

The discovery is GET-only and verifies:

- exact PRE sandbox/company/app;
- Berner and Herdez customer-master identities;
- direct source-item-number probes;
- archive-linked BC item existence;
- configured item UOMs;
- posted Sales Invoice Line history;
- Boyer rolling customer/item context;
- customer shipping addresses when available through the standard API.

No extension or business-data mutation is permitted by that gate.
