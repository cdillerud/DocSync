/// <summary>
/// Codeunit 50105 "GPI Document Link Mgt"
/// Handles HTTP calls to the GPI Hub API for document link operations:
///   - GET document links (list all linked docs for a BC record)
///   - POST upload file (upload to SharePoint via Hub, create link)
///   - DELETE document link (soft-delete via Hub)
/// </summary>
codeunit 50105 "GPI Document Link Mgt"
{
    var
        GPIHubBaseUrl: Text;
        MaxUploadSizeMB: Integer;

    /// <summary>
    /// Initialize with the GPI Hub base URL from setup.
    /// Call this before any API operation.
    /// </summary>
    procedure Initialize()
    var
        SetupUrl: Text;
    begin
        // Read from an application setup table or hardcode for now.
        // In production, this should come from a GPI Hub Setup table.
        SetupUrl := GetGPIHubUrl();
        if SetupUrl = '' then
            Error('GPI Hub URL is not configured. Go to GPI Hub Setup to set the API base URL.');
        GPIHubBaseUrl := SetupUrl;
        MaxUploadSizeMB := 25;
    end;

    /// <summary>
    /// Get the GPI Hub URL. Override this to read from a setup table.
    /// </summary>
    local procedure GetGPIHubUrl(): Text
    begin
        // TODO: Read from a GPI Hub Setup table record.
        // For now, return the configured URL.
        exit('https://http://4.204.41.190:8080/');
    end;

    /// <summary>
    /// Public accessor for the Hub base URL. Used by the factbox iframe.
    /// </summary>
    procedure GetHubBaseUrl(): Text
    begin
        exit(GetGPIHubUrl());
    end;

    /// <summary>
    /// Map a GPI Doc Link Type enum to the Hub API entity path segment.
    /// </summary>
    procedure DocTypeToEntity(DocType: Enum "GPI Doc Link Type"): Text
    begin
        case DocType of
            "GPI Doc Link Type"::"Purchase Invoice",
            "GPI Doc Link Type"::"Posted Purchase Invoice":
                exit('purchaseInvoices');
            "GPI Doc Link Type"::"Purchase Order":
                exit('purchaseOrders');
            "GPI Doc Link Type"::"Sales Order",
            "GPI Doc Link Type"::"Posted Sales Order":
                exit('salesOrders');
            "GPI Doc Link Type"::"Sales Invoice",
            "GPI Doc Link Type"::"Posted Sales Invoice":
                exit('salesInvoices');
            else
                exit('documents');
        end;
    end;

    /// <summary>
    /// Fetch document links from the GPI Hub API and populate local records.
    /// Merges Hub results with existing local GPI Document Link records.
    /// </summary>
    procedure RefreshDocumentLinks(DocType: Enum "GPI Doc Link Type"; BCDocumentNo: Code[20])
    var
        Client: HttpClient;
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
        JsonToken: JsonToken;
        JsonArray: JsonArray;
        JsonObj: JsonObject;
        DocElement: JsonToken;
        i: Integer;
        DocLink: Record "GPI Document Link";
        SPUrl: Text;
        FileName: Text;
        UploadedBy: Text;
        SourceText: Text;
        HubDocId: Text;
    begin
        Initialize();
        RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' +
                      DocTypeToEntity(DocType) + '/' + BCDocumentNo;

        if not Client.Get(RequestUrl, Response) then
            exit; // Silent fail — local records still shown

        if not Response.IsSuccessStatusCode() then
            exit;

        Response.Content().ReadAs(ResponseText);

        // Parse response JSON
        JsonObj.ReadFrom(ResponseText);
        if not JsonObj.Get('documents', JsonToken) then
            exit;

        JsonArray := JsonToken.AsArray();

        for i := 0 to JsonArray.Count() - 1 do begin
            JsonArray.Get(i, DocElement);
            JsonObj := DocElement.AsObject();

            SPUrl := GetJsonText(JsonObj, 'sharepoint_web_url');
            if SPUrl = '' then
                SPUrl := GetJsonText(JsonObj, 'sharepoint_url');

            if SPUrl <> '' then begin
                // Check if this URL already exists in local table
                DocLink.Reset();
                DocLink.SetRange("Document Type", DocType);
                DocLink.SetRange("BC Document No.", BCDocumentNo);
                DocLink.SetFilter("SharePoint Url", '@' + SPUrl);
                if not DocLink.FindFirst() then begin
                    // Insert new record from Hub API response
                    Clear(DocLink);
                    DocLink.Init();
                    DocLink."Document Type" := DocType;
                    DocLink."BC Document No." := BCDocumentNo;
                    DocLink."SharePoint Url" := CopyStr(SPUrl, 1, MaxStrLen(DocLink."SharePoint Url"));

                    FileName := GetJsonText(JsonObj, 'file_name');
                    DocLink."File Name" := CopyStr(FileName, 1, MaxStrLen(DocLink."File Name"));

                    DocLink."SharePoint Drive Id" := CopyStr(
                        GetJsonText(JsonObj, 'sharepoint_drive_id'), 1, MaxStrLen(DocLink."SharePoint Drive Id"));
                    DocLink."SharePoint Item Id" := CopyStr(
                        GetJsonText(JsonObj, 'sharepoint_item_id'), 1, MaxStrLen(DocLink."SharePoint Item Id"));

                    UploadedBy := GetJsonText(JsonObj, 'uploaded_by');
                    DocLink."Uploaded By" := CopyStr(UploadedBy, 1, MaxStrLen(DocLink."Uploaded By"));

                    SourceText := GetJsonText(JsonObj, 'source');
                    case SourceText of
                        'hub':
                            DocLink.Source := "GPI Doc Link Source"::GPIHub;
                        'bc_drop':
                            DocLink.Source := "GPI Doc Link Source"::BCDrop;
                        'zetadocs_legacy':
                            DocLink.Source := "GPI Doc Link Source"::ZetadocsLegacy;
                        else
                            DocLink.Source := "GPI Doc Link Source"::Manual;
                    end;

                    if DocLink.Insert(true) then;
                end;
            end;
        end;
    end;

    /// <summary>
    /// Upload a file to SharePoint via the GPI Hub API.
    /// The Hub handles SP upload, BC link creation, and hub_documents record.
    /// Returns true if successful.
    /// </summary>
    procedure UploadFile(
        DocType: Enum "GPI Doc Link Type";
        BCDocumentNo: Code[20];
        FileName: Text;
        FileInStream: InStream;
        VendorContext: Text
    ): Boolean
    var
        Client: HttpClient;
        MultipartContent: HttpContent;
        FileContent: HttpContent;
        UploadedByContent: HttpContent;
        VendorContent: HttpContent;
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
        ContentHeaders: HttpHeaders;
        Boundary: Text;
        MultipartBody: TextBuilder;
        TempBlob: Codeunit "Temp Blob";
        OutStream: OutStream;
        Base64: Codeunit "Base64 Convert";
        FileBytes: Text;
        CRLF: Text[2];
    begin
        Initialize();
        RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' +
                      DocTypeToEntity(DocType) + '/' + BCDocumentNo + '/upload';

        Boundary := 'GPIUploadBoundary' + Format(CurrentDateTime, 0, '<Year4><Month,2><Day,2><Hours24,2><Minutes,2><Seconds,2>');
        CRLF[1] := 13;
        CRLF[2] := 10;

        // Build multipart body manually
        // File part
        MultipartBody.Append('--' + Boundary + CRLF);
        MultipartBody.Append('Content-Disposition: form-data; name="file"; filename="' + FileName + '"' + CRLF);
        MultipartBody.Append('Content-Type: application/octet-stream' + CRLF);
        MultipartBody.Append(CRLF);

        // Read file stream to base64 then to content
        FileBytes := Base64.ToBase64(FileInStream);
        MultipartBody.Append(FileBytes);
        MultipartBody.Append(CRLF);

        // uploaded_by part
        MultipartBody.Append('--' + Boundary + CRLF);
        MultipartBody.Append('Content-Disposition: form-data; name="uploaded_by"' + CRLF);
        MultipartBody.Append(CRLF);
        MultipartBody.Append(CopyStr(UserId, 1, 50));
        MultipartBody.Append(CRLF);

        // vendor_context part (if provided)
        if VendorContext <> '' then begin
            MultipartBody.Append('--' + Boundary + CRLF);
            MultipartBody.Append('Content-Disposition: form-data; name="vendor_context"' + CRLF);
            MultipartBody.Append(CRLF);
            MultipartBody.Append(VendorContext);
            MultipartBody.Append(CRLF);
        end;

        // Closing boundary
        MultipartBody.Append('--' + Boundary + '--' + CRLF);

        // Set content
        MultipartContent.WriteFrom(MultipartBody.ToText());
        MultipartContent.GetHeaders(ContentHeaders);
        if ContentHeaders.Contains('Content-Type') then
            ContentHeaders.Remove('Content-Type');
        ContentHeaders.Add('Content-Type', 'multipart/form-data; boundary=' + Boundary);

        if not Client.Post(RequestUrl, MultipartContent, Response) then begin
            Message('Failed to connect to GPI Hub.');
            exit(false);
        end;

        Response.Content().ReadAs(ResponseText);

        case Response.HttpStatusCode() of
            200:
                begin
                    Message('File uploaded successfully to SharePoint.');
                    exit(true);
                end;
            413:
                begin
                    Message('File exceeds 25 MB limit. Please choose a smaller file.');
                    exit(false);
                end;
            502:
                begin
                    Message('SharePoint upload failed. Please try again later.');
                    exit(false);
                end;
            else begin
                Message('Upload failed (HTTP %1): %2', Response.HttpStatusCode(), CopyStr(ResponseText, 1, 200));
                exit(false);
            end;
        end;
    end;

    /// <summary>
    /// Delete (soft-remove) a document link via the GPI Hub API.
    /// The SharePoint file is preserved — only the link is removed.
    /// </summary>
    procedure RemoveDocumentLink(
        DocType: Enum "GPI Doc Link Type";
        BCDocumentNo: Code[20];
        DocIdOrItemId: Text
    ): Boolean
    var
        Client: HttpClient;
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
    begin
        Initialize();
        RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' +
                      DocTypeToEntity(DocType) + '/' + BCDocumentNo + '/' + DocIdOrItemId;

        if not Client.Delete(RequestUrl, Response) then begin
            Message('Failed to connect to GPI Hub.');
            exit(false);
        end;

        Response.Content().ReadAs(ResponseText);

        if Response.IsSuccessStatusCode() then begin
            Message('Link removed. SharePoint file preserved for audit.');
            exit(true);
        end;

        Message('Failed to remove link (HTTP %1).', Response.HttpStatusCode());
        exit(false);
    end;

    /// <summary>
    /// Trigger Zetadocs migration via the GPI Hub API.
    /// Idempotent — safe to call multiple times.
    /// </summary>
    procedure MigrateZetadocsLinks(): Text
    var
        Client: HttpClient;
        EmptyContent: HttpContent;
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
    begin
        Initialize();
        RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/migrate-from-zetadocs';

        if not Client.Post(RequestUrl, EmptyContent, Response) then
            exit('Failed to connect to GPI Hub.');

        Response.Content().ReadAs(ResponseText);

        if Response.IsSuccessStatusCode() then
            exit(ResponseText);

        exit('Migration failed: ' + CopyStr(ResponseText, 1, 200));
    end;

    // === JSON Helpers ===

    local procedure GetJsonText(JObj: JsonObject; Key: Text): Text
    var
        JToken: JsonToken;
        JValue: JsonValue;
    begin
        if not JObj.Get(Key, JToken) then
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
