codeunit 70716 "GPI UAT Sample Pack"
{
    Permissions =
        tabledata Customer = rimd,
        tabledata Vendor = rimd,
        tabledata Item = rimd,
        tabledata Location = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd,
        tabledata "Purchase Header" = rimd,
        tabledata "Purchase Line" = rimd,
        tabledata "Transfer Header" = rimd,
        tabledata "Transfer Line" = rimd,
        tabledata "GPI Document Delivery Log" = rimd;

    procedure GenerateSamplePack(PersistChanges: Boolean): Text[50]
    var
        Customer: Record Customer;
        Vendor: Record Vendor;
        Item: Record Item;
        FromLocation: Record Location;
        ToLocation: Record Location;
        SalesReturnHeader: Record "Sales Header";
        PurchaseReturnHeader: Record "Purchase Header";
        TransferHeader: Record "Transfer Header";
        SalesOrderHeader: Record "Sales Header";
        SourceRef: RecordRef;
        DeliveryLog: Record "GPI Document Delivery Log";
        PackCode: Code[8];
        PackId: Text[50];
        EntryNo: Integer;
    begin
        PackCode := NewPackCode();
        PackId := CopyStr('UATPACK-' + PackCode, 1, MaxStrLen(PackId));

        CreateMasterData(PackCode, Customer, Vendor, Item, FromLocation, ToLocation);
        CreateSalesReturn(PackCode, Customer, Item, FromLocation, SalesReturnHeader);
        CreatePurchaseReturn(PackCode, Vendor, Item, FromLocation, PurchaseReturnHeader);
        CreateTransfer(PackCode, Item, FromLocation, ToLocation, TransferHeader);
        CreateOpenSalesOrder(PackCode, Customer, Item, SalesOrderHeader);

        SalesReturnHeader.SetRecFilter();
        SourceRef.GetTable(SalesReturnHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Sales Return Auth.",
            Enum::"GPI Delivery Document Type"::"Sales Return Authorization",
            Database::"Sales Header",
            SalesReturnHeader.SystemId,
            'Sales Return Order',
            SalesReturnHeader."No.",
            'Customer',
            Customer."No.",
            Customer."No.",
            SalesReturnHeader."Location Code",
            StrSubstNo('Sales-Return-Authorization %1.pdf', SalesReturnHeader."No."),
            StrSubstNo('Sales Return Authorization %1', SalesReturnHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        SalesReturnHeader.SetRecFilter();
        SourceRef.GetTable(SalesReturnHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Sales Return WH Notice",
            Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
            Database::"Sales Header",
            SalesReturnHeader.SystemId,
            'Sales Return Order',
            SalesReturnHeader."No.",
            'Location',
            FromLocation.Code,
            Customer."No.",
            FromLocation.Code,
            StrSubstNo('Sales-Return-Warehouse-Notification %1.pdf', SalesReturnHeader."No."),
            StrSubstNo('Sales Return Warehouse Notification %1', SalesReturnHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        PurchaseReturnHeader.SetRecFilter();
        SourceRef.GetTable(PurchaseReturnHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Purchase Return Order",
            Enum::"GPI Delivery Document Type"::"Purchase Return Order",
            Database::"Purchase Header",
            PurchaseReturnHeader.SystemId,
            'Purchase Return Order',
            PurchaseReturnHeader."No.",
            'Vendor',
            Vendor."No.",
            '',
            PurchaseReturnHeader."Location Code",
            StrSubstNo('Purchase-Return-Order %1.pdf', PurchaseReturnHeader."No."),
            StrSubstNo('Purchase Return Order %1', PurchaseReturnHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        PurchaseReturnHeader.SetRecFilter();
        SourceRef.GetTable(PurchaseReturnHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Purchase Return Pick",
            Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
            Database::"Purchase Header",
            PurchaseReturnHeader.SystemId,
            'Purchase Return Order',
            PurchaseReturnHeader."No.",
            'Location',
            FromLocation.Code,
            '',
            FromLocation.Code,
            StrSubstNo('Purchase-Return-Pick-Ticket %1.pdf', PurchaseReturnHeader."No."),
            StrSubstNo('Purchase Return Pick Ticket %1', PurchaseReturnHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        TransferHeader.SetRecFilter();
        SourceRef.GetTable(TransferHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Transfer Pick List",
            Enum::"GPI Delivery Document Type"::"Transfer Pick List",
            Database::"Transfer Header",
            TransferHeader.SystemId,
            'Transfer Order',
            TransferHeader."No.",
            'Location',
            FromLocation.Code,
            '',
            FromLocation.Code,
            StrSubstNo('Transfer-Pick-List %1.pdf', TransferHeader."No."),
            StrSubstNo('Transfer Pick List %1', TransferHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        TransferHeader.SetRecFilter();
        SourceRef.GetTable(TransferHeader);
        CreateSampleLog(
            DeliveryLog,
            Report::"GPI Transfer Receipt Notice",
            Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice",
            Database::"Transfer Header",
            TransferHeader.SystemId,
            'Transfer Order',
            TransferHeader."No.",
            'Location',
            ToLocation.Code,
            '',
            ToLocation.Code,
            StrSubstNo('Transfer-Receipt-Notification %1.pdf', TransferHeader."No."),
            StrSubstNo('Transfer Receipt Notification %1', TransferHeader."No."),
            PackId,
            SourceRef);
        Clear(SourceRef);

        Customer.SetRecFilter();
        SourceRef.GetTable(Customer);
        EntryNo := CreateSampleLog(
            DeliveryLog,
            Report::"GPI Customer Open Orders",
            Enum::"GPI Delivery Document Type"::"Customer Open Order Status",
            Database::Customer,
            Customer.SystemId,
            'Open Order Status',
            Customer."No.",
            'Customer',
            Customer."No.",
            Customer."No.",
            '',
            StrSubstNo(
                'Open-Order-Status %1 %2.pdf',
                Customer."No.",
                Format(WorkDate(), 0, '<Year4>-<Month,2>-<Day,2>')),
            StrSubstNo(
                'Open Order Status as of %1',
                Format(WorkDate(), 0, '<Month,2>/<Day,2>/<Year4>')),
            PackId,
            SourceRef);
        Clear(SourceRef);

        DeliveryLog.Get(EntryNo);
        DeliveryLog."Open Order As Of Date" := WorkDate();
        DeliveryLog."Open Order Count" := 1;
        DeliveryLog."Open Order Line Count" := 1;
        DeliveryLog."Included Order Nos." := SalesOrderHeader."No.";
        DeliveryLog.Modify(true);

        if PersistChanges then
            Commit();

        exit(PackId);
    end;

    local procedure CreateMasterData(PackCode: Code[8]; var Customer: Record Customer; var Vendor: Record Vendor; var Item: Record Item; var FromLocation: Record Location; var ToLocation: Record Location)
    begin
        Customer.Init();
        Customer."No." := BuildNo('UAT-C-', PackCode);
        Customer.Name := CopyStr('UAT Sample Customer ' + PackCode, 1, MaxStrLen(Customer.Name));
        Customer.Address := '100 UAT Sample Street';
        Customer.City := 'Minneapolis';
        Customer.County := 'MN';
        Customer."Post Code" := '55402';
        Customer.Insert(false);

        Vendor.Init();
        Vendor."No." := BuildNo('UAT-V-', PackCode);
        Vendor.Name := CopyStr('UAT Sample Vendor ' + PackCode, 1, MaxStrLen(Vendor.Name));
        Vendor.Address := '200 UAT Vendor Avenue';
        Vendor.City := 'Minneapolis';
        Vendor.County := 'MN';
        Vendor."Post Code" := '55402';
        Vendor.Insert(false);

        Item.Init();
        Item."No." := BuildNo('UAT-I-', PackCode);
        Item.Description := CopyStr('UAT Sample Packaging Item ' + PackCode, 1, MaxStrLen(Item.Description));
        Item.Insert(false);

        FromLocation.Init();
        FromLocation.Code := BuildLocationCode('UF', PackCode);
        FromLocation.Name := CopyStr('UAT Sample Shipping Location', 1, MaxStrLen(FromLocation.Name));
        FromLocation.Address := '300 UAT Warehouse Road';
        FromLocation.City := 'Minneapolis';
        FromLocation.County := 'MN';
        FromLocation."Post Code" := '55402';
        FromLocation.Insert(false);

        ToLocation.Init();
        ToLocation.Code := BuildLocationCode('UT', PackCode);
        ToLocation.Name := CopyStr('UAT Sample Receiving Location', 1, MaxStrLen(ToLocation.Name));
        ToLocation.Address := '400 UAT Receiving Road';
        ToLocation.City := 'Minneapolis';
        ToLocation.County := 'MN';
        ToLocation."Post Code" := '55402';
        ToLocation.Insert(false);
    end;

    local procedure CreateSalesReturn(PackCode: Code[8]; Customer: Record Customer; Item: Record Item; Location: Record Location; var Header: Record "Sales Header")
    var
        Line: Record "Sales Line";
    begin
        Header.Init();
        Header."Document Type" := Header."Document Type"::"Return Order";
        Header."No." := BuildNo('UAT-SR-', PackCode);
        Header."Sell-to Customer No." := Customer."No.";
        Header."Bill-to Customer No." := Customer."No.";
        Header."Sell-to Customer Name" := Customer.Name;
        Header."Sell-to Address" := Customer.Address;
        Header."Sell-to City" := Customer.City;
        Header."Sell-to County" := Customer.County;
        Header."Sell-to Post Code" := Customer."Post Code";
        Header."Location Code" := Location.Code;
        Header."Order Date" := WorkDate();
        Header."Document Date" := WorkDate();
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::"Return Order";
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line.Type := Line.Type::Item;
        Line."No." := Item."No.";
        Line.Description := Item.Description;
        Line.Quantity := 5;
        Line."Unit of Measure Code" := 'EA';
        Line."Unit Price" := 25;
        Line."Line Amount" := 125;
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);
    end;

    local procedure CreatePurchaseReturn(PackCode: Code[8]; Vendor: Record Vendor; Item: Record Item; Location: Record Location; var Header: Record "Purchase Header")
    var
        Line: Record "Purchase Line";
    begin
        Header.Init();
        Header."Document Type" := Header."Document Type"::"Return Order";
        Header."No." := BuildNo('UAT-PR-', PackCode);
        Header."Buy-from Vendor No." := Vendor."No.";
        Header."Pay-to Vendor No." := Vendor."No.";
        Header."Buy-from Vendor Name" := Vendor.Name;
        Header."Buy-from Address" := Vendor.Address;
        Header."Buy-from City" := Vendor.City;
        Header."Buy-from County" := Vendor.County;
        Header."Buy-from Post Code" := Vendor."Post Code";
        Header."Location Code" := Location.Code;
        Header."Order Date" := WorkDate();
        Header."Posting Date" := WorkDate();
        Header."Document Date" := WorkDate();
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::"Return Order";
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line.Type := Line.Type::Item;
        Line."No." := Item."No.";
        Line.Description := Item.Description;
        Line.Quantity := 4;
        Line."Unit of Measure Code" := 'EA';
        Line."Direct Unit Cost" := 18.50;
        Line."Line Amount" := 74;
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);
    end;

    local procedure CreateTransfer(PackCode: Code[8]; Item: Record Item; FromLocation: Record Location; ToLocation: Record Location; var Header: Record "Transfer Header")
    var
        Line: Record "Transfer Line";
    begin
        Header.Init();
        Header."No." := BuildNo('UAT-TR-', PackCode);
        Header."Transfer-from Code" := FromLocation.Code;
        Header."Transfer-to Code" := ToLocation.Code;
        Header."Shipment Date" := WorkDate();
        Header."Receipt Date" := WorkDate() + 2;
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line."Item No." := Item."No.";
        Line.Description := Item.Description;
        Line.Quantity := 12;
        Line."Unit of Measure Code" := 'EA';
        Line."GPI Transfer Visibility" := Enum::"GPI Transfer Visibility"::"Both Transfer Documents";
        Line.Insert(false);
    end;

    local procedure CreateOpenSalesOrder(PackCode: Code[8]; Customer: Record Customer; Item: Record Item; var Header: Record "Sales Header")
    var
        Line: Record "Sales Line";
    begin
        Header.Init();
        Header."Document Type" := Header."Document Type"::Order;
        Header."No." := BuildNo('UAT-SO-', PackCode);
        Header."Sell-to Customer No." := Customer."No.";
        Header."Bill-to Customer No." := Customer."No.";
        Header."Sell-to Customer Name" := Customer.Name;
        Header."Sell-to Address" := Customer.Address;
        Header."Sell-to City" := Customer.City;
        Header."Sell-to County" := Customer.County;
        Header."Sell-to Post Code" := Customer."Post Code";
        Header."Order Date" := WorkDate();
        Header."Document Date" := WorkDate();
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::Order;
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line."Sell-to Customer No." := Customer."No.";
        Line.Type := Line.Type::Item;
        Line."No." := Item."No.";
        Line.Description := Item.Description;
        Line.Quantity := 20;
        Line."Quantity Shipped" := 5;
        Line."Outstanding Quantity" := 15;
        Line."Unit of Measure Code" := 'EA';
        Line."Unit Price" := 8;
        Line."Line Amount" := 160;
        Line."Planned Delivery Date" := WorkDate() + 7;
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);
    end;

    local procedure CreateSampleLog(var DeliveryLog: Record "GPI Document Delivery Log"; ReportId: Integer; DocumentType: Enum "GPI Delivery Document Type"; SourceTableId: Integer; SourceSystemId: Guid; SourceDocumentType: Text[50]; SourceDocumentNo: Code[20]; SourcePartyType: Text[20]; SourcePartyNo: Code[20]; CustomerNo: Code[20]; LocationCode: Code[10]; AttachmentName: Text[250]; SubjectText: Text[2048]; PackId: Text[50]; SourceRef: RecordRef): Integer
    var
        TempBlob: Codeunit "Temp Blob";
        PdfOutStream: OutStream;
        PdfInStream: InStream;
        LogOutStream: OutStream;
    begin
        TempBlob.CreateOutStream(PdfOutStream);
        Report.SaveAs(ReportId, '', ReportFormat::Pdf, PdfOutStream, SourceRef);
        if not TempBlob.HasValue() then
            Error('The UAT sample report %1 did not generate a PDF.', ReportId);

        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DocumentType;
        DeliveryLog.Status := DeliveryLog.Status::Ready;
        DeliveryLog."Customer No." := CustomerNo;
        DeliveryLog."Location Code" := LocationCode;
        DeliveryLog."Report ID" := ReportId;
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog.Subject := SubjectText;
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."Source Table ID" := SourceTableId;
        DeliveryLog."Source SystemId" := SourceSystemId;
        DeliveryLog."Source Document Type" := SourceDocumentType;
        DeliveryLog."Source Document No." := SourceDocumentNo;
        DeliveryLog."Source Party Type" := SourcePartyType;
        DeliveryLog."Source Party No." := SourcePartyNo;
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Policy" := 'UAT Sample Pack';
        DeliveryLog."External Delivery ID" := PackId;
        DeliveryLog.Insert(true);

        TempBlob.CreateInStream(PdfInStream);
        DeliveryLog."Document Content".CreateOutStream(LogOutStream);
        CopyStream(LogOutStream, PdfInStream);
        DeliveryLog.Modify(true);
        exit(DeliveryLog."Entry No.");
    end;

    local procedure NewPackCode(): Code[8]
    begin
        exit(CopyStr(DelChr(Format(CreateGuid()), '=', '{}-'), 1, 8));
    end;

    local procedure BuildNo(Prefix: Text; PackCode: Code[8]): Code[20]
    begin
        exit(CopyStr(Prefix + PackCode, 1, 20));
    end;

    local procedure BuildLocationCode(Prefix: Text; PackCode: Code[8]): Code[10]
    begin
        exit(CopyStr(Prefix + PackCode, 1, 10));
    end;
}
