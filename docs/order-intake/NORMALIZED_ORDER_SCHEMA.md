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
- quantity
- uom
- requested_shipment_date
- requested_delivery_date
- ship_to_candidate
- existing_gamer_order
- notes
- source_coordinates
- quantity_source
- extraction_confidence

## Validation
Business Central remains authoritative for customer, item mapping, quantity/UOM rules, ship-to, price/discount, dimensions, and duplicate control.

The allowed outcomes are `PASS`, `REVIEW`, `REJECT`, and `DUPLICATE`.
