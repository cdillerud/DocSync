# CanPack Role Correction Checkpoint — 2026-09-03

## Why this checkpoint exists

The original Phase-0 fixture was named `CanPack Sales Order Form_Gamer Packaging.xlsx`. Early normalization treated the workbook name as evidence that `CanPack` was the inbound sell-to customer and classified the file as a standard customer PO.

That assumption is now retired.

Gamer's saved CanPack operating procedures identify Can Pack as the vendor/manufacturer side of the transaction:

- Can Pack sends a vendor invoice.
- Gamer processes a Purchase Order against the Can Pack transaction.
- Drop-ship workflows separately reference and process the linked customer Sales Order.
- CanPack operational folders are organized by downstream Gamer customers, including New Glarus.

Additional saved sales-mail evidence ties a `canpack.com` sender to the subject `New Glarus Spotted Cow - Darker Can Interiors`. Separate customer evidence identifies New Glarus Brewing Company as BC customer `NEW`.

This is sufficient to prove that `CanPack` must not be used as the workbook-level BC sell-to customer.

## Corrected source classification

The CanPack XLSX format is now classified as:

`SUPPLIER_SALES_ORDER_SCHEDULE`

Source party role:

`SUPPLIER_MANUFACTURER`

The workbook can contain multiple supplier-side rows and product/material families. A single workbook-level end-customer identity is therefore not assumed.

## Source values versus BC Sales Order values

For CanPack rows:

- `Call-off quantity` is preserved as `physical_quantity`.
- source UOM such as `TS` is preserved as `physical_uom`.
- `Delivering Plant` such as `US50` is preserved as `source_facility_reference`.
- supplier material reference such as `3286_NH01` remains source/customer-material evidence.
- supplier PO/order reference remains preserved for traceability.

The parser now deliberately leaves these BC Sales Order fields unresolved:

- `quantity`
- `uom`
- `ship_to_candidate`
- `location_candidate`
- end-customer number
- BC item
- price

The normalized result is REVIEW until the linked Gamer customer/item/order context is independently resolved.

## Spotted Cow targeted evidence

The current fixture contains Spotted Cow rows using supplier material reference `3286_NH01`, source quantity `194500`, UOM `TS`, and source plant `US50`.

Saved evidence supports New Glarus Brewing Company / customer `NEW` as a targeted end-customer candidate for the Spotted Cow rows only. This relationship must not be generalized to BRITE, Rich Mocha, Carmel Vanilla, or future CanPack rows.

Exact supplier-material-to-BC-item mapping is still unproven.

## Safety state

- CanPack write authorization: **NOT GRANTED**.
- `0.1.0.8` Giovanni Sales Order authority remains unchanged.
- No CanPack Sales Order action is authorized.
- Production remains hard blocked.
- Release, ship, invoice, and post behavior remain blocked/not exposed in Phase 0.

## Next gate

Run `scripts/Discover-GPIOrderIntakeCanPack-RoleAware-PRE-REV3.ps1` in the certified PRE sandbox.

The GET-only gate must:

1. search CanPack as a BC vendor, not as a customer;
2. verify targeted customer `NEW` / New Glarus for Spotted Cow context;
3. normalize punctuation when comparing supplier material refs to BC item numbers/descriptions;
4. inspect full posted sales history for customer `NEW`;
5. print configured Item UOMs for any matched BC items;
6. treat `US50` as a supplier facility reference, never a BC Location by assumption;
7. perform no extension mutation, business-data write, or Sales Order action.
