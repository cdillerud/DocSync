/// <summary>
/// Page 50102 "GPI Document Link Card"
/// Card page for viewing/editing a single GPI Document Link.
/// </summary>
page 50102 "GPI Document Link Card"
{
    Caption = 'GPI Document Link';
    PageType = Card;
    SourceTable = "GPI Document Link";
    ApplicationArea = All;

    layout
    {
        area(Content)
        {
            group(General)
            {
                Caption = 'General';

                field(EntryNo; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    Editable = false;
                    ToolTip = 'Unique identifier for this link record';
                }
                field(DocumentType; Rec."Document Type")
                {
                    ApplicationArea = All;
                    ToolTip = 'Type of BC document this link is attached to';
                }
                field(TargetSystemId; Rec."Target SystemId")
                {
                    ApplicationArea = All;
                    ToolTip = 'SystemId of the target BC record';
                }
                field(BCDocumentNo; Rec."BC Document No.")
                {
                    ApplicationArea = All;
                    ToolTip = 'The BC document number';
                }
            }
            group(SharePoint)
            {
                Caption = 'SharePoint';

                field(SharePointUrl; Rec."SharePoint Url")
                {
                    ApplicationArea = All;
                    ToolTip = 'SharePoint URL for the linked document';
                    ExtendedDatatype = URL;
                }
                field(SharePointDriveId; Rec."SharePoint Drive Id")
                {
                    ApplicationArea = All;
                    ToolTip = 'SharePoint Drive ID';
                }
                field(SharePointItemId; Rec."SharePoint Item Id")
                {
                    ApplicationArea = All;
                    ToolTip = 'SharePoint Item ID';
                }
            }
            group(Audit)
            {
                Caption = 'Audit';

                field(UploadedAt; Rec."Uploaded At")
                {
                    ApplicationArea = All;
                    ToolTip = 'When the document was uploaded';
                }
                field(UploadedBy; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                    ToolTip = 'Who uploaded the document';
                }
                field(Source; Rec.Source)
                {
                    ApplicationArea = All;
                    ToolTip = 'Source of the link';
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
                ToolTip = 'Open the document in SharePoint';
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                begin
                    if Rec."SharePoint Url" <> '' then
                        Hyperlink(Rec."SharePoint Url")
                    else
                        Message('No SharePoint URL available.');
                end;
            }
        }
    }
}
