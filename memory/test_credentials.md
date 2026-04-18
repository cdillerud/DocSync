# Test Credentials

## Login
- Username: `admin`
- Password: `admin`

## Demo Data
- Run `POST /api/sales-dashboard/demo/run-batch` to seed batch demo docs and dunnage patterns
- Use batch-child docs with C-9874 items (e.g., `batch-child-*`) to test dunnage suggestions
- Giovanni customer: C-10250

## Intake Learning (new — hub-wide Giovanni pattern)
- `POST /api/intake/learning/backfill` — run learning across all eligible docs + staging
- `GET /api/intake/learning/summary` — dashboard metrics
- `GET /api/intake/flagged` — docs with actionable BC/Spiro findings
- `GET /api/intake/insights/{doc_id}` — per-doc intake insights
- `GET /api/intake/insights-xls/{staging_id}` — per-XLS-staging insights
- UI: `/intake/learning`
