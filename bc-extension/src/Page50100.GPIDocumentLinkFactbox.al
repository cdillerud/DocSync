/// <summary>
/// Page 50100 "GPI Document Link Factbox"
/// ListPart factbox showing SharePoint documents linked to a BC record.
/// Supports viewing multiple documents, uploading new files via Hub API,
/// and removing links (soft-delete, SP file preserved).
/// </summary>
page 50100 "GPI Document Link Factbox"
{
    Caption = 'GPI Documents';
    PageType = ListPart;
    SourceTable = "GPI Document Link";
    Editable = false;
    RefreshOnActivate = true;
    ShowFilter = false;

    layout
    {
        area(Content)
        {
            repeater(Documents)
            {
                field(FileName; Rec."File Name")
                {
                    ApplicationArea = All;
                    Caption = 'Document';
                    ToolTip = 'Click to open in SharePoint';
                    StyleExpr = FileNameStyle;

                    trigger OnDrillDown()
                    begin
                        if Rec."SharePoint Url" <> '' then
                            Hyperlink(Rec."SharePoint Url")
                        else
                            Message('No SharePoint link available for this document.');
                    end;
                }
                field(UploadedAt; Rec."Uploaded At")
                {
                    ApplicationArea = All;
                    Caption = 'Date';
                    ToolTip = 'When the document was linked';
                    Width = 8;
                }
                field(UploadedBy; Rec."Uploaded By")
                {
                    ApplicationArea = All;
                    Caption = 'By';
                    ToolTip = 'Who uploaded this document';
                    Width = 10;
                }
                field(Source; Rec.Source)
                {
                    ApplicationArea = All;
                    Caption = 'Source';
                    ToolTip = 'GPI Hub = processed by pipeline, BC Drop = uploaded from BC, Legacy = migrated from Zetadocs';
                    StyleExpr = SourceStyle;
                    Width = 6;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(UploadDocument)
            {
                ApplicationArea = All;
                Caption = 'Upload';
                Image = Attach;
                ToolTip = 'Upload a document to SharePoint and link it to this record (25 MB max)';

                trigger OnAction()
                var
                    DocLinkMgt: Codeunit "GPI Document Link Mgt";
                    TempBlob: Codeunit "Temp Blob";
                    FileInStream: InStream;
                    FileName: Text;
                    FileSize: Integer;
                begin
                    // File picker
                    if not UploadIntoStream('Select document to upload', '', 'All Files (*.*)|*.*', FileName, FileInStream) then
                        exit;

                    if FileName = '' then
                        exit;

                    // Client-side size validation (approximate — true check is server-side)
                    // Note: AL doesn't provide stream length easily, so the Hub enforces 25MB.

                    // Upload via Hub API
                    if DocLinkMgt.UploadFile(
                        CurrentDocType,
                        CurrentBCDocumentNo,
                        FileName,
                        FileInStream,
                        CurrentVendorContext
                    ) then begin
                        // Refresh to show new document
                        DocLinkMgt.RefreshDocumentLinks(CurrentDocType, CurrentBCDocumentNo);
                        CurrPage.Update(false);
                    end;
                end;
            }
            action(OpenDocument)
            {
                ApplicationArea = All;
                Caption = 'Open';
                Image = Document;
                ToolTip = 'Open the selected document in SharePoint';

                trigger OnAction()
                begin
                    if Rec."SharePoint Url" <> '' then
                        Hyperlink(Rec."SharePoint Url")
                    else
                        Message('No SharePoint document link available.');
                end;
            }
            action(RemoveLink)
            {
                ApplicationArea = All;
                Caption = 'Remove Link';
                Image = RemoveLine;
                ToolTip = 'Remove this document link. The file remains in SharePoint for audit.';

                trigger OnAction()
                var
                    DocLinkMgt: Codeunit "GPI Document Link Mgt";
                    ItemId: Text;
                begin
                    if not Confirm('Remove the link for "%1"?\n\nThe file will remain in SharePoint.', false, Rec."File Name") then
                        exit;

                    ItemId := Rec."SharePoint Item Id";
                    if ItemId = '' then
                        ItemId := Format(Rec."Entry No.");

                    if DocLinkMgt.RemoveDocumentLink(
                        CurrentDocType,
                        CurrentBCDocumentNo,
                        ItemId
                    ) then begin
                        // Remove from local table
                        if Rec.Delete(true) then;
                        CurrPage.Update(false);
                    end;
                end;
            }
            action(RefreshLinks)
            {
                ApplicationArea = All;
                Caption = 'Refresh';
                Image = Refresh;
                ToolTip = 'Refresh document links from GPI Hub';

                trigger OnAction()
                var
                    DocLinkMgt: Codeunit "GPI Document Link Mgt";
                begin
                    DocLinkMgt.RefreshDocumentLinks(CurrentDocType, CurrentBCDocumentNo);
                    CurrPage.Update(false);
                end;
            }
        }
    }

    var
        FileNameStyle: Text;
        SourceStyle: Text;
        CurrentDocType: Enum "GPI Doc Link Type";
        CurrentBCDocumentNo: Code[20];
        CurrentVendorContext: Text;

    trigger OnAfterGetRecord()
    begin
        // Style the file name as a clickable link
        if Rec."SharePoint Url" <> '' then
            FileNameStyle := 'Favorable'
        else
            FileNameStyle := 'Subordinate';

        // Style source badge
        case Rec.Source of
            "GPI Doc Link Source"::GPIHub:
                SourceStyle := 'Favorable';  // Green
            "GPI Doc Link Source"::BCDrop:
                SourceStyle := 'Strong';      // Blue
            "GPI Doc Link Source"::ZetadocsLegacy:
                SourceStyle := 'Subordinate'; // Gray
            else
                SourceStyle := 'Standard';
        end;

        // Show filename; fall back to URL segment if empty
        if Rec."File Name" = '' then begin
            if Rec."SharePoint Url" <> '' then
                Rec."File Name" := GetFileNameFromUrl(Rec."SharePoint Url");
        end;
    end;

    trigger OnAfterGetCurrRecord()
    begin
        // Sync with Hub on first load
        SyncFromHub();
    end;

    /// <summary>
    /// Set the context for this factbox from the parent page extension.
    /// Called by the page extension's OnAfterGetCurrRecord.
    /// </summary>
    procedure SetContext(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text)
    begin
        CurrentDocType := DocType;
        CurrentBCDocumentNo := BCDocNo;
        CurrentVendorContext := VendorCtx;
    end;

    local procedure SyncFromHub()
    var
        DocLinkMgt: Codeunit "GPI Document Link Mgt";
    begin
        if CurrentBCDocumentNo = '' then
            exit;

        DocLinkMgt.RefreshDocumentLinks(CurrentDocType, CurrentBCDocumentNo);
    end;

    local procedure GetFileNameFromUrl(Url: Text): Text
    var
        SlashPos: Integer;
        FileName: Text;
    begin
        SlashPos := StrLen(Url);
        while (SlashPos > 0) and (Url[SlashPos] <> '/') do
            SlashPos -= 1;
        if SlashPos > 0 then
            FileName := CopyStr(Url, SlashPos + 1)
        else
            FileName := Url;
        exit(CopyStr(FileName, 1, 250));
    end;
}
