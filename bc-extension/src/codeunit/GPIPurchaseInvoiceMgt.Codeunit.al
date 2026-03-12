codeunit 50102 "GPI Purchase Invoice Mgt"
{
    // Purchase Invoice creation logic for GPI Hub integration.

    var
        IntegrationMgt: Codeunit "GPI Integration Mgt";

    /// <summary>
    /// Create a Purchase Invoice from GPI Hub request.
    /// </summary>
    procedure CreatePurchaseInvoice(
        IdempotencyKey: Code[100];
        SourceSystem: Code[50];
        SourceDocID: Code[100];
        TransactionID: Code[100];
        VendorNo: Code[20];
        VendorInvoiceNo: Code[35];
        DocumentDateText: Text;
        PostingDateText: Text;
        var ResultRecordNo: Code[20];
        var ResultSystemID: Guid;
        var ResultIdempotencyStatus: Text[50];
        var ResultSuccess: Boolean;
        var ResultErrorMsg: Text[2048]
    )
    var
        PurchaseHeader: Record "Purchase Header";
        ExistingLog: Record "GPI Integration Log";
        LogEntryNo: Integer;
        ValidationErr: Text;
        DocumentDate: Date;
        PostingDate: Date;
    begin
        ResultSuccess := false;
        ResultIdempotencyStatus := '';
        ResultErrorMsg := '';

        // 1. Idempotency check
        if IntegrationMgt.CheckIdempotency(IdempotencyKey, "GPI Record Type"::"Purchase Invoice", ExistingLog) then begin
            ResultRecordNo := ExistingLog."BC Record No.";
            ResultSystemID := ExistingLog."BC System ID";
            ResultIdempotencyStatus := 'already_exists';
            ResultSuccess := true;
            LogEntryNo := IntegrationMgt.CreateLogEntry(
                IdempotencyKey, SourceSystem, SourceDocID, TransactionID,
                "GPI Record Type"::"Purchase Invoice");
            IntegrationMgt.LogAlreadyExists(LogEntryNo, ResultRecordNo, ResultSystemID);
            exit;
        end;

        // 2. Audit log
        LogEntryNo := IntegrationMgt.CreateLogEntry(
            IdempotencyKey, SourceSystem, SourceDocID, TransactionID,
            "GPI Record Type"::"Purchase Invoice");

        // 3. Validation
        ValidationErr := IntegrationMgt.ValidateRequiredCode(IdempotencyKey, 'idempotencyKey');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        ValidationErr := IntegrationMgt.ValidateRequiredCode(VendorNo, 'vendorNo');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // Validate vendor exists
        if not VerifyVendorExists(VendorNo) then begin
            ValidationErr := StrSubstNo('Vendor "%1" not found in Business Central.', VendorNo);
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // Parse dates
        if DocumentDateText <> '' then begin
            if not Evaluate(DocumentDate, DocumentDateText) then
                DocumentDate := Today;
        end else
            DocumentDate := Today;

        if PostingDateText <> '' then begin
            if not Evaluate(PostingDate, PostingDateText) then
                PostingDate := Today;
        end else
            PostingDate := Today;

        // 4. Create Purchase Invoice
        PurchaseHeader.Init();
        PurchaseHeader."Document Type" := PurchaseHeader."Document Type"::Invoice;
        PurchaseHeader.Insert(true);

        PurchaseHeader.Validate("Buy-from Vendor No.", VendorNo);
        if VendorInvoiceNo <> '' then
            PurchaseHeader."Vendor Invoice No." := VendorInvoiceNo;
        PurchaseHeader.Validate("Document Date", DocumentDate);
        PurchaseHeader.Validate("Posting Date", PostingDate);

        // Set GPI metadata
        PurchaseHeader."GPI Idempotency Key" := IdempotencyKey;
        PurchaseHeader."GPI Source System" := SourceSystem;
        PurchaseHeader."GPI Source Document ID" := SourceDocID;
        PurchaseHeader."GPI Transaction ID" := TransactionID;
        PurchaseHeader."GPI Created By Integration" := CopyStr(UserId, 1, 50);
        PurchaseHeader."GPI Created DateTime" := CurrentDateTime;
        PurchaseHeader.Modify(true);

        // 5. Return
        ResultRecordNo := PurchaseHeader."No.";
        ResultSystemID := PurchaseHeader.SystemId;
        ResultIdempotencyStatus := 'created';
        ResultSuccess := true;
        IntegrationMgt.LogSuccess(LogEntryNo, ResultRecordNo, ResultSystemID, 'created');
    end;

    local procedure VerifyVendorExists(VendorNo: Code[20]): Boolean
    var
        Vendor: Record Vendor;
    begin
        exit(Vendor.Get(VendorNo));
    end;
}
