# Phase 0 Status

- Branch: `feature/order-intake-agent-phase0`
- Business Central write test: guarded `AITEST-` create/read-back/delete round trip **PASSED** in `PRE_GAMERDOCS_CUTOVER_20260831`; cleanup passed.
- Production: hard blocked.
- Release/ship/invoice/post: not exposed.
- Models: added.
- CanPack deterministic parser: added; BC customer/item/UOM profile still unresolved.
- Giovanni deterministic parser: added.
- Giovanni live BC profiling:
  - 16oz Vinegar `C-8808-12026443`: normal load `78.166 M` confirmed by 16 live posted/open lines.
  - 14oz Pizza `C-8479-10000229`: normal full load `89.775 M`; partial/nonstandard quantity evidence also exists.
- Pricing gap: standard BC v2.0 line-create test accepted item/UOM/quantity but returned `unitPrice = 0` when price was omitted. Production creation therefore requires BC-side deterministic pricing/validation authority rather than assuming standard API price calculation.
- Next: profile remaining Giovanni items and design/test the BC-side order-create/pricing authority before any broader write pilot.
