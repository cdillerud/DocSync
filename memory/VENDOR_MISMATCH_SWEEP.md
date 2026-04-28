# Vendor-Mismatch Sweep

- Generated: `2026-04-28T23:38:12.738165+00:00`
- Scope: AP_Invoice (signed: 1a)
- Heuristic: live tier1_batch_runner._vendor_match_likely (signed: 2a, two-axis)
- Mode: **read-only**, no Mongo writes, no BC calls.

## Totals

| metric | count |
|---|---|
| AP_Invoice docs scanned | 165 |
| matches (both axes pass) | 1 |
| **mismatches (either axis fails)** | **38** |
| ↳ name-axis failures (extracted vs displayName/profile) | 38 |
| ↳ code-axis failures (extracted vs `vendor_canonical`) | 38 |
| ↳ both axes failed | 38 |
| ↳ `vendor_canonical` lacks meaningful tokens (e.g. bare numbers) | 0 |
| skipped — no extracted vendor name | 0 |
| skipped — no `vendor_canonical` code | 126 |
| already posted to BC | 0 |
| distinct mismatch (extracted → canonical) pairs | 4 |

## Mismatch class breakdown (doc counts)

| class | docs | meaning |
|---|---|---|
| `alias_driven` | 36 | Traceable to a `vendor_aliases` row — alias_retire / alias_edit |
| `profile_driven` | 0 | Traceable to a `vendor_invoice_profiles` row — profile_correction |
| `doc_prestamp_or_fallback` | 2 | Not traceable to alias/profile — extraction-time pre-stamp or fallback bug |
| `unresolved_or_ambiguous` | 0 | `vendor_canonical` is non-meaningful (bare digits, empty tokens) — manual review |

## Top 4 mismatch pairs

### 1. `NonExistent Vendor XYZ Corp` → `Ardagh - ST` (`ARDAGHM`)

- Affected docs: **19**  ·  class: **`alias_driven`**  ·  axis fail: `{'name': 19, 'code': 19}`
- Sample doc IDs: `b50564b8-9058-433d-bcb6-5b0f105bacb1`, `4a500d76-4864-4e9c-98dd-ee1c64d936a0`, `0160e45c-19e2-44a3-a656-7048f19e9b77`, `78532208-8466-4e93-967e-748d0c947e81`, `e5866bdb-0985-426f-8de6-fe6842a63a26`
- Implicated rule (alias):
  - `alias_id`: `8851566e-48c3-4085-a858-35013f9c6bdf`
  - `alias_string`: `NonExistent Vendor XYZ Corp`
  - `vendor_no`: `ARDAGHM`  ·  `vendor_name`: `Ardagh - FT`
  - `source`: `auto_gap_closer`  ·  `correction_count`: `0`
  - `learned_at`: `2026-04-23T01:18:04.606381+00:00`
- **Recommended remediation: `alias_retire`**

### 2. `Test Vendor Selection Corp` → `Ardagh - ST` (`ARDAGHM`)

- Affected docs: **17**  ·  class: **`alias_driven`**  ·  axis fail: `{'name': 17, 'code': 17}`
- Sample doc IDs: `67dc3827-ce17-484b-ba8b-866fe8eed29d`, `c78c5e7b-7a1c-4dc1-ae56-41b0411c1c18`, `dfc707d6-af0c-415c-a175-047498aaf347`, `293578b2-a44e-406b-8b57-21d26bb4cb35`, `e1ff165d-8b02-41cd-92d4-0880ec56fc37`
- Implicated rule (alias):
  - `alias_id`: `c4166eb7-e913-40a8-a351-c8b3e982a928`
  - `alias_string`: `Test Vendor Selection Corp`
  - `vendor_no`: `ARDAGHM`  ·  `vendor_name`: `Ardagh - FT`
  - `source`: `auto_gap_closer`  ·  `correction_count`: `0`
  - `learned_at`: `2026-04-23T01:19:48.407049+00:00`
- **Recommended remediation: `alias_retire`**

### 3. `NonExistent Vendor XYZ Corp` → `Ardagh - FT` (`Ardagh - FT`)

- Affected docs: **1**  ·  class: **`doc_prestamp_or_fallback`**  ·  axis fail: `{'name': 1, 'code': 1}`
- Sample doc IDs: `b2593ffe-13a0-4557-938b-8d5f0a4969e6`
- Implicated rule: **not traceable** via aliases or profiles (may be a doc-level pre-stamp or extraction-time mapping)
- **Recommended remediation: `doc_re_resolve`**

### 4. `Test Vendor Selection Corp` → `Ardagh - FT` (`Ardagh - FT`)

- Affected docs: **1**  ·  class: **`doc_prestamp_or_fallback`**  ·  axis fail: `{'name': 1, 'code': 1}`
- Sample doc IDs: `b41d162a-d064-44ac-b70d-0ab3cc1f38a2`
- Implicated rule: **not traceable** via aliases or profiles (may be a doc-level pre-stamp or extraction-time mapping)
- **Recommended remediation: `doc_re_resolve`**

## Remediation legend

- `alias_retire` — delete or deactivate the bad `vendor_aliases` row.
- `alias_edit` — keep the alias but redirect `vendor_no` to the correct vendor (used when the alias has been corrected ≥5 times — high signal).
- `profile_correction` — remove the bad name variant from `vendor_invoice_profiles.vendor_name_variants`, or correct `vendor_name`.
- `doc_re_resolve` — no traceable rule; re-run vendor resolution on the doc with current alias/profile state.
- `manual_review` — escalate to a human; signal too ambiguous to auto-fix.

## Batch 2 impact

- Candidates the tier1 selector currently picks: **7**
- At risk (mismatch detected): **0**
- Safe (no mismatch): **7**

### Safe candidates

| doc_id | extracted vendor | resolved vendor_no |
|---|---|---|
| `93dada81-b21e-4d82-af1b-43efa02e7eef` | ANCHOR GLASS CONTAINER CORP | `ANCH` |
| `4f2f127e-4e17-403a-9f3f-50035279a67e` | Unknown Vendor ABC | `None` |
| `0ef00f27-2863-4de7-91bf-ca7aee33737f` | Test Vendor Corp, Inc. | `None` |
| `72b58d21-db4f-4771-b294-0d471f0af257` | Test Vendor Corp, Inc. | `None` |
| `8a7f4745-13ba-4935-9c88-8400fb8fb052` | Test Vendor Corp, Inc. | `None` |
| `9f529ffd-225f-4de5-9dbe-37af86b69db9` | Test Vendor Corp, Inc. | `None` |
| `18ff282a-8993-433e-9a78-03ae60e0c161` | Test Vendor Corp, Inc. | `None` |

**Recommendation:** no_action — none of the current Batch-2 candidates appear in the mismatch set.
