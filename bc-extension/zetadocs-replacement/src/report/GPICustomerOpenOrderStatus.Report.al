report 70580 "GPI Customer Open Orders"
{
    Caption = 'GPI Customer Open Order Status';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPICustomerOpenOrderStatus;

    dataset
    {
        dataitem(Customer; Customer)
        {
            RequestFilterFields = "No.";

            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddressLine; CompanyAddressLine) { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CustomerNo; "No.") { }
            column(CustomerName; Name) { }
            column(CustomerAddressLine; CustomerAddressLine) { }
            column(CustomerContact; Contact) { }
            column(ReportDate; WorkDate()) { }
            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(ContactLine; ContactLine) { }

            dataitem(SalesHeader; "Sales Header")
            {
                DataItemLink = "Sell-to Customer No." = field("No.");
                DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const(Order));

                column(SalesOrderNo; "No.") { }
                column(CustomerPONo; "External Document No.") { }
                column(OrderDate; "Order Date") { }
                column(HeaderRequestedDate; "Requested Delivery Date") { }
                column(HeaderPromisedDate; "Promised Delivery Date") { }

                dataitem(SalesLine; "Sales Line")
                {
                    DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                    DataItemTableView = sorting("Document Type", "Document No.", "Line No.") where(Type = const(Item));

                    column(ItemNo; "No.") { }
                    column(LineDescription; Description) { }
                    column(LineDescription2; "Description 2") { }
                    column(OrderedQuantity; Quantity) { }
                    column(ShippedQuantity; "Quantity Shipped") { }
                    column(OutstandingQuantity; "Outstanding Quantity") { }
                    column(UnitOfMeasureCode; "Unit of Measure Code") { }
                    column(SupplyType; SupplyType) { }
                    column(PurchaseOrderNo; PurchaseOrderNo) { }
                    column(ExpectedDate; ExpectedDate) { }
                    column(StatusText; StatusText) { }

                    trigger OnPreDataItem()
                    begin
                        SetFilter("Outstanding Quantity", '>0');
                    end;

                    trigger OnAfterGetRecord()
                    var
                        PurchaseOrderLineNo: Integer;
                        DropShipment: Boolean;
                    begin
                        if not LineVisibilityMgt.ShouldPrintSalesLine(SalesLine, false) then
                            CurrReport.Skip();

                        GetPurchaseLink(SalesLine, PurchaseOrderNo, PurchaseOrderLineNo);
                        DropShipment := GetDropShipment(SalesLine);
                        ExpectedDate := ResolveExpectedDate(SalesLine, PurchaseOrderNo, PurchaseOrderLineNo);

                        if DropShipment then
                            SupplyType := 'Drop Ship'
                        else
                            SupplyType := 'Warehouse';

                        StatusText := BuildStatusText(SalesLine, PurchaseOrderNo, ExpectedDate, DropShipment);
                    end;
                }

                trigger OnAfterGetRecord()
                begin
                    LineVisibilityMgt.ValidateSalesExternalDocument(SalesHeader);
                end;
            }

            trigger OnAfterGetRecord()
            begin
                CompanyAddressLine := BuildAddressLine(
                    CompanyInfo.Address,
                    CompanyInfo."Address 2",
                    CompanyInfo.City,
                    CompanyInfo.County,
                    CompanyInfo."Post Code");
                CustomerAddressLine := BuildAddressLine(
                    Address,
                    "Address 2",
                    City,
                    County,
                    "Post Code");
                ResolveSalespeople(Customer);
                BuildContactLine();
            end;
        }
    }

    requestpage
    {
        SaveValues = false;
    }

    rendering
    {
        layout(GPICustomerOpenOrderStatus)
        {
            Type = RDLC;
            Caption = 'GPI Customer Open Order Status';
            Summary = 'Customer-facing open Sales Order status with warehouse and drop-ship supply details.';
            LayoutFile = 'src/reportlayout/GPICustomerOpenOrderStatusBranded.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
    end;

    local procedure ResolveSalespeople(Customer: Record Customer)
    var
        Salesperson: Record "Salesperson/Purchaser";
        InsideSalespersonCode: Code[20];
    begin
        Clear(SalespersonName);
        Clear(InsideSalespersonName);

        if (Customer."Salesperson Code" <> '') and Salesperson.Get(Customer."Salesperson Code") then
            SalespersonName := Salesperson.Name;

        InsideSalespersonCode := FindInsideSalespersonCode(Customer);
        if (InsideSalespersonCode <> '') and Salesperson.Get(InsideSalespersonCode) then
            InsideSalespersonName := Salesperson.Name;
    end;

    local procedure FindInsideSalespersonCode(Customer: Record Customer): Code[20]
    var
        CustomerRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
    begin
        CustomerRef.GetTable(Customer);
        for FieldIndex := 1 to CustomerRef.FieldCount do begin
            CandidateField := CustomerRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if ((StrPos(CandidateIdentity, 'inside salesperson') > 0) or
                (StrPos(CandidateIdentity, 'inside sales') > 0) or
                (StrPos(CandidateIdentity, 'isr') > 0)) and
               (StrPos(CandidateIdentity, 'backup') = 0)
            then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
                    exit(CopyStr(CandidateValue, 1, 20));
            end;
        end;
        exit('');
    end;

    local procedure GetPurchaseLink(SalesLine: Record "Sales Line"; var PurchaseOrderNo: Code[20]; var PurchaseOrderLineNo: Integer)
    var
        SalesLineRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
    begin
        Clear(PurchaseOrderNo);
        Clear(PurchaseOrderLineNo);
        SalesLineRef.GetTable(SalesLine);

        for FieldIndex := 1 to SalesLineRef.FieldCount do begin
            CandidateField := SalesLineRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);

            if (((StrPos(CandidateIdentity, 'purchase order no') > 0) or
                 (StrPos(CandidateIdentity, 'purch. order no') > 0)) and
                (StrPos(CandidateIdentity, 'line') = 0))
            then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
                    PurchaseOrderNo := CopyStr(CandidateValue, 1, MaxStrLen(PurchaseOrderNo));
            end;

            if (((StrPos(CandidateIdentity, 'purchase order line no') > 0) or
                 (StrPos(CandidateIdentity, 'purch. order line no') > 0)) and
                (PurchaseOrderLineNo = 0))
            then
                Evaluate(PurchaseOrderLineNo, Format(CandidateField.Value));
        end;
    end;

    local procedure GetDropShipment(SalesLine: Record "Sales Line"): Boolean
    var
        SalesLineRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        Result: Boolean;
    begin
        SalesLineRef.GetTable(SalesLine);
        for FieldIndex := 1 to SalesLineRef.FieldCount do begin
            CandidateField := SalesLineRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if StrPos(CandidateIdentity, 'drop shipment') > 0 then begin
                Evaluate(Result, Format(CandidateField.Value));
                exit(Result);
            end;
        end;
        exit(false);
    end;

    local procedure ResolveExpectedDate(SalesLine: Record "Sales Line"; PurchaseOrderNo: Code[20]; PurchaseOrderLineNo: Integer): Date
    var
        PurchaseLine: Record "Purchase Line";
    begin
        if (PurchaseOrderNo <> '') and (PurchaseOrderLineNo > 0) then
            if PurchaseLine.Get(PurchaseLine."Document Type"::Order, PurchaseOrderNo, PurchaseOrderLineNo) then begin
                if PurchaseLine."Expected Receipt Date" <> 0D then
                    exit(PurchaseLine."Expected Receipt Date");
                if PurchaseLine."Promised Receipt Date" <> 0D then
                    exit(PurchaseLine."Promised Receipt Date");
                if PurchaseLine."Requested Receipt Date" <> 0D then
                    exit(PurchaseLine."Requested Receipt Date");
            end;

        if SalesLine."Promised Delivery Date" <> 0D then
            exit(SalesLine."Promised Delivery Date");
        if SalesLine."Requested Delivery Date" <> 0D then
            exit(SalesLine."Requested Delivery Date");
        if SalesLine."Planned Delivery Date" <> 0D then
            exit(SalesLine."Planned Delivery Date");
        exit(SalesLine."Shipment Date");
    end;

    local procedure BuildStatusText(SalesLine: Record "Sales Line"; PurchaseOrderNo: Code[20]; ExpectedDate: Date; DropShipment: Boolean): Text[50]
    begin
        if (ExpectedDate <> 0D) and (ExpectedDate < WorkDate()) then
            exit('Overdue');
        if SalesLine."Quantity Shipped" > 0 then
            exit('Partially Shipped');
        if (PurchaseOrderNo <> '') and DropShipment then
            exit('Awaiting Supplier');
        if PurchaseOrderNo <> '' then
            exit('On Purchase Order');
        if ExpectedDate <> 0D then
            exit('Scheduled');
        exit('Open');
    end;

    local procedure BuildContactLine()
    begin
        if InsideSalespersonName <> '' then
            ContactLine := StrSubstNo(
                'Please contact %1 at %2 with questions about this open order status.',
                InsideSalespersonName,
                CompanyInfo."Phone No.")
        else
            ContactLine := StrSubstNo(
                'Please contact Gamer Packaging at %1 with questions about this open order status.',
                CompanyInfo."Phone No.");
    end;

    local procedure BuildAddressLine(Address: Text; Address2: Text; City: Text; State: Text; PostCode: Text): Text
    var
        Result: Text;
    begin
        Result := Address;
        if Address2 <> '' then
            Result += ' ' + Address2;
        if City <> '' then begin
            if Result <> '' then
                Result += ', ';
            Result += City;
        end;
        if State <> '' then
            Result += ', ' + State;
        if PostCode <> '' then
            Result += ' ' + PostCode;
        exit(Result);
    end;

    var
        CompanyInfo: Record "Company Information";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        CompanyAddressLine: Text[250];
        CustomerAddressLine: Text[250];
        SalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        ContactLine: Text[250];
        SupplyType: Text[30];
        PurchaseOrderNo: Code[20];
        ExpectedDate: Date;
        StatusText: Text[50];
}
