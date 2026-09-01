# Known-format parsers

Phase 0 parsers are deterministic and operate on customer formats we have explicitly profiled.

- `CanPackXlsxParser`: row-oriented CanPack call-off/order worksheet.
- `GiovanniOorParser`: period-aware parser for Giovanni monthly blanket release schedule.

Both parsers emit the normalized order contract. Neither parser writes to Business Central.

Business Central remains authoritative for duplicate detection, item resolution, quantity/UOM rules, ship-to, pricing, dimensions, and order creation eligibility.
