/// <summary>
/// Page 50100 "GPI Document Link Factbox"
/// CardPart factbox showing SharePoint document link for a BC record.
/// Displays on Purchase Invoice page.
/// </summary>
page 50100 "GPI Document Link Factbox"
{
    Caption = 'GPI Documents';
    PageType = CardPart;
    SourceTable = "GPI Document Link";
    Editable = false;
    RefreshOnActivate = true;

    layout
    {
        area(Content)
        {
            group(DocumentInfo)
            {
                ShowCaption = false;

                field(SharePointUrl; Rec."SharePoint Url")
                {
                    ApplicationArea = All;
                    Caption = 'SharePoint Link';
                    ToolTip = 'Click to open the document in SharePoint';
                    
                    trigger OnDrillDown()
                    begin
                        if Rec."SharePoint Url" <> '' then
                            Hyperlink(Rec."SharePoint Url");
                    end;
                }
                field(UploadedAt; Rec."Uploaded At")
                {
                    ApplicationArea = All;
                    Caption = 'Uploaded';
                    ToolTip = 'Date and time the document was uploaded to SharePoint';
                }
                field(UploadedBy; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                    Caption = 'Uploaded By';
                    ToolTip = 'User or system that uploaded the document';
                    Visible = Rec."Uploaded By" <> '';
                }
                field(Source; Rec.Source)
                {
                    ApplicationArea = All;
                    Caption = 'Source';
                    ToolTip = 'Where this link was created from';
                }
            }
            group(NoDocument)
            {
                ShowCaption = false;
                Visible = not HasDocument;

                label(NoDocumentLabel)
                {
                    ApplicationArea = All;
                    Caption = 'No linked document';
                    Style = Subordinate;
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
                Caption = 'Open Document';
                Image = Document;
                ToolTip = 'Open the linked SharePoint document in a new browser tab';
                Enabled = HasDocument;

                trigger OnAction()
                begin
                    if Rec."SharePoint Url" <> '' then
                        Hyperlink(Rec."SharePoint Url")
                    else
                        Message('No SharePoint document link available.');
                end;
            }
            action(Refresh)
            {
                ApplicationArea = All;
                Caption = 'Refresh';
                Image = Refresh;
                ToolTip = 'Refresh the document link information';

                trigger OnAction()
                begin
                    CurrPage.Update(false);
                end;
            }
        }
    }

    var
        HasDocument: Boolean;

    trigger OnAfterGetRecord()
    begin
        HasDocument := Rec."SharePoint Url" <> '';
    end;

    trigger OnAfterGetCurrRecord()
    begin
        HasDocument := Rec."SharePoint Url" <> '';
    end;
}
