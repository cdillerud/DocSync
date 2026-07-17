page 70621 "GPI Record Document List"
{
    Caption = 'Record Documents';
    PageType = List;
    SourceTable = "GPI Record Document";
    ApplicationArea = All;
    UsageCategory = None;
    SourceTableView = sorting("Source Table ID", "Source SystemId", "Uploaded Date/Time") order(descending);

    layout
    {
        area(Content)
        {
            repeater(Documents)
            {
                field("Original File Name"; Rec."Original File Name")
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the original filename selected by the user.';
                }
                field(Category; Rec.Category)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies the business category for the document.';
                }
                field(Description; Rec.Description)
                {
                    ApplicationArea = All;
                    ToolTip = 'Specifies an optional description for the document.';
                }
                field(Status; Rec.Status)
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Uploaded Date/Time"; Rec."Uploaded Date/Time")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Uploaded By"; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("File Size"; Rec."File Size")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("SharePoint URL"; Rec."SharePoint URL")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Last Error"; Rec."Last Error")
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
            action(OpenInSharePoint)
            {
                ApplicationArea = All;
                Caption = 'Open in SharePoint';
                Image = Web;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    DocumentMgt: Codeunit "GPI Record Document Mgt.";
                begin
                    DocumentMgt.OpenDocument(Rec."Entry No.");
                end;
            }
        }
    }
}
