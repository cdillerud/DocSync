# Bragg DocuSign Validation Findings — Phase 3.2B

> **Packet:** Bragg Live Food Products × Gamer Packaging Supply Agreement (West
> Coast), NPW DRAFT 3/4/2026.
> **Source materials supplied by Charlie:** DocuSign Navigator AI metadata
> export (xlsx) + signed PDF with agreement trail.
> **Deliverables this round:** golden fixture, expected-normalized fixture,
> regression test suite, this report. **Zero production code changes.**
> **Scope:** validation only. **Phase 4 remains gated.**

---

## 1. Summary

| Item | Result |
|---|---|
| What was tested | End-to-end: Navigator metadata row + PDF ground truth → current normalizer + matcher |
| Fixtures committed | 2 (`bragg_metadata_export_redacted.json`, `bragg_expected_normalized.json`) |
| Regression tests added | `test_contracts_bragg_fixture.py` — 25 tests |
| Tests run | 19 passed + 6 xfailed (xfailed = tracked schema/matcher gaps) |
| Unrelated tests regressed | None |
| Production code changed | **None** |

The normalizer does a **strong** job on the Connect-SIM-shape payload
synthesized from the Navigator row + PDF: all parties, all 11 metadata
terms, both pricing lines (PE-1013-110424-R004 and PE-1013-110524-R003 with
correct qty/price/UOM), document, completion/expiration dates, and
normalized-org for BC matching are captured. **What's missing is not
parsing fidelity but coverage of the Navigator shape itself and a handful
of schema fields.**

---

## 2. Coverage matrix — metadata export vs PDF vs current schema

### 2a. Fields successfully extractable today (Connect SIM synthesis)

Every field below is covered by a passing regression test in
`test_contracts_bragg_fixture.py`.

- **Envelope id** → `Agreement.provider_envelope_id` ✅
- **Envelope status** → `Agreement.status="completed"` ✅
- **Agreement title** → `Agreement.title` ✅
- **Expiration date** → `Agreement.expires_at` (tz-aware) ✅
- **Execution / completed date** → `Agreement.completed_at` ✅
- **Sender + both signer companies** → `AgreementParty` rows with
  `normalized_org` populated ✅
- **Agreement Type** → `AgreementTerm(term_key="agreement_type")` ✅
- **Internal agreement id (QUO-...)** → `AgreementTerm(term_key="agreement_id_number")` ✅
- **Effective / execution / expiration dates** → `AgreementTerm` rows ✅
- **Initial term length** → `AgreementTerm(term_key="initial_term_length")="3 Years"` ✅
- **Payment term** (full text from PDF: "1% 10 / Net 45 Days") ✅
- **Price cap increase %** → `AgreementTerm(term_key="price_cap_increase_pct")="6"` ✅
- **Governing law** → `AgreementTerm(term_key="governing_law")="California"` ✅
- **Renewal type + term** → two separate AgreementTerm rows ✅
- **Both pricing lines** → `AgreementPricing` with item_label, description,
  qty, unit_price, UOM correct ✅
- **Document** → `AgreementDocument` ✅

### 2b. Fields only in the PDF, NOT in the Navigator export

These are real contract terms that Navigator's AI metadata does NOT
surface. They're captured in our synthesized Connect-SIM fixture (as
extra custom fields), but **in live production they would only land if
the DocuSign template exposes them as custom fields or we run a separate
PDF extraction pass**:

- **Payment discount** ("1% 10") — Navigator truncates to "45 days"
- **Freight terms** ("DAP Garden Grove, CA")
- **Minimum order quantity** (2,000,000 / PO)
- **Total commitment** (42,053,832 products)
- **Tooling amortization** ($7.12 per thousand products post-commitment)
- **Annual forecast per SKU** (5.78M × 16oz; 4.471M × 32oz)
- **Alternate envelope id** in signature trail
  (A535A3EE-7BBA-8E79-81DC-09A99ECC3D95) — only the primary envelope id
  (3A85F196-5F70-830B-82C2-1BEC243DAB9E) is exposed by Navigator.

### 2c. Fields missing from BOTH metadata export and PDF

None identified for the Bragg packet — all commercially meaningful
fields are present in at least one source.

---

## 3. Current normalizer gaps (tracked as xfails)

These are the 6 live xfails in `test_contracts_bragg_fixture.py`. Each
one auto-flips to a PASS when the gap is fixed (and pytest will tell us
to remove the xfail marker).

| # | Gap | xfail test | Recommended fix location |
|---|---|---|---|
| 1 | Navigator xlsx row cannot be consumed directly by `normalize_envelope()` | `TestNavigatorMetadataDirectConsumption::test_normalizer_can_read_raw_xlsx_row` | New `services/contracts/navigator_normalizer.py` adapter (Phase 4.x) |
| 2 | Matcher silently collapses ambiguous BC candidates to a single link | `TestBCMatchingAmbiguity::test_ambiguous_match_emits_both_plus_exception` | Phase 4.x matcher hardening — emit both + `party_unmatched` with `details.ambiguous=true` |
| 3 | `Agreement.provider_agreement_id` field missing (Navigator UUID) | `TestKnownSchemaGaps::test_navigator_uuid_is_first_class_field` | Add `provider_agreement_id: Optional[str]` to Agreement model |
| 4 | `Agreement.alternate_envelope_ids` list missing (PDF shows 2 envelope ids) | `TestKnownSchemaGaps::test_alternate_envelope_id_captured` | Add `alternate_envelope_ids: List[str]` to Agreement model |
| 5 | `AgreementPricing.location` field missing (per-line ship-to) | `TestKnownSchemaGaps::test_pricing_row_has_location_field` | Add `location: Optional[str]` to AgreementPricing |
| 6 | `payment_term_discount` not separated from combined `payment_term` | `TestKnownSchemaGaps::test_payment_term_discount_exposed_as_own_term` | Template change + normalizer preserves whatever DocuSign sends |

---

## 4. Matcher findings

**Critical gap: ambiguous BC match handling.**

When an agreement's customer company (e.g., "Bragg Live Food Products LLC")
has multiple BC customer records (Charlie confirmed Bragg might — Greg
and Susan manage separate BC codes for the same legal entity), the
current matcher:

1. Ranks candidates by score.
2. Picks the single top-scoring candidate.
3. Emits one `AgreementBCLink` (status: `auto_confirmed` if ≥0.95, else `proposed`).
4. **Silently drops the other candidate.** No `party_unmatched` exception.

Verified by `TestBCMatchingAmbiguity::test_current_matcher_silently_picks_one`
(passes today — it's documenting current behavior).

**Recommended fix (Phase 4.x matcher hardening):**
- If ≥2 candidates score within a tight band (e.g., within 0.05 of the
  top) AND all are above `propose_threshold`:
  - Emit all as `proposed` links (not auto-confirmed).
  - Open a single high-severity `party_unmatched` exception with
    `details.ambiguous=true` and `details.candidate_bc_nos=[...]`.
  - Block auto-confirm for that party until an operator picks one in the
    mapping UI.
- Manual pick → confirm + auto-reject the others + resolve the
  exception + 3 audit rows. Already supported by the existing
  `manual_link` + `reject_link` + `resolve_exception` plumbing.

**Recommended BC mapping rule (in priority order):**
1. **Exact BC code wins** — if an agreement has a `bc_customer_code` custom
   field (see §5 recommendations), use it directly, skip matching.
2. **Normalized party-name match** — if top candidate is unique and
   score ≥ auto-confirm threshold, auto-confirm.
3. **Single proposed** — if top candidate is unique and score ≥ propose,
   emit `proposed`.
4. **Ambiguous proposed + exception** — if multiple candidates tie or
   cluster, emit all as `proposed` + open ambiguity exception (above).
5. **Unmatched** — if no candidate scores ≥ propose, open
   `party_unmatched` exception.
6. **Manual confirmation is sticky** — already implemented; survives
   replay per existing regression test `test_replay_does_not_clobber_manual_link`.

---

## 5. Recommended DocuSign template additions

These are custom fields the Bragg packet would benefit from having added
to the DocuSign template (so Navigator and Connect surface them without
a PDF-extraction fallback). Each maps cleanly to the current schema
with no structural changes:

| Field | Type | Maps to | Why |
|---|---|---|---|
| `bc_customer_code` | string | `AgreementTerm` + short-circuits BC matching | Priority 1 rule above |
| `bc_vendor_code` | string | `AgreementTerm` | Same, vendor side |
| `primary_bc_code` | string | `AgreementTerm` | Tie-breaker when Greg/Susan codes both exist |
| `agreement_owner` | string | `AgreementTerm` | Operational ownership |
| `renewal_owner` | string | `AgreementTerm` | "Who wakes up at 60 days to expiry" |
| `agreement_type` | string | `AgreementTerm` ✅ already extracted | — |
| `effective_date` | date-string | `AgreementTerm` ✅ | — |
| `expiration_date` | date-string | `AgreementTerm` + `Agreement.expires_at` ✅ | — |
| `payment_terms` | string (keep "1% 10 / Net 45") | `AgreementTerm` | Avoid Navigator truncation |
| `pricing_mechanism` | string | `AgreementTerm` | Annual Price Adjustment Formula vs fixed |
| `product_ids` | comma-separated | formData `line_N_item` ✅ (current) | No template change needed |
| `item_numbers` | comma-separated | same | No template change |
| `price_per_m` | decimal | `line_N_price` ✅ | No template change |
| `release_quantities` | integer | `line_N_qty` ✅ | No template change |
| `total_commitment` | integer | `AgreementTerm` | PDF-only today |
| `renewal_type` | string | `AgreementTerm` ✅ | — |
| `renewal_notice_date` | date-string | `AgreementTerm` | Not in Navigator row; needed for renewal workflow |

---

## 6. Naming / env-config findings

- **Pricing tab convention:** our default `^line[_\-]?(\d+)[_\-]?(.+)$`
  works perfectly for Bragg's `line_1_item` / `line_2_price` style.
  **No `CONTRACT_PRICING_TAB_REGEX` override required** for this template.
- **Custom field bucket name:** `textCustomFields` — standard Connect SIM
  shape, works today.
- **Status strings:** Bragg's "completed" maps cleanly via `_STATUS_MAP`.
- **Governing law casing:** "California" (not "CA"). No normalization
  required — stored as-is.

---

## 7. Schema gaps summary (what to change in Phase 4.x)

All additive, all non-breaking:

```python
# models/contracts.py

class Agreement(_ContractBase):
    # ... existing fields ...
    provider_agreement_id: Optional[str] = None           # Navigator UUID
    alternate_envelope_ids: List[str] = Field(default_factory=list)

class AgreementPricing(_ContractBase):
    # ... existing fields ...
    location: Optional[str] = None                        # Bragg per-line ship-to
```

Matcher hardening (no model change, only logic):
```python
# services/contracts/bc_agreement_matcher.py
# in _emit_party_links, detect and emit ambiguous clusters.
```

---

## 8. What happens now

- ⏸️ **No code change** in Phase 3.2B per your guardrails.
- 🟢 Bragg packet is now the **first real-world regression baseline** for
  the Contract Intelligence module.
- 🟢 Six xfails serve as a live gap inventory — they'll auto-flip to
  passes as each fix lands in Phase 4.x, and pytest will flag us to
  remove them.
- ⏸️ Phase 4 (DocuSign SDK + live envelope fetch + model/matcher gap
  fixes) remains gated. Scope is now concretely informed by real data.

---

## 9. Recommended Phase 4 scope (for your sign-off)

Based solely on what this packet revealed:

**P0 (foundational, needed before any live envelope fetch):**
- Add `provider_agreement_id` + `alternate_envelope_ids` to `Agreement`.
- Add `location` to `AgreementPricing`.
- Backfill unique-indexes accordingly.

**P1 (makes the product usable with real Navigator exports):**
- `services/contracts/navigator_normalizer.py` — adapter that converts
  a Navigator row into Connect-SIM shape (or an equivalent internal
  representation) and feeds the existing pipeline.
- One-shot bulk import endpoint: `POST /api/contracts/navigator/import`
  accepting an xlsx or CSV.

**P1 (makes BC matching correct for shared-customer orgs):**
- Matcher ambiguity detection (logic only, no new schema).
- `bc_customer_code` / `primary_bc_code` short-circuit when present as
  custom field.

**P2 (operational polish after the above land):**
- DocuSign template change advisory document (field list from §5) — one
  to send to Charlie / Greg / Susan so future envelopes carry the full
  set.

**P3 (deferred):**
- DocuSign SDK install + live envelope fetch (original Phase 4 target).
  Gating on the above so we don't chase envelope bytes before the data
  model can hold them.
- PDF body extraction fallback for fields the template won't carry.

---

## 10. Carry-overs (still parked, untouched)

- P1: LLM throttling / Gemini `RESOURCE_EXHAUSTED` — UNCHANGED.
- P2: SMC / SC / CITICARGO Batch 2 — UNCHANGED.
- P2: Contaminated `vendor_aliases` cleanup — UNCHANGED.
- P2: Phase 4 Path B Removal (time-gated drain) — UNCHANGED.
- P2: Agreement → Document Hub cross-link — UNCHANGED (deferred by you).
- P2: Suggested-threshold widget — UNCHANGED (deferred by you).

---

## 11. Phase 4A — Payload Shape Reconciliation (✅ completed)

Status: **Dual-path normalizer landed.** Both DocuSign Connect webhook
JSON and Navigator AI Metadata Export rows now feed the same canonical
`NormalizedAgreement` output.

### 11a. What shipped

**Schema additions** (all additive, non-breaking, no migrations required):

| Field | Model | Purpose |
|---|---|---|
| `provider_agreement_id: Optional[str]` | `Agreement` | Navigator UUID (distinct from envelope id) |
| `alternate_envelope_ids: List[str]` | `Agreement` | Secondary envelope ids DocuSign stamps into the signed PDF trail |
| `location: Optional[str]` | `AgreementPricing` | Per-line ship-to (e.g. "Garden Grove, CA") |

**New service**: `services/contracts/navigator_normalizer.py`

- `build_connect_sim_payload(row)` — flat Navigator row → Connect-SIM-shape dict.
- `normalize_navigator_row(row)` — one-shot Navigator → `NormalizedAgreement`.
- Handles the 54-column Navigator schema, mapping 1:1 fields to custom-field
  terms, concatenating `value + unit` pairs ("3" + "Years" → "3 Years"),
  splitting the semicolon-delimited `Parties` column into signer rows, and
  translating Navigator `Status="Active"` to canonical `status="completed"`.
- Emits structured `warnings` (`source="navigator_adapter"`) for any
  schema gap rather than silently dropping data.

**Unified entry point**: `normalize_envelope(payload)` now detects a flat
Navigator row (signature: `"Envelope Id"` + ≥1 Navigator-only column at
top level, no Connect wrapper keys) and dispatches to the adapter. Callers
can stop caring which shape they have.

**Connect path enhancements** (lossless, additive):

- Reads `envelopeSummary.alternateEnvelopeIds` into the new list field.
- Reads `providerAgreementId` (envelope summary hint) or a
  `provider_agreement_id` / `agreement_navigator_uuid` custom field.
- Pricing tab extractor now captures `line_N_location` → `pricing.location`.

### 11b. xfail inventory — post Phase 4A

| # | Gap (Section 3 original) | Phase 4A outcome |
|---|---|---|
| 1 | Navigator xlsx row unreadable by `normalize_envelope` | **✅ RESOLVED** — dispatched to Navigator adapter |
| 2 | Matcher collapses ambiguous BC candidates | ⏸ STILL XFAIL — out of Phase 4A scope (matcher hardening follow-up) |
| 3 | `Agreement.provider_agreement_id` missing | **✅ RESOLVED** — field added; Navigator path populates it |
| 4 | `Agreement.alternate_envelope_ids` missing | **✅ RESOLVED** — field added; Connect payload reads `alternateEnvelopeIds` |
| 5 | `AgreementPricing.location` missing | **✅ RESOLVED** — field added; `line_N_location` tab captured |
| 6 | `payment_term_discount` not split from `payment_term` | ⏸ STILL XFAIL — requires a DocuSign template change to expose the discount as its own custom field; Navigator truncates, normalizer only preserves what DocuSign sends |

### 11c. Test results

- `tests/test_contracts_bragg_fixture.py` — 23 passed, 2 xfailed
  (previously 19 passed, 6 xfailed). Four xfails converted to passes
  in-place with updated comments.
- `tests/test_contracts_navigator_normalizer.py` — **new**, 22 tests
  covering synthesis, end-to-end normalization, dispatch routing, and
  edge cases.
- Full Contract Intelligence suite: 144 passed, 7 skipped, 2 xfailed.
- Remaining xfails (matcher ambiguity, template-side discount split) are
  tracked as post-Phase-4A work; reasons on each marker explain why.

### 11d. Live envelope vs historical import — which path does what?

| Path | When used | Source | Primary strengths | Known gaps |
|---|---|---|---|---|
| **Connect JSON** | Live DocuSign envelope events | `POST /api/docusign/webhook` | Full fidelity (tabs, recipients w/ emails, timestamps), alternate envelope ids, per-line locations | Requires DocuSign template to surface any custom metadata the business wants captured |
| **Navigator Export** | Historical backfill / bulk ingest of already-signed agreements | Batch upload of the AI Metadata xlsx (no UI yet — adapter only) | Wide column coverage (54 fields) for legacy agreements that never went through Connect | No signer emails, no per-line pricing, no discount carve-outs (Navigator-truncated `payment_term`), only one envelope id per row |

### 11e. Remaining gaps before live DocuSign SDK / webhook activation

- **Matcher ambiguity** (xfail 2) — two BC candidates at the same score
  for the same legal entity. Still collapses to one. Scope: matcher
  hardening pass (no schema change).
- **Template-side fields** — `payment_term_discount`, `bc_customer_code`,
  `primary_bc_code`, `renewal_notice_date`, MOQ / total commitment /
  tooling. These are captured in §5's recommendation list; they need
  template edits at DocuSign before Connect can carry them.
- **Navigator bulk-import endpoint** — the adapter is plumbed, but there
  is no HTTP endpoint yet to accept an uploaded xlsx / CSV. Scope for a
  follow-up increment once an initial batch volume is agreed with
  Charlie.
- **DocuSign SDK install + live envelope fetch** — deferred to Phase 4B
  or later. No blocker remains on the normalizer side.

---

## 12. Phase 4B — Navigator import CLI + matcher ambiguity hardening (✅ completed)

Status: **CLI + matcher ambiguity landed.** One of the remaining two
Phase 4A xfails converted. Only one xfail remains: a template-side field
(`payment_term_discount`) that DocuSign itself must expose.

### 12a. Navigator dry-run / commit CLI

File: `backend/scripts/contracts_import_navigator.py`

Runs under the existing container — no new dependencies (openpyxl 3.1.5
+ pandas 3.0.0 already installed).

**Default is dry-run.** Nothing is written to MongoDB unless `--commit`
is passed.

Supported formats:
- `.xlsx` (`--sheet NAME` optional; defaults to the active sheet)
- `.csv`
- `.json` (single naked row, `{"row": {...}}` wrapper, `{"rows": [...]}` wrapper, or a top-level list — compatible with the existing Bragg fixture)

Per-row diagnostics printed for every row:
- envelope id, status, title, Navigator UUID
- party / term / pricing / document / warning counts
- inline warning code + details (e.g. `party_missing_email`)
- commit outcome (committed / duplicate / not committed)

Commit path reuses `ContractIntelligenceService.record_event` +
`process_event` — the same orchestrator that live Connect webhooks use —
so import rows pass through matcher + audit + exception pipeline with
zero duplication.

**Idempotency guarantees:**
- Event id is deterministic: `navigator::{envelope_id}` — replays are a
  no-op at the `agreement_events` unique-index layer.
- The `agreements` unique index on `provider_envelope_id` guards the
  underlying row upsert if the envelope was already ingested via Connect.
- Manual mappings survive: orchestrator's replay logic only rewrites
  `linked_by="system"` links in `{proposed, auto_confirmed}` state.
  Confirmed / rejected / manual-link rows are untouched.

**Usage (VM):**

```bash
# Dry-run (default, no writes):
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx

# Commit:
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --commit

# First N rows only:
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --limit 5

# Specific xlsx sheet:
docker compose exec backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --sheet "Agreements"

# Dry-run against the Bragg fixture that ships with the repo:
docker compose exec backend \
    python -m scripts.contracts_import_navigator \
    backend/tests/fixtures/docusign/bragg/bragg_metadata_export_redacted.json
```

Exit codes: `0` = clean, `1` = argparse error, `2` = file unreadable /
unsupported, `3` = one or more rows failed normalization or commit.

### 12b. Matcher ambiguity hardening

File: `backend/services/contracts/bc_agreement_matcher.py`

**Behavior (new, guarded by a tight default band):**

| Scenario | Phase 4A behavior | Phase 4B behavior |
|---|---|---|
| Top candidate unique, above auto-confirm | `auto_confirmed` link | unchanged |
| Top candidate unique, above propose threshold | `proposed` link | unchanged |
| Top candidate below propose threshold | `party_unmatched` exception | unchanged |
| **Two+ candidates within `ambiguity_band` of top, both ≥ propose** | **silently picked top, dropped rest** | **emits BOTH as `proposed`, opens one high-severity `party_unmatched` exception with `details.ambiguous=True`, `details.candidate_bc_nos=[...]`** |
| Any candidate with `method="exact_no"` (BC code direct hit) | no short-circuit | **single exact-no candidate wins outright, skipping ambiguity analysis** |

**Tunable:**
- `CONTRACT_MATCH_AMBIGUITY_BAND` (default `0.02`).

**No schema change**, no new field, no model migrations. Only emitted
output (links + exceptions) changes shape in the ambiguity case.

**Manual flow still works:**
- Operator picks one of the two proposed links in the mapping UI →
  `manual_link` / `confirm_link` marks it `confirmed` with `linked_by=<actor>`.
- The other candidate can be explicitly rejected via `reject_link`.
- Both outcomes trigger existing audit rows (`confirmed_link`,
  `rejected_link`) and `resolve_exception` closes the ambiguity row.
- Any replay (re-import, webhook resend) skips over manually-modified
  rows per the existing "only refresh `linked_by="system"` and status in
  `{proposed, auto_confirmed}`" rule (regression-covered by
  `test_replay_does_not_clobber_manual_link`).

### 12c. xfail inventory — post Phase 4B

| # | Gap | Status |
|---|---|---|
| 1 | Navigator xlsx row unreadable | ✅ resolved in 4A |
| 2 | Matcher silently collapses ambiguous BC candidates | **✅ RESOLVED in 4B** — emits both as proposed + ambiguity exception |
| 3 | `Agreement.provider_agreement_id` missing | ✅ resolved in 4A |
| 4 | `Agreement.alternate_envelope_ids` missing | ✅ resolved in 4A |
| 5 | `AgreementPricing.location` missing | ✅ resolved in 4A |
| 6 | `payment_term_discount` not split from `payment_term` | ⏸ STILL XFAIL — requires a DocuSign template change; xfail kept so it auto-flips once the field arrives on a live envelope |

### 12d. Tests

- New `tests/test_contracts_import_navigator_cli.py` — 16 tests
  (loaders for xlsx / csv / json, dry-run happy + sad paths, exit codes,
  commit-mode via a fake orchestrator, idempotent-replay behavior).
- Rewrote `TestBCMatchingAmbiguity` in
  `tests/test_contracts_bragg_fixture.py` — the "silently picks one"
  documentation test is replaced by a canonical "emits both + ambiguity
  exception" test; the xfail converted to passing.
- Full Contract Intelligence suite: **161 passed, 7 skipped, 1 xfailed**.
- Zero regressions in existing normalizer, matcher, orchestrator,
  endpoints, golden-fixture, phase3, or phase3.1 suites.

### 12e. What remains before live DocuSign SDK / webhook activation

- DocuSign SDK install, live envelope fetch, and Connect webhook
  activation. No blocker on the normalizer or matcher side.
- A `POST /api/contracts/navigator/import` HTTP endpoint wrapping the
  CLI. Deferred until Charlie confirms the volume/shape of the initial
  batch — the CLI keeps operators unblocked in the interim.
- Per-line PDF body extraction (freight terms, MOQ, total commitment,
  tooling amortization, 1%-10 discount). Still template-side or
  PDF-extraction-pass territory.

---

## 13. Phase 4C(a) — Navigator Import Endpoint + UI Drop Zone (✅ completed)

Status: **HTTP endpoint + UI tab landed.** Charlie can now upload
Navigator exports directly from the Contract Intelligence page; no SCP
or `docker cp` round-trips required. CLI and HTTP share the exact same
service (`services/contracts/navigator_import.py`) so they cannot drift.

### 13a. HTTP endpoint

`POST /api/contracts/navigator/import`

- Admin-gated via `services.auth_deps.require_admin`. Non-admin → 403.
- Multipart upload field `file`. Accepts `.xlsx`, `.xlsm`, `.csv`, `.json`.
- Default mode is dry-run. `?commit=true` persists.
- Optional `?sheet=<name>` selects a specific xlsx worksheet.
- Size cap from `CONTRACT_NAVIGATOR_IMPORT_MAX_BYTES` (default 5 MB,
  hard ceiling 50 MB). Oversize → 413.
- Returns the structured `ImportSummary` shape:

```json
{
  "mode": "dryrun" | "commit",
  "filename": "...",
  "row_count": N,
  "error_count": N,
  "warning_count": N,
  "agreements_detected": N,
  "parties_detected": N,
  "terms_detected": N,
  "pricing_detected": N,
  "documents_detected": N,
  "would_create": N,            // dry-run only
  "would_update": N,            // dry-run only
  "skipped": N,                 // commit only
  "committed": N,               // commit only
  "ambiguity_exceptions": N,    // commit only
  "schema_gap_warnings": N,
  "rows": [
    {
      "index": 1, "envelope_id": "...", "provider_agreement_id": "...",
      "title": "...", "status": "completed",
      "party_count": 2, "term_count": 17,
      "pricing_count": 0, "document_count": 1,
      "warning_count": 2, "warnings": [...],
      "committed": true, "duplicate": false,
      "agreement_id": "...", "link_count": 0,
      "exception_count": 0, "has_ambiguity_exception": false,
      "error": null
    }
  ]
}
```

### 13b. Shared service

`backend/services/contracts/navigator_import.py` — single source of
truth used by both CLI and HTTP layers.

- `parse_upload(data, filename, content_type, sheet)` — bytes → row dicts.
  Validation order: size cap → extension → content-type → parse.
- `dryrun_rows(rows, *, db=None, filename=None)` — async; computes
  ``would_create`` vs. ``would_update`` against the live ``agreements``
  collection when ``db`` is provided.
- `commit_rows(rows, *, db, filename=None)` — async; routes every row
  through ``ContractIntelligenceService.record_event`` +
  ``process_event``. Idempotent via deterministic event id
  ``navigator::{envelope_id}``.
- All validation failures raise ``NavigatorImportError`` (subclass of
  ``ValueError``).

### 13c. UI

`frontend/src/pages/ContractIntelligencePage.jsx` — added a 6th tab
"Import" (`data-testid="tab-navigator-import"`) wrapping a
`<NavigatorImportTab />` component:

- File drop-zone (drag-and-drop or `browse to upload`).
- Validates extension client-side before upload.
- "Run Dry-Run" → calls endpoint with `commit=false`, renders summary
  card with rollup tiles and a per-row table (envelope, status, title,
  P/T/Pr/D counts, outcome).
- "Commit Import" disabled until a dry-run succeeds and at least one
  row is non-error. `confirm()` dialog summarizes
  would_create/would_update before commit. Idempotent — duplicates show
  as `skipped`.
- Ambiguity exceptions are flagged with a yellow `AMBIGUOUS` badge on
  the row outcome.
- Toasts via `sonner` for both success and error paths.

### 13d. CLI preserved

`backend/scripts/contracts_import_navigator.py` is now a thin wrapper
around the shared service. CLI commands remain unchanged:

```bash
docker compose exec -w /app backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx
docker compose exec -w /app backend \
    python -m scripts.contracts_import_navigator /tmp/navigator.xlsx --commit
```

CLI tests (`tests/test_contracts_import_navigator_cli.py`, 16 tests)
still green — backwards-compat adapter layer exposes the legacy
`load_rows`, `dryrun_row`, `commit_row` helpers that prior tests imported.

### 13e. Tests

- New `tests/test_contracts_navigator_import_endpoint.py` — 11 tests:
  - Auth gating (non-admin → 403).
  - Validation: missing file, unsupported extension, oversize.
  - Dry-run: structured response shape, xlsx + csv, no DB writes.
  - Commit: persists, idempotent replay, dry-run after commit reports
    `would_update`.
  - Mixed-row CSV (one good, one bad) — error count + per-row report.
- Full Contract Intelligence suite: **172 passed, 7 skipped, 1 xfailed**
  (was 161 passed pre-Phase-4C(a)).
- Zero regressions in normalizer, Connect SIM path, golden fixtures,
  matcher (incl. ambiguity hardening), orchestrator, phase3, phase3.1,
  endpoints, models.

### 13f. Remaining items before live DocuSign SDK / webhook activation

Same as §12e — Phase 4C(a) does not touch SDK install, live envelope
fetch, webhook activation, or PDF body extraction. Operators are now
fully unblocked on the bulk-import side.

