codeunit 70521 "GPI Line Visibility Mgt."
{
    procedure ShouldPrintSalesLine(SalesLine: Record "Sales Line"; WarehouseDocument: Boolean): Boolean
    begin
        exit(ShouldPrint(SalesLine."GPI Document Visibility", WarehouseDocument));
    end;

    procedure ShouldPrintPurchaseLine(PurchaseLine: Record "Purchase Line"; WarehouseDocument: Boolean): Boolean
    begin
        exit(ShouldPrint(PurchaseLine."GPI Document Visibility", WarehouseDocument));
    end;

    procedure ValidateSalesExternalDocument(SalesHeader: Record "Sales Header")
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetRange("Document Type", SalesHeader."Document Type");
        SalesLine.SetRange("Document No.", SalesHeader."No.");
        if not SalesLine.FindSet() then
            exit;

        repeat
            if IsHiddenFromExternalDocument(SalesLine."GPI Document Visibility") and
               (SalesLine."Line Amount" <> 0)
            then
                Error(
                    'Line %1 on %2 %3 has amount %4 but Document Visibility is %5. Financial lines cannot be hidden from customer/vendor documents.',
                    SalesLine."Line No.",
                    Format(SalesHeader."Document Type"),
                    SalesHeader."No.",
                    Format(SalesLine."Line Amount"),
                    Format(SalesLine."GPI Document Visibility"));
        until SalesLine.Next() = 0;
    end;

    procedure ValidatePurchaseExternalDocument(PurchaseHeader: Record "Purchase Header")
    var
        PurchaseLine: Record "Purchase Line";
    begin
        PurchaseLine.SetRange("Document Type", PurchaseHeader."Document Type");
        PurchaseLine.SetRange("Document No.", PurchaseHeader."No.");
        if not PurchaseLine.FindSet() then
            exit;

        repeat
            if IsHiddenFromExternalDocument(PurchaseLine."GPI Document Visibility") and
               (PurchaseLine."Line Amount" <> 0)
            then
                Error(
                    'Line %1 on %2 %3 has amount %4 but Document Visibility is %5. Financial lines cannot be hidden from customer/vendor documents.',
                    PurchaseLine."Line No.",
                    Format(PurchaseHeader."Document Type"),
                    PurchaseHeader."No.",
                    Format(PurchaseLine."Line Amount"),
                    Format(PurchaseLine."GPI Document Visibility"));
        until PurchaseLine.Next() = 0;
    end;

    procedure ValidateFinancialLineVisibility(LineAmount: Decimal; Visibility: Enum "GPI Document Visibility")
    begin
        if IsHiddenFromExternalDocument(Visibility) and (LineAmount <> 0) then
            Error(
                'A line with amount %1 cannot use Document Visibility %2 because financial lines must appear on customer/vendor documents.',
                Format(LineAmount),
                Format(Visibility));
    end;

    local procedure ShouldPrint(Visibility: Enum "GPI Document Visibility"; WarehouseDocument: Boolean): Boolean
    begin
        case Visibility of
            Visibility::"All Documents":
                exit(true);
            Visibility::"Customer/Vendor Documents Only":
                exit(not WarehouseDocument);
            Visibility::"Warehouse Documents Only":
                exit(WarehouseDocument);
            Visibility::"Do Not Print":
                exit(false);
        end;

        exit(true);
    end;

    local procedure IsHiddenFromExternalDocument(Visibility: Enum "GPI Document Visibility"): Boolean
    begin
        exit(Visibility in [Visibility::"Warehouse Documents Only", Visibility::"Do Not Print"]);
    end;
}
