# §3 Implementation Declaration — Live-Path Sender-Stamp Guard (CODE-CHANGE PLAN, NO CODE EXECUTED)

- Author/agent: Emergent fork agent
- Generated: 2026-04-29 (UTC)
- Status: DRAFT — awaiting user signature before any code lands.
- Parent: `memory/SENDER_STAMPING_REMEDIATION_PLAN.md` §1–§5 (signed).
- §6 self-heal, §7 cleanup, alias retire, profile correction, `sender_vendor_map`
  edits, Batch-2 resumption: ALL OUT OF SCOPE for this declaration.

---

## 1. Goal

Stop new contamination on the live path. Specifically: at the
`intake_document_from_bytes` email-intake path, if a `sender_vendor_map`
mapping disagrees with the extracted invoice vendor name (under the same
heuristic the sweep uses), do not stamp `vendor_canonical` from the
sender mapping. Emit telemetry. Fall through to the next ladder rung.

That single behavior change — at one call site, behind one feature
flag — is the entire scope of this declaration.

## 2. Files touched (exact)

| # | path | change kind | line range | net effect |
|---|---|---|---|---|
| 1 | `services/vendor_name_helpers.py` | additive — new exports | EOF append (+ ~25 lines) | adds `vendor_match_likely`, `_vendor_tokens`, `_VENDOR_STOPWORDS` (moved verbatim from `scripts/tier1_batch_runner.py`); single source of truth |
| 2 | `services/vendor_matching.py` | guarded behavior in `lookup_vendor_by_sender` | 53–101 (in-place) | adds `extracted_vendor: str \| None = None` and `*, strict: bool = True` kwargs; adds env-flag-gated disagreement check; emits telemetry; otherwise byte-identical |
| 3 | `services/document_handlers.py` | one call-site update | 1801–1810 | passes `extracted_vendor=normalized_fields.get("vendor_raw")` to the existing `lookup_vendor_by_sender` call |
| 4 | `scripts/tier1_batch_runner.py` | one-line import shift | top-of-file | re-exports `_vendor_match_likely` from `vendor_name_helpers` so existing imports keep working (back-compat, zero behavior change) |
| 5 | `scripts/vendor_mismatch_sweep.py` | one-line import shift | line 33 | imports `vendor_match_likely` from `vendor_name_helpers` instead of `tier1_batch_runner` |
| 6 | `backend/tests/test_sender_stamp_guard.py` | new file | full | unit + integration coverage of guard semantics + telemetry |

**Sites NOT touched** in this declaration (deliberate scope fence):

- `services/document_handlers.py:535` — non-email intake path, no sender lookup; unaffected.
- `services/document_handlers.py:1204` — `batch_revalidate_production` self-heal; deferred to §6.1.
- `server.py:3845–3888` — second email/reprocess entry point; legacy back-compat path runs through unchanged because `extracted_vendor=` defaults to `None`.
- `routers/vendor_reprocess.py:60–65` — bulk reprocess; same legacy path runs through.

The two unchanged callers (`server.py`, `vendor_reprocess.py`) continue to
operate exactly as today by passing zero new arguments. They get a follow-up
declaration after `services/document_handlers.py` is observed clean.

## 3. Exact code shape

### 3.1 `services/vendor_name_helpers.py` — additive block

```python
# ---------------------------------------------------------------------------
# Vendor-name match heuristic
#
# Single source of truth for the "do these two strings refer to the same
# vendor?" question. Imported by:
#   - services/vendor_matching.py        (live guard)
#   - scripts/tier1_batch_runner.py      (re-export for back-compat)
#   - scripts/vendor_mismatch_sweep.py   (sweep)
# ---------------------------------------------------------------------------
import re

_VENDOR_STOPWORDS = {
    "llc", "inc", "corp", "corporation", "company", "co", "ltd", "limited",
    "the", "and", "of", "for", "group", "holdings",
}


def _vendor_tokens(s: str) -> set:
    """Normalize a vendor name to a set of meaningful tokens
    (≥4 chars, not stopwords)."""
    s = re.sub(r"[^\w\s]", " ", (s or "").lower())
    return {t for t in s.split() if len(t) >= 4 and t not in _VENDOR_STOPWORDS}


def vendor_match_likely(a: str, b: str) -> bool:
    """Heuristic: do these two strings likely refer to the same vendor?

    Substring-tolerant so BC vendor codes (e.g. TUMALOC) match human names
    (e.g. TUMALO CREEK). Returns True when at least one significant token
    from one side is a substring of any token on the other side. Returns
    True when either side has no meaningful tokens (insufficient signal
    to flag as a mismatch — fail-open).
    """
    if not a or not b:
        return True
    if a.strip().lower() == b.strip().lower():
        return True
    ta = _vendor_tokens(a)
    tb = _vendor_tokens(b)
    if not ta or not tb:
        return True
    for x in ta:
        for y in tb:
            if x in y or y in x:
                return True
    return False
```

Behavior identical to the existing `_vendor_match_likely` in
`scripts/tier1_batch_runner.py:502-523`. Bytes verified to match before
deletion of the original.

### 3.2 `services/vendor_matching.py:53-101` — guarded `lookup_vendor_by_sender`

```python
async def lookup_vendor_by_sender(
    sender_email: str,
    extracted_vendor: str | None = None,
    *,
    strict: bool = True,
) -> dict:
    """
    Look up vendor by sender email address.

    Guarded behavior (added 2026-04-29):
      When `extracted_vendor` is provided, `strict=True`, and the env flag
      `SENDER_STAMP_GUARD_ENABLED` is "true" (default), the function refuses
      to return a sender-derived canonical that disagrees with
      `extracted_vendor` under `vendor_match_likely`. A telemetry row is
      emitted to `workflow_events` and the function returns
      `{"vendor_canonical": None, "vendor_match_method": "sender_disagreed",
        "sender_hint": {...}}`.

      When `extracted_vendor` is None or `strict=False`, behavior is
      byte-identical to the pre-guard implementation (back-compat).
    """
    db = get_db()
    if not sender_email:
        return {"vendor_canonical": None, "vendor_match_method": "none"}

    email_lower = sender_email.strip().lower()

    # --- existing email + domain lookup (unchanged) ---
    mapping = await db.sender_vendor_map.find_one(
        {"sender_email": email_lower}, {"_id": 0}
    )
    matched_kind = "sender_email" if mapping and mapping.get("vendor_canonical") else None
    if not matched_kind:
        domain = email_lower.split("@")[-1] if "@" in email_lower else ""
        if domain:
            mapping = await db.sender_vendor_map.find_one(
                {"sender_domain": domain, "domain_confidence": {"$gte": 2}},
                {"_id": 0},
            )
            if mapping and mapping.get("vendor_canonical"):
                matched_kind = "sender_domain"

    if not mapping or not mapping.get("vendor_canonical"):
        return {"vendor_canonical": None, "vendor_match_method": "none"}

    # --- NEW: guard ---
    guard_enabled = os.environ.get("SENDER_STAMP_GUARD_ENABLED", "true").lower() == "true"
    if guard_enabled and strict and extracted_vendor:
        from services.vendor_name_helpers import vendor_match_likely
        sender_name = mapping.get("vendor_name") or mapping.get("vendor_canonical")
        if not vendor_match_likely(extracted_vendor, sender_name):
            await _emit_sender_disagreed(
                db,
                sender_email=email_lower,
                sender_canonical=mapping.get("vendor_canonical"),
                sender_name=sender_name,
                extracted_vendor=extracted_vendor,
                matched_kind=matched_kind,
            )
            return {
                "vendor_canonical": None,
                "vendor_match_method": "sender_disagreed",
                "sender_hint": {
                    "sender_email": email_lower,
                    "sender_canonical": mapping.get("vendor_canonical"),
                    "sender_name": sender_name,
                    "extracted_vendor": extracted_vendor,
                    "matched_kind": matched_kind,
                },
            }

    # --- existing hit-count tracking (only on agreement / legacy path) ---
    if matched_kind == "sender_email":
        try:
            await db.sender_vendor_map.update_one(
                {"sender_email": email_lower},
                {"$inc": {"hit_count": 1},
                 "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}},
            )
        except Exception:
            pass
    return {
        "vendor_canonical": mapping["vendor_canonical"],
        "vendor_match_method": matched_kind,
        "vendor_name": mapping.get("vendor_name", ""),
        "vendor_no": mapping.get("vendor_no", ""),
    }


async def _emit_sender_disagreed(
    db, *, sender_email, sender_canonical, sender_name, extracted_vendor, matched_kind,
):
    """Best-effort telemetry; never raises into the caller."""
    try:
        await db.workflow_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "vendor.sender_disagreed",
            "status": "warning",
            "source_service": "vendor_matching.lookup_vendor_by_sender",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": None,
            "payload": {
                "sender_email": sender_email,
                "sender_canonical": sender_canonical,
                "sender_name": sender_name,
                "extracted_vendor": extracted_vendor,
                "matched_kind": matched_kind,
                "guard_version": "v1",
            },
        })
    except Exception as e:
        logger.warning("[vendor.sender_disagreed] telemetry write failed: %s", e)
```

Required imports added at top of file: `import os`, `import uuid`. Both are
already idiomatic in this file's neighbors.

### 3.3 `services/document_handlers.py:1801-1810` — call-site update

```python
# Phase 7: Vendor alias lookup — sender email first, then text lookup
try:
    vendor_alias_result = {"vendor_canonical": None, "vendor_match_method": "none"}
    # Check sender email → vendor mapping first
    existing_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "email_sender": 1})
    sender_email = (existing_doc or {}).get("email_sender", "")
    if sender_email:
        from services.vendor_matching import lookup_vendor_by_sender
        sender_result = await lookup_vendor_by_sender(
            sender_email,
            extracted_vendor=normalized_fields.get("vendor_raw"),  # NEW
        )
        if sender_result.get("vendor_canonical"):
            vendor_alias_result = sender_result
    if not vendor_alias_result.get("vendor_canonical"):
        vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
except Exception as va_err:
    logger.warning("Vendor alias lookup failed for %s: %s", doc_id, str(va_err))
    vendor_alias_result = {}
```

Single new line. Everything else unchanged. The fallthrough to
`lookup_vendor_alias` already exists and now does the right thing when the
sender result is downgraded to `None` by the guard.

### 3.4 `scripts/tier1_batch_runner.py` — back-compat re-export

Replace the local `_vendor_match_likely` definition (lines 489–523) with:

```python
from services.vendor_name_helpers import vendor_match_likely as _vendor_match_likely
from services.vendor_name_helpers import _vendor_tokens, _VENDOR_STOPWORDS  # noqa: F401
```

This preserves the leading-underscore name so existing callers (and the
sweep, transitively) keep working without source edits beyond §3.5.

### 3.5 `scripts/vendor_mismatch_sweep.py` — direct import

Replace line 33:

```python
from scripts.tier1_batch_runner import _vendor_match_likely, _vendor_tokens
```

with:

```python
from services.vendor_name_helpers import vendor_match_likely as _vendor_match_likely
from services.vendor_name_helpers import _vendor_tokens
```

No other changes to this file.

## 4. Precise guard condition

Guard fires (refuses to stamp) IFF **all four** are true:

1. `os.environ.get("SENDER_STAMP_GUARD_ENABLED", "true").lower() == "true"`
2. `strict=True` (the kwarg default; only `False` when caller opts out)
3. `extracted_vendor` is non-empty
4. A `sender_vendor_map` row was found AND
   `vendor_match_likely(extracted_vendor, mapping.vendor_name or mapping.vendor_canonical)` returns False.

If ANY of (1)–(3) is false, behavior is byte-identical to today (legacy
back-compat). If (1)–(3) are true but (4) is false (i.e. names agree),
the function returns the mapping result and bumps `hit_count` exactly
as today.

## 5. Evidence precedence (within this scope)

This declaration enforces ladder rungs **3 → 4** from the parent plan §4:

- Rung 3 (sender mapping with extracted-vendor agreement) — **return mapping**
- Rung 4 (extracted-vendor name fallback via `lookup_vendor_alias`) — **runs when guard rejects**
- Rung 5 (no stamp) — **runs when alias lookup also fails** (existing behavior)

Rungs 1 and 2 (BC validation > extracted-vendor → BC alias) are NOT
implemented by this declaration. They are part of §6.1 self-heal and a
future declaration. The current code already gives BC validation its own
write at `validation_results.bc_record_info`; this declaration does not
change that.

## 6. Event emission behavior

One new `workflow_events` row per disagreement. Schema:

```json
{
  "event_id": "<uuid>",
  "event_type": "vendor.sender_disagreed",
  "status": "warning",
  "source_service": "vendor_matching.lookup_vendor_by_sender",
  "timestamp": "<iso8601 utc>",
  "actor": null,
  "payload": {
    "sender_email": "kbowman@malg.us",
    "sender_canonical": "Brown Warehouse Company",
    "sender_name": "Brown Warehouse Company",
    "extracted_vendor": "Mid America Logistics Group, LLC",
    "matched_kind": "sender_email",
    "guard_version": "v1"
  }
}
```

No `document_id` is recorded here because `lookup_vendor_by_sender` is
called before the doc identity is in scope of the helper. Operators
correlate via `sender_email` + `timestamp`. (If you want `document_id`
threaded through, that's a one-arg amendment — say so before sign.)

`vendor.canonical_self_healed` is **not** emitted by this declaration —
it belongs to §6.1.

## 7. Feature flag behavior

- `SENDER_STAMP_GUARD_ENABLED=true` (default): guard active.
- `SENDER_STAMP_GUARD_ENABLED=false`: guard fully disabled; every code
  path returns identical bytes to today.
- Flag is read on every call (no module-load caching) so a flip is live
  immediately without backend restart.
- Flag is **not** a code constant; it is read at runtime via
  `os.environ.get(..., "true")`. To add to `backend/.env`, append:
  ```
  SENDER_STAMP_GUARD_ENABLED=true
  ```
  (Optional — the default of "true" applies if the var is absent.)

## 8. Tests (new file `backend/tests/test_sender_stamp_guard.py`)

The test file is part of this declaration's scope. Contract:

### Class A — Pure-function: `vendor_match_likely`
- A1 identical names → True
- A2 substring-token agreement (TUMALO / TUMALOC) → True
- A3 disjoint tokens (Mid America / Brown Warehouse) → False
- A4 either side empty → True (fail-open)
- A5 either side stopword-only → True (fail-open)

### Class B — `lookup_vendor_by_sender` legacy back-compat
- B1 no `extracted_vendor` arg → returns mapping result (today's behavior)
- B2 `strict=False` with disagreement → returns mapping result
- B3 env flag = "false" with disagreement → returns mapping result

### Class C — `lookup_vendor_by_sender` guarded mode
- C1 mapping found, names agree → returns mapping result, `hit_count` incremented
- C2 mapping found, names disagree → returns `{"vendor_canonical": None, "vendor_match_method": "sender_disagreed", "sender_hint": {...}}`, `hit_count` NOT incremented
- C3 disagreement also writes one `workflow_events` row with `event_type=vendor.sender_disagreed`
- C4 telemetry write failure does NOT raise into caller (best-effort)
- C5 no mapping found → returns `{"vendor_canonical": None, "vendor_match_method": "none"}` (unchanged)

### Class D — Integration: `intake_document_from_bytes` smoke
- D1 fixture document with `email_sender = kbowman@malg.us` and extracted `vendor_raw = "Mid America Logistics Group, LLC"` — after intake, doc has `vendor_canonical != "Brown Warehouse Company"` AND a `workflow_events.vendor.sender_disagreed` row exists.
- D2 same fixture with `SENDER_STAMP_GUARD_ENABLED=false` — doc has `vendor_canonical = "Brown Warehouse Company"` (today's behavior preserved).
- D3 fixture where sender mapping agrees with extracted vendor — doc has `vendor_canonical = mapping.vendor_canonical`, NO disagreement event row.

### Class E — Sweep contract preservation
- E1 `vendor_mismatch_sweep` imports `vendor_match_likely` from `vendor_name_helpers` and the import resolves successfully.
- E2 a known-divergent pair from the production sweep (Mid America / Brown) returns False from the imported function — proves no semantic drift in the move.

Pass criterion: 100% of new tests green; no regression in existing tests.
Targeted regression scope: `pytest backend/tests/` post-change. The
session is allowed to skip pre-existing baseline failures (we maintain
the previously-noted 317P/35F/14E baseline; this change must NOT enlarge
the F/E counts).

## 9. Rollback path (per layer)

| layer | rollback action | takes |
|---|---|---|
| Whole change at runtime | set `SENDER_STAMP_GUARD_ENABLED=false` and restart container | <60 s |
| Telemetry only | drop `_emit_sender_disagreed` body to a no-op | 1-line edit |
| Call-site (§3.3) | remove `extracted_vendor=` kwarg | 1-line edit |
| Function-signature kwargs (§3.2) | remove `extracted_vendor` and `strict` kwargs (back-compat callers unaffected) | small revert |
| Heuristic move (§3.1, §3.4, §3.5) | restore the local definition in `tier1_batch_runner.py`; revert the two import lines | full revert; tested as part of a single git revert |
| All-up | `git revert <merge-commit>` reverses every file in this declaration as one atomic change | 1 commit |

Migration risk: zero. No schema change. No data migration. No deletes. The
new `workflow_events.vendor.sender_disagreed` rows are pure telemetry; if
the change is reverted, the rows remain in the collection but no consumer
relies on them.

## 10. Out-of-scope fence (explicit)

This declaration MUST NOT:

- Modify any `sender_vendor_map` row (no learn-side changes, no row deletions).
- Modify any `vendor_aliases` row.
- Modify any `vendor_invoice_profiles` row.
- Modify any `vendor_extraction_profiles` row.
- Modify any `vendor_intelligence_profiles` row.
- Modify any `hub_documents` row except via the existing intake write path.
- Run any retroactive sweep or self-heal script.
- Resume Batch-2 posting.
- Change BC validation logic.
- Change classification or extraction.
- Touch the frontend.
- Touch `server.py:3845–3888` or `routers/vendor_reprocess.py:60–65`
  (deferred follow-up declaration).
- Touch `services/document_handlers.py:1204` (deferred to §6.1).
- Add new HTTP endpoints.
- Change `EXCLUDED_SENDER_DOMAINS` (read-side has the new guard; write-side
  exclusion is not in scope).

If, during implementation, any change appears to require touching
something on this list, work stops and the declaration is amended before
proceeding.

## 11. Sign request

To proceed to actual code:

- **"Sign as-is"** → I implement exactly what's above, run the new test
  file, run the existing regression suite, summarize the diff for review,
  and stop. No production rollout. No Batch-2 action.
- **"Sign with amendments"** → paste your amendments; I update this
  declaration, you re-sign, then I implement.
- **"Reject"** → tell me which assumption is wrong; I re-scope.

Per parent plan §11.4: the guard lands first at
`services/document_handlers.py:2026`. After this lands and is observed
clean for a duration you choose (suggest: until the next vendor-mismatch
sweep run shows zero new contamination on email-intake docs), a follow-up
declaration extends the guard to `server.py:3888` and
`routers/vendor_reprocess.py`.
