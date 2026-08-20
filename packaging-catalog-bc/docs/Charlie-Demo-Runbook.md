# Charlie Demo Runbook

## Purpose

Demonstrate the current Business Central packaging workflow using a clean, real-data-backed scenario in `Sandbox_NoZetadocs_UAT`.

The prepared demo quote is intentionally left in Draft and Not Evaluated status so the guardrail decision can be shown live. The goal of the demo is not just to show buttons. The goal is to explain how Business Central gives sales and management better commercial context before a price is approved.

## Prepared demo quote

- Quote No.: 66
- Customer: WAT / Watkins Inc.
- Product: FG10900B
- Description: Watkins 4oz Spice Bottle Commercial Review
- Quantity: 10
- UOM: M
- Landed Cost per Unit: 91.92
- Proposed Sell Price per Unit: 131.94
- Target Gross Margin %: 13
- Calculated Gross Margin %: 30.33197
- Guardrail Status before demo: Not Evaluated
- Audit Entries before demo: 0

## Historical pricing context

The setup script verified exact posted sales history for WAT + FG10900B + M through 2026-08-19.

- Exact history lines: 74
- Recent-5 median sell price: 146.60
- Proposed sell price: 131.94
- Variance from recent median: -10.00%

Expected guardrail after evaluation: `Below Customer History`

Expected approval requirement: Yes

## Guided live demo instructions

### 1. Open GPI Packaging Quotes and open Quote 66

Open `GPI Packaging Quotes`, locate Quote 66, and open the quote card.

Explain that this is a packaging quote workspace built directly inside Business Central. The quote is tied to a real BC customer and a real BC item, so the commercial review is happening against the same data already used by the business.

Suggested explanation:

"This is a packaging quote inside Business Central. The salesperson can start with an actual customer and packaging item, enter the commercial terms they want to propose, and then have BC evaluate that proposed price against our margin rules, protected pricing, and actual customer buying history."

### 2. Show that the quote is Draft and the line is Not Evaluated

Point out the quote status and the line-level guardrail status before running anything.

The important concept is that Business Central has not made a pricing decision automatically. The user entered the proposed commercial terms, but the guardrail engine has not yet been asked to evaluate them.

Suggested explanation:

"Right now this is still a Draft quote. The salesperson controls the proposed sell price. BC has not approved it, rejected it, or changed it. The line says Not Evaluated because we have not run the commercial guardrails yet."

This distinction is important. The system is designed to support sales judgment, not replace it.

### 3. Review the commercial inputs and explain why each one matters

Walk through the quote line before evaluating it.

#### Customer: WAT / Watkins Inc.

Explain that the customer matters because the guardrail can use customer-specific commercial evidence.

"The customer drives more than the name on the quote. It lets BC check whether there are special pricing rules for this account and compare the proposed price to what this customer has actually paid for this exact item."

#### Product: FG10900B

Point out that the packaging product maps back to the real BC Item.

"We are not creating a disconnected product catalog. This packaging record maps back to the existing Business Central item, so item identity, UOM setup, and commercial history stay tied to the source system."

#### Quantity: 10 M

Explain the UOM conversion.

"The BC base UOM for this item is EA, but this product is commonly sold in M, meaning thousands. Ten M represents 10,000 each. The extension uses the Item Unit of Measure setup so the quantity and unit economics remain consistent when we quote in M instead of EA."

#### Landed Cost per Unit: 91.92

Explain that this is the commercial cost basis.

"This is the landed cost basis used for the quote. The broader design is that landed cost can include supplier cost, freight, tariffs, and other deterministic cost components before we evaluate the sell price."

#### Proposed Sell Price: 131.94

Emphasize that the proposed price is entered by the user.

"The salesperson still chooses the proposed customer price. BC does not automatically replace that price with an AI-generated number."

#### Target Gross Margin: 13%

Explain that the target is one of the business guardrails.

"This gives BC a minimum margin target to evaluate against."

#### Calculated Gross Margin: approximately 30.33%

Pause here because this sets up the point of the demo.

"At first glance this quote looks very healthy. The target margin is 13%, and the proposed price produces about 30.33% gross margin. If margin were the only thing we reviewed, this quote would look completely fine."

That sets up why customer history matters.

### 4. Click Run Guardrail Evaluation

Before clicking, explain what BC is about to do.

"Now I am asking Business Central to evaluate the proposed price. It checks the deterministic commercial rules we have defined. That includes margin, protected pricing rules, and the customer's exact posted sales history for this item and this unit of measure."

Click `Run Guardrail Evaluation`.

Emphasize that this is rules-based logic inside BC. It is not AI independently choosing or rejecting a price.

### 5. Confirm the completion message

The message should report that 1 of 1 line requires approval.

Explain what that means:

"BC found a commercial exception. It is not blocking us from doing business. It is telling us that something about this quote deserves review before we commit to the price."

This is the distinction between a guardrail and an automatic pricing engine.

### 6. Show Below Customer History and Needs Approval

Point to the line-level result.

The expected result is:

- Guardrail Status: `Below Customer History`
- Needs Approval: selected

Explain why the line was flagged:

"The exception is not caused by low margin. The quote is still at about 30.33% gross margin. BC is flagging it because Watkins has recently paid more for this exact item in this exact UOM."

Suggested business explanation:

"A salesperson could look at a 30% margin and think this is a great quote. But if the customer has consistently been paying more, we may be giving away price unnecessarily. This guardrail is designed to catch that kind of margin leakage before the quote goes out."

### 7. Open Show/Hide Review Details and explain the pricing evidence

Use `Show/Hide Review Details` to expose the historical pricing fields.

Walk through the evidence slowly.

#### Customer History Lines: 74

"BC found 74 actual posted sales lines for Watkins, this item, and this UOM. This is not based on one unusual invoice."

#### Customer History Median: 146.60

"For the actual comparison, BC looks at the five most recent exact transactions and calculates the median. The recent-5 median is 146.60. Using a median helps keep one unusual high or low transaction from distorting the comparison."

#### Proposed Sell Price: 131.94

"Our proposed sell price is 131.94."

#### Customer History Variance: -10.00%

"That proposed price is 10% below the customer's recent median for the exact same item and UOM."

Then connect the evidence back to the business decision:

"So the system is telling us that margin is healthy, but we are still about to sell this product to Watkins for roughly 10% less than their recent buying pattern. That is useful commercial context that a rep might not otherwise see while building a quote."

Also explain what BC is not doing:

"BC is not saying that 146.60 is automatically the correct new price. Customer history is evidence for review. There may be a valid reason to quote 131.94, but now someone has to consciously make that decision."

### 8. Show the Commercial Review status as Approval required

Scroll to the Commercial Review section and point out the header-level result.

Expected status:

`Approval required`

Explain that BC rolls line-level exceptions up to the overall quote so a manager can immediately tell whether the quote is clean or needs attention.

"The line has a pricing exception, and BC rolls that up to the quote. A reviewer does not have to inspect every technical field to know that this quote needs a commercial decision."

### 9. Click Ready for Review

Before clicking, explain the workflow transition.

"At this point the salesperson is done preparing the quote and is submitting it for a commercial decision."

Click `Ready for Review`.

Expected result:

- Status: `Ready`
- Review Status: `Ready, approval required`
- Approve Quote: enabled
- Reject Quote: enabled

Explain what changed:

"The quote has now moved out of Draft and into a review state. The pricing exception remains visible, and the reviewer now has an explicit Approve or Reject decision to make."

Also explain that BC reevaluates the quote as part of the transition so the decision is based on the latest commercial inputs.

### 10. Enter an approval note that explains the business reason

Because the quote contains a pricing exception, the approval should include a meaningful business explanation.

For the demo, use a note such as:

`Approved for Watkins based on current competitive situation and account strategy. Pricing is below recent customer history but remains above target margin at 30.33%.`

Explain why the note matters:

"Because this quote is outside the normal customer pricing pattern, the reviewer should document why we are accepting the exception. That gives us accountability and preserves the business reasoning behind the decision."

### 11. Click Approve Quote

Click `Approve Quote`.

Expected result:

- Status: `Approved`
- Review Status: `Approved`
- Decision By: populated
- Decision At: populated
- Approval note: preserved
- Reopen Draft: enabled
- Guardrail evaluation actions: disabled

Explain the final state:

"The quote is now approved with the pricing exception explicitly accepted. The system preserves who approved it, when it was approved, the pricing evidence that was evaluated, and the business reason entered by the reviewer."

### 12. Show the Approval and Audit History

Finish by showing the audit history.

Explain that the audit trail captures the commercial lifecycle of the quote, including evaluation, movement to review, and the final approval decision.

"This gives us a durable record of what price was proposed, what guardrail was triggered, what customer history supported the warning, who made the decision, and why the exception was accepted."

## What Charlie should take away

The most important message is that this workflow does not attempt to automate away sales judgment.

Business Central is giving the salesperson and the reviewer better commercial context at the moment a pricing decision is made.

The workflow combines:

- the salesperson's proposed sell price
- deterministic landed-cost and margin calculations
- protected pricing rules
- customer-specific posted sales history
- explicit exception review
- approval notes
- a durable audit trail

The user still decides what to quote. BC makes the risks visible and makes exceptions explainable and auditable.

## Talking points

- Business Central is applying deterministic pricing and margin rules. AI is not setting the customer price.
- The user chooses the proposed sell price. BC evaluates it against landed cost, target margin, protected pricing rules, and customer-specific posted sales history.
- Historical pricing is review evidence only. It never replaces the user-entered sell price.
- The exact customer/item/UOM history is used so unlike pack sizes or units are not mixed into the comparison.
- The M UOM is normalized from the BC item UOM setup while preserving extended landed cost and proposed sell economics.
- A pricing exception remains visible through Ready for Review and requires an explicit approval decision.
- The final decision and the pricing evidence are preserved in the audit trail.

## Expected live results

After `Run Guardrail Evaluation`:

- Guardrail Status: Below Customer History
- Needs Approval: Yes
- Review Status: Approval required
- Customer History Lines: 74
- Customer History Median: 146.60
- Customer History Variance: -10.00%
- Calculated Gross Margin: approximately 30.33%
- Total Landed Cost: 919.20
- Total Proposed Sell: 1,319.40
- Gross Profit Total: 400.20

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

## Reset for another demo

Do not reuse an already evaluated or approved demo quote if a clean live evaluation is desired.

Run:

```powershell
$Worktree = "$env:USERPROFILE\Documents\DocSync-PackagingCatalog"
$AppPath  = "$Worktree\packaging-catalog-bc"

& "$AppPath\scripts\New-GPICharlieDemoQuote.ps1"
```

The script verifies current protected-pricing rules and historical pricing before creating another clean Draft quote. If setup fails partway through, it removes the partial quote.

## Safety

- UAT only: `Sandbox_NoZetadocs_UAT`
- Do not publish or run this demo setup against Production.
- Do not merge this packaging branch into `main` as part of the demo.
- Do not modify the Zetadocs replacement extension for this demo.
