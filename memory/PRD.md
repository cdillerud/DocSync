# GPI Document Hub — Product Requirements

## Original Problem Statement
Enterprise document processing hub for AP/Sales workflows with Dynamics 365 BC integration. AI-powered classification, validation, routing, and continuous learning.

## Core Architecture
- **Frontend**: React + Tailwind + Shadcn/UI
- **Backend**: FastAPI + MongoDB + Background Schedulers
- **Integrations**: Dynamics 365 BC, OpenAI/Gemini (Emergent LLM Key), MS Graph
- **Production**: Docker Compose on Azure VM at http://4.204.41.190:8080/

## What's Been Implemented

### Phases 1-14 — See previous sessions for full history

### Phase 15 — Validation Gap Annihilation Engine (Apr 7, 2026)

**Starting point**: 1,252 validation gaps across 5 categories.
**Ending point**: 73 blocking + 71 advisory = 144 total (94.2% blocking reduction).

#### Changes Made:
1. **Three-pass PO revalidation** — Pass 1: vendor profile learning (po_expected). Pass 2a: unknown vendor resolution (name aliases + email domain). Pass 2b: cache-first PO lookup (19K+ records) + BC API matching + digit-substring matching.
2. **Vendor profile force-refresh** — Always computes cache stats for po_expected (not skipped when BC API returns data). Force-rebuilds profiles before PO revalidation.
3. **Customer match revalidation** — Customer alias map from successful matches, vendor→customer association history, BC cache fuzzy lookup.
4. **Sales order match revalidation** — 7 strategies: exact cache, external doc number, normalized, digits-only, prefix variations, sibling doc, document flow. Searches salesOrders + salesShipments + salesInvoices.
5. **Vendor match revalidation** — Lower threshold (0.70), BC vendor cache fuzzy match, word-overlap matching, top-candidate acceptance.
6. **Smart duplicate clearing** — Checks BC for existing invoice status (Posted/Paid → not real dup), compares amounts, compares POs, cross-validates with other checks.
7. **Gap count accuracy** — Replaced stale validation_gap_log with direct hub_documents queries. Added gap log cleanup step.
8. **Blocking vs advisory split** — Required checks = blocking (red), non-required = advisory (amber). SO match and customer match are advisory.
9. **Unmatched vendor UI** — Monitor dashboard shows all unmatched vendor names with top 3 BC vendor candidates (fuzzy scored). One-click accept creates alias + auto-resolves all gap docs.
10. **Vendor alias accept endpoint** — POST /api/aliases/vendors/accept-suggestion creates alias and re-validates all matching docs.

#### Results:
| Gap Type | Before | After (Blocking) | After (Advisory) | Reduction |
|---|---|---|---|---|
| PO Validation | 658 | 25 | — | 96% |
| Customer Match | 252 | — | 13 | 95% |
| Duplicate Check | 82 | 6 | — | 93% |
| Vendor Match | 82 | 42 | — | 49% |
| Sales Order Match | 178 | — | 58 | 67% |
| **Total** | **1,252** | **73** | **71** | **94.2%** |

## Learning Dimensions: 21 total
## Active Gap Closers: 11 (was 7)
## Backfill Steps: 11

## Production Stats (Apr 7, 2026)
- 81% AI confidence accuracy, 67% auto-file rate
- 13/23 mature vendors (10 autonomous, 3 stable)
- 73 blocking validation gaps (down from 1,252)

## Upcoming Tasks
- P1: Rep Overrides management UI
- P1: Teams Adaptive Card integration

## Future / Backlog
- P2: Auto-delete on max retries, Vendor Inventory Dashboard, BOM module
- P2: Production-ready email service, Entra ID SSO
- P3: server.py refactor (7,500+ lines), no_bc_match investigation

## Deployment
Docker Compose on Azure VM. "Save to Github" → `git pull && docker compose up -d --build`.
