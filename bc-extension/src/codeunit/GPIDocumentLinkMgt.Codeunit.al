/// <summary>
/// Codeunit 50105 "GPI Document Link Mgt"
/// Handles HTTP calls to the GPI Hub API for document link operations.
/// Exact-record FactBox reads/uploads carry immutable BC SystemId.
/// Legacy two-key read/unlink procedures are retained only to fail closed.
/// </summary>
codeunit 50105 "GPI Document Link Mgt"
{
    Permissions = tabledata "GPI Hub Setup" = R;

    var
        GPIHubBaseUrl: Text;
        MaxUploadSizeMB: Integer;

    procedure Initialize()
    begin
        GPIHubBaseUrl := GetGPIHubUrl();
        MaxUploadSizeMB := 25;
    end;

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

    procedure GetHubBaseUrl(): Text
    begin
        exit(GetGPIHubUrl());
    end;

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

    procedure RefreshDocumentLinks(DocType: Enum "GPI Doc Link Type"; BCDocumentNo: Code[20])
    begin
        Error('BC SystemId is required for GPI document visibility. Use the SystemId-aware FactBox path.');
    end;

    /// <summary>
    /// Upload the original binary stream to the Hub for one exact BC record.
    /// No base64 or hand-built multipart body is used, so file bytes are preserved.
    /// </summary>
    procedure UploadFile(
        DocType: Enum "GPI Doc Link Type";
        BCDocumentNo: Code[20];
        BCSystemId: Guid;
        SourceTableId: Integer;
        SourceDocumentType: Text;
        FileName: Text;
        FileInStream: InStream;
        VendorContext: Text
    ): Boolean
    var
        Client: HttpClient;
        FileContent: HttpContent;
        ContentHeaders: HttpHeaders;
        Response: HttpResponseMessage;
        ResponseText: Text;
        RequestUrl: Text;
        UriHelper: Codeunit Uri;
    begin
        Initialize();

        if IsNullGuid(BCSystemId) then
            Error('BC SystemId is required before a document can be uploaded.');
        if SourceTableId = 0 then
            Error('This Business Central document type is not enabled for GPI Hub upload.');
        if SourceDocumentType = '' then
            Error('Source document type is required before a document can be uploaded.');

        RequestUrl := GPIHubBaseUrl + '/gpi-integration/document-links/' +
                      DocTypeToEntity(DocType) + '/' + BCDocumentNo + '/upload-raw' +
                      '?bc_system_id=' + UriHelper.EscapeDataString(Format(BCSystemId, 0, 4)) +
                      '&source_table_id=' + Format(SourceTableId) +
                      '&source_document_type=' + UriHelper.EscapeDataString(SourceDocumentType) +
                      '&file_name=' + UriHelper.EscapeDataString(FileName) +
                      '&uploaded_by=' + UriHelper.EscapeDataString(CopyStr(UserId, 1, 50)) +
                      '&vendor_context=' + UriHelper.EscapeDataString(VendorContext);

        FileContent.WriteFrom(FileInStream);
        FileContent.GetHeaders(ContentHeaders);
        ContentHeaders.Clear();
        ContentHeaders.Add('Content-Type', 'application/octet-stream');

        if not Client.Post(RequestUrl, FileContent, Response) then begin
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
            409:
                begin
                    Message('Upload blocked because the Business Central record identity is not valid for this document.');
                    exit(false);
                end;
            413:
                begin
                    Message('File exceeds 25 MB limit. Please choose a smaller file.');
                    exit(false);
                end;
            502:
                begin
                    Message('Document delivery did not complete. The Hub retained recovery information where possible.');
                    exit(false);
                end;
            else begin
                Message('Upload failed (HTTP %1): %2', Response.HttpStatusCode(), CopyStr(ResponseText, 1, 200));
                exit(false);
            end;
        end;
    end;

    procedure RemoveDocumentLink(
        DocType: Enum "GPI Doc Link Type";
        BCDocumentNo: Code[20];
        DocIdOrItemId: Text
    ): Boolean
    begin
        Error('BC SystemId is required to remove a GPI document link. Use the SystemId-aware Hub FactBox path.');
        exit(false);
    end;

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
