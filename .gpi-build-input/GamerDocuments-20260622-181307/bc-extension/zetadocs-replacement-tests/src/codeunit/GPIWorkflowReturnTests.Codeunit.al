codeunit 70710 "GPI Workflow Return Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata Vendor = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd,
        tabledata "Purchase Header" = rimd,
        tabledata "Purchase Line" = rimd,
        tabledata "GPI Document Routing Rule" = rimd,
        tabledata "GPI Document Delivery Log" = rimd;

    [Test]
    procedure SalesReturnDraftWritesSavedDraftLog()
    var
        Header: Record "Sales Header";
        Log: Record "GPI Document Delivery Log";
        Workflow: Codeunit "GPI Sales Return Email";
        Mock: Codeunit "GPI Transport Mock";
        Helper: Codeunit "GPI Workflow Test Helper";
        Action: Enum "Email Action";
        RuleEntryNo: Integer;
    begin
        Helper.CreateSalesReturn(Header, RuleEntryNo);
        Helper.ConfigureMock(Mock, Action::"Saved As Draft");
        BindSubscription(Mock);
        Workflow.OpenAuthorizationDraft(Header);
        UnbindSubscription(Mock);

        Helper.FindLog(Database::"Sales Header", Header."No.", Enum::"GPI Delivery Document Type"::"Sales Return Authorization", Log);
        Helper.AssertLog(Log, Log.Status::"Saved As Draft", 'salesreturn@example.com', RuleEntryNo);
    end;

    [Test]
    procedure PurchaseReturnDraftWritesSentLog()
    var
        Header: Record "Purchase Header";
        Log: Record "GPI Document Delivery Log";
        Workflow: Codeunit "GPI Purchase Return Email";
        Mock: Codeunit "GPI Transport Mock";
        Helper: Codeunit "GPI Workflow Test Helper";
        Action: Enum "Email Action";
        RuleEntryNo: Integer;
    begin
        Helper.CreatePurchaseReturn(Header, RuleEntryNo);
        Helper.ConfigureMock(Mock, Action::Sent);
        BindSubscription(Mock);
        Workflow.OpenVendorReturnDraft(Header);
        UnbindSubscription(Mock);

        Helper.FindLog(Database::"Purchase Header", Header."No.", Enum::"GPI Delivery Document Type"::"Purchase Return Order", Log);
        Helper.AssertLog(Log, Log.Status::Sent, 'purchasereturn@example.com', RuleEntryNo);
    end;
}
