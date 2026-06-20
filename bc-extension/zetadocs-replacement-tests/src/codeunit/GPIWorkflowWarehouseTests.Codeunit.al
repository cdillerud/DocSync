codeunit 70712 "GPI Workflow Warehouse Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata Location = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd,
        tabledata "Transfer Header" = rimd,
        tabledata "Transfer Line" = rimd,
        tabledata "GPI Document Routing Rule" = rimd,
        tabledata "GPI Document Delivery Log" = rimd;

    [Test]
    procedure TransferPickDraftWritesDiscardedLog()
    var
        Header: Record "Transfer Header";
        Log: Record "GPI Document Delivery Log";
        Workflow: Codeunit "GPI Transfer Email";
        Mock: Codeunit "GPI Transport Mock";
        Helper: Codeunit "GPI Workflow Test Helper";
        Action: Enum "Email Action";
        RuleEntryNo: Integer;
    begin
        Helper.CreateTransfer(Header, RuleEntryNo);
        Helper.ConfigureMock(Mock, Action::Discarded);
        BindSubscription(Mock);
        Workflow.OpenPickListDraft(Header);
        UnbindSubscription(Mock);

        Helper.FindLog(Database::"Transfer Header", Header."No.", Enum::"GPI Delivery Document Type"::"Transfer Pick List", Log);
        Helper.AssertLog(Log, Log.Status::Discarded, 'transferpick@example.com', RuleEntryNo);
        if Log."Location Code" <> Header."Transfer-from Code" then
            Error('The Transfer recipient location was not logged.');
    end;

    [Test]
    procedure OpenOrderDraftWritesSavedDraftLog()
    var
        Customer: Record Customer;
        Log: Record "GPI Document Delivery Log";
        Workflow: Codeunit "GPI Customer Open Order Email";
        Mock: Codeunit "GPI Transport Mock";
        Helper: Codeunit "GPI Workflow Test Helper";
        Action: Enum "Email Action";
        SalesOrderNo: Code[20];
        RuleEntryNo: Integer;
    begin
        Helper.CreateOpenOrder(Customer, SalesOrderNo, RuleEntryNo);
        Helper.ConfigureMock(Mock, Action::"Saved As Draft");
        BindSubscription(Mock);
        Workflow.OpenOpenOrderDraft(Customer);
        UnbindSubscription(Mock);

        Helper.FindLog(Database::Customer, Customer."No.", Enum::"GPI Delivery Document Type"::"Customer Open Order Status", Log);
        Helper.AssertLog(Log, Log.Status::"Saved As Draft", 'openorders@example.com', RuleEntryNo);
        if Log."Open Order Count" <> 1 then
            Error('The Open Order count was not logged.');
        if Log."Open Order Line Count" <> 1 then
            Error('The Open Order line count was not logged.');
        if StrPos(Log."Included Order Nos.", SalesOrderNo) = 0 then
            Error('The included Sales Order number was not logged.');
    end;
}
