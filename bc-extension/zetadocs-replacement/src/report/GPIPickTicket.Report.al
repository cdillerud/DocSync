report 70522 "GPI Pick Ticket"
{
    Caption = 'GPI Pick Ticket';
    UsageCategory = None;
    ApplicationArea = All;
    DataAccessIntent = ReadOnly;
    DefaultRenderingLayout = GPIPickTicket;

    dataset
    {
        dataitem(SalesHeader; "Sales Header")
        {
            DataItemTableView = sorting("Document Type", "No.") where("Document Type" = const(Order));
            RequestFilterFields = "No.";
            column(CompanyLogo; CompanyInfo.Picture) { }
            column(CompanyName; CompanyInfo.Name) { }
            column(CompanyAddress; CompanyInfo.Address) { }
            column(CompanyAddress2; CompanyInfo."Address 2") { }
            column(CompanyCity; CompanyInfo.City) { }
            column(CompanyState; CompanyInfo.County) { }
            column(CompanyPostCode; CompanyInfo."Post Code") { }
            column(CompanyPhone; CompanyInfo."Phone No.") { }
            column(CompanyHomePage; CompanyInfo."Home Page") { }
            column(WarehouseDisplayName; WarehouseDisplayName) { }
            column(ShipToName; "Ship-to Name") { }
            column(ShipToAddress; "Ship-to Address") { }
            column(ShipToCity; "Ship-to City") { }
            column(ShipToState; "Ship-to County") { }
            column(ShipToPostCode; "Ship-to Post Code") { }
            column(ShipDate; "Shipment Date") { }
            column(OrderNo; "No.") { }
            column(OrderDate; "Order Date") { }
            column(SalespersonName; SalespersonName) { }
            column(InsideSalespersonName; InsideSalespersonName) { }
            column(BackupInsideSalespersonName; BackupInsideSalespersonName) { }
            column(ContactLine; ContactLine) { }
            column(CustomerNo; "Sell-to Customer No.") { }
            column(CustomerPONo; "External Document No.") { }
            column(ShippingAgentDescription; ShippingAgentDescription) { }

            dataitem(SalesLine; "Sales Line")
            {
                DataItemLink = "Document Type" = field("Document Type"), "Document No." = field("No.");
                DataItemTableView = sorting("Document Type", "Document No.", "Line No.");
                column(ItemNo; "No.") { }
                column(LineDescription; Description) { }
                column(LineDescription2; "Description 2") { }
                column(LineLocationCode; "Location Code") { }
                column(Quantity; Quantity) { }
                column(UnitOfMeasureCode; "Unit of Measure Code") { }
            }

            trigger OnAfterGetRecord()
            var
                Location: Record Location;
                ShippingAgent: Record "Shipping Agent";
                Salesperson: Record "Salesperson/Purchaser";
                PrimaryCode: Code[20];
                BackupCode: Code[20];
            begin
                WarehouseDisplayName := "Location Code";
                if Location.Get("Location Code") then begin
                    WarehouseDisplayName := Location.Code + ' ' + Location.Name;
                    if Location."Name 2" <> '' then
                        WarehouseDisplayName := WarehouseDisplayName + ' ' + Location."Name 2";
                end;

                Clear(ShippingAgentDescription);
                if ShippingAgent.Get("Shipping Agent Code") then
                    ShippingAgentDescription := ShippingAgent.Name;

                Clear(SalespersonName);
                if Salesperson.Get("Salesperson Code") then
                    SalespersonName := Salesperson.Name;

                PrimaryCode := FindISRCode(SalesHeader, false);
                Clear(InsideSalespersonName);
                if PrimaryCode <> '' then
                    if Salesperson.Get(PrimaryCode) then
                        InsideSalespersonName := Salesperson.Name;

                BackupCode := FindISRCode(SalesHeader, true);
                Clear(BackupInsideSalespersonName);
                if BackupCode <> '' then
                    if Salesperson.Get(BackupCode) then
                        BackupInsideSalespersonName := Salesperson.Name;

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
        layout(GPIPickTicket)
        {
            Type = RDLC;
            Caption = 'GPI Pick Ticket';
            Summary = 'Gamer-owned Warehouse Pick Instruction layout.';
            LayoutFile = 'src/reportlayout/GPIPickTicket.rdl';
        }
    }

    trigger OnPreReport()
    begin
        CompanyInfo.Get();
        CompanyInfo.CalcFields(Picture);
    end;

    local procedure FindISRCode(SalesHeader: Record "Sales Header"; FindBackup: Boolean): Code[20]
    var
        RecRef: RecordRef;
        Fld: FieldRef;
        i: Integer;
        FieldText: Text;
        IsISR: Boolean;
        IsBackup: Boolean;
    begin
        RecRef.GetTable(SalesHeader);
        for i := 1 to RecRef.FieldCount do begin
            Fld := RecRef.FieldIndex(i);
            FieldText := LowerCase(Fld.Name + ' ' + Fld.Caption);
            IsISR := (StrPos(FieldText, 'inside sales') > 0) or (StrPos(FieldText, 'isr') > 0);
            IsBackup := StrPos(FieldText, 'backup') > 0;
            if IsISR and (IsBackup = FindBackup) then
                exit(CopyStr(Format(Fld.Value), 1, 20));
        end;

        exit('');
    end;

    local procedure BuildContactLine()
    begin
        if (InsideSalespersonName <> '') and (BackupInsideSalespersonName <> '') then
            ContactLine := StrSubstNo('Please contact %1 or %2 at %3 with any questions.', InsideSalespersonName, BackupInsideSalespersonName, CompanyInfo."Phone No.")
        else
            if InsideSalespersonName <> '' then
                ContactLine := StrSubstNo('Please contact %1 at %2 with any questions.', InsideSalespersonName, CompanyInfo."Phone No.")
            else
                ContactLine := StrSubstNo('Please contact Gamer Packaging at %1 with any questions.', CompanyInfo."Phone No.");
    end;

    var
        CompanyInfo: Record "Company Information";
        WarehouseDisplayName: Text[150];
        ShippingAgentDescription: Text[100];
        SalespersonName: Text[100];
        InsideSalespersonName: Text[100];
        BackupInsideSalespersonName: Text[100];
        ContactLine: Text[250];
}
