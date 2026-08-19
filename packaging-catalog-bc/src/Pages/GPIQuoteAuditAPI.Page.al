page 71016 "GPI Quote Audit API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingQuotes';
    APIVersion = 'v1.0';
    Caption = 'packagingQuoteAudits';
    EntityName = 'packagingQuoteAudit';
    EntitySetName = 'packagingQuoteAudits';
    SourceTable = "GPI Quote Audit";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    DelayedInsert = true;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                    Editable = false;
                }
                field(quoteEntryNo; Rec."Quote Entry No.")
                {
                    Caption = 'Quote No.';
                    Editable = false;
                }
                field(lineNo; Rec."Line No.")
                {
                    Caption = 'Line No.';
                    Editable = false;
                }
                field(eventType; Rec."Event Type")
                {
                    Caption = 'Event Type';
                    Editable = false;
                }
                field(eventAt; Rec."Event At")
                {
                    Caption = 'Event At';
                    Editable = false;
                }
                field(eventBy; Rec."Event By")
                {
                    Caption = 'Event By';
                    Editable = false;
                }
                field(quoteStatus; Rec."Quote Status")
                {
                    Caption = 'Quote Status';
                    Editable = false;
                }
                field(quoteDate; Rec."Quote Date")
                {
                    Caption = 'Quote Date';
                    Editable = false;
                }
                field(expirationDate; Rec."Expiration Date")
                {
                    Caption = 'Expiration Date';
                    Editable = false;
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                    Editable = false;
                }
                field(quoteDescription; Rec."Quote Description")
                {
                    Caption = 'Quote Description';
                    Editable = false;
                }
                field(decisionNote; Rec."Decision Note")
                {
                    Caption = 'Decision Note';
                    Editable = false;
                }
                field(productNo; Rec."Product No.")
                {
                    Caption = 'Gamer ID';
                    Editable = false;
                }
                field(bcItemNo; Rec."BC Item No.")
                {
                    Caption = 'BC Item No.';
                    Editable = false;
                }
                field(uomCode; Rec."UOM Code")
                {
                    Caption = 'UOM';
                    Editable = false;
                }
                field(quantity; Rec.Quantity)
                {
                    Caption = 'Quantity';
                    Editable = false;
                }
                field(landedCostPerUnit; Rec."Landed Cost per Unit")
                {
                    Caption = 'Landed Cost per Unit';
                    Editable = false;
                }
                field(proposedSellPrice; Rec."Proposed Sell Price")
                {
                    Caption = 'Proposed Sell Price';
                    Editable = false;
                }
                field(targetGrossMarginPct; Rec."Target Gross Margin %")
                {
                    Caption = 'Target Gross Margin %';
                    Editable = false;
                }
                field(calculatedGrossMarginPct; Rec."Calculated GP %")
                {
                    Caption = 'Calculated Gross Margin %';
                    Editable = false;
                }
                field(guardrailStatus; Rec."Guardrail Status")
                {
                    Caption = 'Guardrail Status';
                    Editable = false;
                }
                field(needsApproval; Rec."Needs Approval")
                {
                    Caption = 'Needs Approval';
                    Editable = false;
                }
                field(guardrailApprover; Rec."Guardrail Approver")
                {
                    Caption = 'Guardrail Approver';
                    Editable = false;
                }
                field(pricingRuleEntryNo; Rec."Pricing Rule Entry No.")
                {
                    Caption = 'Pricing Rule Entry No.';
                    Editable = false;
                }
                field(policyFixedSellPrice; Rec."Policy Fixed Sell Price")
                {
                    Caption = 'Policy Fixed Sell Price';
                    Editable = false;
                }
                field(eventNote; Rec."Event Note")
                {
                    Caption = 'Event Note';
                    Editable = false;
                }
                field(previousCustomerNo; Rec."Previous Customer No.")
                {
                    Caption = 'Previous Customer No.';
                    Editable = false;
                }
                field(previousQuoteDate; Rec."Previous Quote Date")
                {
                    Caption = 'Previous Quote Date';
                    Editable = false;
                }
                field(previousQuantity; Rec."Previous Quantity")
                {
                    Caption = 'Previous Quantity';
                    Editable = false;
                }
                field(previousLandedCost; Rec."Previous Landed Cost")
                {
                    Caption = 'Previous Landed Cost';
                    Editable = false;
                }
                field(previousSellPrice; Rec."Previous Sell Price")
                {
                    Caption = 'Previous Sell Price';
                    Editable = false;
                }
                field(previousTargetGrossMarginPct; Rec."Previous Target GM %")
                {
                    Caption = 'Previous Target Gross Margin %';
                    Editable = false;
                }
                field(previousProductNo; Rec."Previous Product No.")
                {
                    Caption = 'Previous Gamer ID';
                    Editable = false;
                }
                field(previousBCItemNo; Rec."Previous BC Item No.")
                {
                    Caption = 'Previous BC Item No.';
                    Editable = false;
                }
                field(previousUomCode; Rec."Previous UOM Code")
                {
                    Caption = 'Previous UOM';
                    Editable = false;
                }
                field(previousGuardrailStatus; Rec."Previous Guard Status")
                {
                    Caption = 'Previous Guardrail Status';
                    Editable = false;
                }
            }
        }
    }
}
