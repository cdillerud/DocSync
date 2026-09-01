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

- a 14oz Pizza normal full load is physically 89,775 units, while live PRE_GAMERDOCS BC evidence transacts it as `89.775 M`;
- a 16oz Vinegar normal full load is physically 78,166 units, while 16 live PRE_GAMERDOCS posted/open lines unanimously transact it as `78.166 M`;
- 14oz Pizza also has a live `85.05 M` transaction at a different unit price, so partial/nonstandard quantities cannot simply inherit the normal full-load profile.

Earlier document evidence showed a `22 PALLET` presentation for 16oz Vinegar. That evidence is retained as historical/anomalous context but is not the current automation rule because the live 2026 BC transaction history is authoritative.

Therefore no global `/ 1000`, pallet, or truckload conversion is permitted. The BC transaction quantity/UOM must come from an authoritative customer/item profile or direct BC rule, and nonstandard/partial loads require review unless BC can deterministically resolve them.

## Pricing safety rule

Business Central remains the pricing authority. The Order Intake agent must never infer or hard-code sell price from historical transactions.

Live testing also showed that the standard Business Central v2.0 `salesOrderLines` create path can accept an item/UOM/quantity while leaving `unitPrice = 0` when unit price is omitted. Therefore a successful standard API line insert is not proof that BC pricing rules were executed. Production order creation must use a BC-side deterministic pricing/validation path or otherwise prove a nonzero, authoritative price before an order is eligible to pass validation.

## Validation
Business Central remains authoritative for customer, item mapping, quantity/UOM rules, ship-to, price/discount, dimensions, and duplicate control.

The allowed outcomes are `PASS`, `REVIEW`, `REJECT`, and `DUPLICATE`.
