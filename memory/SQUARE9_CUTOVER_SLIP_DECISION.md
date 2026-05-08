# Square9 Cutover — Slip Decision Memo

**To:** CFO, AP Director
**From:** GPI Hub engineering
**Status:** Decision required
**Recommendation:** Read sections 5 and 6 first.

---

## 1. Executive summary

- **Today's audited Hub-vs-Square9 AP match rate is 45.45%.**
- **The defensible ceiling we can reach using only read-only audit work is 56.07%** (after excluding non-AP Square9 docs and recovering matcher misses with strong Hub evidence).
- **The 85% cutover gate is not achievable by Friday through audit-only changes.** The remaining 28.93-percentage-point gap is concentrated in 105 ambiguous documents that require either manual triage or matcher engineering, neither of which fits in this week.

---

## 2. What we know with high confidence

All figures below are pulled directly from read-only artifacts already on the production VM.

**Parity baseline** *(prod_reports/cutover_proof_\<latest\>/summary.json)*

| metric | value |
|---|---:|
| Square9 AP corpus in window (`square_count`) | 253 |
| Hub-Square9 matched | 115 |
| Square9-only (`no_match`) | 138 |
| Hub-only | 307 |
| `match_rate_pct` | 45.45% |

**Square9 `no_match` classification** *(prod_reports/no_match_square9_audit.json)*

Of the 138 Square9-only documents:

| classification | count | % | recommended action |
|---|---:|---:|---|
| Non-AP (treasury / wires / templates / reconciliation) | 14 | 10.1% | exclude from Square9 scope |
| Pre-Hub corpus (before 2024-01-01) | 0 | 0.0% | — |
| Matcher miss with Hub candidate | 19 | 13.8% | improve matcher |
| Vendor not in Hub intake | 0 | 0.0% | — |
| Uncertain | 105 | 76.1% | manual review |

Projected match rate by remediation strategy:

| scenario | match rate |
|---|---:|
| baseline | 45.45% |
| after exclude only | 48.12% |
| after improve only | 52.96% |
| **after both (audit ceiling)** | **56.07%** |

**Hub-only classification** *(prod_reports/hub_only_audit.json)*

| metric | value |
|---|---:|
| Total Hub documents with no Square9 counterpart | 307 |
| `billing@tumalocreek.us` (single sender) | 193 (62.9%) |

**Tumalocreek diagnostic** *(prod_reports/matcher_miss_vendor_diagnostic.json)*

- 193 Hub docs from `billing@tumalocreek.us` were tested against the Square9 corpus.
- Exactly **1** Square9 document mentions tumalocreek anywhere in its name, parent path, or web URL.
- 0 of 193 Hub docs found a strong Square9 candidate.
- **Conclusion:** Square9 does not hold this vendor's invoices. Hub does AP work for tumalocreek that Square9 has never seen. This is a real gap in Square9's coverage, not a matcher bug.

---

## 3. What the 105 uncertain documents mean

These are 105 Square9 documents that:

- look like they should be AP invoices (folder, naming, modified date),
- have a vendor that Hub knows about,
- but **cannot be confidently matched to a specific Hub document** using the headers we currently capture (vendor name, invoice number, file name, amount).

In plain language: Square9 has these on file. Hub may also have them, but we cannot prove it from the index alone.

Plausible reasons (not yet investigated):

- **Different file granularity.** Hub may store one document per invoice; Square9 may store separate files for invoice + remittance + supporting attachments. This makes a 1-to-1 match impossible without splitting or grouping rules.
- **Different intake lanes.** Some Square9 documents may have been uploaded by AP staff manually into Square9 directly, never reaching Hub's email-driven intake.
- **Matcher needs richer evidence.** The current matcher uses headers only. Resolving the 105 uncertain probably requires comparing on PO number, amount extracted from the PDF body, or OCR'd invoice text.

**Manual triage cost estimate:** 105 documents × 5 minutes per document = roughly 9 hours of AP staff time **just to categorize them**. Remediating whatever is found would take additional time on top.

---

## 4. Options

### Option A — Slip cutover by 2 weeks

- Keep Square9 running in parallel.
- Use the 2 weeks for AP triage of the 105 uncertain plus targeted matcher improvements.
- **Cost:** ~2 weeks of engineering + ~9 hours of AP triage time + 2 more weeks of Square9 license / support fees.
- **Risk:** low. Existing AP posting path is unchanged.
- **Outcome:** likely path to a properly defensible 80–90% match rate before deprecating Square9.

### Option B — Cut over Friday at a renegotiated 60% gate, with safeguards

- Lower the cutover gate from 85% to 60% (current audited reach is 56% with documented work; small additional matcher fixes get us comfortably above 60%).
- Retain Square9 in **read-only mode for 30 days** as a verification fallback.
- Maintain a daily AP fallback-log review during the 30-day window: any AP doc that fails to land in Hub is logged and manually reconciled against Square9.
- **Cost:** Square9 read-only retention + ~1 hour/day of AP review for 30 days.
- **Risk:** medium. Some AP documents Square9 holds will not have a verified Hub counterpart at cutover; the fallback log catches anything that breaks downstream.
- **Outcome:** Friday cutover happens. Square9 deprecation completes ~30 days later when the fallback log is consistently empty.

### Option C — Hard slip 2–4 weeks for matcher overhaul

- Build per-vendor extraction profiles, add OCR / PDF-text comparison to the matcher, fully retest against Square9.
- **Cost:** 2–4 weeks of focused engineering. Square9 stays on for the full duration.
- **Risk:** low to medium. Larger code change than Option A; existing AP posting path stays untouched but the matcher itself is reworked.
- **Outcome:** target the original 85% gate with audit-grade evidence behind every match.

---

## 5. Recommendation

> From a technical standpoint, the original 85% gate is not achievable by Friday using defensible audit-only changes. If Friday cutover is still a business requirement, the safest path is to renegotiate the gate to 60%, retain Square9 read-only for 30 days, and run a daily fallback review. If the 85% threshold remains mandatory, cutover should slip.

Two factors weigh in favor of Option B if the business accepts the residual risk:

1. **Hub has structurally broader AP coverage than Square9.** Hub holds 7,540 AP documents to Square9's 253 in the same parity window. The single-vendor diagnostic confirms tumalocreek alone — 193 documents — is real AP work that Square9 simply does not see. Hub is not "behind" Square9; the two systems have different intake scopes.
2. **Rushing matcher engineering to clear 85% by Friday risks regression on the AP posting path**, which is currently proven, audited, and stable. The cost of breaking that path is materially higher than the cost of a 30-day Square9 read-only retention.

Option B is **not** an unconditional recommendation. It is conditional on the business accepting the risk profile of cutting over at a 60% audited match rate with a fallback safety net.

---

## 6. Decision required

CFO and AP Director please pick **one** option by EOD this week:

- [ ] **Option A** — 2-week slip; Square9 parallel; matcher improvements + AP triage of the 105 uncertain.
- [ ] **Option B** — Friday cutover at a revised 60% gate, with Square9 read-only retention for 30 days, daily AP fallback-log review, and an explicit deprecation date 30 days after cutover.
- [ ] **Option C** — 2–4 week hard slip; matcher overhaul; target the original 85% gate.

If Option B is chosen, AP Director also needs to sign off on:

- the 30-day Square9 read-only retention SLA, and
- the daily fallback-log review cadence and ownership.

---

## 7. Referenced read-only artifacts

All on the production VM at `/opt/gpi-hub/prod_reports/`:

- `no_match_square9_audit.csv` / `.json` / `.md` — Square9 `no_match` classification, projection math.
- `hub_only_audit.csv` / `.json` / `.md` — Hub-only classification, tumalocreek dominance.
- `matcher_miss_vendor_diagnostic.csv` / `.json` / `.md` — tumalocreek scope-gap proof.
- `cutover_proof_<latest>/summary.json` / `.md` — full proof-pack snapshot, bucket counts, projections.

All four scripts that generated these artifacts are read-only. No production data has been modified at any point during this investigation.

---

_This memo contains no figures that were not pulled from the read-only artifacts above. It does not claim GPI Hub is cutover-ready. It does not hide the current NO-GO status of the proof pack._
