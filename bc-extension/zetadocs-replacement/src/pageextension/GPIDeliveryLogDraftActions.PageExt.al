pageextension 70527 "GPI Delivery Log Drafts Ext" extends "GPI Document Delivery Log"
{
    actions
    {
        addafter(DownloadPDF)
        {
            action(GPIOpenDraftEmail)
            {
                ApplicationArea = All;
                Caption = 'Open Draft Email';
                Image = Email;
                Enabled = OpenDraftEnabled;
                ToolTip = 'Reopens the exact native Business Central email draft linked to this delivery log entry.';

                trigger OnAction()
                var
                    DraftEmailMgt: Codeunit "GPI Draft Email Mgt.";
                begin
                    DraftEmailMgt.OpenDraft(Rec);
                    CurrPage.Update(false);
                end;
            }

            action(GPIOpenEmailOutbox)
            {
                ApplicationArea = All;
                Caption = 'Email Outbox';
                Image = Email;
                RunObject = page "Email Outbox";
                ToolTip = 'Opens the native Business Central Email Outbox to review all drafts, queued messages, and failed emails available to the current user.';
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        OpenDraftEnabled :=
            (Rec.Status = Rec.Status::"Saved As Draft") and
            not IsNullGuid(Rec."Email Message ID");
    end;

    var
        OpenDraftEnabled: Boolean;
}
