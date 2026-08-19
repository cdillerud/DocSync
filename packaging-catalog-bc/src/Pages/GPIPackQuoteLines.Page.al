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
                    ToolTip = 'Specifies the Gamer packaging product on this quote line.';
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field(Quantity; Rec.Quantity)
                {
                    ApplicationArea = All;
                }
                field("UOM Code"; Rec."UOM Code")
                {
                    ApplicationArea = All;
                }
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
                field("Proposed Sell Price"; Rec."Proposed Sell Price")
                {
                    ApplicationArea = All;
                    Style = Strong;
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
                field("Guardrail Status"; Rec."Guardrail Status")
                {
                    ApplicationArea = All;
                    Style = Attention;
                    StyleExpr = Rec."Needs Approval";
                }
                field("Needs Approval"; Rec."Needs Approval")
                {
                    ApplicationArea = All;
                    Style = Unfavorable;
                    StyleExpr = Rec."Needs Approval";
                }
                field("BC Item No."; Rec."BC Item No.")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Specifies the Business Central item used for customer pricing guardrails and posted-sales context.';
                }
                field("Cost Worksheet Entry No."; Rec."Cost Worksheet Entry No.")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Links the quote line to a saved landed-cost worksheet and copies its landed cost, quantity, and target margin.';
                }
                field("Extended Landed Cost"; Rec."Extended Landed Cost")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Extended Sell"; Rec."Extended Sell")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Gross Profit Total"; Rec."Gross Profit Total")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Guardrail Approver"; Rec."Guardrail Approver")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Policy Fixed Sell Price"; Rec."Policy Fixed Sell Price")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Guardrail Message"; Rec."Guardrail Message")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Customer Hist Lines"; Rec."Customer Hist Lines")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Shows exact posted sales history line count for this customer, BC item, and UOM through the quote date.';
                }
                field("Customer Hist Median"; Rec."Customer Hist Median")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Shows the median sell price from up to the five most recent exact customer, item, and UOM posted sales lines.';
                }
                field("Customer Hist Var %"; Rec."Customer Hist Var %")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Shows the proposed sell price variance from the customer recent-history median.';
                }
                field("Customer Hist Last Date"; Rec."Customer Hist Last Date")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("All Cust Hist Lines"; Rec."All Cust Hist Lines")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Shows exact item and UOM history across all customers. This is context only and never drives an approval by itself.';
                }
                field("All Cust Hist Median"; Rec."All Cust Hist Median")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                    ToolTip = 'Shows the recent all-customer median for this item and UOM. This is context only.';
                }
                field("History Message"; Rec."History Message")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
                }
                field("Evaluated At"; Rec."Evaluated At")
                {
                    ApplicationArea = All;
                    Visible = ShowReviewDetails;
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
                    QuoteHeader: Record "GPI Pack Quote";
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    if QuoteHeader.Get(Rec."Quote Entry No.") then
                        if QuoteHeader.Status in ["GPI Pack Quote Stat"::Approved, "GPI Pack Quote Stat"::Rejected, "GPI Pack Quote Stat"::Expired] then
                            Error('Reopen the quote to Draft before evaluating a decided quote line.');

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
            action(ToggleReviewDetails)
            {
                ApplicationArea = All;
                Caption = 'Show/Hide Review Details';

                trigger OnAction()
                begin
                    ShowReviewDetails := not ShowReviewDetails;
                    CurrPage.Update(false);
                end;
            }
        }
    }

    var
        ShowReviewDetails: Boolean;
}
