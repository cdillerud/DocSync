/// <summary>
/// Page 50100 "GPI Document Link Factbox"
/// Native CardPart factbox for BC SaaS — no control add-ins.
/// Fetches document links from the GPI Hub API via HttpClient.
/// Opens the full document viewer in a browser tab via Hyperlink.
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
                ToolTip = 'Open linked documents in GPI Hub (browser).';
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
                ToolTip = 'Upload a document to GPI Hub for this record.';
                Image = Attach;

                trigger OnAction()
                var
                    GPILinkMgt: Codeunit "GPI Document Link Mgt";
                    FileInStream: InStream;
                    FileName: Text;
                begin
                    if CurrentBCDocumentNo = '' then
                        exit;

                    if not UploadIntoStream('Select file to upload', '', 'All Files (*.*)|*.*', FileName, FileInStream) then
                        exit;

                    if GPILinkMgt.UploadFile(CurrentDocType, CurrentBCDocumentNo, FileName, FileInStream, CurrentVendorContext) then
                        FetchDocumentLinks();
                end;
            }
        }
    }

    var
        CurrentDocType: Enum "GPI Doc Link Type";
        CurrentBCDocumentNo: Code[20];
        CurrentVendorContext: Text;
        DocumentCountText: Text;
        LatestFileName: Text;
        LatestDateText: Text;
        HasDocuments: Boolean;

    procedure SetContext(DocType: Enum "GPI Doc Link Type"; BCDocNo: Code[20]; VendorCtx: Text)
    begin
        CurrentDocType := DocType;
        CurrentBCDocumentNo := BCDocNo;
        CurrentVendorContext := VendorCtx;
        FetchDocumentLinks();
    end;

    local procedure FetchDocumentLinks()
    var
        GPILinkMgt: Codeunit "GPI Document Link Mgt";
        Client: HttpClient;
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

        GPILinkMgt.Initialize();
        RequestUrl := GPILinkMgt.GetHubBaseUrl() + '/gpi-integration/document-links/' +
                      GPILinkMgt.DocTypeToEntity(CurrentDocType) + '/' + CurrentBCDocumentNo;

        if not Client.Get(RequestUrl, Response) then begin
            DocumentCountText := '-';
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
        GPILinkMgt: Codeunit "GPI Document Link Mgt";
        FactboxUrl: Text;
    begin
        if CurrentBCDocumentNo = '' then
            exit;

        GPILinkMgt.Initialize();
        FactboxUrl := GPILinkMgt.GetHubBaseUrl() + '/gpi-integration/factbox-ui/' +
                      GPILinkMgt.DocTypeToEntity(CurrentDocType) + '/' + CurrentBCDocumentNo;

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
