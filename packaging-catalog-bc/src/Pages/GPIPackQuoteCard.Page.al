page 71010 "GPI Pack Quote Card"
{
    PageType = Document;
    SourceTable = "GPI Pack Quote";
    ApplicationArea = All;
    Caption = 'GPI Packaging Quote';

    layout
    {
        area(Content)
        {
            group(General)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Quote Date"; Rec."Quote Date")
                {
                    ApplicationArea = All;
                }
                field("Expiration Date"; Rec."Expiration Date")
                {
                    ApplicationArea = All;
                }
                field("Customer No."; Rec."Customer No.")
                {
                    ApplicationArea = All;
                    ShowMandatory = true;
                    ToolTip = 'Specifies the customer whose protected pricing and exact posted sales history are evaluated for this quote.';

                    trigger OnValidate()
                    begin
                        CurrPage.Update(true);
                    end;
                }
                field("Customer Name"; Rec."Customer Name")
                {
                    ApplicationArea = All;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    Editable = false;
                    Style = Strong;
                }
                field("Line Count"; Rec."Line Count")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Approval Line Count"; Rec."Approval Line Count")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Style = Attention;
                    StyleExpr = Rec."Approval Line Count" > 0;
                }
            }
            part(Lines; "GPI Pack Quote Lines")
            {
                ApplicationArea = All;
                Caption = 'Packaging Quote Lines';
                SubPageLink = "Quote Entry No." = field("Entry No.");
                UpdatePropagation = Both;
            }
            group(Review)
            {
                Caption = 'Commercial Review';

                field(CommercialReviewStatus; CommercialReviewStatus)
                {
                    ApplicationArea = All;
                    Caption = 'Review Status';
                    Editable = false;
                    Style = Attention;
                    StyleExpr = ReviewNeedsAttention;
                    ToolTip = 'Summarizes the next commercial step, including missing customer or line inputs, guardrail evaluation, approval, or final decision status.';
                }
                field("Total Landed Cost"; Rec."Total Landed Cost")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Style = Strong;
                }
                field("Total Sell"; Rec."Total Sell")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Style = Strong;
                }
                field(DisplayGrossProfitTotal; DisplayGrossProfitTotal)
                {
                    ApplicationArea = All;
                    Caption = 'Gross Profit Total';
                    Editable = false;
                    ToolTip = 'Shows quote gross profit after every quote line has a positive proposed sell price. It remains zero while pricing is incomplete.';
                }
                field(OverallGrossMarginPct; OverallGrossMarginPct)
                {
                    ApplicationArea = All;
                    Caption = 'Overall Gross Margin %';
                    DecimalPlaces = 0 : 2;
                    Editable = false;
                    Style = Strong;
                    ToolTip = 'Shows total quote gross profit divided by total proposed sell after every quote line has a positive proposed sell price.';
                }
                field("Last Evaluated At"; Rec."Last Evaluated At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Last Evaluated By"; Rec."Last Evaluated By")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field(Notes; Rec.Notes)
                {
                    ApplicationArea = All;
                    MultiLine = true;
                }
            }
            group(Decision)
            {
                Caption = 'Approval Decision';

                field("Decision Note"; Rec."Decision Note")
                {
                    ApplicationArea = All;
                    MultiLine = true;
                    ToolTip = 'Enter the commercial approval or rejection rationale. A note is required when approving a pricing exception and for all rejections.';
                }
                field("Decision At"; Rec."Decision At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Decision By"; Rec."Decision By")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Audit Count"; Rec."Audit Count")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
            }
            part(AuditHistory; "GPI Quote Audits")
            {
                ApplicationArea = All;
                Caption = 'Approval and Audit History';
                SubPageLink = "Quote Entry No." = field("Entry No.");
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(EvaluateAll)
            {
                ApplicationArea = All;
                Caption = 'Evaluate All Guardrails';
                Image = Calculate;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.EvaluateQuote(Rec);
                    UpdateCommercialReview();
                    CurrPage.Update(false);
                end;
            }
            action(ReadyForReview)
            {
                ApplicationArea = All;
                Caption = 'Ready for Review';
                Image = SendApprovalRequest;
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Draft;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.SetReadyForReview(Rec);
                    UpdateCommercialReview();
                    CurrPage.Update(false);
                end;
            }
            action(ApproveQuote)
            {
                ApplicationArea = All;
                Caption = 'Approve Quote';
                Image = Approve;
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Ready;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.ApproveQuote(Rec);
                    UpdateCommercialReview();
                    CurrPage.Update(false);
                end;
            }
            action(RejectQuote)
            {
                ApplicationArea = All;
                Caption = 'Reject Quote';
                Image = Reject;
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Ready;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.RejectQuote(Rec);
                    UpdateCommercialReview();
                    CurrPage.Update(false);
                end;
            }
            action(Reopen)
            {
                ApplicationArea = All;
                Caption = 'Reopen Draft';
                Image = ReOpen;
                Enabled = Rec.Status <> "GPI Pack Quote Stat"::Draft;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    QuoteMgt.ReopenQuote(Rec);
                    UpdateCommercialReview();
                    CurrPage.Update(false);
                end;
            }
            action(PricingGuardrails)
            {
                ApplicationArea = All;
                Caption = 'Pricing Guardrails';
                Image = Price;
                RunObject = page "GPI Pricing Guards";
            }
            action(LandedCostWorksheets)
            {
                ApplicationArea = All;
                Caption = 'Landed Cost Worksheets';
                Image = Calculate;
                RunObject = page "GPI Pack Cost Works";
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        UpdateCommercialReview();
    end;

    trigger OnAfterGetCurrRecord()
    begin
        UpdateCommercialReview();
    end;

    var
        OverallGrossMarginPct: Decimal;
        DisplayGrossProfitTotal: Decimal;
        CommercialReviewStatus: Text[50];
        ReviewNeedsAttention: Boolean;
        HasUnpricedLines: Boolean;
        HasIncompleteLineInputs: Boolean;

    local procedure UpdateCommercialReview()
    var
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        Rec.CalcFields("Total Landed Cost", "Total Sell", "Gross Profit Total", "Approval Line Count", "Line Count");

        HasUnpricedLines := false;
        HasIncompleteLineInputs := false;
        QuoteLine.SetRange("Quote Entry No.", Rec."Entry No.");
        if QuoteLine.FindSet() then
            repeat
                if QuoteLine."Proposed Sell Price" <= 0 then
                    HasUnpricedLines := true;
                if (QuoteLine.Quantity <= 0) or (QuoteLine."Landed Cost per Unit" <= 0) then
                    HasIncompleteLineInputs := true;
            until QuoteLine.Next() = 0;

        if (not HasUnpricedLines) and (Rec."Total Sell" > 0) then begin
            DisplayGrossProfitTotal := Rec."Gross Profit Total";
            OverallGrossMarginPct := Round((Rec."Gross Profit Total" / Rec."Total Sell") * 100, 0.01);
        end else begin
            DisplayGrossProfitTotal := 0;
            OverallGrossMarginPct := 0;
        end;

        ReviewNeedsAttention := false;

        case Rec.Status of
            "GPI Pack Quote Stat"::Approved:
                CommercialReviewStatus := 'Approved';
            "GPI Pack Quote Stat"::Rejected:
                begin
                    CommercialReviewStatus := 'Rejected';
                    ReviewNeedsAttention := true;
                end;
            "GPI Pack Quote Stat"::Expired:
                begin
                    CommercialReviewStatus := 'Expired';
                    ReviewNeedsAttention := true;
                end;
            "GPI Pack Quote Stat"::Ready:
                begin
                    if Rec."Approval Line Count" > 0 then begin
                        CommercialReviewStatus := 'Ready, approval required';
                        ReviewNeedsAttention := true;
                    end else
                        CommercialReviewStatus := 'Ready for review';
                end;
            else begin
                if Rec."Line Count" = 0 then begin
                    CommercialReviewStatus := 'Add a quote line';
                    ReviewNeedsAttention := true;
                end else
                    if Rec."Customer No." = '' then begin
                        CommercialReviewStatus := 'Customer required';
                        ReviewNeedsAttention := true;
                    end else
                        if HasIncompleteLineInputs then begin
                            CommercialReviewStatus := 'Line inputs incomplete';
                            ReviewNeedsAttention := true;
                        end else
                            if HasUnpricedLines then begin
                                CommercialReviewStatus := 'Proposed sell required';
                                ReviewNeedsAttention := true;
                            end else
                                if Rec."Last Evaluated At" = 0DT then
                                    CommercialReviewStatus := 'Ready to evaluate'
                                else
                                    if Rec."Approval Line Count" > 0 then begin
                                        CommercialReviewStatus := 'Approval required';
                                        ReviewNeedsAttention := true;
                                    end else
                                        CommercialReviewStatus := 'Within policy';
            end;
        end;
    end;
}
