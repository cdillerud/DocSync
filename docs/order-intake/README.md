# GPI Order Intake Agent — Phase 0

This branch contains the first read-only implementation scaffolding for customer PO intake.

Goals:
- deterministic parsing for known CanPack and Giovanni Excel formats;
- normalized inbound-order model;
- shadow-only validation output;
- no Business Central writes.

The first fixtures are the supplied CanPack sales order form and Giovanni monthly blanket OOR workbook.
