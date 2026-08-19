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
                }
                field("Line Count"; Rec."Line Count")
                {
                    ApplicationArea = All;
                }
                field("Approval Line Count"; Rec."Approval Line Count")
                {
                    ApplicationArea = All;
                }
                field("Last Evaluated At"; Rec."Last Evaluated At")
                {
                    ApplicationArea = All;
                }
                field("Last Evaluated By"; Rec."Last Evaluated By")
                {
                    ApplicationArea = All;
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
                }
                field("Decision By"; Rec."Decision By")
                {
                    ApplicationArea = All;
                }
                field("Audit Count"; Rec."Audit Count")
                {
                    ApplicationArea = All;
                }
            }
            part(Lines; "GPI Pack Quote Lines")
            {
                ApplicationArea = All;
                SubPageLink = "Quote Entry No." = field("Entry No.");
                UpdatePropagation = Both;
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
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Ready;

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
                Enabled = Rec.Status = "GPI Pack Quote Stat"::Ready;

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
