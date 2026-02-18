# GPI Document Hub - Shadow Mode Memo

**Date:** February 18, 2026  
**Status:** SHADOW MODE ACTIVE  
**Duration:** 0 days (just started)

---

## Summary

Shadow Mode is live. No operational changes. Metrics collection only.

The GPI Document Hub has been deployed to production with all automation features **disabled**. The system is now collecting real-world data to validate readiness for controlled draft creation.

---

## Current Configuration

| Feature Flag | Status |
|-------------|--------|
| CREATE_DRAFT_HEADER | OFF |
| DEMO_MODE | OFF |

---

## What's Running

- ✅ Document intake and classification
- ✅ Vendor matching (exact, normalized, alias, fuzzy)
- ✅ SharePoint storage
- ✅ Metrics collection
- ✅ Alias engine (learning from manual resolutions)
- ✅ ROI Dashboard
- ❌ Draft creation (disabled)

---

## Readiness Gates (Locked Formula)

All 4 gates must pass for enablement:

| Factor | Weight | Target | Current | Gate |
|--------|--------|--------|---------|------|
| High Confidence Docs (≥0.92) | 35 pts | ≥60% | 0% | ✗ |
| Alias Exception Rate | 20 pts | <5% | 0% | ✓ |
| Stable Vendors (≥0.94 avg) | 25 pts | ≥3 | 0 | ✗ |
| Data Volume | 20 pts | ≥100 docs | 6 | ✗ |

**Current Score:** 20.6 / 100  
**Gates Passed:** 1 / 4

---

## Observation Checkpoints

- [ ] Week 1 Review: Feb 25, 2026
- [ ] Week 2 Review: Mar 4, 2026
- [ ] Week 3 Review (if needed): Mar 11, 2026

---

## What We're Monitoring

1. **Match Score Distribution**
   - Want: 80%+ above 0.92 threshold
   - Current: 0% (need more data)

2. **Alias Exception Rate**
   - Want: <5%
   - Current: 0% (no alias matches yet)

3. **Vendor Stability**
   - Want: ≥3 vendors consistently ≥0.94
   - Current: 0 stable vendors

4. **Data Volume**
   - Want: ≥100 documents
   - Current: 6 documents

---

## Phase 8 Trigger Conditions

When ALL gates pass (score ≥80 + 4/4 gates):

1. Enable CREATE_DRAFT_HEADER
2. Restrict to 3 known stable vendors only
3. Match methods: exact_no, exact_name, normalized (exclude alias initially)
4. Monitor draft modification rate (<10% target)

---

## Notes

- 3 vendor aliases pre-loaded
- Top friction vendor: Acme Supplies Inc. (2 exceptions)
- No bugs or issues observed
- Backend refactoring deferred until after Phase 8

---

## Contact

For questions about Shadow Mode status, check:
- ROI Dashboard → Shadow Mode Status card
- API: GET /api/reports/shadow-mode-performance
