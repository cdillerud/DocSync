pageextension 70520 "GPI Invoice Sender Setup" extends "GPI Posted Invoice Queue"
{
    layout
    {
        addfirst(Content)
        {
            group(GPIAccountingInvoiceSender)
            {
                Caption = 'Accounting Invoice Sender';

                field(GPIAccountingSenderStatus; AccountingSenderStatus)
                {
                    ApplicationArea = All;
                    Caption = 'Status';
                    Editable = false;
                    StyleExpr = AccountingSenderStyle;
                    ToolTip = 'Shows whether the GPI Invoice Batch email scenario is assigned to an Accounting email account.';
                }

                field(GPIAccountingSenderName; AccountingSenderName)
                {
                    ApplicationArea = All;
                    Caption = 'Account Name';
                    Editable = false;
                    ToolTip = 'Shows the Business Central email account assigned to the GPI Invoice Batch scenario.';
                }

                field(GPIAccountingSenderEmail; AccountingSenderEmail)
                {
                    ApplicationArea = All;
                    Caption = 'Sender Email Address';
                    Editable = false;
                    ToolTip = 'Shows the email address used to send invoice batches.';
                }

                field(GPIAccountingSenderConnector; AccountingSenderConnector)
                {
                    ApplicationArea = All;
                    Caption = 'Connector';
                    Editable = false;
                    ToolTip = 'Shows the connector used by the assigned Accounting email account.';
                }
            }
        }
    }

    actions
    {
        addfirst(Processing)
        {
            action(GPIConfigureAccountingSender)
            {
                ApplicationArea = All;
                Caption = 'Configure Accounting Sender';
                Image = Setup;
                Promoted = true;
                PromotedCategory = Process;
                ToolTip = 'Opens Email Scenario Assignment so GPI Invoice Batch can be assigned to the Accounting invoice mailbox.';

                trigger OnAction()
                begin
                    Page.RunModal(Page::"Email Scenario Setup");
                    RefreshAccountingSender();
                    CurrPage.Update(false);
                end;
            }

            action(GPIRefreshAccountingSender)
            {
                ApplicationArea = All;
                Caption = 'Refresh Accounting Sender';
                Image = Refresh;
                ToolTip = 'Refreshes the Accounting invoice sender shown on this page.';

                trigger OnAction()
                begin
                    RefreshAccountingSender();
                    CurrPage.Update(false);
                end;
            }
        }
    }

    trigger OnOpenPage()
    begin
        RefreshAccountingSender();
    end;

    local procedure RefreshAccountingSender()
    var
        EmailScenario: Codeunit "Email Scenario";
        EmailAccount: Record "Email Account";
    begin
        Clear(AccountingSenderName);
        Clear(AccountingSenderEmail);
        Clear(AccountingSenderConnector);

        if not EmailScenario.IsThereEmailAccountSetForScenario(Enum::"Email Scenario"::"GPI Invoice Batch") then begin
            AccountingSenderStatus := 'Not configured';
            AccountingSenderStyle := 'Unfavorable';
            exit;
        end;

        EmailScenario.GetEmailAccount(Enum::"Email Scenario"::"GPI Invoice Batch", EmailAccount);
        AccountingSenderStatus := 'Configured';
        AccountingSenderStyle := 'Favorable';
        AccountingSenderName := EmailAccount.Name;
        AccountingSenderEmail := EmailAccount."Email Address";
        AccountingSenderConnector := Format(EmailAccount.Connector);
    end;

    var
        AccountingSenderStatus: Text[50];
        AccountingSenderName: Text[250];
        AccountingSenderEmail: Text[250];
        AccountingSenderConnector: Text[100];
        AccountingSenderStyle: Text;
}
