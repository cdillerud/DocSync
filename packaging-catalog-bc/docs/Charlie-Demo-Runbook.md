# Charlie Demo Runbook

## Purpose

Demonstrate the current Business Central packaging workflow using a clean, real-data-backed scenario in `Sandbox_NoZetadocs_UAT`.

The primary prepared quote is intentionally left in Draft and Not Evaluated status so the commercial guardrail decision can be shown live. The demo now connects product context, posted landed-cost evidence, customer pricing history, margin review, approval, and audit into one story.

The key message is that Business Central provides commercial evidence and deterministic guardrails. The salesperson still chooses the proposed sell price, and the reviewer still makes the approval decision.

## Primary prepared demo quote

- Quote No.: 67
- Customer: TREEHUG / Tree Hugger Containers LLC
- Product: F08234
- BC Item: F08234
- Description: Tree Hugger F08234 Historical Landed-Cost Commercial Review
- Quantity: 168
- UOM: M
- Landed Cost per Unit: 135.38
- Proposed Sell Price per Unit: 163.55
- Target Gross Margin %: 13
- Calculated Gross Margin %: approximately 17.22409
- Guardrail Status before demo: Not Evaluated
- Audit Entries before demo: 0

The quote notes explicitly state that the 135.38/M landed-cost basis comes from historical posted Business Central evidence dated 2025-12-19. It is not being represented as a current 2026 freight quote.

## Posted landed-cost evidence

The primary scenario is backed by posted Business Central Value Entries for Item Ledger Entry 615641.

- Evidence date: 2025-12-19
- Quantity: 168,000 EA
- Direct product cost: 15,254.40 total
- Direct product cost per EA: 0.09080
- Freight: 2,557.46
- Customs: 94.10
- Drayage: 1,715.00
- Tariff: 3,122.82
- Total posted item charges: 7,489.38
- Total posted cost: 22,743.78
- Historical landed cost per EA: 0.13538
- Historical landed cost per M: 135.38
- Posted charge codes: CUSTOMS, DRAYAGE, FREIGHT, TARIFF

This historical evidence validates how the landed-cost model should be structured. It does not make the 2025 freight charges a current 2026 rate.

## Historical customer pricing context

The setup script verified exact posted sales history for TREEHUG + F08234 + M through 2026-08-19.

- Exact history lines: 37
- Recent-5 median sell price: 181.72
- Proposed sell price: 163.55
- Variance from recent median: approximately -10.00%
- Gross margin at proposed sell: approximately 17.22%
- Target gross margin: 13%
- Applicable protected-pricing rules: none

Expected guardrail after evaluation: `Below Customer History`

Expected approval requirement: Yes

The scenario is useful because the proposed price clears the margin target but is still materially below the customer's recent exact-item pricing. That allows the customer-history guardrail to remain the visible business reason for review.

## Guided live demo instructions

### 1. Start with the packaging product

Open `GPI Packaging Products` and open product `F08234`.

Explain that the packaging record maps back to the actual Business Central Item and is not a separate disconnected product universe.

Suggested explanation:

"This packaging record is linked to the existing Business Central item. We can add packaging-specific sourcing and commercial context without replacing the item master that the company already uses."

Point out the relevant product context:

- Product: F08234
- Material: GLASS
- Capacity: 3 OZ
- Vendor: HWAHSIA
- Current Supplier Unit Cost: 0.0908 per EA
- Gram Weight: 86

Explain that the current supplier cost is the direct product-cost basis. It should not be confused with a fully landed cost.

### 2. Open Historical Cost Evidence

From the product, click `Historical Cost Evidence`.

The page should show posted Business Central cost groups for the item. Locate the most recent charged entry dated 2025-12-19, Item Ledger Entry 615641.

Walk through the cost stack:

- Direct product cost
- Freight
- Customs
- Drayage
- Tariff
- Total charges
- Total actual cost
- Landed cost per EA
- Landed cost per M

Suggested explanation:

"This is where the landed-cost model becomes grounded in real Business Central transactions. The direct product cost was about 9.08 cents each. Business Central also has posted freight, customs, drayage, and tariff charges assigned to the item receipt. When those are included, the historical actual landed cost was about 13.538 cents each, or 135.38 per thousand."

Immediately clarify the time basis:

"This is historical posted evidence from December 2025. I am using it to show and validate the cost model. I am not presenting those freight charges as a current 2026 freight quote. A production workflow would use the current authoritative freight source for a current quote."

This distinction is important. The demo should show that Business Central can explain landed cost without overstating the freshness of the freight data.

### 3. Open GPI Packaging Quotes and open Quote 67

Open `GPI Packaging Quotes`, locate Quote 67, and open the quote card.

Explain that the quote uses the historical posted landed-cost evidence as its UAT demo cost basis and says so explicitly in the Notes field.

Suggested explanation:

"Now we are moving from product and cost evidence into the commercial quote. This is still the same Business Central item and a real customer. The quote notes identify exactly where the demo landed-cost basis came from, so the evidence is traceable rather than hidden."

### 4. Show that the quote is Draft and the line is Not Evaluated

Point out the quote status and the line-level guardrail status before running anything.

Suggested explanation:

"Right now this is still a Draft quote. The salesperson controls the proposed sell price. BC has not approved it, rejected it, or changed it. The line says Not Evaluated because we have not run the commercial guardrails yet."

The system is designed to support sales judgment, not replace it.

### 5. Review the commercial inputs

Walk through the quote line before evaluating it.

#### Customer: TREEHUG / Tree Hugger Containers LLC

"The customer matters because BC can check protected pricing rules and compare the proposed price to what this specific customer has actually paid for this exact item and UOM."

#### Product: F08234

"This line maps to the same Business Central item we just reviewed, so the product, cost evidence, UOM setup, and customer history all stay tied to the same source system."

#### Quantity: 168 M

"The Business Central base UOM is EA, while this commercial history is in M. One M represents 1,000 each, so 168 M represents 168,000 each. The extension uses the Business Central Item Unit of Measure setup to preserve the economics when the quote is expressed in M."

#### Landed Cost per Unit: 135.38

"For this UAT scenario, 135.38 per M is based on the latest posted historical landed-cost evidence we just reviewed. It includes direct product cost plus posted freight, customs, drayage, and tariff. The note on the quote also identifies it as historical evidence."

#### Proposed Sell Price: 163.55

"The salesperson still chooses the proposed customer price. BC does not replace that price with an AI-generated number."

#### Target Gross Margin: 13%

"This is one of the deterministic commercial thresholds BC evaluates."

#### Calculated Gross Margin: approximately 17.22%

Pause here because this creates the setup for the guardrail.

"At first glance the quote clears the 13% target. The proposed price produces about 17.22% gross margin, so this is not a low-margin exception."

That sets up why customer history matters.

### 6. Click Run Guardrail Evaluation

Before clicking, explain what BC is about to do.

"Now I am asking Business Central to evaluate the proposed price. It checks deterministic commercial rules, including target margin, protected pricing rules, and this customer's exact posted sales history for this item and this unit of measure."

Click `Run Guardrail Evaluation`.

Emphasize that this is deterministic Business Central logic. AI is not independently choosing or rejecting the price.

### 7. Confirm the completion message

The message should report that 1 of 1 line requires approval.

Suggested explanation:

"BC found a commercial exception. It is not blocking us from doing business. It is telling us that this quote deserves review before we commit to the price."

### 8. Show Below Customer History and Needs Approval

Expected line result:

- Guardrail Status: `Below Customer History`
- Needs Approval: selected

Explain why it was flagged:

"The exception is not low margin. The quote still clears the 13% target. BC is flagging it because Tree Hugger has recently paid more for this exact item in this exact UOM."

Suggested business explanation:

"A rep could look at a 17% margin and decide the quote is acceptable. But if this customer has consistently paid more for the same item, we may be giving away price unnecessarily. The guardrail catches that before the quote goes out."

### 9. Show the review details and pricing evidence

Use `Show/Hide Review Details` to expose the historical pricing fields.

Walk through the evidence:

#### Customer History Lines: 37

"BC found 37 actual posted sales lines for Tree Hugger, this item, and this UOM."

#### Customer History Median: 181.72

"For the comparison, BC uses the five most recent exact transactions and calculates the median. The recent-5 median is 181.72."

#### Proposed Sell Price: 163.55

"Our proposed sell price is 163.55."

#### Customer History Variance: approximately -10.00%

"That proposed price is about 10% below the customer's recent median for the exact same item and UOM."

Connect the evidence back to the business decision:

"The quote clears target margin, but the customer has recently been paying more. BC is surfacing that pricing leakage risk while the salesperson and reviewer can still decide whether there is a valid business reason for the lower price."

Also explain what BC is not doing:

"BC is not saying that 181.72 automatically becomes the new price. Customer history is evidence for review. The salesperson still proposes the price, and the reviewer decides whether the exception is justified."

### 10. Show the Commercial Review status as Approval required

Scroll to the Commercial Review section.

Expected status:

`Approval required`

Suggested explanation:

"The line-level exception rolls up to the quote so the reviewer can immediately see that a commercial decision is required."

### 11. Click Ready for Review

Before clicking:

"At this point the salesperson is done preparing the quote and is submitting it for a commercial decision."

Click `Ready for Review`.

Expected result:

- Status: `Ready`
- Review Status: `Ready, approval required`
- Approve Quote: enabled
- Reject Quote: enabled

Explain that BC reevaluates the quote as part of the transition so the decision is based on the current commercial inputs.

### 12. Enter an approval note

For the demo, use:

`Approved for Tree Hugger based on current account strategy. Proposed pricing is below recent customer history but remains above the 13% target margin at approximately 17.22%. Historical landed-cost evidence was reviewed as supporting UAT context.`

Explain why the note matters:

"Because this quote is outside the recent customer pricing pattern, the reviewer should document why the exception is being accepted."

### 13. Click Approve Quote

Expected result:

- Status: `Approved`
- Review Status: `Approved`
- Decision By: populated
- Decision At: populated
- Approval note: preserved
- Reopen Draft: enabled
- Guardrail evaluation actions: disabled

Suggested explanation:

"The quote is now approved with the pricing exception explicitly accepted. Business Central preserves who approved it, when it was approved, the commercial evidence that triggered review, and the business reason for the decision."

### 14. Show the Approval and Audit History

Finish by showing the audit history.

Suggested explanation:

"This gives us a durable record of what price was proposed, what guardrail was triggered, what customer history supported the warning, who made the decision, and why the exception was accepted."

The core flow is:

`supplier and cost evidence -> salesperson-entered price -> automated commercial review -> human approval -> durable audit trail`

## What Charlie should take away

The workflow does not attempt to automate away sales judgment.

Business Central is giving the salesperson and reviewer better commercial context at the moment a pricing decision is made.

The current demo combines:

- an existing Business Central Item
- packaging-specific catalog context
- current supplier cost
- historical posted freight, customs, drayage, and tariff evidence
- UOM normalization
- the salesperson's proposed sell price
- deterministic target-margin evaluation
- protected-pricing checks
- customer-specific posted sales history
- explicit exception review
- approval notes
- a durable audit trail

The user still decides what to quote. BC makes the cost basis, pricing risk, and exceptions visible, explainable, and auditable.

## Talking points

- Business Central is the commercial source of truth. The packaging layer enriches existing BC items instead of replacing them.
- Posted Value Entries provide traceable historical evidence for direct item cost and assigned Item Charges.
- Historical posted freight evidence is clearly distinguished from a current freight quote.
- Business Central is applying deterministic pricing and margin rules. AI is not setting the customer price.
- The user chooses the proposed sell price. BC evaluates it against cost, target margin, protected pricing rules, and customer-specific posted sales history.
- Historical customer pricing is review evidence only. It never replaces the user-entered sell price.
- Exact customer/item/UOM history is used so unlike pack sizes or units are not mixed into the comparison.
- The M UOM is normalized from the BC item UOM setup while preserving extended cost and sell economics.
- A pricing exception remains visible through Ready for Review and requires an explicit approval decision.
- The final decision and pricing evidence are preserved in the audit trail.

## Expected live results for Quote 67

After `Run Guardrail Evaluation`:

- Guardrail Status: Below Customer History
- Needs Approval: Yes
- Review Status: Approval required
- Customer History Lines: 37
- Customer History Median: 181.72
- Customer History Variance: approximately -10.00%
- Calculated Gross Margin: approximately 17.22%
- Total Landed Cost: approximately 22,743.84 based on the rounded 135.38/M quote cost
- Total Proposed Sell: 27,476.40
- Gross Profit Total: approximately 4,732.56

The underlying historical posted total for Item Ledger Entry 615641 was 22,743.78. The six-cent difference from the quote extended amount is caused by using the displayed rounded landed cost of 135.38/M on 168 M.

After `Ready for Review`:

- Status: Ready
- Review Status: Ready, approval required
- Approve Quote: enabled
- Reject Quote: enabled

After approval:

- Status: Approved
- Review Status: Approved
- Decision By: populated
- Decision At: populated
- Approval note: preserved
- Reopen Draft: enabled
- Guardrail evaluation actions: disabled

## Fallback guardrail demo

Quote 66 remains a clean fallback if a shorter pricing-history-only demonstration is needed.

- Quote No.: 66
- Customer: WAT / Watkins Inc.
- Product: FG10900B
- Quantity: 10 M
- Cost basis: 91.92/M
- Proposed Sell: 131.94/M
- Target GM: 13%
- Calculated GM: approximately 30.33%
- Customer History Lines: 74
- Recent-5 Median: 146.60
- Expected Guardrail: Below Customer History
- Audit Entries before evaluation: 0

For Quote 66, do not describe 91.92/M as a current fully landed cost. It is the direct supplier-cost basis converted from EA to M.

## Reset for another primary full-flow demo

Do not reuse an already evaluated or approved demo quote if a clean live evaluation is desired.

Run:

```powershell
$Worktree = "$env:USERPROFILE\Documents\DocSync-PackagingCatalog"
$AppPath  = "$Worktree\packaging-catalog-bc"

& "$AppPath\scripts\New-GPICharlieFullFlowQuote.ps1"
```

The script rechecks the product mapping, latest posted landed-cost evidence, protected-pricing rules, customer sales history, target margin, and UOM normalization before creating another clean Draft quote. If setup fails after quote creation begins, it attempts to remove the partial quote and line.

For the shorter Watkins fallback scenario, run:

```powershell
& "$AppPath\scripts\New-GPICharlieDemoQuote.ps1"
```

## Safety

- UAT only: `Sandbox_NoZetadocs_UAT`
- Leave Quote 67 unevaluated until the intended live demo.
- Do not publish or run the demo setup scripts against Production.
- Do not merge the packaging branch into `main` as part of the demo.
- Do not modify the Zetadocs replacement extension for this demo.
