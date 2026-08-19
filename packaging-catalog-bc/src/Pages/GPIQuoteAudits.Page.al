page 71015 "GPI Quote Audits"
{
    PageType = ListPart;
    SourceTable = "GPI Quote Audit";
    SourceTableView = sorting("Entry No.") order(descending);
    ApplicationArea = All;
    Caption = 'Quote Approval and Audit History';
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(History)
            {
                field("Event At"; Rec."Event At")
                {
                    ApplicationArea = All;
                }
                field("Event Type"; Rec."Event Type")
                {
                    ApplicationArea = All;
                }
                field("Event By"; Rec."Event By")
                {
                    ApplicationArea = All;
                }
                field("Quote Status"; Rec."Quote Status")
                {
                    ApplicationArea = All;
                }
                field("Line No."; Rec."Line No.")
                {
                    ApplicationArea = All;
                }
                field("Quote Date"; Rec."Quote Date")
                {
                    ApplicationArea = All;
                }
                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                }
                field("Quote Description"; Rec."Quote Description")
                {
                    ApplicationArea = All;
                }
                field("Decision Note"; Rec."Decision Note")
                {
                    ApplicationArea = All;
                }
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;
                }
                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                }
                field("UOM Code"; Rec."UOM Code")
                {
                    ApplicationArea = All;
                }
                field(Quantity; Rec.Quantity)
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
                {
                    ApplicationArea = All;
                }
                field("Proposed Sell Price"; Rec."Proposed Sell Price")
                {
                    ApplicationArea = All;
                }
                field("Target Gross Margin %"; Rec."Target Gross Margin %")
                {
                    ApplicationArea = All;
                }
                field("Calculated GP %"; Rec."Calculated GP %")
                {
                    ApplicationArea = All;
                }
                field("Guardrail Status"; Rec."Guardrail Status")
                {
                    ApplicationArea = All;
                }
                field("Needs Approval"; Rec."Needs Approval")
                {
                    ApplicationArea = All;
                }
                field("Guardrail Approver"; Rec."Guardrail Approver")
                {
                    ApplicationArea = All;
                }
                field("Policy Fixed Sell Price"; Rec."Policy Fixed Sell Price")
                {
                    ApplicationArea = All;
                }
                field("Event Note"; Rec."Event Note")
                {
                    ApplicationArea = All;
                }
                field("Previous Customer No."; Rec."Previous Customer No.")
                {
                    ApplicationArea = All;
                }
                field("Previous Quote Date"; Rec."Previous Quote Date")
                {
                    ApplicationArea = All;
                }
                field("Previous Product No."; Rec."Previous Product No.")
                {
                    ApplicationArea = All;
                }
                field("Previous BC Item No."; Rec."Previous BC Item No.")
                {
                    ApplicationArea = All;
                }
                field("Previous UOM Code"; Rec."Previous UOM Code")
                {
                    ApplicationArea = All;
                }
                field("Previous Sell Price"; Rec."Previous Sell Price")
                {
                    ApplicationArea = All;
                }
                field("Previous Landed Cost"; Rec."Previous Landed Cost")
                {
                    ApplicationArea = All;
                }
                field("Previous Quantity"; Rec."Previous Quantity")
                {
                    ApplicationArea = All;
                }
                field("Previous Target GM %"; Rec."Previous Target GM %")
                {
                    ApplicationArea = All;
                }
                field("Previous Guard Status"; Rec."Previous Guard Status")
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
