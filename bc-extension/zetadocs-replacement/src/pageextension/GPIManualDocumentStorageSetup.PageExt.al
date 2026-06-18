pageextension 70522 "GPI Manual Doc Storage Setup" extends "GPI SharePoint Archive Setup"
{
    layout
    {
        addafter(ConnectionTest)
        {
            group(ManualDocumentStorage)
            {
                Caption = 'Drag-and-Drop Documents';

                field(ManualDocumentStorageInfo; ManualDocumentStorageInfo)
                {
                    ApplicationArea = All;
                    Caption = 'Configuration';
                    Editable = false;
                    MultiLine = true;
                    ToolTip = 'Explains how Business Central document attachments are stored in SharePoint.';
                }
            }
        }
    }

    actions
    {
        addafter(AssignArchiveScenario)
        {
            action(ConfigureManualDocumentStorage)
            {
                ApplicationArea = All;
                Caption = 'Configure Drag-and-Drop Storage';
                Image = Attach;
                ToolTip = 'Assigns the standard Doc. Attach. - External Storage scenario to the SharePoint file account used for manual document uploads.';

                trigger OnAction()
                begin
                    Page.RunModal(Page::"File Scenario Setup");
                    Message('Assign Doc. Attach. - External Storage to the GPI Document Archive SharePoint account. Business Central will then prompt for the external attachment storage setup.');
                end;
            }
        }
    }

    trigger OnOpenPage()
    begin
        ManualDocumentStorageInfo :=
            'Business Central''s standard Documents factboxes support multiple-file upload and drag-and-drop. ' +
            'Assign the Doc. Attach. - External Storage scenario to the GPI Document Archive SharePoint account, ' +
            'then select a root folder such as Manual Documents.';
    end;

    var
        ManualDocumentStorageInfo: Text[1024];
}
