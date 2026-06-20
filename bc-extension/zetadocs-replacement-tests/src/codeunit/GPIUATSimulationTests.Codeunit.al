codeunit 70714 "GPI UAT Simulation Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata Vendor = rimd,
        tabledata Location = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd,
        tabledata "Purchase Header" = rimd,
        tabledata "Purchase Line" = rimd,
        tabledata "Transfer Header" = rimd,
        tabledata "Transfer Line" = rimd,
        tabledata "GPI Document Routing Rule" = rimd,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI SharePoint Archive Setup" = rimd;

    [Test]
    procedure SalesReturnAuthorizationPageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Sales Header";
        Log: Record "GPI Document Delivery Log";
        SalesReturnPage: TestPage "Sales Return Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        RuleEntryNo: Integer;
    begin
        WorkflowHelper.CreateSalesReturn(Header, RuleEntryNo);
        UATHelper.ConvertRuleToUATReplace(RuleEntryNo);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        SalesReturnPage.OpenEdit();
        SalesReturnPage.GoToRecord(Header);
        SalesReturnPage.GPIEmailReturnAuthorization.Invoke();
        SalesReturnPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Sales Header", Header."No.", Enum::"GPI Delivery Document Type"::"Sales Return Authorization", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Sales Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Sales Return Authorization",
            StrSubstNo('Sales Return Authorization %1', Header."No."),
            StrSubstNo('Sales-Return-Authorization %1.pdf', Header."No."),
            RuleEntryNo);
    end;

    [Test]
    procedure SalesReturnWarehousePageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Sales Header";
        Log: Record "GPI Document Delivery Log";
        SalesReturnPage: TestPage "Sales Return Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        AuthorizationRuleEntryNo: Integer;
        WarehouseRuleEntryNo: Integer;
        LocationCode: Code[10];
    begin
        WorkflowHelper.CreateSalesReturn(Header, AuthorizationRuleEntryNo);
        LocationCode := UATHelper.AddSalesReturnLocation(Header);
        WarehouseRuleEntryNo := UATHelper.CreateUATReplaceRule(
            Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
            '',
            '',
            LocationCode);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        SalesReturnPage.OpenEdit();
        SalesReturnPage.GoToRecord(Header);
        SalesReturnPage.GPIEmailReturnWarehouseNotice.Invoke();
        SalesReturnPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Sales Header", Header."No.", Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Sales Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
            StrSubstNo('Sales Return Warehouse Notification %1', Header."No."),
            StrSubstNo('Sales-Return-Warehouse-Notification %1.pdf', Header."No."),
            WarehouseRuleEntryNo);
        if Log."Location Code" <> LocationCode then
            Error('The Sales Return warehouse location was not logged.');
    end;

    [Test]
    procedure PurchaseReturnOrderPageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Purchase Header";
        Log: Record "GPI Document Delivery Log";
        PurchaseReturnPage: TestPage "Purchase Return Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        RuleEntryNo: Integer;
    begin
        WorkflowHelper.CreatePurchaseReturn(Header, RuleEntryNo);
        UATHelper.ConvertRuleToUATReplace(RuleEntryNo);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        PurchaseReturnPage.OpenEdit();
        PurchaseReturnPage.GoToRecord(Header);
        PurchaseReturnPage.GPIEmailPurchaseReturnOrder.Invoke();
        PurchaseReturnPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Purchase Header", Header."No.", Enum::"GPI Delivery Document Type"::"Purchase Return Order", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Purchase Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Purchase Return Order",
            StrSubstNo('Purchase Return Order %1', Header."No."),
            StrSubstNo('Purchase-Return-Order %1.pdf', Header."No."),
            RuleEntryNo);
    end;

    [Test]
    procedure PurchaseReturnPickPageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Purchase Header";
        Log: Record "GPI Document Delivery Log";
        PurchaseReturnPage: TestPage "Purchase Return Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        VendorRuleEntryNo: Integer;
        WarehouseRuleEntryNo: Integer;
        LocationCode: Code[10];
    begin
        WorkflowHelper.CreatePurchaseReturn(Header, VendorRuleEntryNo);
        LocationCode := UATHelper.AddPurchaseReturnLocation(Header);
        WarehouseRuleEntryNo := UATHelper.CreateUATReplaceRule(
            Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
            '',
            '',
            LocationCode);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        PurchaseReturnPage.OpenEdit();
        PurchaseReturnPage.GoToRecord(Header);
        PurchaseReturnPage.GPIEmailPurchaseReturnPick.Invoke();
        PurchaseReturnPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Purchase Header", Header."No.", Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Purchase Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
            StrSubstNo('Purchase Return Pick Ticket %1', Header."No."),
            StrSubstNo('Purchase-Return-Pick-Ticket %1.pdf', Header."No."),
            WarehouseRuleEntryNo);
        if Log."Location Code" <> LocationCode then
            Error('The Purchase Return warehouse location was not logged.');
    end;

    [Test]
    procedure TransferPickPageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Transfer Header";
        Log: Record "GPI Document Delivery Log";
        TransferPage: TestPage "Transfer Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        RuleEntryNo: Integer;
    begin
        WorkflowHelper.CreateTransfer(Header, RuleEntryNo);
        UATHelper.ConvertRuleToUATReplace(RuleEntryNo);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        TransferPage.OpenEdit();
        TransferPage.GoToRecord(Header);
        TransferPage.GPIEmailTransferPickList.Invoke();
        TransferPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Transfer Header", Header."No.", Enum::"GPI Delivery Document Type"::"Transfer Pick List", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Transfer Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Transfer Pick List",
            StrSubstNo('Transfer Pick List %1', Header."No."),
            StrSubstNo('Transfer-Pick-List %1.pdf', Header."No."),
            RuleEntryNo);
        if Log."Location Code" <> Header."Transfer-from Code" then
            Error('The Transfer-from location was not logged.');
    end;

    [Test]
    procedure TransferReceiptPageActionCreatesIsolatedUATDelivery()
    var
        Header: Record "Transfer Header";
        Log: Record "GPI Document Delivery Log";
        TransferPage: TestPage "Transfer Order";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        PickRuleEntryNo: Integer;
        ReceiptRuleEntryNo: Integer;
    begin
        WorkflowHelper.CreateTransfer(Header, PickRuleEntryNo);
        ReceiptRuleEntryNo := UATHelper.CreateUATReplaceRule(
            Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice",
            '',
            '',
            Header."Transfer-to Code");
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        TransferPage.OpenEdit();
        TransferPage.GoToRecord(Header);
        TransferPage.GPIEmailTransferReceiptNotice.Invoke();
        TransferPage.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::"Transfer Header", Header."No.", Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::"Transfer Header",
            Header."No.",
            Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice",
            StrSubstNo('Transfer Receipt Notification %1', Header."No."),
            StrSubstNo('Transfer-Receipt-Notification %1.pdf', Header."No."),
            ReceiptRuleEntryNo);
        if Log."Location Code" <> Header."Transfer-to Code" then
            Error('The Transfer-to location was not logged.');
    end;

    [Test]
    procedure OpenOrderCardPageActionCreatesIsolatedUATDelivery()
    var
        Customer: Record Customer;
        Log: Record "GPI Document Delivery Log";
        CustomerCard: TestPage "Customer Card";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        SalesOrderNo: Code[20];
        RuleEntryNo: Integer;
    begin
        WorkflowHelper.CreateOpenOrder(Customer, SalesOrderNo, RuleEntryNo);
        UATHelper.ConvertRuleToUATReplace(RuleEntryNo);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureEditorMock(Mock);

        BindSubscription(Mock);
        CustomerCard.OpenEdit();
        CustomerCard.GoToRecord(Customer);
        CustomerCard.GPIEmailOpenOrderStatus.Invoke();
        CustomerCard.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::Customer, Customer."No.", Enum::"GPI Delivery Document Type"::"Customer Open Order Status", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::Customer,
            Customer."No.",
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            OpenOrderSubject(),
            OpenOrderFileName(Customer."No."),
            RuleEntryNo);
        AssertOpenOrderSummary(Log, SalesOrderNo);
    end;

    [Test]
    [HandlerFunctions('UATConfirmHandler,UATMessageHandler')]
    procedure OpenOrderBatchPageActionCreatesIsolatedUATDelivery()
    var
        Customer: Record Customer;
        Log: Record "GPI Document Delivery Log";
        CustomerList: TestPage "Customer List";
        Mock: Codeunit "GPI Transport Mock";
        WorkflowHelper: Codeunit "GPI Workflow Test Helper";
        UATHelper: Codeunit "GPI UAT Simulation Helper";
        SalesOrderNo: Code[20];
        RuleEntryNo: Integer;
    begin
        WorkflowHelper.CreateOpenOrder(Customer, SalesOrderNo, RuleEntryNo);
        UATHelper.ConvertRuleToUATReplace(RuleEntryNo);
        UATHelper.DisableAutomaticArchive();
        UATHelper.ConfigureBatchMock(Mock);
        Clear(LastBatchMessage);

        BindSubscription(Mock);
        CustomerList.OpenView();
        CustomerList.GoToRecord(Customer);
        CustomerList.GPIBatchOpenOrderStatus.Invoke();
        CustomerList.Close();
        UnbindSubscription(Mock);

        WorkflowHelper.FindLog(Database::Customer, Customer."No.", Enum::"GPI Delivery Document Type"::"Customer Open Order Status", Log);
        UATHelper.AssertUATLog(
            Log,
            Database::Customer,
            Customer."No.",
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            OpenOrderSubject(),
            OpenOrderFileName(Customer."No."),
            RuleEntryNo);
        AssertOpenOrderSummary(Log, SalesOrderNo);
        if StrPos(LastBatchMessage, 'Sent: 1') = 0 then
            Error('The simulated batch completion message did not report one sent document. Message: %1', LastBatchMessage);
    end;

    local procedure AssertOpenOrderSummary(Log: Record "GPI Document Delivery Log"; SalesOrderNo: Code[20])
    begin
        if Log."Open Order Count" <> 1 then
            Error('Expected one open Sales Order but received %1.', Log."Open Order Count");
        if Log."Open Order Line Count" <> 1 then
            Error('Expected one open Sales Order line but received %1.', Log."Open Order Line Count");
        if StrPos(Log."Included Order Nos.", SalesOrderNo) = 0 then
            Error('The simulated UAT Delivery Log did not include Sales Order %1.', SalesOrderNo);
    end;

    local procedure OpenOrderSubject(): Text
    begin
        exit(StrSubstNo(
            'Open Order Status as of %1',
            Format(WorkDate(), 0, '<Month,2>/<Day,2>/<Year4>')));
    end;

    local procedure OpenOrderFileName(CustomerNo: Code[20]): Text
    begin
        exit(StrSubstNo(
            'Open-Order-Status %1 %2.pdf',
            CustomerNo,
            Format(WorkDate(), 0, '<Year4>-<Month,2>-<Day,2>')));
    end;

    [ConfirmHandler]
    local procedure UATConfirmHandler(Question: Text[1024]; var Reply: Boolean)
    begin
        Reply := true;
    end;

    [MessageHandler]
    local procedure UATMessageHandler(MessageText: Text[1024])
    begin
        LastBatchMessage := MessageText;
    end;

    var
        LastBatchMessage: Text[1024];
}
