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
                        CurrPage.Update(false);
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
            part(Lines; "GPI Pack Quote Lines")
            {
                ApplicationArea = All;
                SubPageLink = "Quote Entry No." = field("Entry No.");
                UpdatePropagation = Both;
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

                trigger OnAction()
                var
                    QuoteMgt: Codeunit "GPI Pack Quote Mgt";
                begin
                    CurrPage.SaveRecord();
                    QuoteMgt.SetReadyForReview(Rec);
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
