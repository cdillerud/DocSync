codeunit 50103 "GPI Customer Mgt"
{
    // Customer creation logic for GPI Hub integration.

    var
        IntegrationMgt: Codeunit "GPI Integration Mgt";

    /// <summary>
    /// Create a Customer from GPI Hub request.
    /// </summary>
    procedure CreateCustomer(
        IdempotencyKey: Code[100];
        SourceSystem: Code[50];
        SourceDocID: Code[100];
        CustomerName: Text[100];
        Address: Text[100];
        City: Text[30];
        StateCode: Code[10];
        PostalCode: Code[20];
        CountryCode: Code[10];
        var ResultRecordNo: Code[20];
        var ResultSystemID: Guid;
        var ResultIdempotencyStatus: Text[50];
        var ResultSuccess: Boolean;
        var ResultErrorMsg: Text[2048]
    )
    var
        Customer: Record Customer;
        ExistingLog: Record "GPI Integration Log";
        LogEntryNo: Integer;
        ValidationErr: Text;
    begin
        ResultSuccess := false;
        ResultIdempotencyStatus := '';
        ResultErrorMsg := '';

        // 1. Idempotency check
        if IntegrationMgt.CheckIdempotency(IdempotencyKey, "GPI Record Type"::Customer, ExistingLog) then begin
            ResultRecordNo := ExistingLog."BC Record No.";
            ResultSystemID := ExistingLog."BC System ID";
            ResultIdempotencyStatus := 'already_exists';
            ResultSuccess := true;
            LogEntryNo := IntegrationMgt.CreateLogEntry(
                IdempotencyKey, SourceSystem, SourceDocID, '',
                "GPI Record Type"::Customer);
            IntegrationMgt.LogAlreadyExists(LogEntryNo, ResultRecordNo, ResultSystemID);
            exit;
        end;

        // 2. Audit log
        LogEntryNo := IntegrationMgt.CreateLogEntry(
            IdempotencyKey, SourceSystem, SourceDocID, '',
            "GPI Record Type"::Customer);

        // 3. Validation
        ValidationErr := IntegrationMgt.ValidateRequiredCode(IdempotencyKey, 'idempotencyKey');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        ValidationErr := IntegrationMgt.ValidateRequired(CustomerName, 'name');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // 4. Create Customer (number series auto-assigns No.)
        Customer.Init();
        Customer.Insert(true);

        Customer.Validate(Name, CustomerName);
        if Address <> '' then
            Customer.Address := Address;
        if City <> '' then
            Customer.City := City;
        if StateCode <> '' then
            Customer.County := StateCode;
        if PostalCode <> '' then
            Customer."Post Code" := PostalCode;
        if CountryCode <> '' then
            Customer.Validate("Country/Region Code", CountryCode);

        // GPI metadata
        Customer."GPI Idempotency Key" := IdempotencyKey;
        Customer."GPI Source System" := SourceSystem;
        Customer."GPI Source Document ID" := SourceDocID;
        Customer."GPI Created By Integration" := CopyStr(UserId, 1, 50);
        Customer."GPI Created DateTime" := CurrentDateTime;
        Customer.Modify(true);

        // 5. Return
        ResultRecordNo := Customer."No.";
        ResultSystemID := Customer.SystemId;
        ResultIdempotencyStatus := 'created';
        ResultSuccess := true;
        IntegrationMgt.LogSuccess(LogEntryNo, ResultRecordNo, ResultSystemID, 'created');
    end;
}
