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

        EventId := CopyStr('al-sample-delivery-sent-' + Format(CurrentDateTime(), 0, 9), 1, MaxStrLen(EventId));
        EventId := ConvertStr(EventId, ':', '-');
        EventId := ConvertStr(EventId, '.', '-');
        CorrelationId := CopyStr('al-sandbox-test-' + Format(CurrentDateTime(), 0, 9), 1, MaxStrLen(CorrelationId));
        CorrelationId := ConvertStr(CorrelationId, ':', '-');
        CorrelationId := ConvertStr(CorrelationId, '.', '-');

        Builder.BuildSampleDeliverySentPayload(Setup, EventId, CorrelationId, Payload);

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
}
