# Phase 3.2 — Real DocuSign Webhook Validation Runbook

> **Goal:** Send 1+ real / sandbox DocuSign envelopes through the production
> webhook and verify the Contract Intelligence pipeline behaves correctly
> end-to-end. Adjust assumptions (pricing-tab convention, party shape, etc.)
> based on findings. **No code changes during this phase unless a finding
> warrants one** — collect findings first, then we scope adjustments.
>
> **Read-only on production data.** No BC writes. No DocuSign writes.

---

## Step 0 — Pre-flight (preview environment, no production touch)

Before anything goes near production, **dry-run the normalizer** against a
captured DocuSign sample payload. Lets you catch field-shape issues without
firing a real envelope.

1. In DocuSign Admin → Connect → your configuration → **Logs**, copy the JSON
   body of any past message. Or use DocuSign Connect's "Send Test" feature
   and capture the JSON.
2. Save it to a file on the VM, e.g. `/tmp/connect_sample.json`.
3. Dry-run the normalizer (still no DB writes, just parser output):

   ```bash
   docker compose exec backend python -m scripts.contracts_dryrun_normalizer \
       /tmp/connect_sample.json
   ```

4. Inspect the printed sections:
   - `Resolved agreement` → status / title / sender / dates parse correctly?
   - `Parties` → signers and CCs all present? `normalized_org` populated?
     This is the field used for BC matching — bad values here = bad matching.
   - `Terms` → custom fields and `formData` term tabs come through?
   - `Pricing` → **THIS IS THE TAB-CONVENTION CHECK**. If empty when you
     expected lines, your DocuSign template uses a different naming scheme
     than the default `line_N_<attr>`. Fix in env, not code: set
     `CONTRACT_PRICING_TAB_REGEX` to a 2-capture-group regex matching your
     templates, redeploy, dry-run again.
   - `Warnings` → anything here is a parser flag worth investigating.

**If dry-run looks good → proceed. If not → file findings and stop.**

---

## Step 1 — Deploy current Contract Intelligence work

On the production VM:

```bash
cd /opt/gpi-hub
git pull
docker compose build --no-cache backend
docker compose up -d
```

Verify health:

```bash
curl -s http://localhost:8080/api/health -o /dev/null -w "%{http_code}\n"
# expect 200

curl -s http://localhost:8080/api/contracts/health | python3 -m json.tool
# expect docusign.webhook_ready=false at this point (HMAC not set yet)
```

---

## Step 2 — Set the HMAC secret

Generate a strong random secret:

```bash
openssl rand -hex 32
```

Add to the production backend env (in `docker-compose.yml` env block, OR
your env file pattern):

```env
DOCUSIGN_HMAC_SECRET=<the_hex_string_from_openssl>
```

Optionally also set `DOCUSIGN_HMAC_SECRET_2=` (blank for now; populate later
when you want to rotate without downtime).

Restart backend, re-check:

```bash
docker compose up -d --force-recreate backend
sleep 5
curl -s http://localhost:8080/api/contracts/health | python3 -m json.tool
# expect docusign.webhook_ready=true and hmac_secret_count=1
```

The webhook will now refuse any unsigned event with HTTP 401 instead of 503.

---

## Step 3 — Configure DocuSign Connect

In DocuSign Admin → Settings → **Connect** → Add Configuration:

- **Type**: JSON SIM (Send Individual Messages)
- **URL**: `https://<your-public-host>/api/docusign/webhook`
- **Trigger events** (recommended starter set):
  - `envelope-sent`
  - `envelope-delivered`
  - `envelope-completed`
  - `envelope-declined`
  - `envelope-voided`
- **Include data** (recommended):
  - Envelope Documents: NO (Phase 1 doesn't fetch docs; turn ON only if
    you want raw bytes archived in `raw_payload`).
  - Recipients: YES
  - Custom Fields: YES
  - Form Data: YES (critical for term + pricing extraction)
- **HMAC Security**:
  - Add a new HMAC key with the same secret as `DOCUSIGN_HMAC_SECRET`.
  - Header name will be `x-docusign-signature-1` automatically.
- Save.

DocuSign will ping the URL once on save with a tiny test event — that's a
good first signal:

```bash
docker compose exec backend python -m scripts.contracts_validation_probe \
    --recent-events 5
```

You should see one row with `hmac_valid=true`, `processed=true|false`.

---

## Step 4 — Fire a real / sandbox envelope

The cleanest test is a *new* sandbox envelope with at least:
- 1 signer (for party matching)
- 1 custom field (`effective_date`, etc.) (for terms)
- 2 form-data tabs in the pricing convention you actually use (`line_1_item`,
  `line_1_qty`, `line_1_price`) — or whatever your final tab convention is.
- 2 documents.

Once sent, watch:

```bash
# Most recent event flow:
docker compose exec backend python -m scripts.contracts_validation_probe --latest

# Or poll:
watch -n 2 'docker compose exec backend python -m scripts.contracts_validation_probe --recent-events 5'
```

When the envelope completes, run a focused inspection:

```bash
docker compose exec backend python -m scripts.contracts_validation_probe \
    --envelope-id <the_envelope_id_from_docusign>
```

---

## Step 5 — Validation checklist

For the envelope above, verify each of the following. Note any FAILs in the
report at the end of this document.

| # | Check | Expected | Where to look |
|---|---|---|---|
| 1 | Raw payload landed in `agreement_events` | 1 row per Connect message; `hmac_valid=true` | probe `Events` section |
| 2 | Idempotent replay | DocuSign retries (wait for one or use Connect "Republish") show `duplicate=True` and only 1 row in DB | probe `Events` section |
| 3 | Agreement upserted | `provider_envelope_id` matches; `status` matches DocuSign's view | probe `Agreement` section |
| 4 | Sender persisted | `sender_name` / `sender_email` populated | probe `Agreement` |
| 5 | Signers + CCs persisted | One row per recipient; `signing_status` reflects DocuSign | probe `Parties` |
| 6 | `normalized_org` populated | Used for BC matching — must NOT be null/blank for org parties | probe `Parties` |
| 7 | Terms extracted from `customFields` | `effective_date` etc. → terms with `source=custom_field` | probe `Terms` |
| 8 | Terms extracted from `formData` | Non-pricing tab values → terms with `source=form_data` | probe `Terms` |
| 9 | Pricing extracted (if applicable) | One row per line; `item_label`, `quantity`, `unit_price` populated | probe `Pricing` |
| 10 | Documents persisted | 1 row per envelope document with `name` and `provider_document_id` | probe `Documents` |
| 11 | BC matching attempted | At least 1 customer link OR an `party_unmatched` exception | probe `BC Links` + `Exceptions` |
| 12 | Audit rows emitted | `agreement_normalized` + 1 per link/exception | probe `Audit` |
| 13 | UI surfaces the agreement | `/contracts` → Agreements tab shows the new row | browser |
| 14 | UI surfaces the exceptions | `/contracts` → Exceptions tab shows opens | browser |
| 15 | Inline mapping works | Click "Map" on an open exception, search by name, confirm a link, verify exception → resolved + audit row | browser |
| 16 | Reject flow works | Open agreement detail, click Reject on an auto_confirmed link, write a note, verify status → rejected + audit row | browser |

---

## Step 6 — File findings

Copy this template and fill in:

```
PHASE 3.2 — VALIDATION REPORT  (date: ____)

Envelope used: ________________
DocuSign account / sandbox: ________________

[CHECKLIST]
1.  PASS / FAIL — note: ________________
2.  PASS / FAIL — note: ________________
... (through 16)

[PAYLOAD ASSUMPTIONS THAT NEED ADJUSTMENT]
- Pricing tab convention:   matches `line_N_<attr>` ?  YES / NO  (if NO, real
                            convention is: __________________________________)
- Party `companyName` field present in payload?  YES / NO
- Custom-field bucket names (`textCustomFields` / `listCustomFields`) match?
- Any DocuSign field NOT yet mapped that would be useful?

[UI FINDINGS]
- Anything that rendered wrong / awkward?
- Any missing data-testid hooks for ops tooling?

[RECOMMENDED PHASE 4 SCOPE]
- e.g., "Install docusign-esign SDK + add envelope-document download" or
        "Add poll-based backfill for envelopes signed before webhook went live"
        or "Index BC items by name for in-UI item search"
```

---

## Quick reference — useful one-liners

```bash
# Latest event flow
docker compose exec backend python -m scripts.contracts_validation_probe --latest

# By envelope
docker compose exec backend python -m scripts.contracts_validation_probe \
    --envelope-id <id>

# Recent N events (good for debugging "did anything land?")
docker compose exec backend python -m scripts.contracts_validation_probe \
    --recent-events 20

# Dry-run normalizer against a captured payload
docker compose exec backend python -m scripts.contracts_dryrun_normalizer \
    /tmp/connect_sample.json

# Health probe (should show webhook_ready=true and hmac_secret_count>=1)
curl -s http://localhost:8080/api/contracts/health | python3 -m json.tool

# Send a fake unsigned event — should reject with 401:
curl -s -X POST http://localhost:8080/api/docusign/webhook \
    -H "content-type: application/json" \
    -d '{"event":"test"}' \
    -o /dev/null -w "HTTP %{http_code}\n"

# Send a properly-signed test event (uses the same secret you set):
SECRET="<paste DOCUSIGN_HMAC_SECRET here>"
BODY='{"event":"envelope-completed","eventId":"local-smoke-1","data":{"envelopeId":"local-smoke","envelopeSummary":{"envelopeId":"local-smoke","status":"completed","subject":"Smoke","sender":{"userName":"Tester","email":"tester@example.com"},"recipients":{"signers":[]},"envelopeDocuments":[],"customFields":{"textCustomFields":[]},"formData":[]}}}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$SECRET" -hex | awk '{print $2}')
curl -s -X POST http://localhost:8080/api/docusign/webhook \
    -H "content-type: application/json" \
    -H "x-docusign-signature-1: $SIG" \
    -d "$BODY"
# expect: {"acknowledged":true,"duplicate":false,"event_id":"local-smoke-1"}

# Replay the SAME body — must be idempotent:
curl -s -X POST http://localhost:8080/api/docusign/webhook \
    -H "content-type: application/json" \
    -H "x-docusign-signature-1: $SIG" \
    -d "$BODY"
# expect: {"acknowledged":true,"duplicate":true,"event_id":"local-smoke-1"}
```

---

## What I'm waiting on from you

1. **Outcome of Step 0 (dry-run)**: do all sections look right? Any `Pricing
   (0)` when you expected lines? → If so, paste the form-data tab names you
   actually use and I'll give you the regex.
2. **Outcome of Steps 1-5**: pasted output of `--envelope-id <id>` for one
   real envelope, plus the filled-in checklist from Step 6.
3. **Recommended Phase 4 scope** based on what we learn.

I will NOT make code changes during this phase unless you explicitly ask
for one in response to a finding. Carry-over items remain parked.
