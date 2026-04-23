"""Drop Ship archetype module (Lane C Step 6).

Scope note: gate-layer extraction seam for the Drop Ship archetype.
The live authoritative DS rules continue to live in
``services/so_rules_engine.py`` (``_check_drop_ship_rules``,
``_determine_stage``). This package intentionally provides
authoritative-equivalent scaffolding only — no classifier, no wire-in,
no auto-registration.

Severity parity with the live rules:
  - drop_ship_po_missing ................... block  (SO-008 parity)
  - drop_ship_po_cost_unverified ........... warn   (SO-009 parity)
  - drop_ship_inventory_line_not_marked .... warn   (ancillary parity)
"""
