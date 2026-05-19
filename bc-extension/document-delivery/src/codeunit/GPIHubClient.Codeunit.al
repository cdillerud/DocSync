codeunit 70150003 "GPI Hub Client"
{
    Access = Internal;

    procedure SendDeliverySentEvent(Payload: Text; EventId: Text[100]; CorrelationId: Text[100]; RecordType: Text[100]; RecordNo: Code[50]; DocumentType: Text[50]; FileName: Text[250]) Success: Boolean
    begin
        exit(SendEvent('/api/bc-document-events/delivery-sent', 'delivery_sent', Payload, EventId, CorrelationId, RecordType, RecordNo, DocumentType, FileName));
    end;

    procedure TestConnection(var Setup: Record "GPI Doc Delivery Setup") Success: Boolean
    var
        Client: HttpClient;
        Response: HttpResponseMessage;
        ResponseText: Text;
        Url: Text;
    begin
        if Setup."Hub Base URL" = '' then
            Error('GPI Hub Base URL is required.');

        Url := NormalizeBaseUrl(Setup."Hub Base URL") + '/api/bc-document-events/status';
        AddDefaultHeaders(Client, Setup);

        Success := Client.Get(Url, Response);
        Response.Content().ReadAs(ResponseText);

        Setup."Last Test At" := CurrentDateTime();
        if Success and Response.IsSuccessStatusCode() then
            Setup."Last Test Status" := CopyStr('OK: ' + ResponseText, 1, MaxStrLen(Setup."Last Test Status"))
        else
            Setup."Last Test Status" := CopyStr('FAILED: ' + Format(Response.HttpStatusCode()) + ' ' + ResponseText, 1, MaxStrLen(Setup."Last Test Status"));
        Setup.Modify(true);

        exit(Success and Response.IsSuccessStatusCode());
    end;

    local procedure SendEvent(EndpointPath: Text; EventType: Text[50]; Payload: Text; EventId: Text[100]; CorrelationId: Text[100]; RecordType: Text[100]; RecordNo: Code[50]; DocumentType: Text[50]; FileName: Text[250]) Success: Boolean
    var
        Setup: Record "GPI Doc Delivery Setup";
        Client: HttpClient;
        RequestContent: HttpContent;
        RequestHeaders: HttpHeaders;
        Response: HttpResponseMessage;
        ResponseText: Text;
        Url: Text;
        LogEntry: Record "GPI Doc Delivery Log";
    begin
        GetSetup(Setup);

        if not Setup."Integration Enabled" then begin
            CreateSkippedLog(EventType, EventId, CorrelationId, RecordType, RecordNo, DocumentType, FileName, 'Integration is disabled. Event was not sent.');
            exit(false);
        end;

        if Setup."Hub Base URL" = '' then
            Error('GPI Hub Base URL is required.');

        Url := NormalizeBaseUrl(Setup."Hub Base URL") + EndpointPath;
        AddDefaultHeaders(Client, Setup);

        RequestContent.WriteFrom(Payload);
        RequestContent.GetHeaders(RequestHeaders);
        if RequestHeaders.Contains('Content-Type') then
            RequestHeaders.Remove('Content-Type');
        RequestHeaders.Add('Content-Type', 'application/json');

        Success := Client.Post(Url, RequestContent, Response);
        Response.Content().ReadAs(ResponseText);

        LogEntry.Init();
        LogEntry."Event ID" := EventId;
        LogEntry."Event Type" := EventType;
        LogEntry."Correlation ID" := CorrelationId;
        LogEntry."BC Record Type" := RecordType;
        LogEntry."BC Record No." := RecordNo;
        LogEntry."Document Type" := DocumentType;
        LogEntry."File Name" := FileName;
        LogEntry."Endpoint" := CopyStr(Url, 1, MaxStrLen(LogEntry."Endpoint"));
        LogEntry."HTTP Status Code" := Response.HttpStatusCode();
        LogEntry.Success := Success and Response.IsSuccessStatusCode();
        LogEntry."Created At" := CurrentDateTime();
        LogEntry."Created By" := UserId();
        ParseHubResponse(ResponseText, LogEntry);
        LogEntry.SetResponseBody(ResponseText);

        if not LogEntry.Success then
            LogEntry."Error Message" := CopyStr(Response.ReasonPhrase() + ' ' + ResponseText, 1, MaxStrLen(LogEntry."Error Message"));

        LogEntry.Insert(true);

        Setup."Last Event Sent At" := CurrentDateTime();
        if LogEntry.Success then
            Clear(Setup."Last Event Error")
        else
            Setup."Last Event Error" := LogEntry."Error Message";
        Setup.Modify(true);

        exit(LogEntry.Success);
    end;

    local procedure ParseHubResponse(ResponseText: Text; var LogEntry: Record "GPI Doc Delivery Log")
    var
        ResponseJson: JsonObject;
        Token: JsonToken;
        TextValue: Text;
    begin
        if ResponseText = '' then
            exit;

        if not ResponseJson.ReadFrom(ResponseText) then
            exit;

        if ResponseJson.Get('duplicate', Token) then
            if Token.IsValue() then
                LogEntry.Duplicate := Token.AsValue().AsBoolean();

        if ResponseJson.Get('document_id', Token) then
            if Token.IsValue() then begin
                TextValue := Token.AsValue().AsText();
                LogEntry."Hub Document ID" := CopyStr(TextValue, 1, MaxStrLen(LogEntry."Hub Document ID"));
            end;
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

    local procedure CreateSkippedLog(EventType: Text[50]; EventId: Text[100]; CorrelationId: Text[100]; RecordType: Text[100]; RecordNo: Code[50]; DocumentType: Text[50]; FileName: Text[250]; Reason: Text[500])
    var
        LogEntry: Record "GPI Doc Delivery Log";
    begin
        LogEntry.Init();
        LogEntry."Event ID" := EventId;
        LogEntry."Event Type" := EventType;
        LogEntry."Correlation ID" := CorrelationId;
        LogEntry."BC Record Type" := RecordType;
        LogEntry."BC Record No." := RecordNo;
        LogEntry."Document Type" := DocumentType;
        LogEntry."File Name" := FileName;
        LogEntry.Success := false;
        LogEntry."Error Message" := Reason;
        LogEntry."Created At" := CurrentDateTime();
        LogEntry."Created By" := UserId();
        LogEntry.Insert(true);
    end;

    local procedure AddDefaultHeaders(var Client: HttpClient; var Setup: Record "GPI Doc Delivery Setup")
    var
        Headers: HttpHeaders;
    begin
        Headers := Client.DefaultRequestHeaders();

        if not Headers.Contains('Accept') then
            Headers.Add('Accept', 'application/json');

        if Setup."API Key" <> '' then begin
            if Headers.Contains('X-GPI-Hub-Api-Key') then
                Headers.Remove('X-GPI-Hub-Api-Key');
            Headers.Add('X-GPI-Hub-Api-Key', Setup."API Key");
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
