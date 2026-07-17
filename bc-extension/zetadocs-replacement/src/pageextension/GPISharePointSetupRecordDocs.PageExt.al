pageextension 70620 "GPI SP Setup Record Docs" extends "GPI SharePoint Archive Setup"
{
    layout
    {
        addafter("Warehouse Folder")
        {
            field("Record Documents Folder"; Rec."Record Documents Folder")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies the SharePoint folder used for files attached to Business Central records. The default is Record Documents.';
            }
            field("Maximum Upload Size MB"; Rec."Maximum Upload Size MB")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies the maximum record document upload size. The default is 25 MB.';
            }
            field("Blocked Upload Extensions"; Rec."Blocked Upload Extensions")
            {
                ApplicationArea = All;
                ToolTip = 'Specifies semicolon-separated file extensions that cannot be uploaded.';
            }
        }
    }
}
