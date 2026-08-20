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
                    ShowMandatory = true;
                    ToolTip = 'Specifies the quoted quantity. A positive quantity is required before pricing guardrails can be evaluated.';

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("UOM Code"; Rec."UOM Code")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
                {
                    ApplicationArea = All;
                    ShowMandatory = true;
                    Style = Strong;
                    ToolTip = 'Specifies the landed cost per unit used for gross-margin calculations. This can be entered directly or copied from a landed-cost worksheet.';

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("Proposed Sell Price"; Rec."Proposed Sell Price")
                {
                    ApplicationArea = All;
                    ShowMandatory = true;
                    Style = Attention;
                    StyleExpr = Rec."Proposed Sell Price" <= 0;
                    ToolTip = 'Enter the proposed customer sell price per unit. Business Central evaluates this price but does not choose it automatically.';

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("Target Gross Margin %"; Rec."Target Gross Margin %")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the target gross margin used for deterministic sell-price guidance and margin exception review.';

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("Suggested Sell Price"; Rec."Suggested Sell Price")
                {
                    ApplicationArea = All;
                    Style = Strong;
                    ToolTip = 'Shows deterministic guidance calculated from landed cost and target gross margin. It does not replace the user-entered proposed sell price.';
                }
                field("Calculated GP %"; Rec."Calculated GP %")
                {
                    ApplicationArea = All;
                    Style = Strong;
                    ToolTip = 'Shows the gross margin produced by the current landed cost and proposed sell price.';
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
                Enabled = LineEvaluationEnabled;

                trigger OnAction()
                var
                    QuoteHeader: Record "GPI Pack Quote";
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    if QuoteHeader.Get(Rec."Quote Entry No.") then
                        if QuoteHeader.Status <> "GPI Pack Quote Stat"::Draft then
                            Error('Reopen the quote to Draft before evaluating a quote line.');

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

    trigger OnAfterGetRecord()
    begin
        UpdateLineEvaluationEnabled();
    end;

    trigger OnAfterGetCurrRecord()
    begin
        UpdateLineEvaluationEnabled();
    end;

    var
        ShowReviewDetails: Boolean;
        LineEvaluationEnabled: Boolean;

    local procedure UpdateLineEvaluationEnabled()
    var
        QuoteHeader: Record "GPI Pack Quote";
    begin
        LineEvaluationEnabled := false;
        if Rec."Quote Entry No." = 0 then
            exit;
        if not QuoteHeader.Get(Rec."Quote Entry No.") then
            exit;

        LineEvaluationEnabled := QuoteHeader.Status = "GPI Pack Quote Stat"::Draft;
    end;
}
