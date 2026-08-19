page 71011 "GPI Pack Quote Lines"
{
    PageType = ListPart;
    SourceTable = "GPI Pack Quote Line";
    ApplicationArea = All;
    Caption = 'Packaging Quote Lines';
    DelayedInsert = true;
    AutoSplitKey = true;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field("Line No."; Rec."Line No.")
                {
                    ApplicationArea = All;
                    Visible = false;
                }
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central item used for customer pricing guardrails and posted-sales context.';
                }
                field("UOM Code"; Rec."UOM Code")
                {
                    ApplicationArea = All;
                }
                field(Quantity; Rec.Quantity)
                {
                    ApplicationArea = All;
                }
                field("Cost Worksheet Entry No."; Rec."Cost Worksheet Entry No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Links the quote line to a saved landed-cost worksheet and copies its landed cost, quantity, and target margin.';
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
                field("Suggested Sell Price"; Rec."Suggested Sell Price")
                {
                    ApplicationArea = All;
                }
                field("Calculated GP %"; Rec."Calculated GP %")
                {
                    ApplicationArea = All;
                }
                field("Extended Landed Cost"; Rec."Extended Landed Cost")
                {
                    ApplicationArea = All;
                }
                field("Extended Sell"; Rec."Extended Sell")
                {
                    ApplicationArea = All;
                }
                field("Gross Profit Total"; Rec."Gross Profit Total")
                {
                    ApplicationArea = All;
                }
                field("Guardrail Status"; Rec."Guardrail Status")
                {
                    ApplicationArea = All;
                    Style = Attention;
                    StyleExpr = Rec."Needs Approval";
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
                field("Guardrail Message"; Rec."Guardrail Message")
                {
                    ApplicationArea = All;
                }
                field("Evaluated At"; Rec."Evaluated At")
                {
                    ApplicationArea = All;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(EvaluateLine)
            {
                ApplicationArea = All;
                Caption = 'Evaluate Guardrail';
                Image = Calculate;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.EvaluateLine(Rec);
                    Rec.Modify(false);
                    CurrPage.Update(false);
                end;
            }
            action(OpenCostWorksheet)
            {
                ApplicationArea = All;
                Caption = 'Open Landed Cost Worksheet';
                Image = Calculate;
                Enabled = Rec."Cost Worksheet Entry No." <> 0;

                trigger OnAction()
                var
                    CostWork: Record "GPI Pack Cost Work";
                begin
                    CostWork.Get(Rec."Cost Worksheet Entry No.");
                    Page.Run(Page::"GPI Pack Cost Calc", CostWork);
                end;
            }
        }
    }
}
