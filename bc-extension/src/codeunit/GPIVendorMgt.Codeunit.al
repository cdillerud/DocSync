codeunit 50104 "GPI Vendor Mgt"
{
    // Vendor creation logic for GPI Hub integration.

    var
        IntegrationMgt: Codeunit "GPI Integration Mgt";

    /// <summary>
    /// Create a Vendor from GPI Hub request.
    /// </summary>
    procedure CreateVendor(
        IdempotencyKey: Code[100];
        SourceSystem: Code[50];
        SourceDocID: Code[100];
        VendorName: Text[100];
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
        Vendor: Record Vendor;
        ExistingLog: Record "GPI Integration Log";
        LogEntryNo: Integer;
        ValidationErr: Text;
    begin
        ResultSuccess := false;
        ResultIdempotencyStatus := '';
        ResultErrorMsg := '';

        // 1. Idempotency check
        if IntegrationMgt.CheckIdempotency(IdempotencyKey, "GPI Record Type"::Vendor, ExistingLog) then begin
            ResultRecordNo := ExistingLog."BC Record No.";
            ResultSystemID := ExistingLog."BC System ID";
            ResultIdempotencyStatus := 'already_exists';
            ResultSuccess := true;
            LogEntryNo := IntegrationMgt.CreateLogEntry(
                IdempotencyKey, SourceSystem, SourceDocID, '',
                "GPI Record Type"::Vendor);
            IntegrationMgt.LogAlreadyExists(LogEntryNo, ResultRecordNo, ResultSystemID);
            exit;
        end;

        // 2. Audit log
        LogEntryNo := IntegrationMgt.CreateLogEntry(
            IdempotencyKey, SourceSystem, SourceDocID, '',
            "GPI Record Type"::Vendor);

        // 3. Validation
        ValidationErr := IntegrationMgt.ValidateRequiredCode(IdempotencyKey, 'idempotencyKey');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        ValidationErr := IntegrationMgt.ValidateRequired(VendorName, 'name');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // 4. Create Vendor
        Vendor.Init();
        Vendor.Insert(true);

        Vendor.Validate(Name, VendorName);
        if Address <> '' then
            Vendor.Address := Address;
        if City <> '' then
            Vendor.City := City;
        if StateCode <> '' then
            Vendor.County := StateCode;
        if PostalCode <> '' then
            Vendor."Post Code" := PostalCode;
        if CountryCode <> '' then
            Vendor.Validate("Country/Region Code", CountryCode);

        // GPI metadata
        Vendor."GPI Idempotency Key" := IdempotencyKey;
        Vendor."GPI Source System" := SourceSystem;
        Vendor."GPI Source Document ID" := SourceDocID;
        Vendor."GPI Created By Integration" := CopyStr(UserId, 1, 50);
        Vendor."GPI Created DateTime" := CurrentDateTime;
        Vendor.Modify(true);

        // 5. Return
        ResultRecordNo := Vendor."No.";
        ResultSystemID := Vendor.SystemId;
        ResultIdempotencyStatus := 'created';
        ResultSuccess := true;
        IntegrationMgt.LogSuccess(LogEntryNo, ResultRecordNo, ResultSystemID, 'created');
    end;
}
