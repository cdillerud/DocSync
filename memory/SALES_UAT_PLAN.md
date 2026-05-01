# Sales UAT Plan — Lane 3 (PLAN-ONLY, NON-POSTING)

- Author/agent: Emergent fork agent
- Generated: 2026-04-30 (UTC)
- Status: DRAFT — awaiting user signature.
- Scope: define what sales staff can safely test **right now**,
  during Phase 1 — AP Hardening and Controlled Rollout, in
  parallel with Lane 1 (safe AP sandbox execution) and Lane 2
  (accounting UAT).
- Parent: `FAST_TRACK_EXECUTION_PLAN.md`.
- **Sales posting is not live.** Nothing in this plan implies
  the sales flow is production-ready. Lane 3 is intake,
  classification, PO interpretation, readiness / exception
  review, and general usability — **observation only**.

## 0. Out-of-scope fence

Sales UAT users do **not**:

- Submit any sales order to BC (sandbox or prod).
- Create, edit, or delete customer master, customer aliases,
  or pricing / discount records.
- Trigger any outbound document (quote, confirmation, ASN,
  invoice).
- Change hub doc status, workflow_status, or any posting-related
  field.
- Invoke any script.
- Touch any Lane 1 (AP) or Lane 2 (accounting posting) surface.
- Open a parked-class investigation. Sales-side equivalents of
  parked AP classes are filed as `KNOWN-CLASS` and closed.
- Escalate a single finding into a customer-master fix. That
  is engineering work behind a signed declaration.

## 1. Goal

Get sales eyes on the non-posting sales surfaces early, so we
learn:

- Whether **intake** captures the right content from customer
  emails / PDFs.
- Whether **document classification** (PO, change order, RFQ,
  order confirmation, generic correspondence, etc.) looks
  correct to a salesperson.
- Whether **customer PO interpretation** — line items,
  quantities, pricing, ship-to, requested date — looks correct.
- Whether **order-readiness and exception review** is clear
  and actionable for sales.
- Whether the **workflow usability** is good enough to pilot.

Findings feed into engineering through the issue template in
§7. Engineering does not act on findings inline; fixes go
through the existing signed-declaration discipline. **Sales
posting remains parked.**

## 2. Cohort + access

- **Size:** ≤ 3 sales users in round 1.
- **Named participants:** TBD at sign time (no silent
  expansion).
- **Access:** existing sales-role hub login. No new permissions
  granted by this plan.
- **Environment:** sandbox / non-production only. Users must
  never be pointed at a prod-connected sales surface.

## 3. What sales can look at

All read-only, observation-only:

1. **Document intake queue (sales).** Recently arrived sales
   documents with sender, received time, classification, and
   current status.
2. **Classification panel.** What the system decided the doc
   is (PO, change order, order confirmation, RFQ, generic
   correspondence), and confidence.
3. **Customer PO interpretation panel.** Customer canonical,
   customer BC number (if resolved), PO number, line items,
   quantities, unit prices, totals, ship-to address, requested
   delivery date.
4. **Readiness / exception panel.** Why a doc is or is not
   ready for further action (ambiguous customer, missing line
   items, price / quantity inconsistency, unknown ship-to, etc.).
5. **Workflow surface.** The visible lifecycle of a sales doc
   from intake → classification → interpretation → readiness
   review → (parked: order creation).

## 4. What sales should NOT do

- Not click any “Create order”, “Send confirmation”, or
  “Post to BC” control. If such a control is visible in their
  role, **file a finding immediately** with severity `blocker`
  — it should not be reachable by UAT.
- Not edit extracted values.
- Not assume a sales-side parked class is a new bug. File as
  `KNOWN-CLASS` per §6 triage.
- Not share sandbox URLs, test data, or customer document
  contents outside the UAT cohort.

## 5. Lightweight test script (per session)

Each session is ≤ 45 minutes. Run twice per week. One user per
session; findings are per-session, per-doc.

### Session steps

1. **Open the sales intake queue.** Note the top 10 docs by
   received time.
2. For each of the top 10:
   a. Open the document.
   b. Read the classification and confidence. Do you agree?
   c. If classified as a PO or change order, open the
      interpretation panel.
      - Does the customer match?
      - Do the line items, quantities, and unit prices match
        what you see in the PDF/email?
      - Does ship-to match?
      - Does requested date match?
   d. Read the readiness / exception panel.
      - Can you tell, in plain English, why the doc is or is
        not ready?
3. **Walk the workflow surface end to end** (read-only). Is
   the status progression readable? Can you tell where a doc
   is stuck without asking engineering?
4. **File findings** per §7 template. One finding per doc,
   not one combined entry.

### What to pay extra attention to

- A classification that is confidently wrong (high confidence,
  but the document is not that type).
- Customer canonicals that resolve to a BC number you don’t
  recognize or that looks like a placeholder.
- Line items where the quantity × unit price does not match
  the line total in the PDF.
- Ship-to addresses that collapse to a warehouse you wouldn’t
  expect for that customer.
- Exceptions that are technically accurate but unreadable to
  a salesperson.

## 6. Triage buckets (filled in by engineering, not the user)

- `EXPECTED` — known behaviour; close.
- `KNOWN-CLASS` — matches an already-parked sales-side class
  (fill in class name at triage). No inline fix.
- `NEW-CLASS` — candidate for its own signed investigation
  declaration. No inline fix.
- `UX-ONLY` — UI / copy / nav; queued for a UX-only
  declaration.

## 7. Issue template

```
Finding ID: (auto)
Submitter: <username>
Session date (UTC): <YYYY-MM-DD>
Doc id (sales): <uuid if available, otherwise best identifier>
Surface: intake | classification | interpretation | readiness | workflow
Classification (system): <value>   confidence: <value>
Customer (system canonical): <value>
Customer BC number (if resolved): <value>
PO number (extracted): <value>
Line count (extracted): <n>
Any total (extracted): <value>
Ship-to (extracted): <value>
Requested date (extracted): <value>
What I observed:
  <one paragraph, plain English>
What I would have expected:
  <one paragraph, plain English>
Severity (submitter estimate):
  blocker | major | minor | cosmetic
Attachments:
  <screenshot or copied panel text if possible>

--- (engineering-only below) ---
Triage bucket: EXPECTED | KNOWN-CLASS | NEW-CLASS | UX-ONLY
Parked-class reference (if KNOWN-CLASS): <fill at triage>
Engineering action: none-inline (standard)
Follow-up declaration: <name or “n/a”>
```

## 8. Explicitly NOT live yet

Sales users should be told, in plain English, and the issue
template should have a sticky reminder:

- Order creation against BC is not live. Any “order created”
  effect you see in the UI is either a visualization of what
  would happen, or a bug (file as `blocker`).
- Pricing / discount updates from sales-side documents are
  not live.
- Automated confirmation emails are not live.
- Shipping / fulfillment triggers are not live.
- Anything that would touch a real customer record in BC is
  not live.

The purpose of Lane 3 is to validate that the system's
**understanding** of sales documents is good enough to
eventually drive those flows — not to drive them today.

## 9. Cadence + success

- Twice per week, ≤ 45 minutes per session.
- Target over 2 weeks: ≥ 2 users × 2 sessions × 3 findings =
  ≥ 12 findings triaged by bucket.
- Success = sales has filed findings, each finding is in a
  triage bucket, zero findings have been acted on by
  engineering inline without a signed declaration, and **no
  sales document has been posted anywhere** as a result of
  UAT.

## 10. Escalation

- A `blocker` severity finding that would imply sales posting
  is reachable by UAT users is escalated to engineering and
  the signing operator within 24h.
- A `blocker` finding that is also `NEW-CLASS` is escalated
  to engineering within 24h for a decision on whether to draft
  a new signed investigation declaration. No inline fix.
- Any finding that would require a production write is
  **rejected at triage**. Sales UAT is non-posting, full stop.

## 11. Sign request

- **"Sign as-is"** → plan goes live with ≤ 3 named users.
  Engineering wires the shared finding-capture location and
  shares access with the cohort.
- **"Sign with amendments: [paste]"** → revise; re-sign.
- **"Reject"** → re-scope direction.

Signing this plan does **not** make sales posting live. It
does **not** grant any write authority to sales users. It
only authorizes observation + findings capture on the
existing non-posting sales surfaces.
