pageextension 70150004 "GPI Sales Order Ext" extends "Sales Order"
{
    actions
    {
        addlast(Processing)
        {
            action(GPIPreviewOrderConfirmation)
            {
                ApplicationArea = All;
                Caption = 'Preview GPI Order Confirmation';
                Image = ViewReport;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Requests deterministic delivery routing from GPI Hub and opens a read-only email and PDF preview. This Sprint 1 action does not create or send an email and does not write to SharePoint.';

                trigger OnAction()
                var
                    Preflight: Codeunit "GPI SO Confirm Preflight";
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    Preflight.Preview(SalesHeader);
                end;
            }
        }
    }
}
