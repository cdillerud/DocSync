# Normalized Inbound Order Contract

Every inbound customer order format is converted to a common order model before Business Central validation.

## Source
- message_id
- internet_message_id
- sender
- subject
- received_datetime
- attachment_name
- attachment_sha256
- source_format
- source_sheet

## Customer
- resolved_customer_no
- candidate_customer_name
- resolution_method
- resolution_confidence
- evidence

## Document
- document_type (`STANDARD_PO` or `BLANKET_RELEASE_BATCH`)
- blanket_reference
- period
- source_revision_key

## Release
- customer_release_reference
- load_number
- product_context
- customer_item_reference
- description
- `quantity`: BC-ready Sales Order quantity only
- `uom`: BC-ready Sales Order UOM only
- `physical_quantity`: customer/source physical packout evidence
- `physical_uom`: unit describing the physical source quantity
- requested_shipment_date
- requested_delivery_date
- ship_to_candidate
- existing_gamer_order
- notes
- source_coordinates
- quantity_source
- quantity_resolution_method
- extraction_confidence

## Quantity safety rule

`physical_quantity` and `quantity` are not interchangeable.

Giovanni demonstrates why this distinction is mandatory:

- a 14oz Pizza full load is physically 89,775 units, while historical BC evidence transacts the item as `89.775 M`;
- a 16oz Vinegar full load is physically 78,166 units, while historical BC evidence shows `22 PALLET`.

Therefore no global `/ 1000`, pallet, or truckload conversion is permitted. The BC transaction quantity/UOM must come from an authoritative customer/item profile or direct BC rule.

## Validation
Business Central remains authoritative for customer, item mapping, quantity/UOM rules, ship-to, price/discount, dimensions, and duplicate control.

The allowed outcomes are `PASS`, `REVIEW`, `REJECT`, and `DUPLICATE`.
