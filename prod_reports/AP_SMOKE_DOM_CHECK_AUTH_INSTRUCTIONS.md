# AP Smoke DOM Check — Authentication Instructions

> **INTERNAL — IT / Engineering only.** Read-only browser pass.
> No backend changes, no Mongo writes, no Save/Mark Ready/Post,
> no matcher/classifier/routing changes.

The automated AP UI smoke checker (`backend/scripts/ap_smoke_walk_dom_check.py`)
opens each P0/P1 document in Playwright Chromium and asserts that the
AP Review panel renders cleanly (no raw JSON warnings, no snake_case
blocker codes, all 5 AP fields visible). The only blocker for running
it against a Hub deployment that requires login is **session
authentication** — the headless browser context starts logged out.

This page documents the supported, client-side-only auth path:
**Capture login state once on a workstation with a real browser, then
feed the resulting JSON file to the DOM checker via
`--storage-state-path`.** No backend bypass. No credentials in scripts.
No SCP required (the DOM check can run from the same machine that
captured state).

---

## TL;DR

```bash
# (one-time, on your laptop)
pip install playwright
python -m playwright install chromium

# 1. Capture login state (opens a real browser; sign in normally)
python tools/capture_hub_storage_state.py \
  --hub-origin http://4.204.41.190:8080 \
  --out hub_storage_state.json

# 2. Run the DOM checker against the smoke set with that state
python tools/run_ap_smoke_dom_check_local.py \
  --hub-origin http://4.204.41.190:8080 \
  --storage-state-path hub_storage_state.json
```

That's it. Outputs land under `prod_reports/`:
- `AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv`
- `AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md`
- `ap_smoke_walk_screens/*.png`

---

## Step 1 — Install Playwright on your workstation

You need a machine with a visible desktop (Windows / macOS / Linux with
GUI). The VM container can't capture login state because it has no
display.

```bash
pip install playwright
python -m playwright install chromium
```

If your laptop already has Chrome and you just need Playwright Python,
the second command downloads the bundled Chromium it controls — leave
your normal browser alone.

---

## Step 2 — Capture login state

```bash
python tools/capture_hub_storage_state.py \
  --hub-origin http://4.204.41.190:8080 \
  --out hub_storage_state.json
```

What happens:

1. A Chromium window opens at the given Hub origin.
2. You sign in **the same way you normally do** (SSO, username/password,
   MFA — whatever the Hub uses).
3. As soon as the page no longer shows a `<input type="password">`, the
   helper exports the authenticated session (cookies + localStorage) to
   `hub_storage_state.json`.
4. The terminal prints the next command to run.

Defaults you may want to override:

- `--hub-origin` — defaults to `http://4.204.41.190:8080`.
- `--out` — JSON file to write. Default `hub_storage_state.json` in CWD.
- `--login-timeout-s` — how long the helper will wait for you to finish
  signing in. Default 300s.

The helper is strictly read-only: it does not click anything, does not
post anything, does not touch Mongo. It only navigates to the origin
and waits for you.

---

## Step 3 — Run the DOM checker locally

The bundled local runner is the easiest way to avoid SCP'ing the JSON
to the VM:

```bash
python tools/run_ap_smoke_dom_check_local.py \
  --hub-origin http://4.204.41.190:8080 \
  --storage-state-path hub_storage_state.json
```

Equivalent direct invocation if you prefer the underlying script:

```bash
python backend/scripts/ap_smoke_walk_dom_check.py \
  --hub-origin http://4.204.41.190:8080 \
  --priorities P0,P1 \
  --input-csv prod_reports/AP_INTERNAL_SMOKE_TEST_DOCUMENT_SET.csv \
  --out-csv prod_reports/AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv \
  --out-summary-md prod_reports/AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md \
  --screenshot-dir prod_reports/ap_smoke_walk_screens \
  --storage-state-path hub_storage_state.json
```

### Should I run this on the VM or locally?

Run it **locally** (same workstation that captured login state). That's
the whole point of the storage-state file — it lets you keep the
authenticated browser session alongside the test runner without
copying credentials anywhere.

The VM path still works if you really want it (`scp hub_storage_state.json
azureuser@…:/opt/gpi-hub/`) and then run the same command inside the
backend container with the appropriate path. But it is **not required.**

---

## Expected outputs

After a successful run:

- `AP_SMOKE_WALK_DOM_CHECK_RESULTS.csv` — one row per checked document.
  Columns include `overall_pass`, `ap_review_panel_present`,
  `raw_json_warning_visible`, `raw_snake_case_blocker_visible`, plus
  per-field visibility for vendor / invoice number / invoice date /
  total amount / PO number.
- `AP_SMOKE_WALK_DOM_CHECK_SUMMARY.md` — human-readable pass/fail
  breakdown, including a "Failures" section that lists every reason a
  doc failed.
- `ap_smoke_walk_screens/*.png` — full-page screenshots, one per doc,
  named by `hub_doc_id`.

Process exit codes:

- `0` — every doc passed.
- `2` — input file or storage state missing / invalid.
- `3` — priority filter matched zero rows.
- `4` — at least one doc failed structural checks. Inspect the summary.

---

## How to tell if login failed

If the storage state has expired or you skipped Step 2, every doc will
fail with the new explicit error:

```
login_redirect_detected; Hub UI is gated behind a login form. Pass
--storage-state-path with a JSON exported by
tools/capture_hub_storage_state.py so the Playwright context is already
authenticated. The script does NOT fall back to manual testing.
```

When that happens, re-run Step 2 to refresh `hub_storage_state.json`.
Sessions usually outlive a single UAT run, but very long-lived auth
cookies are cookie/IDP-dependent — re-capture if you see the message.

---

## What this does **not** do

- Does **not** add any backend authentication code paths.
- Does **not** persist anything in Mongo.
- Does **not** click Save / Mark Ready / Post / Re-process / Approve.
- Does **not** trigger any matcher, classifier, routing, or DocuSign
  flow.
- Does **not** require AP team involvement — this is internal IT/eng
  validation only, run before AP UAT engagement.

If the automated checker can't run (e.g., Playwright still won't
launch despite OS deps), the manual fallback is still
`prod_reports/AP_SMOKE_WALK_PACKET.html`. But because the automated
checker is now the supported smoke-test path, prefer it.
