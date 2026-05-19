codeunit 70150004 "GPI Doc Delivery Test"
{
    Access = Internal;

    procedure SendSampleDeliverySentEvent()
    var
        Setup: Record "GPI Doc Delivery Setup";
        Client: Codeunit "GPI Hub Client";
        Builder: Codeunit "GPI Hub Event Builder";
        Payload: Text;
        EventId: Text[100];
        CorrelationId: Text[100];
    begin
        GetSetup(Setup);

        EventId := MakeSafeId('al-sample-delivery-sent');
        CorrelationId := MakeSafeId('al-sandbox-test');

        Payload := Builder.BuildSampleDeliverySentPayload(Setup, EventId, CorrelationId);

        if Client.SendDeliverySentEvent(Payload, EventId, CorrelationId, 'Posted Sales Invoice', 'AL-SAMPLE-INV-001', 'SALES_INVOICE', 'AL-SAMPLE-INV-001.pdf') then
            Message('Sample delivery event sent to GPI Hub.')
        else
            Message('Sample delivery event was not sent successfully. Check GPI Document Delivery Log.');
    end;

    procedure TestConnection()
    var
        Setup: Record "GPI Doc Delivery Setup";
        Client: Codeunit "GPI Hub Client";
    begin
        GetSetup(Setup);
        if Client.TestConnection(Setup) then
            Message('GPI Hub connection succeeded.')
        else
            Message('GPI Hub connection failed. Check Last Test Status on setup.');
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

    local procedure MakeSafeId(Prefix: Text[50]) SafeId: Text[100]
    begin
        SafeId := CopyStr(Prefix + '-' + Format(CurrentDateTime(), 0, 9), 1, MaxStrLen(SafeId));
        SafeId := ConvertStr(SafeId, ':./\ ', '-----');
    end;
}
