page 71104 "GPI Spiro Cust Maps"
{
    PageType = List;
    SourceTable = "GPI Spiro Cust Map";
    ApplicationArea = All;
    UsageCategory = Administration;
    Caption = 'GPI Spiro Customer Mappings';

    layout
    {
        area(Content)
        {
            repeater(Mappings)
            {
                field("BC Customer No."; Rec."BC Customer No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the Business Central customer mapped to a Spiro company.';
                }
                field("BC Customer Name"; Rec."BC Customer Name")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("BC Customer SystemId"; Rec."BC Customer SystemId")
                {
                    ApplicationArea = All;
                    Editable = false;
                    Visible = false;
                }
                field("Spiro Company ID"; Rec."Spiro Company ID")
                {
                    ApplicationArea = All;
                }
                field("Spiro Company Name"; Rec."Spiro Company Name")
                {
                    ApplicationArea = All;
                }
                field("Spiro Company URL"; Rec."Spiro Company URL")
                {
                    ApplicationArea = All;
                }
                field("Last Synced At"; Rec."Last Synced At")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Last Synced By"; Rec."Last Synced By")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenSpiroCompany)
            {
                ApplicationArea = All;
                Caption = 'Open Spiro Company';
                Image = LinkWeb;
                Enabled = Rec."Spiro Company URL" <> '';

                trigger OnAction()
                begin
                    if Rec."Spiro Company URL" = '' then
                        Error('No Spiro company URL is stored for this mapping.');
                    Hyperlink(Rec."Spiro Company URL");
                end;
            }
        }
    }
}
