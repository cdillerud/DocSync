# Phase B Implementation Declaration — Extend Sender-Stamp Guard to Legacy Paths (CODE-CHANGE PLAN, NO CODE EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any code lands.
- Parent: `memory/SENDER_STAMP_GUARD_IMPLEMENTATION_DECLARATION.md` (signed, deployed, observed clean).
- Observation evidence (`gpi_document_hub.workflow_events`):
  - 1 `vendor.sender_disagreed` event from `rotondowarehouse.com` (third
    forwarder domain detected, beyond `cargomodules.com` and `malg.us`).
  - GUARD HELD — affected doc resolved to `OWENS` via alias fallthrough.
  - Zero false-positive candidates over the observation window.
- Out of scope (preserved): §6.1 self-heal-symmetry, §6.2 retroactive sweep,
  §7 alias/profile/intelligence cleanup, Batch-2 resumption.

---

## 1. Goal

Extend the existing `extracted_vendor` / `document_id` kwargs to the two
remaining call sites of `lookup_vendor_by_sender`. After this lands, every
production code path that reads `sender_vendor_map` and writes
`vendor_canonical` runs through the same guard.

Single behavior change: two existing call sites pass two existing kwargs.
No new functions, no new flags, no new tests of guard semantics
(those are already covered by the parent declaration's Class C).

## 2. Files touched (exact)

| # | path | change kind | line range | net effect |
|---|---|---|---|---|
| 1 | `server.py` | one call-site update | 3845–3854 | passes `extracted_vendor=` and `document_id=` to the existing `lookup_vendor_by_sender` call |
| 2 | `routers/vendor_reprocess.py` | one call-site update | 60–65 | same pattern |
| 3 | `backend/tests/test_sender_stamp_guard.py` | additive | end of file | adds Class F — call-site adoption smoke (verifies the kwargs are passed by importing the modules and checking the source) |

Total expected production diff: ~6 lines across 2 files. No new file; no
function-signature changes; no env-flag changes; no telemetry-schema
changes.

## 3. Exact code shape

### 3.1 `server.py:3845–3854` — call-site update

Current code (verified at signing time — line numbers will drift; the
match is on the call to `lookup_vendor_by_sender` inside the email-intake
reprocess path):

```python
if sender_email:
    from services.vendor_matching import lookup_vendor_by_sender
    sender_result = await lookup_vendor_by_sender(sender_email)
    if sender_result.get("vendor_canonical"):
        vendor_alias_result = sender_result
```

After:

```python
if sender_email:
    from services.vendor_matching import lookup_vendor_by_sender
    sender_result = await lookup_vendor_by_sender(
        sender_email,
        extracted_vendor=normalized_fields.get("vendor_raw"),
        document_id=doc_id,
    )
    if sender_result.get("vendor_canonical"):
        vendor_alias_result = sender_result
```

Pre-flight guard before code lands: `doc_id` and `normalized_fields` must
both be in scope at the call site (they are — verified during the static
search). If either has drifted, the implementation step stops and the
declaration is amended.

### 3.2 `routers/vendor_reprocess.py:60–65` — call-site update

Current code (single-doc reprocess):

```python
sender_email = (doc.get("email_sender") or "").strip()
sender_result = await lookup_vendor_by_sender(sender_email) if sender_email else \
    {"vendor_canonical": None, "vendor_match_method": "none"}
```

After:

```python
sender_email = (doc.get("email_sender") or "").strip()
extracted_vendor = (doc.get("extracted_fields") or {}).get("vendor")
sender_result = await lookup_vendor_by_sender(
    sender_email,
    extracted_vendor=extracted_vendor,
    document_id=doc.get("id"),
) if sender_email else {"vendor_canonical": None, "vendor_match_method": "none"}
```

Note: this path uses `doc.extracted_fields.vendor` (live doc field) where
the email-intake path uses `normalized_fields.vendor_raw` (in-flight
extraction result). Both are the same surface — the extracted vendor name
as the system saw it. Guard treats them identically.

### 3.3 No `services/vendor_matching.py` change

Function signature, env-flag behavior, telemetry, and `_emit_sender_disagreed`
are unchanged from the parent declaration. The two new call sites simply
populate the kwargs the function already accepts.

## 4. Tests

### Class F — Legacy-path adoption smoke (new in `test_sender_stamp_guard.py`)

Three small static-analysis tests that protect against future regressions
where a maintainer accidentally drops the kwargs from one of these call
sites. No new behavioral coverage — Class C already proves the function
itself works; Class F just proves the call sites pass the right things.

- F1: `routers/vendor_reprocess.py` source contains the substring
  `lookup_vendor_by_sender(` and the matching call literal also contains
  `extracted_vendor=` AND `document_id=`. Fails loudly if either kwarg is
  removed in a future edit.
- F2: same check against `services/document_handlers.py` (already-landed
  call site — protects against accidental regressions there too).
- F3: same check against `server.py` for the new call site.

Implementation hint (no code lands until signed): use a small helper
that reads the module's source via `inspect.getsource`, finds each
`lookup_vendor_by_sender(` block within ~200 chars after the match, and
asserts the kwargs are present.

This adds 3 tests; total Class A–F count after this declaration: 24.

## 5. Precise guard condition (unchanged from parent)

Same as parent §4. No change to when the guard fires.

## 6. Event emission behavior (unchanged from parent)

Same `vendor.sender_disagreed` schema (with optional `document_id`). The
two new call sites BOTH have document context in scope, so both will
populate `document_id`. The Q3 observability query continues to work
unchanged.

## 7. Feature flag behavior (unchanged from parent)

`SENDER_STAMP_GUARD_ENABLED=false` continues to disable the guard
globally. Flipping it off does NOT break the new call sites — the
function returns the legacy mapping result regardless of which call site
invoked it.

## 8. Rollback path

| layer | rollback action | takes |
|---|---|---|
| Whole change at runtime | `SENDER_STAMP_GUARD_ENABLED=false` + restart | <60 s |
| Per call site | remove the two new kwargs at the affected line | 2-line revert per site |
| Both call sites | `git revert <merge-commit>` | 1 commit |

Migration risk: zero. No schema change, no data migration, no new
collections. The new telemetry rows (if any fire from the new sites) use
the same schema already in use.

## 9. Out-of-scope fence (explicit)

This declaration MUST NOT:

- Modify the function signature of `lookup_vendor_by_sender` (already
  shipped in parent).
- Modify `_emit_sender_disagreed` or its event schema.
- Modify the env flag, default value, or read path.
- Modify `services/vendor_name_helpers.py`.
- Modify any DB row outside the existing intake / reprocess write paths.
- Run any retroactive sweep, self-heal, or cleanup script.
- Modify `services/document_handlers.py:1204` (deferred to §6.1).
- Resume Batch-2 posting.
- Touch the frontend.
- Add new HTTP endpoints.

If any change appears to require touching something on this list, work
stops and the declaration is amended before proceeding.

## 10. Observation window after this lands

After Phase B is implemented, observe the same Q1–Q4 queries (against
`gpi_document_hub`). Expected change vs the current snapshot:

- Q2 may surface NEW forwarder domains beyond `rotondowarehouse.com`,
  `cargomodules.com`, `malg.us` — specifically domains that previously
  only contaminated docs through the `server.py:3888` reprocess path or
  the `vendor_reprocess.py` bulk path.
- Each new event MUST show `verdict: "GUARD HELD"` in Q3. A `GUARD MISS`
  here would mean a fourth stamping path exists that we missed.
- Q4 should remain empty (no new false-positive class introduced by
  changing where the guard fires).

If after a similar observation cycle Q3 stays clean and Q4 stays empty,
**every production sender-stamping path is guarded**. That unlocks the
next sequence: §6.1 (live self-heal symmetry) → §6.2 (retroactive sweep)
→ §7 cleanup → Batch-2 resumption.

## 11. Sign request

To proceed to actual code:

- **"Sign as-is"** → I implement exactly what's above. Output: code diff,
  test results, brief observation-query reminder. No deploy, no Batch-2
  action.
- **"Sign with amendments"** → paste your amendments; I update this
  declaration; you re-sign; then I implement.
- **"Reject"** → tell me which assumption is wrong; I re-scope.

## 12. What this declaration deliberately does NOT do

- It does not change `lookup_vendor_by_sender`.
- It does not change the env flag.
- It does not change the telemetry schema.
- It does not change `vendor_name_helpers.py`.
- It does not touch §6.1, §6.2, or §7.
- It does not resume Batch-2.

Each of those is its own signed declaration after this one is signed and
observed clean.
