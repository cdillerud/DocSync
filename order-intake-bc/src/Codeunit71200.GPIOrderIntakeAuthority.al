/// <summary>
/// Phase-0 Business Central authority for GPI Order Intake.
/// Creates only tagged Draft/Open Sales Orders in the certified PRE sandbox.
/// Uses standard Sales Header / Sales Line validation so BC remains authoritative
/// for customer, item, UOM, location, dates, discounts and pricing.
/// </summary>
codeunit 71200 "GPI Order Intake Authority"
{
    Permissions =
        tabledata Customer = R,
        tabledata Item = R,
        tabledata Location = R,
        tabledata "Sales Header" = RIM,
        tabledata "Sales Line" = RIM,
        tabledata "Sales Invoice Header" = R;

    procedure CreateValidatedDraft(
        CustomerNo: Code[20];
        ItemNo: Code[20];
        Quantity: Decimal;
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10];
        OrderDate: Date;
        ShipmentDate: Date;
        ExternalDocumentNo: Code[35];
        var CreatedSalesHeader: Record "Sales Header";
        var CreatedSalesLine: Record "Sales Line")
    var
        Customer: Record Customer;
        Item: Record Item;
        Location: Record Location;
        ExistingSalesHeader: Record "Sales Header";
        SalesInvoiceHeader: Record "Sales Invoice Header";
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        AssertPhase0Target(EnvironmentInformation, ExternalDocumentNo);
        AssertRequiredInputs(
            CustomerNo,
            ItemNo,
            Quantity,
            UnitOfMeasureCode,
            LocationCode,
            OrderDate,
            ShipmentDate,
            ExternalDocumentNo);

        if not Customer.Get(CustomerNo) then
            Error('Order Intake customer %1 does not exist.', CustomerNo);

        if not Item.Get(ItemNo) then
            Error('Order Intake item %1 does not exist.', ItemNo);
        if Item.Blocked then
            Error('Order Intake item %1 is blocked.', ItemNo);

        if not Location.Get(LocationCode) then
            Error('Order Intake location %1 does not exist.', LocationCode);

        ExistingSalesHeader.SetRange("Sell-to Customer No.", CustomerNo);
        ExistingSalesHeader.SetRange("External Document No.", ExternalDocumentNo);
        if not ExistingSalesHeader.IsEmpty() then
            Error(
                'Duplicate blocked. Sales document already exists for customer %1 and external document %2.',
                CustomerNo,
                ExternalDocumentNo);

        SalesInvoiceHeader.SetRange("Sell-to Customer No.", CustomerNo);
        SalesInvoiceHeader.SetRange("External Document No.", ExternalDocumentNo);
        if not SalesInvoiceHeader.IsEmpty() then
            Error(
                'Duplicate blocked. Posted sales invoice already exists for customer %1 and external document %2.',
                CustomerNo,
                ExternalDocumentNo);

        CreatedSalesHeader.Init();
        CreatedSalesHeader."Document Type" := CreatedSalesHeader."Document Type"::Order;
        CreatedSalesHeader.Insert(true);
        CreatedSalesHeader.Validate("Sell-to Customer No.", CustomerNo);
        CreatedSalesHeader.Validate("External Document No.", ExternalDocumentNo);
        CreatedSalesHeader.Validate("Order Date", OrderDate);
        CreatedSalesHeader.Validate("Document Date", OrderDate);
        CreatedSalesHeader.Validate("Location Code", LocationCode);
        CreatedSalesHeader.Validate("Shipment Date", ShipmentDate);
        CreatedSalesHeader.Modify(true);

        CreatedSalesLine.Init();
        CreatedSalesLine."Document Type" := CreatedSalesLine."Document Type"::Order;
        CreatedSalesLine."Document No." := CreatedSalesHeader."No.";
        CreatedSalesLine."Line No." := 10000;
        CreatedSalesLine.Insert(true);
        CreatedSalesLine.Validate(Type, CreatedSalesLine.Type::Item);
        CreatedSalesLine.Validate("No.", ItemNo);
        CreatedSalesLine.Validate("Location Code", LocationCode);
        CreatedSalesLine.Validate("Shipment Date", ShipmentDate);
        CreatedSalesLine.Validate("Unit of Measure Code", UnitOfMeasureCode);
        CreatedSalesLine.Validate(Quantity, Quantity);

        // Explicitly execute the standard Sales Line price-calculation path after
        // all known pricing context has been validated onto the line.
        CreatedSalesLine.UpdateUnitPrice(CreatedSalesLine.FieldNo(Quantity));
        CreatedSalesLine.Modify(true);

        CreatedSalesLine.TestField("No.", ItemNo);
        CreatedSalesLine.TestField("Location Code", LocationCode);
        CreatedSalesLine.TestField("Unit of Measure Code", UnitOfMeasureCode);
        CreatedSalesLine.TestField(Quantity, Quantity);

        if CreatedSalesLine."Unit Price" <= 0 then
            Error(
                'BC pricing validation returned Unit Price %1 for customer %2, item %3, quantity %4 %5, location %6, order date %7, shipment date %8. The draft order was rolled back.',
                CreatedSalesLine."Unit Price",
                CustomerNo,
                ItemNo,
                Quantity,
                UnitOfMeasureCode,
                LocationCode,
                OrderDate,
                ShipmentDate);
    end;

    local procedure AssertPhase0Target(
        EnvironmentInformation: Codeunit "Environment Information";
        ExternalDocumentNo: Code[35])
    var
        EnvironmentName: Text;
    begin
        if not EnvironmentInformation.IsSandbox() then
            Error('GPI Order Intake Phase 0 is sandbox-only. Production execution is blocked.');

        EnvironmentName := EnvironmentInformation.GetEnvironmentName();
        if EnvironmentName <> 'PRE_GAMERDOCS_CUTOVER_20260831' then
            Error(
                'GPI Order Intake Phase 0 is hard-pinned to PRE_GAMERDOCS_CUTOVER_20260831. Current environment is %1.',
                EnvironmentName);

        if CopyStr(ExternalDocumentNo, 1, 7) <> 'AITEST-' then
            Error('GPI Order Intake Phase 0 only permits AITEST- external document numbers.');
    end;

    local procedure AssertRequiredInputs(
        CustomerNo: Code[20];
        ItemNo: Code[20];
        Quantity: Decimal;
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10];
        OrderDate: Date;
        ShipmentDate: Date;
        ExternalDocumentNo: Code[35])
    begin
        if CustomerNo = '' then
            Error('Customer No. is required.');
        if ItemNo = '' then
            Error('Item No. is required.');
        if Quantity <= 0 then
            Error('Quantity must be greater than zero.');
        if UnitOfMeasureCode = '' then
            Error('Unit of Measure Code is required.');
        if LocationCode = '' then
            Error('Location Code is required.');
        if OrderDate = 0D then
            Error('Order Date is required.');
        if ShipmentDate = 0D then
            Error('Shipment Date is required.');
        if ExternalDocumentNo = '' then
            Error('External Document No. is required.');
    end;
}
