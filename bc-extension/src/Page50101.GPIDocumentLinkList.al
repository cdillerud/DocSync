/// <summary>
/// Page 50101 "GPI Document Link List"
/// List page for viewing all GPI Document Links.
/// Used for administration and troubleshooting.
/// </summary>
page 50101 "GPI Document Link List"
{
    Caption = 'GPI Document Links';
    PageType = List;
    SourceTable = "GPI Document Link";
    ApplicationArea = All;
    UsageCategory = Lists;
    Editable = false;
    CardPageId = "GPI Document Link Card";

    layout
    {
        area(Content)
        {
            repeater(Links)
            {
                field(EntryNo; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'Unique identifier for this link record';
                }
                field(DocumentType; Rec."Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Type of BC document this link is attached to';
                }
                field(BCDocumentNo; Rec."BC Document No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'The BC document number';
                }
                field(SharePointUrl; Rec."SharePoint Url")
                {
                    ApplicationArea = All;
                    ToolTip = 'SharePoint URL for the linked document';
                }
                field(UploadedAt; Rec."Uploaded At")
                {
                    ApplicationArea = All;
                    ToolTip = 'When the document was uploaded';
                }
                field(Source; Rec.Source)
                {
                    ApplicationArea = All;
                    ToolTip = 'Source of the link (GPI Hub or Manual)';
                }
                field(LastError; Rec."Last Error")
                {
                    ApplicationArea = All;
                    ToolTip = 'Last error message if any';
                    Style = Attention;
                    StyleExpr = Rec."Last Error" <> '';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenSharePoint)
            {
                ApplicationArea = All;
                Caption = 'Open in SharePoint';
                Image = Web;
                ToolTip = 'Open the selected document in SharePoint';
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                begin
                    if Rec."SharePoint Url" <> '' then
                        Hyperlink(Rec."SharePoint Url")
                    else
                        Message('No SharePoint URL available for this record.');
                end;
            }
        }
    }
}
