codeunit 70703 "GPI Workflow Validation Tests"
{
    Subtype = Test;

    [Test]
    procedure OpenSalesReturnCannotBeEmailed()
    var
        SalesReturnEmail: Codeunit "GPI Sales Return Email";
        SalesHeader: Record "Sales Header" temporary;
    begin
        SalesHeader."Document Type" := SalesHeader."Document Type"::"Return Order";
        SalesHeader."No." := 'GPI-SRET-TEST';
        SalesHeader."Sell-to Customer No." := 'GPI-CUST';
        SalesHeader.Status := SalesHeader.Status::Open;

        AssertError SalesReturnEmail.OpenAuthorizationDraft(SalesHeader);
        AssertContains(GetLastErrorText(), 'Released', 'Open Sales Return Orders should be blocked from sending.');
    end;

    [Test]
    procedure OpenPurchaseReturnCannotBeEmailed()
    var
        PurchaseReturnEmail: Codeunit "GPI Purchase Return Email";
        PurchaseHeader: Record "Purchase Header" temporary;
    begin
        PurchaseHeader."Document Type" := PurchaseHeader."Document Type"::"Return Order";
        PurchaseHeader."No." := 'GPI-PRET-TEST';
        PurchaseHeader."Buy-from Vendor No." := 'GPI-VEND';
        PurchaseHeader.Status := PurchaseHeader.Status::Open;

        AssertError PurchaseReturnEmail.OpenVendorReturnDraft(PurchaseHeader);
        AssertContains(GetLastErrorText(), 'Released', 'Open Purchase Return Orders should be blocked from sending.');
    end;

    [Test]
    procedure TransferLocationsMustBeDifferent()
    var
        TransferEmail: Codeunit "GPI Transfer Email";
        TransferHeader: Record "Transfer Header" temporary;
    begin
        TransferHeader."No." := 'GPI-TR-TEST';
        TransferHeader."Transfer-from Code" := 'MAIN';
        TransferHeader."Transfer-to Code" := 'MAIN';

        AssertError TransferEmail.OpenPickListDraft(TransferHeader);
        AssertContains(GetLastErrorText(), 'different locations', 'A Transfer Order cannot use the same source and destination.');
    end;

    [Test]
    procedure OpenTransferCannotBeEmailed()
    var
        TransferEmail: Codeunit "GPI Transfer Email";
        TransferHeader: Record "Transfer Header" temporary;
    begin
        TransferHeader."No." := 'GPI-TR-OPEN';
        TransferHeader."Transfer-from Code" := 'MAIN';
        TransferHeader."Transfer-to Code" := 'EAST';
        TransferHeader.Status := TransferHeader.Status::Open;

        AssertError TransferEmail.OpenPickListDraft(TransferHeader);
        AssertContains(GetLastErrorText(), 'Released', 'Open Transfer Orders should be blocked from sending.');
    end;

    [Test]
    procedure CustomerWithoutOutstandingLinesCannotPreviewOpenOrderStatus()
    var
        OpenOrderEmail: Codeunit "GPI Customer Open Order Email";
        Customer: Record Customer temporary;
    begin
        Customer."No." := 'GPI-NO-ORDERS';

        AssertError OpenOrderEmail.PreviewOpenOrderStatus(Customer);
        AssertContains(GetLastErrorText(), 'no open Sales Order item lines', 'Customers without outstanding lines should be rejected.');
    end;

    local procedure AssertContains(ActualText: Text; ExpectedFragment: Text; FailureMessage: Text)
    begin
        if StrPos(LowerCase(ActualText), LowerCase(ExpectedFragment)) = 0 then
            Error('%1 Actual error: %2', FailureMessage, ActualText);
    end;
}
