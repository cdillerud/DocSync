codeunit 70715 "GPI UAT Simulation Helper"
{
    procedure ConfigureEditorMock(var Mock: Codeunit "GPI Transport Mock")
    var
        EmailAction: Enum "Email Action";
    begin
        Mock.ConfigureSenderAccount('workflow.sender@example.com', 'Workflow Test Sender');
        Mock.ConfigureCommitSuppression();
        Mock.ConfigureEmailEditor(true, EmailAction::Sent, '');
    end;

    procedure ConfigureBatchMock(var Mock: Codeunit "GPI Transport Mock")
    begin
        Mock.ConfigureSenderAccount('workflow.sender@example.com', 'Workflow Test Sender');
        Mock.ConfigureCommitSuppression();
        Mock.ConfigureEmailSend(true, true, '');
    end;

    procedure DisableAutomaticArchive()
    var
        Setup: Record "GPI SharePoint Archive Setup";
    begin
        if not Setup.Get('SETUP') then begin
            Setup.Init();
            Setup."Primary Key" := 'SETUP';
            Setup.Insert(false);
        end;

        Setup.Enabled := false;
        Setup.Modify(false);
    end;

    procedure ConvertRuleToUATReplace(RuleEntryNo: Integer)
    var
        Rule: Record "GPI Document Routing Rule";
    begin
        Rule.Get(RuleEntryNo);
        Rule.Priority := 99999;
        Rule."Recipient Action" := Rule."Recipient Action"::Replace;
        Rule."To Addresses" := UATRecipient();
        Rule."CC Addresses" := '';
        Rule."BCC Addresses" := '';
        Rule."Effective Start Date" := 0D;
        Rule."Effective End Date" := 0D;
        Rule.Enabled := true;
        Rule.Modify(false);
    end;

    procedure CreateUATReplaceRule(DocumentType: Enum "GPI Delivery Document Type"; CustomerNo: Code[20]; VendorNo: Code[20]; LocationCode: Code[10]): Integer
    var
        Rule: Record "GPI Document Routing Rule";
    begin
        Rule.Init();
        Rule.Enabled := true;
        Rule.Priority := 99999;
        Rule."Rule Name" := CopyStr('UAT Replace ' + Format(CreateGuid()), 1, MaxStrLen(Rule."Rule Name"));
        Rule."Delivery Document Type" := DocumentType;
        Rule."Customer No." := CustomerNo;
        Rule."Vendor No." := VendorNo;
        Rule."Location Code" := LocationCode;
        Rule."Recipient Action" := Rule."Recipient Action"::Replace;
        Rule."To Addresses" := UATRecipient();
        Rule."CC Addresses" := '';
        Rule."BCC Addresses" := '';
        Rule.Insert(false);
        exit(Rule."Entry No.");
    end;

    procedure AddSalesReturnLocation(var Header: Record "Sales Header"): Code[10]
    var
        LocationCode: Code[10];
    begin
        LocationCode := CreateLocation('UAT Sales Return');
        Header."Location Code" := LocationCode;
        Header.Modify(false);
        exit(LocationCode);
    end;

    procedure AddPurchaseReturnLocation(var Header: Record "Purchase Header"): Code[10]
    var
        LocationCode: Code[10];
    begin
        LocationCode := CreateLocation('UAT Purchase Return');
        Header."Location Code" := LocationCode;
        Header.Modify(false);
        exit(LocationCode);
    end;

    procedure AssertUATLog(var Log: Record "GPI Document Delivery Log"; ExpectedSourceTableId: Integer; ExpectedSourceNo: Code[20]; ExpectedDocumentType: Enum "GPI Delivery Document Type"; ExpectedSubject: Text; ExpectedFileName: Text; ExpectedRuleEntryNo: Integer)
    var
        EmptyId: Guid;
    begin
        if Log."Source Table ID" <> ExpectedSourceTableId then
            Error('Expected source table %1 but received %2.', ExpectedSourceTableId, Log."Source Table ID");
        if Log."Source Document No." <> ExpectedSourceNo then
            Error('Expected source document %1 but received %2.', ExpectedSourceNo, Log."Source Document No.");
        if Log."Delivery Document Type" <> ExpectedDocumentType then
            Error('Expected document type %1 but received %2.', ExpectedDocumentType, Log."Delivery Document Type");
        if Log.Status <> Log.Status::Sent then
            Error('Expected a simulated Sent status but received %1.', Log.Status);
        if Log."To Recipients" <> UATRecipient() then
            Error('The UAT Replace rule did not isolate delivery to %1. Actual To: %2.', UATRecipient(), Log."To Recipients");
        if Log."CC Recipients" <> '' then
            Error('The UAT Replace rule left an unexpected CC recipient: %1.', Log."CC Recipients");
        if Log."BCC Recipients" <> '' then
            Error('The UAT Replace rule left an unexpected BCC recipient: %1.', Log."BCC Recipients");
        if Log."Sender Email Address" <> 'workflow.sender@example.com' then
            Error('The simulated sender account was not used. Actual sender: %1.', Log."Sender Email Address");
        if Log."Routing Rule Entry Nos." <> Format(ExpectedRuleEntryNo) then
            Error('Expected routing rule %1 but received %2.', ExpectedRuleEntryNo, Log."Routing Rule Entry Nos.");
        if Log.Subject <> ExpectedSubject then
            Error('Expected subject "%1" but received "%2".', ExpectedSubject, Log.Subject);
        if Log."Attachment Filename" <> ExpectedFileName then
            Error('Expected attachment "%1" but received "%2".', ExpectedFileName, Log."Attachment Filename");
        if Log."Created Date/Time" = 0DT then
            Error('The UAT simulation did not record a created date/time.');
        if Log."Completed Date/Time" = 0DT then
            Error('The UAT simulation did not record a completed date/time.');
        if Log."Error Message" <> '' then
            Error('The UAT simulation recorded an unexpected error: %1', Log."Error Message");
        if Log."Email Message ID" = EmptyId then
            Error('The UAT simulation did not record an email message ID.');

        Log.CalcFields("Document Content");
        if not Log."Document Content".HasValue then
            Error('The UAT simulation did not retain the generated PDF in the Delivery Log.');
    end;

    procedure UATRecipient(): Text[250]
    begin
        exit('CDillerud@gamerpackaging.com');
    end;

    local procedure CreateLocation(LocationName: Text): Code[10]
    var
        Location: Record Location;
    begin
        Location.Init();
        Location.Code := NewLocationCode('U');
        Location.Name := CopyStr(LocationName, 1, MaxStrLen(Location.Name));
        Location.Insert(false);
        exit(Location.Code);
    end;

    local procedure NewLocationCode(Prefix: Text): Code[10]
    begin
        exit(CopyStr(Prefix + DelChr(Format(CreateGuid()), '=', '{}-'), 1, 10));
    end;
}
