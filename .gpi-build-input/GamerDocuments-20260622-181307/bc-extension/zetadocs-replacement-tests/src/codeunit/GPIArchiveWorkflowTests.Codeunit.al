codeunit 70713 "GPI Archive Workflow Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI SharePoint Archive Setup" = rimd;

    [Test]
    procedure MockedArchiveSuccessUpdatesDeliveryLog()
    var
        LogEntry: Record "GPI Document Delivery Log";
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
        TransportMock: Codeunit "GPI Transport Mock";
        EntryNo: Integer;
    begin
        ConfigureArchiveSetup(true);
        EntryNo := CreateSentDeliveryLog('email-delivery-123');
        LogEntry.Get(EntryNo);

        TransportMock.ConfigureDeliveryLogArchive(
            true,
            '06-20-2026/GPI Archive Customer/Sales/GPI-Test.pdf',
            'GPI-Test.pdf',
            'sharepoint-item-123',
            'https://example.sharepoint.com/GPI-Test.pdf?web=1',
            '');
        BindSubscription(TransportMock);
        ArchiveMgt.ArchiveDeliveryLog(LogEntry);
        UnbindSubscription(TransportMock);

        Clear(LogEntry);
        LogEntry.Get(EntryNo);
        LogEntry.CalcFields("Document Content");

        AssertEqualText(Format(LogEntry."Archive Status"::Archived), Format(LogEntry."Archive Status"), 'The archive status was not set to Archived.');
        AssertEqualInteger(1, LogEntry."Archive Attempt Count", 'The archive attempt count is incorrect.');
        AssertEqualText('06-20-2026/GPI Archive Customer/Sales/GPI-Test.pdf', LogEntry."Archive Path", 'The archive path was not stored.');
        AssertEqualText('GPI-Test.pdf', LogEntry."Archive File Name", 'The archive filename was not stored.');
        AssertEqualText('sharepoint-item-123', LogEntry."SharePoint Item ID", 'The SharePoint item ID was not stored.');
        AssertEqualText('https://example.sharepoint.com/GPI-Test.pdf?web=1', LogEntry."SharePoint URL", 'The SharePoint URL was not stored.');
        AssertEqualText('email-delivery-123', LogEntry."External Delivery ID", 'The email delivery ID was overwritten by the archive operation.');
        AssertEqualText('', LogEntry."Last Archive Error", 'A successful archive retained an error message.');
        AssertTrue(LogEntry."Local PDF Cleared", 'The local PDF cleared flag was not set.');
        AssertFalse(LogEntry."Document Content".HasValue, 'The local PDF was not cleared after successful archive.');
        AssertTrue(LogEntry."Archived Date/Time" <> 0DT, 'The archived date/time was not recorded.');
        AssertEqualInteger(EntryNo, TransportMock.GetCapturedDeliveryLogEntryNo(), 'The wrong Delivery Log entry was sent to the archive transport.');
    end;

    [Test]
    procedure MockedArchiveFailureUpdatesDeliveryLog()
    var
        LogEntry: Record "GPI Document Delivery Log";
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
        TransportMock: Codeunit "GPI Transport Mock";
        EntryNo: Integer;
    begin
        ConfigureArchiveSetup(true);
        EntryNo := CreateSentDeliveryLog('email-delivery-456');
        LogEntry.Get(EntryNo);

        TransportMock.ConfigureDeliveryLogArchive(
            false,
            '',
            '',
            '',
            '',
            'Mock SharePoint upload failure');
        BindSubscription(TransportMock);
        ArchiveMgt.ArchiveDeliveryLog(LogEntry);
        UnbindSubscription(TransportMock);

        Clear(LogEntry);
        LogEntry.Get(EntryNo);
        LogEntry.CalcFields("Document Content");

        AssertEqualText(Format(LogEntry."Archive Status"::Failed), Format(LogEntry."Archive Status"), 'The archive status was not set to Failed.');
        AssertEqualInteger(1, LogEntry."Archive Attempt Count", 'The failed archive attempt count is incorrect.');
        AssertEqualText('Mock SharePoint upload failure', LogEntry."Last Archive Error", 'The archive failure message was not stored.');
        AssertEqualText('email-delivery-456', LogEntry."External Delivery ID", 'The email delivery ID changed after archive failure.');
        AssertFalse(LogEntry."Local PDF Cleared", 'A failed archive marked the local PDF as cleared.');
        AssertTrue(LogEntry."Document Content".HasValue, 'A failed archive removed the local PDF.');
        AssertTrue(LogEntry."Last Archive Attempt" <> 0DT, 'The last archive attempt date/time was not recorded.');
    end;

    [Test]
    procedure ArchivedDeliveryLogIsNotRetried()
    var
        LogEntry: Record "GPI Document Delivery Log";
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
        EntryNo: Integer;
    begin
        ConfigureArchiveSetup(false);
        EntryNo := CreateSentDeliveryLog('email-delivery-789');
        LogEntry.Get(EntryNo);
        LogEntry."Archive Status" := LogEntry."Archive Status"::Archived;
        LogEntry."Archive Attempt Count" := 7;
        LogEntry.Modify(false);

        ArchiveMgt.ArchiveDeliveryLog(LogEntry);

        Clear(LogEntry);
        LogEntry.Get(EntryNo);
        AssertEqualInteger(7, LogEntry."Archive Attempt Count", 'An already archived Delivery Log was retried.');
        AssertEqualText(Format(LogEntry."Archive Status"::Archived), Format(LogEntry."Archive Status"), 'The archived status changed unexpectedly.');
    end;

    local procedure ConfigureArchiveSetup(ClearLocalPdf: Boolean)
    var
        Setup: Record "GPI SharePoint Archive Setup";
    begin
        if not Setup.Get('SETUP') then begin
            Setup.Init();
            Setup."Primary Key" := 'SETUP';
            Setup.Insert(false);
        end;

        Setup.Enabled := true;
        Setup."SharePoint Web Base URL" := 'https://example.sharepoint.com/archive';
        Setup."Root Folder" := 'Archive';
        Setup."Sales Folder" := 'Sales';
        Setup."Purchase Folder" := 'Purchase';
        Setup."Warehouse Folder" := 'Warehouse';
        Setup."Clear Local PDF After Archive" := ClearLocalPdf;
        Setup.Modify(false);
    end;

    local procedure CreateSentDeliveryLog(EmailDeliveryId: Text): Integer
    var
        Customer: Record Customer;
        LogEntry: Record "GPI Document Delivery Log";
        DocumentOutStream: OutStream;
        CustomerNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'GPI Archive Customer';
        Customer.Insert(false);

        LogEntry.Init();
        LogEntry."Delivery Document Type" := LogEntry."Delivery Document Type"::"Customer Open Order Status";
        LogEntry.Status := LogEntry.Status::Sent;
        LogEntry."Customer No." := CustomerNo;
        LogEntry."Attachment Filename" := 'GPI-Test.pdf';
        LogEntry."External Delivery ID" := EmailDeliveryId;
        LogEntry."Source Table ID" := Database::Customer;
        LogEntry."Source Document Type" := 'Open Order Status';
        LogEntry."Source Document No." := CustomerNo;
        LogEntry."Source Party Type" := 'Customer';
        LogEntry."Source Party No." := CustomerNo;
        LogEntry."Created Date/Time" := CurrentDateTime();
        LogEntry."Completed Date/Time" := CurrentDateTime();
        LogEntry."Archive Status" := LogEntry."Archive Status"::Pending;
        LogEntry."Document Content".CreateOutStream(DocumentOutStream, TextEncoding::UTF8);
        DocumentOutStream.WriteText('MOCK-PDF-CONTENT');
        LogEntry.Insert(false);
        exit(LogEntry."Entry No.");
    end;

    local procedure NewTestCode(Prefix: Text): Code[20]
    var
        GuidText: Text;
    begin
        GuidText := DelChr(Format(CreateGuid()), '=', '{}-');
        exit(CopyStr(Prefix + GuidText, 1, 20));
    end;

    local procedure AssertTrue(Condition: Boolean; FailureMessage: Text)
    begin
        if not Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertFalse(Condition: Boolean; FailureMessage: Text)
    begin
        if Condition then
            Error('%1', FailureMessage);
    end;

    local procedure AssertEqualInteger(Expected: Integer; Actual: Integer; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected %2 but received %3.', FailureMessage, Expected, Actual);
    end;

    local procedure AssertEqualText(Expected: Text; Actual: Text; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected "%2" but received "%3".', FailureMessage, Expected, Actual);
    end;
}
