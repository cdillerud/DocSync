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
