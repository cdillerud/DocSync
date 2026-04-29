# DocuSign Golden Fixtures (Phase 3.2)

This directory holds **redacted, real-world DocuSign Connect payloads** captured
from production / sandbox envelopes. They are the regression baseline for the
Contract Intelligence normalizer + matcher.

## Why golden fixtures

Synthetic test payloads (already covered in `test_contracts_normalizer.py`)
verify the parser against *our assumptions* about the DocuSign Connect SIM
shape. Golden fixtures verify the parser against the **actual shape your
DocuSign account emits** — which can drift over time as DocuSign changes
their API or as your templates evolve.

If a future DocuSign API change breaks our parser, the golden fixture test
will fail in CI on the very next run, not three weeks later when an analyst
notices `agreement_count` flatlined.

## Conventions

* One JSON file per envelope. Filename: `<short_descriptor>__<envelope_status>.json`
  (e.g. `acme_msa__completed.json`, `vendor_nda__voided.json`).
* Each file is the **raw Connect SIM body** (the JSON DocuSign POSTs to the
  webhook) — minus the redactions described below.
* Files are loaded automatically by `tests/test_contracts_golden_fixtures.py`.

## Redaction contract

The golden fixture **must preserve** the parser-relevant shape:

| Preserve | Reason |
|---|---|
| Envelope structure (top-level keys) | parser navigates these |
| `data.envelopeSummary.status` | drives status mapping |
| `data.envelopeSummary.recipients.{signers,carbonCopies,…}` arrays + recipient ids | drives party extraction |
| `customFields.{textCustomFields,listCustomFields}[].name` | drives term extraction |
| `formData[].name` | drives term + pricing extraction |
| Tab/field naming convention | this is what we're regression-testing |
| Date / number / currency / status enum values | drives parsing logic |
| `envelopeDocuments[].name` (mime / page / size) | drives document extraction |

The fixture **must redact** any PII, and any data that could leak company
strategy:

| Redact | Replace with |
|---|---|
| Recipient `name` | `Redacted Name 1`, `Redacted Name 2`, … (deterministic by index) |
| Recipient `email` | `redacted+1@example.com`, `redacted+2@example.com`, … |
| Recipient `companyName` | `Redacted Co 1`, `Redacted Co 2`, … |
| Sender `userName` / `email` / `companyName` | same scheme |
| Custom-field / form-data **values** that contain customer-specific terms (price, MSA dollar amounts, etc.) | replace value, but keep the **field name** intact |
| Any `accountId` / `userId` / `apiVersion` URIs / signing tokens | replace with `redacted-xxx` |
| Document content (if you turned on "Include Documents" in Connect) | drop the `documentBase64` / `pdfBytes` field entirely; keep the metadata |

The `contracts_redact_payload.py` helper (in `backend/scripts/`) handles the
default redaction set automatically. Use `--extra-paths` for any
template-specific values you also want scrubbed.

## How to add a fixture

```bash
# 1. Capture a Connect message (from DocuSign Connect logs, or a captured
#    webhook body in your reverse proxy).
#
# 2. Redact PII:
docker compose exec backend python -m scripts.contracts_redact_payload \
    /tmp/connect_raw.json \
    --extra-paths data.envelopeSummary.subject \
    --extra-paths data.envelopeSummary.emailSubject \
    > /tmp/connect_redacted.json

# 3. Sanity-check by running the dry-run normalizer:
docker compose exec backend python -m scripts.contracts_dryrun_normalizer \
    /tmp/connect_redacted.json

# 4. If output looks correct + redaction is complete, add the file:
cp /tmp/connect_redacted.json \
    /app/backend/tests/fixtures/docusign/<short_descriptor>__<status>.json

# 5. Commit. The auto-discovery harness will pick it up on the next test run.
```

## What's tested per fixture

`tests/test_contracts_golden_fixtures.py` runs these checks for **every**
`.json` file in this directory:

1. **Normalizer accepts the payload** — no `ValueError`, no exception.
2. **Envelope id resolved** — `agreement.provider_envelope_id` is non-empty.
3. **Status mapped to a known value** — i.e. NOT `unknown`.
4. **At least one party** (sender or signer).
5. **Warnings are JSON-serializable** — they cycle through Mongo persistence.
6. **Persisted shape is JSON-serializable** — `model_dump(mode="json")` works
   for the agreement, every party, every term, every pricing row, every
   document.

Add fixture-specific assertions (e.g., "this MSA must produce >= 3 terms")
inline in the test file when you have a fixture that's worth pinning down.

## Why no fixtures committed yet

The first fixture comes from your real DocuSign account during the Phase 3.2
validation pass. Until then, the harness is in place but discovers zero
files and gracefully passes.
