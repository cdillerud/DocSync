page 71013 "GPI Quote Line API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingQuotes';
    APIVersion = 'v1.0';
    Caption = 'packagingQuoteLines';
    EntityName = 'packagingQuoteLine';
    EntitySetName = 'packagingQuoteLines';
    SourceTable = "GPI Pack Quote Line";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = true;
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
                field(quoteEntryNo; Rec."Quote Entry No.")
                {
                    Caption = 'Quote No.';
                }
                field(lineNo; Rec."Line No.")
                {
                    Caption = 'Line No.';
                    Editable = false;
                }
                field(productNo; Rec."Product No.")
                {
                    Caption = 'Gamer ID';
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                }
                field(bcItemNo; Rec."BC Item No.")
                {
                    Caption = 'BC Item No.';
                }
                field(uomCode; Rec."UOM Code")
                {
                    Caption = 'UOM';
                }
                field(quantity; Rec.Quantity)
                {
                    Caption = 'Quantity';
                }
                field(costWorksheetEntryNo; Rec."Cost Worksheet Entry No.")
                {
                    Caption = 'Landed Cost Worksheet';
                }
                field(landedCostPerUnit; Rec."Landed Cost per Unit")
                {
                    Caption = 'Landed Cost per Unit';
                }
                field(proposedSellPrice; Rec."Proposed Sell Price")
                {
                    Caption = 'Proposed Sell Price per Unit';
                }
                field(targetGrossMarginPct; Rec."Target Gross Margin %")
                {
                    Caption = 'Target Gross Margin %';
                }
                field(suggestedSellPrice; Rec."Suggested Sell Price")
                {
                    Caption = 'Suggested Sell Price per Unit';
                    Editable = false;
                }
                field(calculatedGrossMarginPct; Rec."Calculated GP %")
                {
                    Caption = 'Calculated Gross Margin %';
                    Editable = false;
                }
                field(extendedLandedCost; Rec."Extended Landed Cost")
                {
                    Caption = 'Extended Landed Cost';
                    Editable = false;
                }
                field(extendedSell; Rec."Extended Sell")
                {
                    Caption = 'Extended Sell';
                    Editable = false;
                }
                field(grossProfitTotal; Rec."Gross Profit Total")
                {
                    Caption = 'Gross Profit Total';
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
                field(policyFixedSellPrice; Rec."Policy Fixed Sell Price")
                {
                    Caption = 'Policy Fixed Sell Price';
                    Editable = false;
                }
                field(guardrailMessage; Rec."Guardrail Message")
                {
                    Caption = 'Guardrail Message';
                    Editable = false;
                }
                field(evaluatedAt; Rec."Evaluated At")
                {
                    Caption = 'Evaluated At';
                    Editable = false;
                }
                field(evaluatedBy; Rec."Evaluated By")
                {
                    Caption = 'Evaluated By';
                    Editable = false;
                }
            }
        }
    }
}
