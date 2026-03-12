codeunit 50101 "GPI Sales Order Mgt"
{
    // Sales Order creation logic for GPI Hub integration.

    var
        IntegrationMgt: Codeunit "GPI Integration Mgt";

    /// <summary>
    /// Create a Sales Order from GPI Hub request.
    /// Handles idempotency, validation, header + line creation.
    /// </summary>
    procedure CreateSalesOrder(
        IdempotencyKey: Code[100];
        SourceSystem: Code[50];
        SourceDocID: Code[100];
        TransactionID: Code[100];
        CustomerNo: Code[20];
        ExternalDocNo: Code[35];
        OrderDateText: Text;
        var ResultRecordNo: Code[20];
        var ResultSystemID: Guid;
        var ResultIdempotencyStatus: Text[50];
        var ResultSuccess: Boolean;
        var ResultErrorMsg: Text[2048]
    )
    var
        SalesHeader: Record "Sales Header";
        ExistingLog: Record "GPI Integration Log";
        LogEntryNo: Integer;
        ValidationErr: Text;
        OrderDate: Date;
    begin
        ResultSuccess := false;
        ResultIdempotencyStatus := '';
        ResultErrorMsg := '';

        // 1. Idempotency check
        if IntegrationMgt.CheckIdempotency(IdempotencyKey, "GPI Record Type"::"Sales Order", ExistingLog) then begin
            ResultRecordNo := ExistingLog."BC Record No.";
            ResultSystemID := ExistingLog."BC System ID";
            ResultIdempotencyStatus := 'already_exists';
            ResultSuccess := true;

            // Log the duplicate attempt
            LogEntryNo := IntegrationMgt.CreateLogEntry(
                IdempotencyKey, SourceSystem, SourceDocID, TransactionID,
                "GPI Record Type"::"Sales Order");
            IntegrationMgt.LogAlreadyExists(LogEntryNo, ResultRecordNo, ResultSystemID);
            exit;
        end;

        // 2. Create audit log entry
        LogEntryNo := IntegrationMgt.CreateLogEntry(
            IdempotencyKey, SourceSystem, SourceDocID, TransactionID,
            "GPI Record Type"::"Sales Order");

        // 3. Validation
        ValidationErr := IntegrationMgt.ValidateRequiredCode(IdempotencyKey, 'idempotencyKey');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        ValidationErr := IntegrationMgt.ValidateRequiredCode(CustomerNo, 'customerNo');
        if ValidationErr <> '' then begin
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // Validate customer exists
        if not VerifyCustomerExists(CustomerNo) then begin
            ValidationErr := StrSubstNo('Customer "%1" not found in Business Central.', CustomerNo);
            IntegrationMgt.LogFailure(LogEntryNo, ValidationErr, true);
            ResultErrorMsg := ValidationErr;
            exit;
        end;

        // Parse order date
        if OrderDateText <> '' then begin
            if not Evaluate(OrderDate, OrderDateText) then
                OrderDate := Today;
        end else
            OrderDate := Today;

        // 4. Create Sales Order header
        SalesHeader.Init();
        SalesHeader."Document Type" := SalesHeader."Document Type"::Order;
        SalesHeader.Insert(true);

        // Set fields using standard validation
        SalesHeader.Validate("Sell-to Customer No.", CustomerNo);
        if ExternalDocNo <> '' then
            SalesHeader."External Document No." := ExternalDocNo;
        SalesHeader.Validate("Order Date", OrderDate);

        // Set GPI metadata
        SalesHeader."GPI Idempotency Key" := IdempotencyKey;
        SalesHeader."GPI Source System" := SourceSystem;
        SalesHeader."GPI Source Document ID" := SourceDocID;
        SalesHeader."GPI Transaction ID" := TransactionID;
        SalesHeader."GPI Created By Integration" := CopyStr(UserId, 1, 50);
        SalesHeader."GPI Created DateTime" := CurrentDateTime;
        SalesHeader.Modify(true);

        // 5. Return result
        ResultRecordNo := SalesHeader."No.";
        ResultSystemID := SalesHeader.SystemId;
        ResultIdempotencyStatus := 'created';
        ResultSuccess := true;

        IntegrationMgt.LogSuccess(LogEntryNo, ResultRecordNo, ResultSystemID, 'created');
    end;

    /// <summary>
    /// Add a line to an existing Sales Order.
    /// </summary>
    procedure AddSalesOrderLine(
        DocumentNo: Code[20];
        LineType: Text;
        ItemNo: Code[20];
        Quantity: Decimal;
        UnitPrice: Decimal;
        Description: Text[100];
        var ResultSuccess: Boolean;
        var ResultErrorMsg: Text[2048]
    )
    var
        SalesLine: Record "Sales Line";
        SalesHeader: Record "Sales Header";
        NextLineNo: Integer;
    begin
        ResultSuccess := false;

        // Validate sales order exists
        SalesHeader.SetRange("Document Type", SalesHeader."Document Type"::Order);
        SalesHeader.SetRange("No.", DocumentNo);
        if not SalesHeader.FindFirst() then begin
            ResultErrorMsg := StrSubstNo('Sales Order "%1" not found.', DocumentNo);
            exit;
        end;

        // Get next line number
        SalesLine.SetRange("Document Type", SalesLine."Document Type"::Order);
        SalesLine.SetRange("Document No.", DocumentNo);
        if SalesLine.FindLast() then
            NextLineNo := SalesLine."Line No." + 10000
        else
            NextLineNo := 10000;

        // Create the line
        SalesLine.Init();
        SalesLine."Document Type" := SalesLine."Document Type"::Order;
        SalesLine."Document No." := DocumentNo;
        SalesLine."Line No." := NextLineNo;
        SalesLine.Insert(true);

        // Set type
        case UpperCase(LineType) of
            'ITEM':
                SalesLine.Validate(Type, SalesLine.Type::Item);
            'RESOURCE':
                SalesLine.Validate(Type, SalesLine.Type::Resource);
            'G/L ACCOUNT', 'GL_ACCOUNT':
                SalesLine.Validate(Type, SalesLine.Type::"G/L Account");
            else
                SalesLine.Validate(Type, SalesLine.Type::Item);
        end;

        if ItemNo <> '' then
            SalesLine.Validate("No.", ItemNo);
        if Description <> '' then
            SalesLine.Description := Description;
        if Quantity <> 0 then
            SalesLine.Validate(Quantity, Quantity);
        if UnitPrice <> 0 then
            SalesLine.Validate("Unit Price", UnitPrice);

        SalesLine.Modify(true);
        ResultSuccess := true;
    end;

    local procedure VerifyCustomerExists(CustomerNo: Code[20]): Boolean
    var
        Customer: Record Customer;
    begin
        exit(Customer.Get(CustomerNo));
    end;
}
