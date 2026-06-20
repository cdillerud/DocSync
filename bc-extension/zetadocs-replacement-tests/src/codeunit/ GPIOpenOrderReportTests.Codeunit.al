codeunit 70704 "GPI Open Order Report Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd;

    [Test]
    procedure OpenOrderReportRendersNonemptyPdf()
    var
        Customer: Record Customer;
        CustomerRef: RecordRef;
        TempBlob: Codeunit "Temp Blob";
        PdfOutStream: OutStream;
        CustomerNo: Code[20];
        OrderNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        OrderNo := NewTestCode('GPIO');
        CreateCustomer(CustomerNo, 'GPI Open Order PDF Test');
        CreateSalesOrder(OrderNo, CustomerNo);
        CreateSalesLine(
            OrderNo,
            10000,
            'GPI-PDF-ITEM',
            10,
            2,
            8,
            80,
            Enum::"GPI Document Visibility"::"All Documents");

        Customer.SetRange("No.", CustomerNo);
        CustomerRef.GetTable(Customer);
        TempBlob.CreateOutStream(PdfOutStream);
        Report.SaveAs(
            Report::"GPI Customer Open Orders",
            '',
            ReportFormat::Pdf,
            PdfOutStream,
            CustomerRef);

        if not TempBlob.HasValue() then
            Error('The Customer Open Order Status report did not render a PDF.');
    end;

    local procedure CreateCustomer(CustomerNo: Code[20]; CustomerName: Text[100])
    var
        Customer: Record Customer;
    begin
        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := CustomerName;
        Customer.Insert(false);
    end;

    local procedure CreateSalesOrder(OrderNo: Code[20]; CustomerNo: Code[20])
    var
        SalesHeader: Record "Sales Header";
    begin
        SalesHeader.Init();
        SalesHeader."Document Type" := SalesHeader."Document Type"::Order;
        SalesHeader."No." := OrderNo;
        SalesHeader."Sell-to Customer No." := CustomerNo;
        SalesHeader."Bill-to Customer No." := CustomerNo;
        SalesHeader."Order Date" := WorkDate();
        SalesHeader.Insert(false);
    end;

    local procedure CreateSalesLine(OrderNo: Code[20]; LineNo: Integer; ItemNo: Code[20]; Quantity: Decimal; QuantityShipped: Decimal; OutstandingQuantity: Decimal; LineAmount: Decimal; Visibility: Enum "GPI Document Visibility")
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.Init();
        SalesLine."Document Type" := SalesLine."Document Type"::Order;
        SalesLine."Document No." := OrderNo;
        SalesLine."Line No." := LineNo;
        SalesLine.Type := SalesLine.Type::Item;
        SalesLine."No." := ItemNo;
        SalesLine.Description := ItemNo;
        SalesLine.Quantity := Quantity;
        SalesLine."Quantity Shipped" := QuantityShipped;
        SalesLine."Outstanding Quantity" := OutstandingQuantity;
        SalesLine."Unit of Measure Code" := 'EA';
        SalesLine."Line Amount" := LineAmount;
        SalesLine."GPI Document Visibility" := Visibility;
        SalesLine.Insert(false);
    end;

    local procedure NewTestCode(Prefix: Text): Code[20]
    var
        GuidText: Text;
    begin
        GuidText := DelChr(Format(CreateGuid()), '=', '{}-');
        exit(CopyStr(Prefix + GuidText, 1, 20));
    end;
}
