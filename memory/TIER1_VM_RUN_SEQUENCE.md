# Tier 1 — Production VM Run Sequence

**Where this runs:** the VM at `/opt/gpi-hub` (real BC sandbox credentials).
**Where this does NOT run:** the preview environment (placeholder credentials; preflight check #6 will refuse).

**Before you start:** confirm the VM is currently green (legacy login still works at the URL you normally use). All steps below are read-only or sandbox-only. None of them touch production BC.

---

## Step 0 — Pull and rebuild

```bash
cd /opt/gpi-hub
git pull
docker compose build --no-cache backend
docker compose up -d
docker compose logs --tail=20 backend | grep -iE 'startup|ready|error' | head
```

Expected: backend starts cleanly, no new errors vs your last successful boot.

---

## Step 1 — Preflight

```bash
docker compose exec backend python /app/backend/scripts/tier1_batch_runner.py preflight
```

**Expected output:** all 6 checks ✅. Specifically:
- Check 2 (BC sandbox status) shows `write_env=Sandbox_11_3_2025, block_prod=True`
- Check 3 (catalog freshness) PASSES if the catalog has been synced in the last 7 days. **If FAILS, go to Step 2 first, then re-run preflight.**
- Check 6 (credential plausibility) shows `OK — credentials look like real Azure GUIDs`. If this FAILS on the VM, your VM `.env` has the same placeholder values as preview — stop and tell me; do not proceed.

**If any other check fails, stop and bring back the output.**

---

## Step 2 — Catalog refresh (only if Step 1 check #3 fails)

```bash
docker compose exec backend curl -sX POST \
  "http://localhost:8001/api/gpi-integration/catalog/sync?entity=all" \
  --max-time 180 | head -c 2000
```

**Expected:** JSON body with sync result (items + GL accounts counts), no Microsoft auth error.
**If you get `AADSTS900023`:** your VM's `BC_TENANT_ID`/`BC_CLIENT_ID` are not valid; stop and bring back the error.

Then re-run **Step 1** and confirm check #3 is now ✅.

---

## Step 3 — Candidate selection (read-only)

```bash
docker compose exec backend python /app/backend/scripts/tier1_batch_runner.py select
```

**Expected output:** a table of up to 10 candidate AP_Invoice docs with `doc_id`, vendor, invoice number, total, line count, status. **If fewer than 10 are returned, that's a finding — bring it back.**

---

## Step 4 — Dry-run (read-only — vendor re-resolve, dup check, line completeness, risks)

```bash
docker compose exec backend python /app/backend/scripts/tier1_batch_runner.py dry-run
```

This re-runs preflight + selection + the per-candidate normalization pass.

**Expected output per candidate (the format the user requested):**
```
[N] doc_id=<uuid>
    vendor:       <name>  (<vendor_no or 'unresolved'>)
    invoice_no:   <number>
    total:        <amount>
    duplicate:    clean | HIT — <detail> | skip
    risks:        <up to 2 risk notes>
```

**Bring this output back to me unedited.** I review the candidate list and risk notes before any POST is approved.

---

## Step 5 — Wait for my review

Do **NOT** run `post --confirm` until I've reviewed the dry-run output and explicitly approved the batch.

When approved, the post step runs:

```bash
docker compose exec backend python /app/backend/scripts/tier1_batch_runner.py post --confirm
```

This will:
- Re-run preflight + selection + dry-run
- Refuse if any candidate has no resolvable vendor (hard guard)
- Sequentially POST to BC sandbox, ~2s pause between docs, 60s/doc timeout
- Append every result to `/app/memory/TIER1_BATCH_RESULTS.md`
- **Stop on first F-BUG**
- **Stop on 2 consecutive identical malformed response shapes** (repeatable-malformed guard)
- Print the bucket summary at the end

---

## Step 6 — Report

After the post run, this rolls up the worksheet:

```bash
docker compose exec backend python /app/backend/scripts/tier1_post_batch_report.py
```

Bring back the output. I read it and recommend the highest-priority fix for batch-2 (or declare Tier 1 viable if ≥7/10 P1+P2 with zero F-BUG).

---

## Standing guardrails (won't change without a new signoff)

- ❌ Will not lift `hub_settings.type=shadow_mode`
- ❌ Will not flip `PILOT_MODE_ENABLED`
- ❌ Will not modify any `BC_*` env var
- ❌ Will not modify any auto-post setting
- ❌ Will not bypass the credential plausibility guard
- ❌ Will not run more than 10 documents per batch
- ❌ Will not write to production BC (env guard refuses)
- ❌ Will not start sales / outbound delivery / search / auth / Phase 3

If anything in Steps 1–4 surprises you (different output, errors not listed here), stop and bring back what you saw. Don't push past warnings.
