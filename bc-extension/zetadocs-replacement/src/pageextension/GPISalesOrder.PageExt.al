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
                ToolTip = 'Creates the Gamer-owned Sales Order Confirmation as a PDF, attaches it to a native Business Central email, and opens the email for review. Nothing is sent automatically.';

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
                ToolTip = 'Creates the Gamer-owned Prepayment Notice as a PDF, attaches it to a native Business Central email, and opens the email for review. Nothing is sent automatically.';

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

            action(GPIEmailPickTicket)
            {
                ApplicationArea = All;
                Caption = 'Preview and Email Pick Ticket';
                Image = Email;
                Promoted = true;
                PromotedCategory = Process;
                PromotedIsBig = true;
                ToolTip = 'Creates report 50013 as a PDF, sends it to the email addresses on the Sales Order location, and opens the native Business Central email for review. Nothing is sent automatically.';

                trigger OnAction()
                var
                    SalesOrderEmail: Codeunit "GPI Sales Order Email";
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesOrderEmail.OpenPickTicketDraft(SalesHeader);
                end;
            }

            action(GPIPreviewOwnedOrderConfirmation)
            {
                ApplicationArea = All;
                Caption = 'Preview GPI-Owned Order Confirmation';
                Image = Print;
                Promoted = false;
                ToolTip = 'Previews the Gamer-owned Sales Order Confirmation report 70520. It does not create or send an email.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesHeader.SetRecFilter();
                    Report.RunModal(Report::"GPI Sales Order Confirmation", true, false, SalesHeader);
                end;
            }

            action(GPIPreviewOwnedPrepaymentNotice)
            {
                ApplicationArea = All;
                Caption = 'Preview GPI-Owned Prepayment Notice';
                Image = Print;
                Promoted = false;
                ToolTip = 'Previews the Gamer-owned Prepayment Notice report 70521. It does not create or send an email.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesHeader.SetRecFilter();
                    Report.RunModal(Report::"GPI Prepayment Notice", true, false, SalesHeader);
                end;
            }

            action(GPIPreviewOwnedPickTicket)
            {
                ApplicationArea = All;
                Caption = 'Preview GPI-Owned Pick Ticket';
                Image = Print;
                Promoted = false;
                ToolTip = 'Previews the Gamer-owned Pick Ticket report 70522. It does not create or send an email.';

                trigger OnAction()
                var
                    SalesHeader: Record "Sales Header";
                begin
                    CurrPage.SaveRecord();
                    SalesHeader.Get(Rec."Document Type", Rec."No.");
                    SalesHeader.SetRecFilter();
                    Report.RunModal(Report::"GPI Pick Ticket", true, false, SalesHeader);
                end;
            }
        }
    }
}
