codeunit 70150009 "GPI SO Confirm Preflight"
{
    Access = Internal;

    procedure Preview(var SalesHeader: Record "Sales Header")
    var
        Setup: Record "GPI Doc Delivery Setup";
        PreviewBuffer: Record "GPI Delivery Preview Buffer" temporary;
        PreviewPage: Page "GPI Delivery Preview";
        Payload: Text;
        ResponseText: Text;
        Endpoint: Text;
        CorrelationId: Text[100];
        HttpStatusCode: Integer;
    begin
        ValidateSalesOrder(SalesHeader);
        GetSetup(Setup);

        if not Setup."Integration Enabled" then
            Error('GPI Document Delivery integration is disabled. Enable it on GPI Document Delivery Setup after the sandbox connection test succeeds.');

        if Setup."Hub Base URL" = '' then
            Error('GPI Hub Base URL is required on GPI Document Delivery Setup.');

        CorrelationId := BuildCorrelationId(SalesHeader);
        Payload := BuildPreflightPayload(SalesHeader, Setup, CorrelationId);
        Endpoint := NormalizeBaseUrl(Setup."Hub Base URL") + '/api/document-delivery/v1/preflight';

        if not PostJson(Setup, Endpoint, Payload, ResponseText, HttpStatusCode) then begin
            InsertLog(
                CorrelationId,
                SalesHeader,
                Endpoint,
                HttpStatusCode,
                false,
                false,
                '',
                '',
                ResponseText,
                CopyStr(ResponseText, 1, 500));
            Error('GPI Hub preflight failed with HTTP status %1. Check GPI Document Delivery Log for the response.', HttpStatusCode);
        end;

        ParsePreflightResponse(ResponseText, SalesHeader, CorrelationId, PreviewBuffer);

        InsertLog(
            CorrelationId,
            SalesHeader,
            Endpoint,
            HttpStatusCode,
            true,
            PreviewBuffer.Duplicate,
            PreviewBuffer."Package ID",
            PreviewBuffer."File Name",
            ResponseText,
            CopyStr(PreviewBuffer.Warnings, 1, 500));

        PreviewPage.SetPreview(PreviewBuffer);
        PreviewPage.RunModal();
    end;

    local procedure ValidateSalesOrder(var SalesHeader: Record "Sales Header")
    begin
        if SalesHeader."Document Type" <> SalesHeader."Document Type"::Order then
            Error('GPI Order Confirmation preview is only available for Sales Orders.');

        if SalesHeader."No." = '' then
            Error('A Sales Order number is required.');

        if SalesHeader."Sell-to Customer No." = '' then
            Error('A sell-to customer is required before requesting a GPI delivery preflight.');
    end;

    local procedure BuildCorrelationId(var SalesHeader: Record "Sales Header") CorrelationId: Text[100]
    var
        CorrelationText: Text;
    begin
        CorrelationText := LowerCase(
            StrSubstNo(
                'bc-so-%1-%2-%3',
                SalesHeader."No.",
                Format(SalesHeader.SystemRowVersion),
                Format(UserSecurityId())));
        CorrelationId := CopyStr(CorrelationText, 1, MaxStrLen(CorrelationId));
    end;

    local procedure BuildPreflightPayload(var SalesHeader: Record "Sales Header"; var Setup: Record "GPI Doc Delivery Setup"; CorrelationId: Text[100]) Payload: Text
    var
        Customer: Record Customer;
        SalespersonPurchaser: Record "Salesperson/Purchaser";
        Root: JsonObject;
        DocumentJson: JsonObject;
        CustomerJson: JsonObject;
        OrderJson: JsonObject;
        ActorsJson: JsonObject;
        MetadataJson: JsonObject;
        CustomerEmail: Text;
        SalespersonEmail: Text;
        FileName: Text[250];
    begin
        CustomerEmail := SalesHeader."Sell-to E-Mail";
        if Customer.Get(SalesHeader."Sell-to Customer No.") then
            if CustomerEmail = '' then
                CustomerEmail := Customer."E-Mail";

        if SalesHeader."Salesperson Code" <> '' then
            if SalespersonPurchaser.Get(SalesHeader."Salesperson Code") then
                SalespersonEmail := SalespersonPurchaser."E-Mail";

        FileName := CopyStr('Sales-Order ' + SalesHeader."No." + '.pdf', 1, MaxStrLen(FileName));

        Root.Add('correlation_id', CorrelationId);

        DocumentJson.Add('document_type', 'SALES_ORDER_CONFIRMATION');
        DocumentJson.Add('record_type', 'Sales Order');
        DocumentJson.Add('record_no', SalesHeader."No.");
        DocumentJson.Add('system_id', Format(SalesHeader.SystemId));
        DocumentJson.Add('report_id', 50020);
        DocumentJson.Add('requested_action', 'PREVIEW');
        DocumentJson.Add('template_code', 'SALES_ORDER_CONFIRMATION_DEFAULT');
        DocumentJson.Add('file_name', FileName);
        Root.Add('document', DocumentJson);

        CustomerJson.Add('customer_no', SalesHeader."Sell-to Customer No.");
        CustomerJson.Add('sell_to_customer_no', SalesHeader."Sell-to Customer No.");
        CustomerJson.Add('bill_to_customer_no', SalesHeader."Bill-to Customer No.");
        CustomerJson.Add('ship_to_customer_no', SalesHeader."Sell-to Customer No.");
        CustomerJson.Add('organization', SalesHeader."Sell-to Customer Name");
        CustomerJson.Add('document_email', CustomerEmail);
        if Customer."No." <> '' then
            CustomerJson.Add('default_email', Customer."E-Mail");
        Root.Add('customer', CustomerJson);

        OrderJson.Add('order_type', 'SALES_ORDER');
        OrderJson.Add('external_document_no', SalesHeader."External Document No.");
        OrderJson.Add('location_code', SalesHeader."Location Code");
        Root.Add('order', OrderJson);

        ActorsJson.Add('initiated_by', UserId());
        ActorsJson.Add('sender_email', UserId());
        ActorsJson.Add('osr_code', SalesHeader."Salesperson Code");
        ActorsJson.Add('osr_email', SalespersonEmail);
        Root.Add('actors', ActorsJson);

        MetadataJson.Add('company_id', Setup."Company ID");
        MetadataJson.Add('company_name', Setup."Company Name");
        MetadataJson.Add('environment_name', Setup."Environment Name");
        MetadataJson.Add('bc_company_name', CompanyName());
        MetadataJson.Add('system_row_version', Format(SalesHeader.SystemRowVersion));
        MetadataJson.Add('sprint', '1');
        MetadataJson.Add('preview_only', true);
        Root.Add('metadata', MetadataJson);

        Root.WriteTo(Payload);
    end;

    local procedure PostJson(var Setup: Record "GPI Doc Delivery Setup"; Endpoint: Text; Payload: Text; var ResponseText: Text; var HttpStatusCode: Integer) Success: Boolean
    var
        Client: HttpClient;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        DefaultHeaders: HttpHeaders;
        Response: HttpResponseMessage;
        TransportSuccess: Boolean;
    begin
        DefaultHeaders := Client.DefaultRequestHeaders();
        DefaultHeaders.Add('Accept', 'application/json');
        if Setup."API Key" <> '' then
            DefaultHeaders.Add('X-GPI-Hub-Api-Key', Setup."API Key");

        RequestContent.WriteFrom(Payload);
        RequestContent.GetHeaders(RequestHeaders);
        if RequestHeaders.Contains('Content-Type') then
            RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        TransportSuccess := Client.Post(Endpoint, RequestContent, Response);
        HttpStatusCode := Response.HttpStatusCode();
        Response.Content().ReadAs(ResponseText);

        exit(TransportSuccess and Response.IsSuccessStatusCode());
    end;

    local procedure ParsePreflightResponse(ResponseText: Text; var SalesHeader: Record "Sales Header"; CorrelationId: Text[100]; var PreviewBuffer: Record "GPI Delivery Preview Buffer" temporary)
    var
        Root: JsonObject;
        PackageJson: JsonObject;
        DocumentJson: JsonObject;
        EmailJson: JsonObject;
        ArchiveJson: JsonObject;
        RoutingJson: JsonObject;
        Token: JsonToken;
        Duplicate: Boolean;
        CanCreateDraft: Boolean;
        ReportId: Integer;
        TextValue: Text;
    begin
        if not Root.ReadFrom(ResponseText) then
            Error('GPI Hub returned an invalid JSON preflight response.');

        GetBooleanValue(Root, 'duplicate', Duplicate);

        if not Root.Get('package', Token) then
            Error('GPI Hub preflight response did not contain a package.');
        if not Token.IsObject() then
            Error('GPI Hub preflight package was not a JSON object.');
        PackageJson := Token.AsObject();

        PreviewBuffer.Init();
        PreviewBuffer."Entry No." := 1;
        PreviewBuffer."Record No." := SalesHeader."No.";
        PreviewBuffer."Correlation ID" := CorrelationId;
        PreviewBuffer.Duplicate := Duplicate;

        if GetTextValue(PackageJson, 'package_id', TextValue) then
            PreviewBuffer."Package ID" := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer."Package ID"));
        if GetTextValue(PackageJson, 'status', TextValue) then
            PreviewBuffer.Status := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer.Status));
        if GetBooleanValue(PackageJson, 'can_create_email_draft', CanCreateDraft) then
            PreviewBuffer."Can Create Draft" := CanCreateDraft;

        if PackageJson.Get('document', Token) and Token.IsObject() then begin
            DocumentJson := Token.AsObject();
            if GetIntegerValue(DocumentJson, 'report_id', ReportId) then
                PreviewBuffer."Report ID" := ReportId;
            if GetTextValue(DocumentJson, 'file_name', TextValue) then
                PreviewBuffer."File Name" := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer."File Name"));
        end;

        if PackageJson.Get('email', Token) and Token.IsObject() then begin
            EmailJson := Token.AsObject();
            if GetTextValue(EmailJson, 'from', TextValue) then
                PreviewBuffer."From Address" := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer."From Address"));
            PreviewBuffer."To Recipients" := CopyStr(GetArrayText(EmailJson, 'to'), 1, MaxStrLen(PreviewBuffer."To Recipients"));
            PreviewBuffer."CC Recipients" := CopyStr(GetArrayText(EmailJson, 'cc'), 1, MaxStrLen(PreviewBuffer."CC Recipients"));
            PreviewBuffer."BCC Recipients" := CopyStr(GetArrayText(EmailJson, 'bcc'), 1, MaxStrLen(PreviewBuffer."BCC Recipients"));
            if GetTextValue(EmailJson, 'subject', TextValue) then
                PreviewBuffer.Subject := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer.Subject));
            if GetTextValue(EmailJson, 'body_text', TextValue) then
                PreviewBuffer.Body := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer.Body));
        end;

        if PackageJson.Get('archive', Token) and Token.IsObject() then begin
            ArchiveJson := Token.AsObject();
            if GetTextValue(ArchiveJson, 'folder_path', TextValue) then
                PreviewBuffer."Archive Path" := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer."Archive Path"));
        end;

        if PackageJson.Get('routing', Token) and Token.IsObject() then begin
            RoutingJson := Token.AsObject();
            if GetTextValue(RoutingJson, 'routing_rule_applied', TextValue) then
                PreviewBuffer."Routing Rule" := CopyStr(TextValue, 1, MaxStrLen(PreviewBuffer."Routing Rule"));
        end;

        PreviewBuffer.Warnings := CopyStr(GetWarningsText(PackageJson), 1, MaxStrLen(PreviewBuffer.Warnings));
        PreviewBuffer.Insert();
    end;

    local procedure GetTextValue(Json: JsonObject; PropertyName: Text; var Value: Text) Found: Boolean
    var
        Token: JsonToken;
    begin
        Clear(Value);
        if not Json.Get(PropertyName, Token) then
            exit(false);
        if not Token.IsValue() then
            exit(false);
        Value := Token.AsValue().AsText();
        exit(true);
    end;

    local procedure GetBooleanValue(Json: JsonObject; PropertyName: Text; var Value: Boolean) Found: Boolean
    var
        Token: JsonToken;
    begin
        Clear(Value);
        if not Json.Get(PropertyName, Token) then
            exit(false);
        if not Token.IsValue() then
            exit(false);
        Value := Token.AsValue().AsBoolean();
        exit(true);
    end;

    local procedure GetIntegerValue(Json: JsonObject; PropertyName: Text; var Value: Integer) Found: Boolean
    var
        Token: JsonToken;
    begin
        Clear(Value);
        if not Json.Get(PropertyName, Token) then
            exit(false);
        if not Token.IsValue() then
            exit(false);
        Value := Token.AsValue().AsInteger();
        exit(true);
    end;

    local procedure GetArrayText(Json: JsonObject; PropertyName: Text) Result: Text
    var
        Token: JsonToken;
        ItemToken: JsonToken;
        Items: JsonArray;
        Index: Integer;
        ItemText: Text;
    begin
        if not Json.Get(PropertyName, Token) then
            exit('');
        if not Token.IsArray() then
            exit('');

        Items := Token.AsArray();
        for Index := 0 to Items.Count() - 1 do
            if Items.Get(Index, ItemToken) and ItemToken.IsValue() then begin
                ItemText := ItemToken.AsValue().AsText();
                if ItemText <> '' then begin
                    if Result <> '' then
                        Result += '; ';
                    Result += ItemText;
                end;
            end;
    end;

    local procedure GetWarningsText(PackageJson: JsonObject) Result: Text
    var
        Token: JsonToken;
        ItemToken: JsonToken;
        Warnings: JsonArray;
        WarningJson: JsonObject;
        Index: Integer;
        Severity: Text;
        Code: Text;
        MessageText: Text;
        WarningLine: Text;
    begin
        if not PackageJson.Get('warnings', Token) then
            exit('');
        if not Token.IsArray() then
            exit('');

        Warnings := Token.AsArray();
        for Index := 0 to Warnings.Count() - 1 do
            if Warnings.Get(Index, ItemToken) and ItemToken.IsObject() then begin
                WarningJson := ItemToken.AsObject();
                GetTextValue(WarningJson, 'severity', Severity);
                GetTextValue(WarningJson, 'code', Code);
                GetTextValue(WarningJson, 'message', MessageText);

                WarningLine := StrSubstNo('%1 %2: %3', UpperCase(Severity), Code, MessageText);
                if Result <> '' then
                    Result += '\';
                Result += WarningLine;
            end;
    end;

    local procedure InsertLog(CorrelationId: Text[100]; var SalesHeader: Record "Sales Header"; Endpoint: Text; HttpStatusCode: Integer; Success: Boolean; Duplicate: Boolean; PackageId: Text; FileName: Text; ResponseText: Text; ErrorText: Text)
    var
        LogEntry: Record "GPI Doc Delivery Log";
    begin
        LogEntry.Init();
        LogEntry."Event ID" := CopyStr('preflight-' + CorrelationId, 1, MaxStrLen(LogEntry."Event ID"));
        LogEntry."Event Type" := 'preflight';
        LogEntry."Correlation ID" := CorrelationId;
        LogEntry."BC Record Type" := 'Sales Order';
        LogEntry."BC Record No." := SalesHeader."No.";
        LogEntry."Document Type" := 'SALES_ORDER_CONFIRMATION';
        LogEntry."File Name" := CopyStr(FileName, 1, MaxStrLen(LogEntry."File Name"));
        LogEntry."Endpoint" := CopyStr(Endpoint, 1, MaxStrLen(LogEntry."Endpoint"));
        LogEntry."HTTP Status Code" := HttpStatusCode;
        LogEntry.Success := Success;
        LogEntry.Duplicate := Duplicate;
        LogEntry."Hub Document ID" := CopyStr(PackageId, 1, MaxStrLen(LogEntry."Hub Document ID"));
        LogEntry."Error Message" := CopyStr(ErrorText, 1, MaxStrLen(LogEntry."Error Message"));
        LogEntry."Created At" := CurrentDateTime();
        LogEntry."Created By" := UserId();
        LogEntry.SetResponseBody(ResponseText);
        LogEntry.Insert(true);
    end;

    local procedure GetSetup(var Setup: Record "GPI Doc Delivery Setup")
    begin
        if not Setup.Get('SETUP') then begin
            Setup.Init();
            Setup."Primary Key" := 'SETUP';
            Setup."Integration Enabled" := false;
            Setup."Log Successful Events" := true;
            Setup.Insert(true);
        end;
    end;

    local procedure NormalizeBaseUrl(BaseUrl: Text): Text
    begin
        BaseUrl := DelChr(BaseUrl, '<>', ' ');
        while CopyStr(BaseUrl, StrLen(BaseUrl), 1) = '/' do
            BaseUrl := CopyStr(BaseUrl, 1, StrLen(BaseUrl) - 1);
        exit(BaseUrl);
    end;
}
