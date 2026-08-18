page 71003 "GPI Pack Price History"
{
    PageType = ListPart;
    SourceTable = "GPI Pack Price History";
    ApplicationArea = All;
    Caption = 'GPI Packaging Price History';
    Editable = false;

    layout
    {
        area(Content)
        {
            repeater(History)
            {
                field("Effective Date"; Rec."Effective Date")
                {
                    ApplicationArea = All;
                }
                field("Old Unit Cost"; Rec."Old Unit Cost")
                {
                    ApplicationArea = All;
                }
                field("New Unit Cost"; Rec."New Unit Cost")
                {
                    ApplicationArea = All;
                }
                field("Old Metric Ton Cost"; Rec."Old Metric Ton Cost")
                {
                    ApplicationArea = All;
                }
                field("New Metric Ton Cost"; Rec."New Metric Ton Cost")
                {
                    ApplicationArea = All;
                }
                field(Note; Rec.Note)
                {
                    ApplicationArea = All;
                }
                field("Changed At"; Rec."Changed At")
                {
                    ApplicationArea = All;
                }
            }
        }
    }
}
