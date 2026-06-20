codeunit 70711 "GPI Workflow Test Helper"
{
    procedure ConfigureMock(var Mock: Codeunit "GPI Transport Mock"; Action: Enum "Email Action")
    begin
        Mock.ConfigureSenderAccount('workflow.sender@example.com', 'Workflow Test Sender');
        Mock.ConfigureCommitSuppression();
        Mock.ConfigureEmailEditor(true, Action, '');
    end;

    procedure CreateSalesReturn(var Header: Record "Sales Header"; var RuleEntryNo: Integer)
    var
        Customer: Record Customer;
        Line: Record "Sales Line";
        CustomerNo: Code[20];
    begin
        CustomerNo := NewCode('C');
        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'Workflow Sales Return';
        Customer.Insert(false);

        Header.Init();
        Header."Document Type" := Header."Document Type"::"Return Order";
        Header."No." := NewCode('SR');
        Header."Sell-to Customer No." := CustomerNo;
        Header."Bill-to Customer No." := CustomerNo;
        Header."Sell-to Customer Name" := Customer.Name;
        Header."Order Date" := WorkDate();
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::"Return Order";
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line.Type := Line.Type::Item;
        Line."No." := NewCode('I');
        Line.Description := 'Workflow Item';
        Line.Quantity := 1;
        Line."Unit of Measure Code" := 'EA';
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);

        RuleEntryNo := CreateRule(Enum::"GPI Delivery Document Type"::"Sales Return Authorization", CustomerNo, '', '', 'salesreturn@example.com');
    end;

    procedure CreatePurchaseReturn(var Header: Record "Purchase Header"; var RuleEntryNo: Integer)
    var
        Vendor: Record Vendor;
        Line: Record "Purchase Line";
        VendorNo: Code[20];
    begin
        VendorNo := NewCode('V');
        Vendor.Init();
        Vendor."No." := VendorNo;
        Vendor.Name := 'Workflow Purchase Return';
        Vendor.Insert(false);

        Header.Init();
        Header."Document Type" := Header."Document Type"::"Return Order";
        Header."No." := NewCode('PR');
        Header."Buy-from Vendor No." := VendorNo;
        Header."Pay-to Vendor No." := VendorNo;
        Header."Buy-from Vendor Name" := Vendor.Name;
        Header."Order Date" := WorkDate();
        Header."Posting Date" := WorkDate();
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::"Return Order";
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line.Type := Line.Type::Item;
        Line."No." := NewCode('I');
        Line.Description := 'Workflow Item';
        Line.Quantity := 1;
        Line."Unit of Measure Code" := 'EA';
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);

        RuleEntryNo := CreateRule(Enum::"GPI Delivery Document Type"::"Purchase Return Order", '', VendorNo, '', 'purchasereturn@example.com');
    end;

    procedure CreateTransfer(var Header: Record "Transfer Header"; var RuleEntryNo: Integer)
    var
        FromLocation: Record Location;
        ToLocation: Record Location;
        Line: Record "Transfer Line";
    begin
        FromLocation.Init();
        FromLocation.Code := NewLocationCode('F');
        FromLocation.Name := 'Workflow From';
        FromLocation.Insert(false);

        ToLocation.Init();
        ToLocation.Code := NewLocationCode('T');
        ToLocation.Name := 'Workflow To';
        ToLocation.Insert(false);

        Header.Init();
        Header."No." := NewCode('TR');
        Header."Transfer-from Code" := FromLocation.Code;
        Header."Transfer-to Code" := ToLocation.Code;
        Header."Shipment Date" := WorkDate();
        Header."Receipt Date" := WorkDate();
        Header.Status := Header.Status::Released;
        Header.Insert(false);

        Line.Init();
        Line."Document No." := Header."No.";
        Line."Line No." := 10000;
        Line."Item No." := NewCode('I');
        Line.Description := 'Workflow Item';
        Line.Quantity := 1;
        Line."Unit of Measure Code" := 'EA';
        Line."GPI Transfer Visibility" := Enum::"GPI Transfer Visibility"::"Both Transfer Documents";
        Line.Insert(false);

        RuleEntryNo := CreateRule(Enum::"GPI Delivery Document Type"::"Transfer Pick List", '', '', FromLocation.Code, 'transferpick@example.com');
    end;

    procedure CreateOpenOrder(var Customer: Record Customer; var SalesOrderNo: Code[20]; var RuleEntryNo: Integer)
    var
        Header: Record "Sales Header";
        Line: Record "Sales Line";
    begin
        Customer.Init();
        Customer."No." := NewCode('C');
        Customer.Name := 'Workflow Open Order';
        Customer.Insert(false);

        SalesOrderNo := NewCode('SO');
        Header.Init();
        Header."Document Type" := Header."Document Type"::Order;
        Header."No." := SalesOrderNo;
        Header."Sell-to Customer No." := Customer."No.";
        Header."Bill-to Customer No." := Customer."No.";
        Header."Sell-to Customer Name" := Customer.Name;
        Header."Order Date" := WorkDate();
        Header.Insert(false);

        Line.Init();
        Line."Document Type" := Line."Document Type"::Order;
        Line."Document No." := SalesOrderNo;
        Line."Line No." := 10000;
        Line."Sell-to Customer No." := Customer."No.";
        Line.Type := Line.Type::Item;
        Line."No." := NewCode('I');
        Line.Description := 'Workflow Item';
        Line.Quantity := 1;
        Line."Outstanding Quantity" := 1;
        Line."Unit of Measure Code" := 'EA';
        Line."GPI Document Visibility" := Enum::"GPI Document Visibility"::"All Documents";
        Line.Insert(false);

        RuleEntryNo := CreateRule(Enum::"GPI Delivery Document Type"::"Customer Open Order Status", Customer."No.", '', '', 'openorders@example.com');
    end;

    procedure FindLog(SourceTableId: Integer; SourceNo: Code[20]; DocumentType: Enum "GPI Delivery Document Type"; var Log: Record "GPI Document Delivery Log")
    begin
        Log.SetRange("Source Table ID", SourceTableId);
        Log.SetRange("Source Document No.", SourceNo);
        Log.SetRange("Delivery Document Type", DocumentType);
        if not Log.FindLast() then
            Error('No Delivery Log was created for %1.', SourceNo);
    end;

    procedure AssertLog(Log: Record "GPI Document Delivery Log"; ExpectedStatus: Enum "GPI Delivery Status"; ExpectedRecipient: Text; RuleEntryNo: Integer)
    var
        EmptyId: Guid;
    begin
        if Log.Status <> ExpectedStatus then
            Error('Expected status %1 but received %2.', ExpectedStatus, Log.Status);
        if Log."To Recipients" <> ExpectedRecipient then
            Error('Expected recipient %1 but received %2.', ExpectedRecipient, Log."To Recipients");
        if Log."Sender Email Address" <> 'workflow.sender@example.com' then
            Error('The mocked sender was not logged.');
        if Log."Routing Rule Entry Nos." <> Format(RuleEntryNo) then
            Error('The routing rule was not logged.');
        if Log."Completed Date/Time" = 0DT then
            Error('The Delivery Log was not completed.');
        if Log."Email Message ID" = EmptyId then
            Error('The email message ID was not logged.');
    end;

    local procedure CreateRule(DocumentType: Enum "GPI Delivery Document Type"; CustomerNo: Code[20]; VendorNo: Code[20]; LocationCode: Code[10]; Recipient: Text): Integer
    var
        Rule: Record "GPI Document Routing Rule";
    begin
        Rule.Init();
        Rule.Enabled := true;
        Rule.Priority := 10;
        Rule."Rule Name" := CopyStr('Workflow ' + Format(CreateGuid()), 1, MaxStrLen(Rule."Rule Name"));
        Rule."Delivery Document Type" := DocumentType;
        Rule."Customer No." := CustomerNo;
        Rule."Vendor No." := VendorNo;
        Rule."Location Code" := LocationCode;
        Rule."Recipient Action" := Rule."Recipient Action"::Add;
        Rule."To Addresses" := Recipient;
        Rule.Insert(false);
        exit(Rule."Entry No.");
    end;

    local procedure NewCode(Prefix: Text): Code[20]
    begin
        exit(CopyStr(Prefix + DelChr(Format(CreateGuid()), '=', '{}-'), 1, 20));
    end;

    local procedure NewLocationCode(Prefix: Text): Code[10]
    begin
        exit(CopyStr(Prefix + DelChr(Format(CreateGuid()), '=', '{}-'), 1, 10));
    end;
}
