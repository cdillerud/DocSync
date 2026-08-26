page 50190 "GPI Hub Setup"
{
    Caption = 'GPI Hub Setup';
    PageType = Card;
    SourceTable = "GPI Hub Setup";
    ApplicationArea = All;
    UsageCategory = Administration;
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            group(Connection)
            {
                Caption = 'Connection';

                field("Hub Base URL"; Rec."Hub Base URL")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the HTTPS base URL of the GPI Document Hub API, including /api and without a trailing slash. Configure UAT and Production independently.';
                }
            }
        }
    }

    trigger OnOpenPage()
    begin
        EnsureSetupRecord();
    end;

    local procedure EnsureSetupRecord()
    begin
        if Rec.Get('SETUP') then
            exit;

        Rec.Init();
        Rec."Primary Key" := 'SETUP';
        Rec.Insert(true);
    end;
}
