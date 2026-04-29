# Sender-Stamping Remediation Plan (PLAN ONLY — NO CODE)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any code change
- Scope: read-only diagnostic complete; this document describes the proposed
  fix surface, but no code, no schema change, and no DB write is
  authorised by this document.

## 0. Summary

A learned `sender_vendor_map` collection is allowed to write
`vendor_canonical` on a document **without** comparing the sender-derived
identity against the extracted invoice vendor. When forwarders relay invoices
(e.g. `cargomodules.com` forwarding MKC Customs Brokers' invoice;
`malg.us` forwarding documents on Brown Warehouse's behalf) the document is
stamped with the *forwarder's* identity, not the invoice's. Downstream
learning systems then treat the wrong stamp as ground truth, which propagates
contamination into `vendor_aliases`, `vendor_extraction_profiles`,
`vendor_intelligence_profiles`, and `vendor_realtime_intelligence`.

This plan proposes a narrow guard at the four known stamping sites, an
explicit evidence-precedence ladder, an opt-in self-heal sweep for already
contaminated docs, an opt-in cleanup for contaminated learning rows, and a
revised Batch-2 disposition.

## 1. Confirmed root cause

Two provenance traces (MKC `b2a9d129…`, Mid America `2606d9b4…`) both show:

- Extraction got the invoice vendor right.
- Entity resolution (or BC validation) returned `unmatched` / `not resolved`
  in MKC's case; for Mid America, BC validation actually **succeeded** and
  identified `MIDAMER` correctly.
- `sender_vendor_map` had a row keyed by the forwarder's email/domain that
  pointed at a *different* canonical (`CARGOMO`, `Brown Warehouse Company`).
- The doc-stamping path took the sender-mapping result without checking
  whether the extracted vendor name agrees, then wrote `vendor_canonical` to
  the doc.
- For Mid America, even after BC validation succeeded with the right
  identity, `vendor_canonical` was never re-evaluated against
  `bc_record_info.displayName`. The `batch_revalidate_production` self-heal
  at `services/document_handlers.py:1204` exists in code but did not run
  against this doc.

## 2. Stamping sites (final inventory)

All four sites must be touched by the guard. None of them currently compare
the sender-derived canonical to the extracted vendor name before writing.

| # | file | line | path |
|---|---|---|---|
| 1 | `services/vendor_matching.py` | 53–101 | `lookup_vendor_by_sender()` (read-only library function — but consumers trust its return value blindly) |
| 2 | `services/document_handlers.py` | 1801–1810 → **stamp at 2026** | `intake_document_from_bytes` (primary email intake path; both reproductions stamp here) |
| 3 | `server.py` | 3845–3854 → **stamp at 3888** | intake/reprocess endpoint (email path) |
| 4 | `routers/vendor_reprocess.py` | 60–65 → stamp via `_reprocess_single` return value | bulk reprocess endpoints (sender-first; existing `extracted_field` fallback at 80–90 only fires when there is no sender match — it does not protect the sender path) |

Existing partial protection (preserve unchanged): `services/vendor_matching.py:104-131`
(`EXCLUDED_SENDER_DOMAINS` blocks *learning* on internal domains like
`gamerpackaging.com`. The lookup path has no equivalent guard. We plan to
keep this learning-side exclusion as-is.)

## 3. Guard placement and shape (proposed)

### 3.1 Where the guard goes
Rather than duplicate the check at every stamping site, propose a single
guard inside `lookup_vendor_by_sender()` (site 1). All three caller sites
(2, 3, 4) already use its return value; one change there protects all of
them. The guard's input contract grows by one optional argument:

```
async def lookup_vendor_by_sender(
    sender_email: str,
    extracted_vendor: str | None = None,   # NEW (proposed)
    *, strict: bool = True,                # NEW (proposed)
) -> dict
```

Existing call sites that don't yet have `extracted_vendor` can pass
`None`; the guard then runs in legacy mode (no comparison; same behavior as
today). New call sites pass the extracted vendor and get the guarded
behavior.

This avoids forcing every caller to update on the same commit and keeps
rollback to a single line per site (drop the `extracted_vendor=` kwarg).

### 3.2 Guard logic (pseudocode — illustrative only)

```
mapping = sender_vendor_map.find_one(...)
if not mapping:
    return {"vendor_canonical": None, ...}

# Legacy / no-extracted-vendor path: behave as today (back-compat).
if extracted_vendor is None or not strict:
    return mapping_to_result(mapping)

if vendor_names_likely_match(extracted_vendor, mapping.vendor_name):
    # Sender mapping agrees with the invoice — safe to use.
    return mapping_to_result(mapping)

# Disagreement: refuse to stamp, downgrade to a hint, log telemetry.
return {
    "vendor_canonical": None,
    "vendor_match_method": "sender_disagreed",
    "sender_hint": {
        "sender_email": sender_email,
        "sender_canonical": mapping.vendor_canonical,
        "extracted_vendor": extracted_vendor,
    },
}
```

`vendor_names_likely_match` reuses the same heuristic the sweep already
imports (`tier1_batch_runner._vendor_match_likely`), giving a single source
of truth for "do these two strings refer to the same vendor?". No new
heuristic is introduced.

### 3.3 What is explicitly NOT in scope of this guard

- No change to `learn_sender_vendor()` (writes are already guarded by
  `EXCLUDED_SENDER_DOMAINS`; further write-side guards are a separate signed
  step if needed).
- No change to `vendor_aliases` lookup (`lookup_vendor_alias`) — it is name-
  based and isn't the stamper.
- No change to BC validation, classification, extraction, or any AP/Sales
  workflow logic.

## 4. Evidence precedence ladder (proposed canonical order)

When deciding what to write into `vendor_canonical`, this is the proposed
priority — strongest evidence first:

1. **BC validation success.** If `validation_results.bc_record_info.number`
   is present and non-empty, treat the BC-resolved vendor as truth. Stamp
   `vendor_canonical = bc_record_info.displayName or bc_record_info.number`.
2. **Extracted vendor → alias-table lookup that resolves to a BC vendor**
   (`lookup_vendor_alias` returning a `vendor_no` that exists in BC). This is
   the "name on the invoice agrees with the alias map" path.
3. **Sender-based mapping, ONLY IF the extracted vendor name aligns with
   the sender-mapped vendor name** under `_vendor_match_likely`. (Today's
   bypass becomes today's guard.)
4. **Extracted vendor field as last-resort canonical** (mirrors today's
   `extracted_field` fallback at `vendor_reprocess.py:80-90`).
5. **No stamp.** `vendor_canonical = None`,
   `vendor_match_method = "none"` (or `"sender_disagreed"` when a sender
   hint was rejected). Doc routes to needs-review with a clear blocker.

This ladder is enforced AT WRITE TIME, not by ordering `lookup_*` calls.
That is, even if `lookup_vendor_by_sender` returns first chronologically,
its result must be downgraded if BC validation later returns a different
vendor on the same intake transaction.

## 5. Disagreement behavior (sender vs extracted)

When `lookup_vendor_by_sender` finds a mapping but
`_vendor_match_likely(extracted_vendor, mapping.vendor_name)` returns False:

- Do NOT write `vendor_canonical` from the sender mapping.
- Do NOT silently fall through (a silent fallthrough loses the signal that
  there is a sender-mismatch — operations need that telemetry).
- DO record a structured hint on the doc:
  `vendor_match_method = "sender_disagreed"`, plus
  `vendor_resolution.sender_hint = {sender_email, sender_canonical, extracted_vendor}`.
- DO emit a `workflow_events` row (`vendor.sender_disagreed`) keyed by
  `document_id`, so the rejection is auditable.
- DO continue to the next ladder rung (text alias lookup, then extracted-
  field fallback).

This makes the rejection observable without writing anything destructive.

## 6. Self-heal behavior

Two distinct self-heal opportunities, both proposed as opt-in (flag-gated)
*sweeps*, never as background jobs that run silently:

### 6.1 Self-heal at validation time (live path)
At the existing intake/revalidate sites, after `validate_bc_match` returns,
if `bc_record_info.number` is present AND
`bc_record_info.displayName` does NOT match the current
`vendor_canonical` under `_vendor_match_likely`, overwrite
`vendor_canonical` with the BC display name. Mirror the
`bc_vendor_number` write that already happens at line 1204. Add a
`workflow_events` row (`vendor.canonical_self_healed`) carrying
`{from, to, source: "bc_validation"}`.

This makes the existing line-1204 self-heal symmetric across all stamping
paths instead of only firing in `batch_revalidate_production`.

### 6.2 One-shot retroactive sweep (script — opt-in)
Write a separate signed-step script `vendor_canonical_self_heal_sweep.py`
(read-only by default, `--apply` for the write). For every AP_Invoice doc:
- If `bc_record_info.number` exists and disagrees with
  `vendor_canonical` under the heuristic, queue a self-heal write.
- For each queued doc, write `vendor_canonical = bc_info.displayName`,
  `bc_vendor_number = bc_info.number`, append a `workflow_events` row
  describing the change.
- Output a per-doc audit log so we can roll back individual writes if
  needed.

Run mode: dry-run by default; `--apply --batch-size N --max N` to actually
execute. Idempotent.

## 7. Cleanup plan for contaminated learning rows

Three collections carry contamination derived from the original mis-stamp:

### 7.1 `vendor_aliases` (auto-learned bad mappings)
Targets: rows where `source = "auto_learned"` AND `match_method =
"document_history"` AND `vendor_no` ≠ resolved BC `vendor_no` for any
historical doc tied to that alias.

Examples from the trace:
- `MKC CUSTOMS BROKERS INTL → CARGOMO`
- `HAPAGLLOYD AMERICA → CARGOMO`

Action (separate signed step): write a script that lists
auto-learned aliases whose alias_string fails `_vendor_match_likely`
against the alias's own `vendor_name`. Operator reviews the list. For
clear bad mappings, the existing alias-retire write is one row delete.
Do not delete `bc_cache_seed` aliases automatically.

### 7.2 `vendor_extraction_profiles`
Targets: rows where `vendor_no` is a name (not a code) — symptom of the
schema corruption visible on the Brown Warehouse profile. Also rows where
`vendor_name` does not match the `vendor_no` lookup table.

Action (separate signed step): a read-only audit script identifies these
rows. Cleanup is per-row review; no automatic deletion in this plan.

### 7.3 `vendor_intelligence_profiles`
Targets: rows whose `name_variants` array contains a string that fails
`_vendor_match_likely` against the row's own `vendor_name`.

Action (separate signed step): read-only audit. Per-variant review and
removal — never row-level deletion (these profiles also carry valuable
real telemetry).

### 7.4 `sender_vendor_map` (the source of contamination)
Targets: rows where the mapped `vendor_canonical` does not align (under
`_vendor_match_likely`) with the canonical name actually invoiced from
that sender's emails (computable by joining `sender_vendor_map` against
the corrected `hub_documents` after self-heal §6.2 runs).

Action (separate signed step): retire (set `enabled=false` rather than
delete, to preserve audit) any row that the self-heal sweep flips. Add a
new write-side guard in `learn_sender_vendor` so future internal-forwarder
domains can be added to `EXCLUDED_SENDER_DOMAINS` without code changes
(via env var or config collection).

## 8. Rollback posture

Per stage:

- **§3 guard.** Single-line revert per call site (drop the
  `extracted_vendor=` kwarg). Backward-compatible default keeps current
  behavior. The guard cannot be "stuck on" — turn off by `strict=False` at
  any caller. Recommend a feature flag `SENDER_STAMP_GUARD_ENABLED` (env
  var) so production can flip the guard off in <60 seconds without a code
  change.
- **§4 evidence ladder.** No code change in this plan — only a documented
  contract. Implementation lands as part of the §3 guard step.
- **§5 disagreement behavior.** Telemetry-only. No destructive change.
  Rolling back means dropping the `workflow_events` write and the
  `vendor_resolution.sender_hint` field — both additive.
- **§6.1 live self-heal.** Add an env flag
  `BC_VALIDATION_SELF_HEAL_ENABLED`. Off → byte-identical to today.
- **§6.2 retroactive sweep.** Off by default. `--apply` is the only way to
  write. Each write carries `workflow_events.previous_canonical` so a
  reverse sweep can restore exactly the prior state.
- **§7 cleanup steps.** Each is its own signed declaration. None run
  automatically.

## 9. Revised Batch-2 disposition

Per the latest tightened sweep:

| status | count | disposition |
|---|---|---|
| At-risk (mismatch) | 4 | 1× SC Warehouses (alias_driven) + 3× Mid America (doc_prestamp_or_fallback). **Stay excluded.** |
| Safe but suspicious | 1 | CITICARGO (`vendor_canonical` empty, fallback to `bc_info.number=112522`). **Stay excluded** until §6.2 runs and either confirms or corrects. |
| Genuinely safe | 5 | Tomahawk, Progressive×2, Tumalo×2 — both axes pass. **Eligible for posting.** |

Recommended sequencing:

1. Implement §3 guard (signed step). Re-run vendor-mismatch sweep. Confirm
   the at-risk count does not regress on new ingestions.
2. Run §6.2 retroactive self-heal in `--dry-run`. Confirm Mid America 3 docs
   would heal to MIDAMER. Run with `--apply` once signed.
3. Re-run vendor-mismatch sweep. The 3 Mid America docs should leave the
   mismatch set; the SC Warehouses bucket remains until §7.1 runs.
4. **Only after** the sweep is cleaner than today, post the 5 genuinely
   safe candidates as Batch-2.
5. Defer the long-tail `doc_prestamp_or_fallback` cluster (CARGOMO et al.,
   ~16 docs) to Batch-3 — once §3+§6 are merged, none of them stamp
   incorrectly going forward; the historical contamination cleanup in §7 is
   not on the critical path for posting.

## 10. Out of scope for this plan

- No change to `_vendor_match_likely` itself. The "group" stopword false
  positives the sweep surfaced (Group Warehouses, Smurfit Westrock,
  Aptargroup) are a heuristic limitation, not a stamping defect. Separate
  signed step if you want to address them.
- No change to BC validation, classification, extraction, intake routing,
  or any non-vendor-stamping pipeline.
- No new endpoints. No frontend changes.
- No retro-write to `bc_purchase_invoice`. Self-heal is a vendor-canonical
  fix only; whether to re-attempt posting on healed docs is a separate
  Batch-2/3 disposition decision.

## 11. Open questions for the operator before signing §3 (the guard)

1. **`strict=True` default vs `False` default?** Default-True means new
   call sites get the guard automatically; the back-compat path (no
   `extracted_vendor=`) still bypasses it. Default-False means callers must
   opt in explicitly. Recommend default-True with the env-flag escape
   hatch.
2. **Heuristic alignment.** OK to reuse
   `tier1_batch_runner._vendor_match_likely` as the canonical
   "names-likely-match" function? It's the same one the sweep uses — single
   source of truth. (Alternative: extract it to
   `services/vendor_name_helpers.py` so the import is cleaner and the
   sweep + guard share a stable home.)
3. **`workflow_events` event type names.** Proposed
   `vendor.sender_disagreed` (rejection telemetry) and
   `vendor.canonical_self_healed` (BC self-heal). Any naming preference?
4. **Which call site lands first** — §2 (`document_handlers`) covers both
   reproductions and is the primary email-intake path. Recommend landing
   the guard there first under a feature flag, leaving §3 + §4 unchanged
   until §2 is observed clean.

## 12. What this plan deliberately does NOT do

- It does not change any code.
- It does not retire any alias.
- It does not edit any profile or learning row.
- It does not modify `sender_vendor_map`.
- It does not resume Batch-2.
- It does not re-resolve any document.
- It does not run the self-heal sweep.

Each of those is its own signed declaration after this plan is signed.
