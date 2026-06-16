pageextension 70510 "GPI Sales Order Email Ext" extends "Sales Order"
{
    actions
    {
        addlast(Processing)
        {
            action(GPIEmailOrderConfirmation)
            {
                ApplicationArea = All;
                Caption = 'Preview and Email Order Confirmation';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Creates report 50020 as a PDF, attaches it to a native Business Central email, and opens the email for review. Nothing is sent automatically.';

                trigger OnAction()
                var
                    SalesOrderEmail: Codeunit "GPI Sales Order Email";
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesOrderEmail.OpenSalesOrderConfirmationDraft(SalesHeader);
                end;
            }

            action(GPIEmailPrepaymentNotice)
            {
                ApplicationArea = All;
                Caption = 'Preview and Email Prepayment Notice';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Creates report 50003 as a PDF, attaches it to a native Business Central email, and opens the email for review. Nothing is sent automatically.';

                trigger OnAction()
                var
                    SalesOrderEmail: Codeunit "GPI Sales Order Email";
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesOrderEmail.OpenPrepaymentNoticeDraft(SalesHeader);
                end;
            }
        }
    }
}
