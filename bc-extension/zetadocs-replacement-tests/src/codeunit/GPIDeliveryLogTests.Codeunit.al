codeunit 70706 "GPI Delivery Log Tests"
{
    Subtype = Test;
    Permissions =
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI Record Document" = r;

    [Test]
    procedure OpenOrderMetadataFieldsPersist()
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        EntryNo: Integer;
        CustomerNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Customer Open Order Status";
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Customer No." := CustomerNo;
        DeliveryLog."Source Table ID" := Database::Customer;
        DeliveryLog."Source Document Type" := 'Open Order Status';
        DeliveryLog."Source Document No." := CustomerNo;
        DeliveryLog."Source Party Type" := 'Customer';
        DeliveryLog."Source Party No." := CustomerNo;
        DeliveryLog."Open Order As Of Date" := DMY2Date(19, 6, 2026);
        DeliveryLog."Open Order Count" := 2;
        DeliveryLog."Open Order Line Count" := 5;
        DeliveryLog."Included Order Nos." := 'SO-100, SO-200';
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog.Insert(false);
        EntryNo := DeliveryLog."Entry No.";

        Clear(DeliveryLog);
        DeliveryLog.Get(EntryNo);

        AssertEqualDate(DMY2Date(19, 6, 2026), DeliveryLog."Open Order As Of Date", 'The open-order as-of date did not persist.');
        AssertEqualInteger(2, DeliveryLog."Open Order Count", 'The open-order count did not persist.');
        AssertEqualInteger(5, DeliveryLog."Open Order Line Count", 'The open-order line count did not persist.');
        AssertEqualText('SO-100, SO-200', DeliveryLog."Included Order Nos.", 'The included Sales Order list did not persist.');
    end;

    [Test]
    procedure DeliveryLogDocumentBlobRoundTrips()
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        DocumentOutStream: OutStream;
        DocumentInStream: InStream;
        StoredText: Text;
        EntryNo: Integer;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Customer Open Order Status";
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Source Table ID" := Database::Customer;
        DeliveryLog."Source Document No." := NewTestCode('GPIC');
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Document Content".CreateOutStream(DocumentOutStream, TextEncoding::UTF8);
        DocumentOutStream.WriteText('GPI-TEST-PDF-CONTENT');
        DeliveryLog.Insert(false);
        EntryNo := DeliveryLog."Entry No.";

        Clear(DeliveryLog);
        DeliveryLog.Get(EntryNo);
        DeliveryLog.CalcFields("Document Content");
        DeliveryLog."Document Content".CreateInStream(DocumentInStream, TextEncoding::UTF8);
        DocumentInStream.ReadText(StoredText);

        AssertEqualText('GPI-TEST-PDF-CONTENT', StoredText, 'The Delivery Log document Blob content changed or did not persist.');
    end;

    [Test]
    procedure SourceKeyLocatesCustomerOpenOrderEntry()
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        CustomerNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Customer Open Order Status";
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Source Table ID" := Database::Customer;
        DeliveryLog."Source Document No." := CustomerNo;
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog.Insert(false);

        DeliveryLog.Reset();
        DeliveryLog.SetRange("Source Table ID", Database::Customer);
        DeliveryLog.SetRange("Source Document No.", CustomerNo);

        if not DeliveryLog.FindFirst() then
            Error('The Delivery Log Source key could not locate the Customer Open Order Status entry.');
    end;

    [Test]
    procedure SentDeliveryAppearsInGamerDocumentsBuffer()
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        TempDocument: Record "GPI Record Document" temporary;
        DocumentMgt: Codeunit "GPI Record Document Mgt.";
        SourceSystemId: Guid;
        EntryNo: Integer;
    begin
        SourceSystemId := CreateGuid();

        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Order Confirmation";
        DeliveryLog.Status := DeliveryLog.Status::Sent;
        DeliveryLog."Source Table ID" := Database::"Sales Header";
        DeliveryLog."Source SystemId" := SourceSystemId;
        DeliveryLog."Source Document Type" := 'Order';
        DeliveryLog."Source Document No." := NewTestCode('GPISO');
        DeliveryLog."Attachment Filename" := 'Order-Confirmation.pdf';
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog.Insert(false);
        EntryNo := DeliveryLog."Entry No.";

        DocumentMgt.BuildDocumentBuffer(
            Database::"Sales Header",
            SourceSystemId,
            TempDocument);

        if not TempDocument.Get(-EntryNo) then
            Error('The sent Delivery Log document was not added to the Gamer Documents buffer.');

        AssertEqualText(
            'Order-Confirmation.pdf',
            TempDocument."Original File Name",
            'The sent document filename is incorrect.');
        AssertEqualText(
            'Order Confirmation',
            TempDocument.Category,
            'The sent document category is incorrect.');
        AssertEqualText(
            'Sent',
            TempDocument.Description,
            'The sent document status is incorrect.');
    end;

    [Test]
    procedure DraftDeliveryDoesNotAppearInGamerDocumentsBuffer()
    var
        DeliveryLog: Record "GPI Document Delivery Log";
        TempDocument: Record "GPI Record Document" temporary;
        DocumentMgt: Codeunit "GPI Record Document Mgt.";
        SourceSystemId: Guid;
        EntryNo: Integer;
    begin
        SourceSystemId := CreateGuid();

        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Pick Ticket";
        DeliveryLog.Status := DeliveryLog.Status::"Saved As Draft";
        DeliveryLog."Source Table ID" := Database::"Sales Header";
        DeliveryLog."Source SystemId" := SourceSystemId;
        DeliveryLog."Source Document Type" := 'Order';
        DeliveryLog."Source Document No." := NewTestCode('GPISO');
        DeliveryLog."Attachment Filename" := 'Pick-Ticket.pdf';
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog.Insert(false);
        EntryNo := DeliveryLog."Entry No.";

        DocumentMgt.BuildDocumentBuffer(
            Database::"Sales Header",
            SourceSystemId,
            TempDocument);

        if TempDocument.Get(-EntryNo) then
            Error('A saved draft was incorrectly added to the Gamer Documents buffer.');
    end;

    local procedure NewTestCode(Prefix: Text): Code[20]
    var
        GuidText: Text;
    begin
        GuidText := DelChr(Format(CreateGuid()), '=', '{}-');
        exit(CopyStr(Prefix + GuidText, 1, 20));
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

    local procedure AssertEqualDate(Expected: Date; Actual: Date; FailureMessage: Text)
    begin
        if Expected <> Actual then
            Error('%1 Expected %2 but received %3.', FailureMessage, Expected, Actual);
    end;
}