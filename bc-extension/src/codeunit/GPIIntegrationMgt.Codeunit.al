codeunit 50100 "GPI Integration Mgt"
{
    // Core integration management: idempotency, audit logging, validation helpers.

    /// <summary>
    /// Check if an idempotency key has already been processed.
    /// Returns true if found (duplicate), sets LogEntry to the existing record.
    /// </summary>
    procedure CheckIdempotency(IdempotencyKey: Code[100]; RecordType: Enum "GPI Record Type"; var LogEntry: Record "GPI Integration Log"): Boolean
    begin
        if IdempotencyKey = '' then
            exit(false);

        LogEntry.Reset();
        LogEntry.SetRange("Idempotency Key", IdempotencyKey);
        LogEntry.SetRange("Record Type", RecordType);
        LogEntry.SetRange(Success, true);
        if LogEntry.FindFirst() then
            exit(true);

        exit(false);
    end;

    /// <summary>
    /// Create a new integration log entry for an incoming request.
    /// </summary>
    procedure CreateLogEntry(
        IdempotencyKey: Code[100];
        SourceSystem: Code[50];
        SourceDocID: Code[100];
        TransactionID: Code[100];
        RecordType: Enum "GPI Record Type"
    ): Integer
    var
        LogEntry: Record "GPI Integration Log";
    begin
        LogEntry.Init();
        LogEntry."Idempotency Key" := IdempotencyKey;
        LogEntry."Source System" := SourceSystem;
        LogEntry."Source Document ID" := SourceDocID;
        LogEntry."Transaction ID" := TransactionID;
        LogEntry."Record Type" := RecordType;
        LogEntry."Request Status" := LogEntry."Request Status"::Pending;
        LogEntry."Created DateTime" := CurrentDateTime;
        LogEntry."Created By Integration" := CopyStr(UserId, 1, 50);
        LogEntry.Insert(true);
        exit(LogEntry."Entry No.");
    end;

    /// <summary>
    /// Update a log entry with success result.
    /// </summary>
    procedure LogSuccess(
        EntryNo: Integer;
        BCRecordNo: Code[20];
        BCSystemID: Guid;
        IdempotencyStatus: Text[50]
    )
    var
        LogEntry: Record "GPI Integration Log";
    begin
        if not LogEntry.Get(EntryNo) then
            exit;

        LogEntry.Success := true;
        LogEntry."Request Status" := LogEntry."Request Status"::Created;
        LogEntry."BC Record No." := BCRecordNo;
        LogEntry."BC System ID" := BCSystemID;
        LogEntry."Idempotency Status" := IdempotencyStatus;
        LogEntry.Modify(true);
    end;

    /// <summary>
    /// Update a log entry with already_exists result.
    /// </summary>
    procedure LogAlreadyExists(
        EntryNo: Integer;
        BCRecordNo: Code[20];
        BCSystemID: Guid
    )
    var
        LogEntry: Record "GPI Integration Log";
    begin
        if not LogEntry.Get(EntryNo) then
            exit;

        LogEntry.Success := true;
        LogEntry."Request Status" := LogEntry."Request Status"::"Already Exists";
        LogEntry."BC Record No." := BCRecordNo;
        LogEntry."BC System ID" := BCSystemID;
        LogEntry."Idempotency Status" := 'already_exists';
        LogEntry.Modify(true);
    end;

    /// <summary>
    /// Update a log entry with failure result.
    /// </summary>
    procedure LogFailure(
        EntryNo: Integer;
        ErrorMsg: Text[2048];
        IsValidationError: Boolean
    )
    var
        LogEntry: Record "GPI Integration Log";
    begin
        if not LogEntry.Get(EntryNo) then
            exit;

        LogEntry.Success := false;
        if IsValidationError then
            LogEntry."Request Status" := LogEntry."Request Status"::"Validation Error"
        else
            LogEntry."Request Status" := LogEntry."Request Status"::Failed;
        LogEntry."Error Message" := ErrorMsg;
        LogEntry."Idempotency Status" := 'failed';
        LogEntry.Modify(true);
    end;

    /// <summary>
    /// Validate that a required field is not empty.
    /// </summary>
    procedure ValidateRequired(FieldValue: Text; FieldName: Text): Text
    begin
        if FieldValue = '' then
            exit(StrSubstNo('Required field "%1" is missing or empty.', FieldName));
        exit('');
    end;

    /// <summary>
    /// Validate that a required code field is not empty.
    /// </summary>
    procedure ValidateRequiredCode(FieldValue: Code[100]; FieldName: Text): Text
    begin
        if FieldValue = '' then
            exit(StrSubstNo('Required field "%1" is missing or empty.', FieldName));
        exit('');
    end;
}
