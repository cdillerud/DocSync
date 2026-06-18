page 70518 "GPI Linked Documents"
{
    Caption = 'GPI Linked Documents';
    PageType = List;
    SourceTable = "GPI Linked Document";
    ApplicationArea = All;
    UsageCategory = None;
    InsertAllowed = false;
    DeleteAllowed = false;

    layout
    {
        area(Content)
        {
            repeater(Documents)
            {
                field("File Name"; Rec."File Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the filename stored in SharePoint.';

                    trigger OnDrillDown()
                    begin
                        OpenInSharePoint();
                    end;
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies an optional description for the document.';
                }
                field(Category; Rec.Category)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies an optional category for the document.';
                }
                field("Uploaded Date/Time"; Rec."Uploaded Date/Time")
                {
                    ApplicationArea = All;
                }
                field("Uploaded By"; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                }
                field("File Size"; Rec."File Size")
                {
                    ApplicationArea = All;
                    Visible = false;
                }
                field("Source Document No."; Rec."Source Document No.")
                {
                    ApplicationArea = All;
                    Visible = false;
                }
                field("Archive Path"; Rec."Archive Path")
                {
                    ApplicationArea = All;
                    Visible = false;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenDocument)
            {
                ApplicationArea = All;
                Caption = 'Open in SharePoint';
                Image = Web;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                begin
                    OpenInSharePoint();
                end;
            }
        }
    }

    local procedure OpenInSharePoint()
    begin
        if Rec."SharePoint URL" = '' then
            Error('This linked document does not have a SharePoint URL.');
        Hyperlink(Rec."SharePoint URL");
    end;
}
