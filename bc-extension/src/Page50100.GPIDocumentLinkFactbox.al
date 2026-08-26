/// <summary>
/// Page 50100 "GPI Document Link Factbox"
/// Native CardPart factbox for BC SaaS — no control add-ins.
/// Exact-record reads and uploads carry immutable BC SystemId and Hub M2M auth.
/// </summary>
page 50100 "GPI Document Link Factbox"
{
    Caption = 'GPI Documents';
    PageType = CardPart;
    Editable = false;
    RefreshOnActivate = true;

    layout
    {
        area(Content)
        {
            group(Summary)
            {
                ShowCaption = false;

                field(DocumentCount; DocumentCountText)
                {
                    ApplicationArea = All;
                    Caption = 'Linked Documents';
                    ToolTip = 'Number of documents linked to this record in GPI Hub.';
                    Style = Strong;
                    StyleExpr = HasDocuments;
                }
                field(LatestFile; LatestFileName)
                {
                    ApplicationArea = All;
                    Caption = 'Latest';
                    ToolTip = 'Most recently linked document.';
                }
                field(LatestDate; LatestDateText)
                {
                    ApplicationArea = All;
                    Caption = 'Date';
                    ToolTip = 'Date of the most recently linked document.';
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(OpenInHub)
            {
                ApplicationArea = All;
                Caption = 'View All';
                ToolTip = 'Open linked documents in the authenticated GPI Hub browser experience.';
                Image = ViewDocumentLine;

                trigger OnAction()
                begin
                    OpenFactboxInBrowser();
                end;
            }
            action(RefreshLinks)
            {
                ApplicationArea = All;
                Caption = 'Refresh';
                ToolTip = 'Refresh document links from GPI Hub.';
                Image = Refresh;

                trigger OnAction()
                begin
                    FetchDocumentLinks();
                end;
            }
            action(UploadFile)
            {
                ApplicationArea = All;
                Caption = 'Upload File';
                ToolTip = 'Upload a document to GPI Hub for this exact Business Central record.';
                Image = Attach;
                Enabled = HasExactIdentity;

                trigger OnAction()
                var
                    GPILinkMgt: Codeunit "GPI Document Link Mgt";
                    FileInStream: InStream;
                    FileName: Text;
                begin
                    if CurrentBCDocumentNo = '' then
                        exit;
                    if IsNullGuid(CurrentBCSystemId) then
                        Error('BC SystemId is required before a document can be uploaded.');

                    if not UploadIntoStream('Select file to upload', '', 'All Files (*.*)|*.*', FileName, FileInStream) then
                        exit;

                    if GPILinkMgt.UploadFile(
                        CurrentDocType,
                        CurrentBCDocumentNo,
                        CurrentBCSystemId,
                        GetSourceTableId(),
                        GetSourceDocumentType(),
                        FileName,
                        FileInStream,
                        CurrentVendorContext)
                    then
                        FetchDocumentLinks();
                end;
            }
        }
    }

    var
        CurrentDocType: Enum "GPI Doc Link Type";
        CurrentBCDocumentNo: Code[20];
        CurrentBCSystemId: Guid;
        CurrentVendorContext: Text;
        DocumentCountText: Text;
        LatestFileName: Text;
        LatestDateText: Text;
        HasDocuments: Boolean;
        HasExactIdentity: Boolean;

    procedure SetContext(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text)
    begin
        Clear(CurrentBCSystemId);
        HasExactIdentity := false;
        SetContextInternal(DocType, BCDocNo, VendorCtx);
    end;

    procedure SetContext(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text; BCSystemId: Guid)
    begin
        CurrentBCSystemId := BCSystemId;
        HasExactIdentity := not IsNullGuid(CurrentBCSystemId);
        SetContextInternal(DocType, BCDocNo, VendorCtx);
    end;

    local procedure SetContextInternal(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text)
    begin
        CurrentDocType := DocType;
        CurrentBCDocumentNo := BCDocNo;
        CurrentVendorContext := VendorCtx;
        FetchDocumentLinks();
    end;

    local procedure GetSourceTableId(): Integer
    begin
        case CurrentDocType of
            "GPI Doc Link Type"::"Purchase Invoice":
                exit(38);
            "GPI Doc Link Type"::"Posted Purchase Invoice":
                exit(122);
            "GPI Doc Link Type"::"Purchase Order":
                exit(38);
            "GPI Doc Link Type"::"Posted Sales Shipment":
                exit(110);
            else
                exit(0);
        end;
    end;

    local procedure GetSourceDocumentType(): Text
    begin
        case CurrentDocType of
            "GPI Doc Link Type"::"Purchase Invoice":
                exit('Purchase Invoice');
            "GPI Doc Link Type"::"Posted Purchase Invoice":
                exit('Posted Purchase Invoice');
            "GPI Doc Link Type"::"Purchase Order":
                exit('Purchase Order');
            "GPI Doc Link Type"::"Posted Sales Shipment":
                exit('Posted Sales Shipment');
            else
                exit('');
        end;
    end;

    local procedure AddIdentityQuery(BaseUrl: Text): Text
    var
        UriHelper: Codeunit Uri;
        SourceTableId: Integer;
        SourceDocumentType: Text;
    begin
        if IsNullGuid(CurrentBCSystemId) then
            exit(BaseUrl);

        SourceTableId := GetSourceTableId();
        SourceDocumentType := GetSourceDocumentType();
        exit(
            BaseUrl + '?bc_system_id=' + UriHelper.EscapeDataString(Format(CurrentBCSystemId, 0, 4)) +
            '&source_table_id=' + Format(SourceTableId) +
            '&source_document_type=' + UriHelper.EscapeDataString(SourceDocumentType));
    end;

    local procedure BuildRecordUrl(PathPrefix: Text): Text
    var
        GPILinkMgt: Codeunit "GPI Document Link Mgt";
        UriHelper: Codeunit Uri;
    begin
        GPILinkMgt.Initialize();
        exit(
            GPILinkMgt.GetHubBaseUrl() + PathPrefix +
            GPILinkMgt.DocTypeToEntity(CurrentDocType) + '/' +
            UriHelper.EscapeDataString(CurrentBCDocumentNo));
    end;

    local procedure FetchDocumentLinks()
    var
        Client: HttpClient;
        GPILinkMgt: Codeunit "GPI Document Link Mgt";
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
        JsonObj: JsonObject;
        JsonToken: JsonToken;
        JsonArray: JsonArray;
        DocElement: JsonToken;
        DocObj: JsonObject;
        DocCount: Integer;
        FileName: Text;
        CreatedUtc: Text;
    begin
        DocumentCountText := '...';
        LatestFileName := '';
        LatestDateText := '';
        HasDocuments := false;

        if CurrentBCDocumentNo = '' then begin
            DocumentCountText := '0';
            exit;
        end;

        RequestUrl := BuildRecordUrl('/gpi-integration/document-links/');
        RequestUrl := AddIdentityQuery(RequestUrl);
        GPILinkMgt.ConfigureHubClient(Client);

        if not Client.Get(RequestUrl, Response) then begin
            DocumentCountText := '-';
            exit;
        end;

        if Response.HttpStatusCode() = 401 then begin
            DocumentCountText := '!';
            exit;
        end;

        if not Response.IsSuccessStatusCode() then begin
            DocumentCountText := '-';
            exit;
        end;

        Response.Content().ReadAs(ResponseText);
        JsonObj.ReadFrom(ResponseText);

        if not JsonObj.Get('documents', JsonToken) then begin
            DocumentCountText := '0';
            exit;
        end;

        JsonArray := JsonToken.AsArray();
        DocCount := JsonArray.Count();
        DocumentCountText := Format(DocCount);
        HasDocuments := DocCount > 0;

        if DocCount > 0 then begin
            JsonArray.Get(0, DocElement);
            DocObj := DocElement.AsObject();
            LatestFileName := GetJsonValue(DocObj, 'file_name');
            if StrLen(LatestFileName) > 40 then
                LatestFileName := CopyStr(LatestFileName, 1, 37) + '...';
            CreatedUtc := GetJsonValue(DocObj, 'created_utc');
            if CreatedUtc <> '' then
                LatestDateText := CopyStr(CreatedUtc, 1, 10);
        end;
    end;

    local procedure OpenFactboxInBrowser()
    var
        FactboxUrl: Text;
    begin
        if CurrentBCDocumentNo = '' then
            exit;

        FactboxUrl := BuildRecordUrl('/gpi-integration/factbox-ui/');
        FactboxUrl := AddIdentityQuery(FactboxUrl);
        Hyperlink(FactboxUrl);
    end;

    local procedure GetJsonValue(JObj: JsonObject; FieldName: Text): Text
    var
        JToken: JsonToken;
        JValue: JsonValue;
    begin
        if not JObj.Get(FieldName, JToken) then
            exit('');
        if JToken.IsValue() then begin
            JValue := JToken.AsValue();
            if JValue.IsNull() or JValue.IsUndefined() then
                exit('');
            exit(JValue.AsText());
        end;
        exit('');
    end;
}
