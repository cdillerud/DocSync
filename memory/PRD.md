# GPI Document Hub - PRD

## Original Problem Statement
Build a "GPI Document Hub" test platform that replaces Zetadocs-style document linking in Microsoft Dynamics 365 Business Central by using SharePoint Online as the document repository and a middleware hub to orchestrate ingestion, metadata, approvals, and attachment linking back to BC.

## Current Status: PHASE 7 - OBSERVATION MODE + C1

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
| 7 | 🔄 | **Observed stability + C1 Email Polling** (CURRENT) |
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

1. **Configure EMAIL_POLLING_USER** in .env
2. **Set EMAIL_POLLING_ENABLED=true** when ready to start data collection
3. **Monitor /api/email-polling/status** for intake health
4. **Continue Phase 7 observation** (14 days)
5. **When readiness_score ≥ 80** → Phase 8: Controlled Vendor Enablement

---

## Testing Results (Latest)
- Phase C1: 42/42 tests passed
- All previous phases: Fully functional
