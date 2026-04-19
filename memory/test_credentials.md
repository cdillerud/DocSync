# Test Credentials

## Login
- Username: `admin`
- Password: `admin`

## Demo Data
- Run `POST /api/sales-dashboard/demo/run-batch` to seed batch demo docs and dunnage patterns
- Use batch-child docs with C-9874 items (e.g., `batch-child-*`) to test dunnage suggestions
- Giovanni customer: C-10250
- Rep Overrides demo fixture: `C-DEMO-OVRD-1` / "Acme Demo Co." → Demo Rep (`demo.rep@example.com`, salesperson_code `DEMO01`). Persisted in `customer_rep_overrides` so `/admin/rep-overrides` always has one visible row. Do NOT delete permanently.
- Prior-week digest fixture: `2026-W15` row in `learning_digests`. Persisted so the `/learning/ops` Week-over-Week banner always has data to compare against. Do NOT delete.


## Intake Learning (new — hub-wide Giovanni pattern)
- `POST /api/intake/learning/backfill` — run learning across all eligible docs + staging
- `POST /api/intake/learning/refresh-active?lookback_hours=24` — re-learn for customers with new BC activity
- `GET /api/intake/learning/summary` — dashboard metrics
- `GET /api/intake/flagged` — docs with actionable BC/Spiro findings
- `GET /api/intake/insights/{doc_id}` — per-doc intake insights
- `GET /api/intake/insights-xls/{staging_id}` — per-XLS-staging insights
- UI: `/intake/learning`
- Daily scheduler refreshes active customers automatically (interval: 24h, configurable via `INTAKE_LEARNING_INTERVAL_SECONDS`)
