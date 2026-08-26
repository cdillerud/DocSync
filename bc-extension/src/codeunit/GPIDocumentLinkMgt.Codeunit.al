/// <summary>
/// Codeunit 50105 "GPI Document Link Mgt"
/// Handles HTTP calls to the GPI Hub API for document link operations.
/// Exact-record FactBox reads are performed by page 50100 with BC SystemId.
/// Legacy two-key read/unlink procedures are retained only to fail closed.
/// </summary>
codeunit 50105 "GPI Document Link Mgt"
{
    Permissions = tabledata "GPI Hub Setup" = R;

    var
        GPIHubBaseUrl: Text;
        MaxUploadSizeMB: Integer;

    /// <summary>
    /// Initialize with the GPI Hub base URL from setup.
    /// Call this before any API operation.
    /// </summary>
    procedure Initialize()
    begin
        GPIHubBaseUrl := GetGPIHubUrl();
        MaxUploadSizeMB := 25;
    end;

    /// <summary>
    /// Read the GPI Hub base URL from environment-specific Business Central setup.
    /// The URL must use HTTPS and is normalized without a trailing slash.
    /// </summary>
    local procedure GetGPIHubUrl(): Text
    var
        HubSetup: Record "GPI Hub Setup";
        HubUrl: Text;
    begin
        if not HubSetup.Get('SETUP') then
            Error('GPI Hub URL is not configured. Open GPI Hub Setup and enter the HTTPS API base URL.');

        HubUrl := DelChr(HubSetup."Hub Base URL", '>', '/');
        if HubUrl = '' then
            Error('GPI Hub URL is not configured. Open GPI Hub Setup and enter the HTTPS API base URL.');

        if LowerCase(CopyStr(HubUrl, 1, 8)) <> 'https://' then
            Error('GPI Hub URL must use HTTPS. Open GPI Hub Setup and correct the API base URL.');

        exit(HubUrl);
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
            "GPI Doc Link Type"::"Posted Sales Shipment":
                exit('postedSalesShipments');
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
    /// Retired compatibility surface. Document number alone is not sufficient
    /// immutable identity for parity reads. Page 50100 performs the active read
    /// with BC SystemId in the query string.
    /// </summary>
    procedure RefreshDocumentLinks(DocType: Enum "GPI Doc Link Type"; BCDocumentNo: Code[20])
    begin
        Error('BC SystemId is required for GPI document visibility. Use the SystemId-aware FactBox path.');
    end;

    /// <summary>
    /// Upload a file to SharePoint via the GPI Hub API.
    /// The server resolves the exact BC SystemId before creating a SharePoint artifact.
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
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
        ContentHeaders: HttpHeaders;
        Boundary: Text;
        MultipartBody: TextBuilder;
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

        MultipartBody.Append('--' + Boundary + CRLF);
        MultipartBody.Append('Content-Disposition: form-data; name="file"; filename="' + FileName + '"' + CRLF);
        MultipartBody.Append('Content-Type: application/octet-stream' + CRLF);
        MultipartBody.Append(CRLF);

        FileBytes := Base64.ToBase64(FileInStream);
        MultipartBody.Append(FileBytes);
        MultipartBody.Append(CRLF);

        MultipartBody.Append('--' + Boundary + CRLF);
        MultipartBody.Append('Content-Disposition: form-data; name="uploaded_by"' + CRLF);
        MultipartBody.Append(CRLF);
        MultipartBody.Append(CopyStr(UserId, 1, 50));
        MultipartBody.Append(CRLF);

        if VendorContext <> '' then begin
            MultipartBody.Append('--' + Boundary + CRLF);
            MultipartBody.Append('Content-Disposition: form-data; name="vendor_context"' + CRLF);
            MultipartBody.Append(CRLF);
            MultipartBody.Append(VendorContext);
            MultipartBody.Append(CRLF);
        end;

        MultipartBody.Append('--' + Boundary + '--' + CRLF);

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
    /// Retired compatibility surface. Unlink must carry immutable BC SystemId,
    /// which is enforced by the Hub FactBox DELETE route. No active BC action
    /// calls this two-key procedure.
    /// </summary>
    procedure RemoveDocumentLink(
        DocType: Enum "GPI Doc Link Type";
        BCDocumentNo: Code[20];
        DocIdOrItemId: Text
    ): Boolean
    begin
        Error('BC SystemId is required to remove a GPI document link. Use the SystemId-aware Hub FactBox path.');
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
}
