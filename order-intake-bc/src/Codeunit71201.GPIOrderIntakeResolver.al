/// <summary>
/// Phase-0 deterministic resolver for Giovanni order-intake contexts.
/// The incoming PO owns quantity. Business Central validates the requested item/UOM/location,
/// while Unit Price is resolved only from repeated posted Sales Invoice Line evidence for the
/// pricing context customer + item + UOM + location. Quantity is evidence, not a required price key.
/// Boyer Customer Item Sales is corroborating rolling-cache evidence only and never price authority.
/// </summary>
codeunit 71201 "GPI Order Intake Resolver"
{
    Permissions =
        tabledata "Item Unit of Measure" = R,
        tabledata "Sales Invoice Line" = R,
        tabledata "Customer Item Sales" = R;

    procedure ResolveGiovanniUnitPrice(
        CustomerNo: Code[20];
        ItemNo: Code[20];
        Quantity: Decimal;
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10];
        var ResolvedUnitPrice: Decimal;
        var MatchingPriceEvidenceCount: Integer;
        var LatestEvidenceDocumentNo: Code[20];
        var BoyerRollingStateCorroborates: Boolean)
    var
        SalesInvoiceLine: Record "Sales Invoice Line";
        CustomerItemSales: Record "Customer Item Sales";
        LatestCreatedAt: DateTime;
        SecondLatestCreatedAt: DateTime;
        LatestUnitPrice: Decimal;
        SecondLatestUnitPrice: Decimal;
        LatestDocumentNo: Code[20];
        SecondLatestDocumentNo: Code[20];
    begin
        AssertSupportedGiovanniContext(
            CustomerNo,
            ItemNo,
            Quantity,
            UnitOfMeasureCode,
            LocationCode);

        FindTwoLatestPricingContextInvoices(
            CustomerNo,
            ItemNo,
            UnitOfMeasureCode,
            LocationCode,
            SalesInvoiceLine,
            LatestCreatedAt,
            LatestUnitPrice,
            LatestDocumentNo,
            SecondLatestCreatedAt,
            SecondLatestUnitPrice,
            SecondLatestDocumentNo);

        if LatestCreatedAt = 0DT then
            Error(
                'Order Intake pricing REVIEW required. No posted invoice evidence exists for customer %1, item %2, UOM %3, location %4.',
                CustomerNo,
                ItemNo,
                UnitOfMeasureCode,
                LocationCode);

        if SecondLatestCreatedAt = 0DT then
            Error(
                'Order Intake pricing REVIEW required. Only one posted invoice observation exists for customer %1, item %2, UOM %3, location %4. Latest document is %5 at Unit Price %6.',
                CustomerNo,
                ItemNo,
                UnitOfMeasureCode,
                LocationCode,
                LatestDocumentNo,
                LatestUnitPrice);

        if (LatestUnitPrice <= 0) or (SecondLatestUnitPrice <= 0) then
            Error(
                'Order Intake pricing REVIEW required. Latest pricing-context posted invoice prices must both be greater than zero. Documents %1/%2 returned %3/%4.',
                LatestDocumentNo,
                SecondLatestDocumentNo,
                LatestUnitPrice,
                SecondLatestUnitPrice);

        if LatestUnitPrice <> SecondLatestUnitPrice then
            Error(
                'Order Intake pricing REVIEW required. The two most recent pricing-context posted invoices disagree on Unit Price. %1 = %2; %3 = %4.',
                LatestDocumentNo,
                LatestUnitPrice,
                SecondLatestDocumentNo,
                SecondLatestUnitPrice);

        ResolvedUnitPrice := LatestUnitPrice;
        LatestEvidenceDocumentNo := LatestDocumentNo;

        SalesInvoiceLine.Reset();
        ApplyPricingContextFilters(
            SalesInvoiceLine,
            CustomerNo,
            ItemNo,
            UnitOfMeasureCode,
            LocationCode);
        SalesInvoiceLine.SetRange("Unit Price", ResolvedUnitPrice);
        MatchingPriceEvidenceCount := SalesInvoiceLine.Count();

        BoyerRollingStateCorroborates := false;
        if CustomerItemSales.Get(CustomerNo, ItemNo) then
            BoyerRollingStateCorroborates :=
                (CustomerItemSales."Last Sold Unit of Measure Code" = UnitOfMeasureCode) and
                (CustomerItemSales."Last Unit Price" = ResolvedUnitPrice) and
                (CustomerItemSales."Location Code" = LocationCode);
    end;

    local procedure FindTwoLatestPricingContextInvoices(
        CustomerNo: Code[20];
        ItemNo: Code[20];
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10];
        var SalesInvoiceLine: Record "Sales Invoice Line";
        var LatestCreatedAt: DateTime;
        var LatestUnitPrice: Decimal;
        var LatestDocumentNo: Code[20];
        var SecondLatestCreatedAt: DateTime;
        var SecondLatestUnitPrice: Decimal;
        var SecondLatestDocumentNo: Code[20])
    var
        CandidateCreatedAt: DateTime;
    begin
        Clear(LatestCreatedAt);
        Clear(LatestUnitPrice);
        Clear(LatestDocumentNo);
        Clear(SecondLatestCreatedAt);
        Clear(SecondLatestUnitPrice);
        Clear(SecondLatestDocumentNo);

        SalesInvoiceLine.Reset();
        ApplyPricingContextFilters(
            SalesInvoiceLine,
            CustomerNo,
            ItemNo,
            UnitOfMeasureCode,
            LocationCode);

        if SalesInvoiceLine.FindSet() then
            repeat
                CandidateCreatedAt := SalesInvoiceLine.SystemCreatedAt;
                if CandidateCreatedAt > LatestCreatedAt then begin
                    SecondLatestCreatedAt := LatestCreatedAt;
                    SecondLatestUnitPrice := LatestUnitPrice;
                    SecondLatestDocumentNo := LatestDocumentNo;

                    LatestCreatedAt := CandidateCreatedAt;
                    LatestUnitPrice := SalesInvoiceLine."Unit Price";
                    LatestDocumentNo := SalesInvoiceLine."Document No.";
                end else
                    if CandidateCreatedAt > SecondLatestCreatedAt then begin
                        SecondLatestCreatedAt := CandidateCreatedAt;
                        SecondLatestUnitPrice := SalesInvoiceLine."Unit Price";
                        SecondLatestDocumentNo := SalesInvoiceLine."Document No.";
                    end;
            until SalesInvoiceLine.Next() = 0;
    end;

    local procedure ApplyPricingContextFilters(
        var SalesInvoiceLine: Record "Sales Invoice Line";
        CustomerNo: Code[20];
        ItemNo: Code[20];
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10])
    begin
        SalesInvoiceLine.SetRange("Sell-to Customer No.", CustomerNo);
        SalesInvoiceLine.SetRange(Type, SalesInvoiceLine.Type::Item);
        SalesInvoiceLine.SetRange("No.", ItemNo);
        SalesInvoiceLine.SetRange("Unit of Measure Code", UnitOfMeasureCode);
        SalesInvoiceLine.SetRange("Location Code", LocationCode);
    end;

    local procedure AssertSupportedGiovanniContext(
        CustomerNo: Code[20];
        ItemNo: Code[20];
        Quantity: Decimal;
        UnitOfMeasureCode: Code[10];
        LocationCode: Code[10])
    var
        ItemUnitOfMeasure: Record "Item Unit of Measure";
    begin
        if CustomerNo <> 'GIOVANN' then
            Error('Order Intake Phase-0 resolver currently supports only customer GIOVANN. Customer %1 requires REVIEW.', CustomerNo);

        if Quantity <= 0 then
            Error('Order Intake quantity REVIEW required for Giovanni item %1. Quantity must be greater than zero.', ItemNo);

        if UnitOfMeasureCode = '' then
            Error('Order Intake UOM REVIEW required for Giovanni item %1. UOM is required.', ItemNo);

        if LocationCode = '' then
            Error('Order Intake location is required before pricing can be resolved.');

        case ItemNo of
            'C-8808-12026443',
            'C-8479-10000229',
            'C-503004-12033478',
            'C-503003-12033922':
                begin
                    if not ItemUnitOfMeasure.Get(ItemNo, UnitOfMeasureCode) then
                        Error(
                            'Order Intake UOM REVIEW required for Giovanni item %1. UOM %2 is not configured for the item in Business Central.',
                            ItemNo,
                            UnitOfMeasureCode);
                end;
            'C-9874-10001833':
                Error(
                    'Order Intake quantity-source REVIEW required for Giovanni 24oz Pasta item %1. The current blanket workbook does not state quantity and both 62.062 M and 56.42 M repeat in authoritative history; an explicit quantity source or resolved business distinction is required.',
                    ItemNo);
            'C-8682-12013925':
                Error(
                    'Order Intake exception REVIEW required for Giovanni mixed/exception Salsa item %1. This item is never eligible for normal-row automatic resolution.',
                    ItemNo);
            else
                Error(
                    'Order Intake Giovanni item %1 is not in the Phase-0 deterministic resolver allow-list. REVIEW required.',
                    ItemNo);
        end;
    end;
}
