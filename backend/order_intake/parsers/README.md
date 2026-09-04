# Known-format parsers

Phase 0 parsers are deterministic and operate on source formats we have explicitly profiled.

- `CanPackXlsxParser`: row-oriented CanPack supplier/manufacturer schedule. Supplier quantity/UOM/plant remain source evidence until linked customer-order mappings are proven.
- `GiovanniOorParser`: period-aware parser for the Giovanni monthly blanket release schedule.
- `HerdezCoupaPdfTextParser`: deterministic parser for the profiled Herdez/Coupa digital-PDF text layout.
- `BernerPdfEvidenceParser`: deterministic normalizer for structured evidence extracted from the profiled Berner scanned/image PDF layout.

## PDF extraction boundary

PDF extraction is transport, not business interpretation.

- Digital/text PDFs: extract text, identify the profiled customer format, then run its deterministic parser.
- Image/scanned PDFs: use document vision/OCR to produce structured evidence, then run the same normalized evidence contract.
- A format must not silently switch between extraction strategies unless that strategy has been profiled and regression-tested for that format.

The real Berner PO `241355` is image-only in the available archive copy; standard PDF text extraction returned no body. The real Herdez PO `4500063632` contains embedded text and is parsed deterministically from that text.

## Source facts versus Business Central authority

All parsers emit the normalized order contract. No parser writes to Business Central.

Customer POs may directly state transaction quantity/UOM, dates, ship-to, and source price. Those values are preserved as source facts. A stated PO price is evidence only and does not become Business Central pricing authority.

Supplier/manufacturer schedules may use supplier quantity/UOM/plant/reference schemes. Those values remain source evidence until the linked end-customer/item/UOM/location context is explicitly resolved.

Business Central remains authoritative for duplicate detection, customer resolution, item/customer-item mapping, configured UOM validation, ship-to/location, pricing, dimensions, and order creation eligibility.
