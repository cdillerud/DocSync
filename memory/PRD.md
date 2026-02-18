# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Current Status: PHASE 7 - OBSERVATION MODE + Week 1 Hardening

**Shadow Mode Started:** February 18, 2026  
**Email Polling:** Implemented (disabled by default)  
**Feature Freeze:** 14 days (until ~Mar 4, 2026)

---

## What's Been Implemented

### Phase 1-6 ✅ Complete

### Phase 7 - Observation Mode 🔄 ACTIVE

#### Phase 7 C1: Email Polling (Observation Infrastructure) ✅
Minimal, reversible, shadow-only email polling for data collection.

**NOT a product feature** — this is observation instrumentation plumbing.

**Implementation:**
- Feature flag: `EMAIL_POLLING_ENABLED` (default: OFF)
- Poll interval: `EMAIL_POLLING_INTERVAL_MINUTES` (default: 5)
- Target mailbox: `EMAIL_POLLING_USER` (e.g., ap@gamerpackaging.com)
- Lookback window: `EMAIL_POLLING_LOOKBACK_MINUTES` (default: 60)
- Safety limits: 25 messages/run, 25MB max attachment

**Process Flow:**
```
Poll → Fetch Attachments → Check Idempotency → Save to SharePoint → 
Process via Intake → Mark Message (Category) → Log Result
```

**Collections Added:**
- `mail_intake_log` - Per-attachment idempotency tracking
- `mail_poll_runs` - Per-run statistics

**What Phase C1 Does:**
- ✅ Polls for unread messages with attachments
- ✅ Skips inline images and signatures
- ✅ Checks for duplicate processing (idempotency)
- ✅ Stores in SharePoint first (durability)
- ✅ Processes through existing intake pipeline
- ✅ Marks messages with category "HubShadowProcessed"
- ✅ Logs all results for observability

**What Phase C1 Does NOT Do:**
- ❌ Move messages between folders
- ❌ Delete messages
- ❌ Create BC drafts (controlled by separate flag)
- ❌ Any BC writes

**New Endpoints:**
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/email-polling/status` | GET | Config + last 24h stats |
| `/api/email-polling/trigger` | POST | Manual poll run (testing) |
| `/api/email-polling/logs` | GET | Mail intake logs |

**Rollback:** Set `EMAIL_POLLING_ENABLED=false`. No data loss, no operational impact.

---

#### Phase 7 Week 1: Hardening (Observability) ✅ IMPLEMENTED 2026-02-18

**Purpose:** Tighten signal quality and observability before Phase 8 enablement.

**1️⃣ Missing Fields Drilldown Endpoint**
- Endpoint: `GET /api/metrics/extraction-misses`
- Parameters: `field` (vendor/invoice_number/amount), `days`, `limit`
- Returns: document_id, file_name, vendor_extracted, invoice_number_extracted, amount_extracted, which_required_fields_missing, ai_confidence, first_500_chars_text
- Purpose: Identify WHY extraction is failing for specific documents

**2️⃣ Canonical Normalization at Ingestion**
- New `canonical_fields` object stored on every document at ingestion time
- Fields stored:
  - `vendor_normalized` (lowercase, trimmed)
  - `invoice_number_clean` (whitespace stripped, uppercase)
  - `amount_float` (parsed to float)
  - `due_date_iso` (ISO 8601 format)
  - `invoice_date_iso` (ISO 8601 format)
  - `po_number_clean` (whitespace stripped, uppercase)
- Raw values preserved alongside normalized for audit trail
- Applied to both `intake_document` and `_internal_intake_document` paths

**3️⃣ Stable Vendor Metric**
- Endpoint: `GET /api/metrics/stable-vendors`
- Parameters: `min_count` (default 5), `min_completeness` (0.85), `max_variants` (3), `days`
- Criteria:
  - count >= min_count
  - required field completeness >= min_completeness (85%)
  - alias variance <= max_variants
  - no conflicting invoice numbers
- Purpose: Identify candidates for Phase 8 controlled enablement
- **Does NOT enable anything** - metric only

**4️⃣ Draft Candidate Flag (Non-Operational)**
- Computed at ingestion time for every document
- Stored fields: `draft_candidate` (bool), `draft_candidate_score` (0-100), `draft_candidate_reason` (array)
- Criteria for `draft_candidate = True`:
  - document_type == AP_Invoice
  - vendor present
  - invoice_number present
  - amount present
  - ai_confidence >= 0.92
- **Does NOT create drafts or change status**
- Endpoint: `GET /api/metrics/draft-candidates`
- Dashboard can now show:
  - ReadyForDraftCandidate: X%
  - ReadyToLink: Y%
  - NeedsHumanReview: Z%

**What Phase 7 Week 1 Does NOT Touch:**
- ❌ Match score thresholds
- ❌ CREATE_DRAFT_HEADER enablement
- ❌ Vendor overrides
- ❌ Readiness weights
- ❌ AI prompts
- ❌ Document types

---

## Locked Readiness Formula (Phase 7)

| Factor | Weight | Target | Gate Criteria |
|--------|--------|--------|---------------|
| High Confidence Docs (≥0.92) | 35 pts | ≥60% | `high_confidence_pct >= 60` |
| Alias Exception Rate | 20 pts | <5% | `alias_exception_rate < 5` |
| Stable Vendors | 25 pts | ≥3 | `stable_vendors >= 3` |
| Data Volume | 20 pts | ≥100 | `total_docs >= 100` |

**Enablement Threshold:** ≥80 pts AND all 4 gates passed

---

## Enterprise Maturity Ladder

| Phase | Status | Description |
|-------|--------|-------------|
| 3 | ✅ | Deterministic matching |
| 4 | ✅ | Safe draft gating |
| 5 | ✅ | Executive ROI visibility |
| 6 | ✅ | Production instrumentation |
| 7 | 🔄 | **Observed stability + C1 Email Polling + Week 1 Hardening** (CURRENT) |
| 8 | ⏳ | Controlled automation |
| 9 | ⏳ | Vendor-level tuning |
| 10 | ⏳ | Zetadocs retirement |

---

## Phase C Rollout Plan

| Phase | Status | Description |
|-------|--------|-------------|
| C1 | ✅ | Poll + ingest + log + metrics (category tagging only) |
| C2 | ⏳ | Add folder move after success (HubShadow folder) |
| C3 | ⏳ | Production mode (HubProcessed folder, draft enablement) |

---

## Next Steps

1. **Deploy Phase 7 Week 1 changes to VM** via git pull + deploy.sh
2. **Run backfill** to test canonical normalization with real data
3. **Monitor `/api/metrics/stable-vendors`** for Phase 8 candidates
4. **Review `/api/metrics/draft-candidates`** for readiness rates
5. **When readiness_score ≥ 80** → Phase 8: Controlled Vendor Enablement

---

## API Endpoints Summary (Phase 7 Week 1)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/metrics/extraction-quality` | GET | Overall extraction quality + draft candidate rate |
| `/api/metrics/extraction-misses` | GET | Missing field drilldown |
| `/api/metrics/stable-vendors` | GET | Stable vendor candidates for Phase 8 |
| `/api/metrics/draft-candidates` | GET | Draft candidate distribution |

---

## Testing Results (Latest)
- Phase C1: 42/42 tests passed
- Phase 7 Week 1: All 4 endpoints functional
- All previous phases: Fully functional
