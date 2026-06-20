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

    [Test]
    procedure XmlDatasetIncludesOnlyVisibleOutstandingItemLines()
    var
        XmlText: Text;
        CustomerNo: Code[20];
        FirstOrderNo: Code[20];
        SecondOrderNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        FirstOrderNo := NewTestCode('GPIA');
        SecondOrderNo := NewTestCode('GPIB');
        CreateCustomer(CustomerNo, 'GPI Open Order XML Test');
        CreateSalesOrder(FirstOrderNo, CustomerNo);
        CreateSalesOrder(SecondOrderNo, CustomerNo);

        CreateSalesLine(FirstOrderNo, 10000, 'GPI-INCLUDED-A', 10, 4, 6, 60, Enum::"GPI Document Visibility"::"All Documents");
        CreateSalesLine(FirstOrderNo, 20000, 'GPI-FULLY-SHIPPED', 5, 5, 0, 0, Enum::"GPI Document Visibility"::"All Documents");
        CreateSalesLine(FirstOrderNo, 30000, 'GPI-HIDDEN-ZERO', 2, 0, 2, 0, Enum::"GPI Document Visibility"::"Do Not Print");
        CreateSalesLine(SecondOrderNo, 10000, 'GPI-INCLUDED-B', 3, 0, 3, 30, Enum::"GPI Document Visibility"::"Customer/Vendor Documents Only");

        XmlText := RenderOpenOrderXml(CustomerNo);

        AssertContains(XmlText, FirstOrderNo, 'The first open Sales Order was not included.');
        AssertContains(XmlText, SecondOrderNo, 'The second open Sales Order was not included.');
        AssertContains(XmlText, 'GPI-INCLUDED-A', 'The first visible outstanding line was not included.');
        AssertContains(XmlText, 'GPI-INCLUDED-B', 'The second visible outstanding line was not included.');
        AssertNotContains(XmlText, 'GPI-FULLY-SHIPPED', 'A fully shipped line was included.');
        AssertNotContains(XmlText, 'GPI-HIDDEN-ZERO', 'A Do Not Print line was included.');
    end;

    [Test]
    procedure HiddenNonzeroLineStopsReportGeneration()
    var
        Customer: Record Customer;
        CustomerRef: RecordRef;
        TempBlob: Codeunit "Temp Blob";
        XmlOutStream: OutStream;
        CustomerNo: Code[20];
        OrderNo: Code[20];
    begin
        CustomerNo := NewTestCode('GPIC');
        OrderNo := NewTestCode('GPIO');
        CreateCustomer(CustomerNo, 'GPI Hidden Financial Line Test');
        CreateSalesOrder(OrderNo, CustomerNo);
        CreateSalesLine(OrderNo, 10000, 'GPI-HIDDEN-AMOUNT', 1, 0, 1, 25, Enum::"GPI Document Visibility"::"Warehouse Documents Only");

        Customer.SetRange("No.", CustomerNo);
        CustomerRef.GetTable(Customer);
        TempBlob.CreateOutStream(XmlOutStream);

        AssertError Report.SaveAs(
            Report::"GPI Customer Open Orders",
            '',
            ReportFormat::Xml,
            XmlOutStream,
            CustomerRef);
        AssertContains(GetLastErrorText(), 'financial lines must appear', 'The report did not enforce the financial-line visibility rule.');
    end;

    local procedure RenderOpenOrderXml(CustomerNo: Code[20]): Text
    var
        Customer: Record Customer;
        CustomerRef: RecordRef;
        TempBlob: Codeunit "Temp Blob";
        XmlOutStream: OutStream;
        XmlInStream: InStream;
        XmlText: Text;
        XmlLine: Text;
    begin
        Customer.SetRange("No.", CustomerNo);
        CustomerRef.GetTable(Customer);
        TempBlob.CreateOutStream(XmlOutStream, TextEncoding::UTF8);
        Report.SaveAs(
            Report::"GPI Customer Open Orders",
            '',
            ReportFormat::Xml,
            XmlOutStream,
            CustomerRef);
        TempBlob.CreateInStream(XmlInStream, TextEncoding::UTF8);
        while not XmlInStream.EOS do begin
            XmlInStream.ReadText(XmlLine);
            XmlText += XmlLine;
        end;
        exit(XmlText);
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

    local procedure AssertContains(ActualText: Text; ExpectedFragment: Text; FailureMessage: Text)
    begin
        if StrPos(ActualText, ExpectedFragment) = 0 then
            Error('%1 Expected fragment: %2', FailureMessage, ExpectedFragment);
    end;

    local procedure AssertNotContains(ActualText: Text; UnexpectedFragment: Text; FailureMessage: Text)
    begin
        if StrPos(ActualText, UnexpectedFragment) > 0 then
            Error('%1 Unexpected fragment: %2', FailureMessage, UnexpectedFragment);
    end;

}
