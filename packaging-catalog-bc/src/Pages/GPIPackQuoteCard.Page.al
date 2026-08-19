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
}
