codeunit 70520 "GPI Document Policy Mgt."
{
    procedure EnsureSalesSendAllowed(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type")
    begin
        case DeliveryDocumentType of
            DeliveryDocumentType::"Order Confirmation",
            DeliveryDocumentType::"Pick Ticket":
                if SalesHeader.Status <> SalesHeader.Status::Released then
                    Error(
                        '%1 %2 must be Released before it can be sent. Preview remains available while the document is %3.',
                        Format(DeliveryDocumentType),
                        SalesHeader."No.",
                        Format(SalesHeader.Status));
            DeliveryDocumentType::"Prepayment Notice":
                EnsurePendingPrepayment(SalesHeader);
        end;
    end;

    procedure EnsurePurchaseOrderReleased(PurchaseHeader: Record "Purchase Header"; DocumentDescription: Text)
    begin
        if PurchaseHeader.Status <> PurchaseHeader.Status::Released then
            Error(
                '%1 for Purchase Order %2 can be previewed while the order is %3, but it cannot be sent until the Purchase Order is Released.',
                DocumentDescription,
                PurchaseHeader."No.",
                Format(PurchaseHeader.Status));
    end;

    procedure ResolveSalesDocumentRecipients(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    begin
        ResolveSalesRecipients(
            SalesHeader,
            DeliveryDocumentType,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);
    end;

    procedure ResolveBlanketSalesOrderRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    begin
        ResolveSalesRecipients(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Blanket Sales Order",
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);
    end;

    procedure ResolvePostedInvoiceRecipients(SalesInvoiceHeader: Record "Sales Invoice Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        SpecificRuleApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyInvoiceRoutingRules(
            SalesInvoiceHeader,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);

        if ToRecipients.Count() = 0 then
            AddRecipientsFromText(ToRecipients, GetCustomerPrimaryContactEmail(SalesInvoiceHeader."Bill-to Customer No."));

        if not SpecificRuleApplied then
            ApplyInvoiceRoutingRules(
                SalesInvoiceHeader,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries);

        NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients);
    end;

    procedure ResolveWarehousePOSenderAccount(PurchaseHeader: Record "Purchase Header"; var TempEmailAccount: Record "Email Account" temporary): Text
    var
        EmailAccountMgt: Codeunit "Email Account";
        Salesperson: Record "Salesperson/Purchaser";
        InsideSalespersonCode: Code[20];
        SenderEmailAddress: Text;
    begin
        InsideSalespersonCode := GetInsideSalespersonCode(PurchaseHeader);
        if InsideSalespersonCode = '' then
            Error(
                'Purchase Order %1 does not have an identifiable ISR on the Purchase Header. Populate the ISR before sending the Warehouse Purchase Order.',
                PurchaseHeader."No.");

        if not Salesperson.Get(InsideSalespersonCode) then
            Error(
                'ISR %1 on Purchase Order %2 does not exist in Salespeople/Purchasers.',
                InsideSalespersonCode,
                PurchaseHeader."No.");

        SenderEmailAddress := DelChr(Salesperson."E-Mail", '<>', ' ');
        if SenderEmailAddress = '' then
            Error(
                'ISR %1 does not have an email address on the Salesperson/Purchaser Card.',
                InsideSalespersonCode);

        Clear(TempEmailAccount);
        EmailAccountMgt.GetAllAccounts(TempEmailAccount);
        if TempEmailAccount.FindSet() then
            repeat
                if LowerCase(DelChr(TempEmailAccount."Email Address", '<>', ' ')) = LowerCase(SenderEmailAddress) then
                    exit(SenderEmailAddress);
            until TempEmailAccount.Next() = 0;

        Error(
            'No Business Central Email Account is registered for ISR %1 (%2). Add that mailbox in Email Accounts before sending Warehouse Purchase Orders from the ISR.',
            InsideSalespersonCode,
            SenderEmailAddress);
    end;

    procedure GetSalesLineWarehouseDisplay(SalesLine: Record "Sales Line"; var DisplayQuantity: Decimal; var DisplayUnitOfMeasureCode: Code[10])
    begin
        DisplayQuantity := SalesLine.Quantity;
        DisplayUnitOfMeasureCode := SalesLine."Unit of Measure Code";

        if SalesLine.Type <> SalesLine.Type::Item then
            exit;

        ResolveWarehouseDisplay(
            SalesLine."No.",
            SalesLine."Quantity (Base)",
            DisplayQuantity,
            DisplayUnitOfMeasureCode);
    end;

    procedure GetPurchaseLineWarehouseDisplay(PurchaseLine: Record "Purchase Line"; var DisplayQuantity: Decimal; var DisplayUnitOfMeasureCode: Code[10])
    begin
        DisplayQuantity := PurchaseLine.Quantity;
        DisplayUnitOfMeasureCode := PurchaseLine."Unit of Measure Code";

        if PurchaseLine.Type <> PurchaseLine.Type::Item then
            exit;

        ResolveWarehouseDisplay(
            PurchaseLine."No.",
            PurchaseLine."Quantity (Base)",
            DisplayQuantity,
            DisplayUnitOfMeasureCode);
    end;

    local procedure EnsurePendingPrepayment(SalesHeader: Record "Sales Header")
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        CurrentStatus: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(FieldIdentity, 'prepayment') > 0) and
               (StrPos(FieldIdentity, 'status') > 0)
            then begin
                CurrentStatus := DelChr(Format(CandidateField.Value), '<>', ' ');
                if LowerCase(CurrentStatus) <> 'pending prepayment' then
                    Error(
                        'Prepayment Notice for Sales Order %1 can be previewed, but it cannot be sent until %2 is Pending Prepayment. Current value: %3.',
                        SalesHeader."No.",
                        CandidateField.Caption,
                        CurrentStatus);
                exit;
            end;
        end;

        Error(
            'The Prepayment Status field could not be identified on Sales Order %1. Confirm the installed field caption or ID before sending.',
            SalesHeader."No.");
    end;

    local procedure ResolveSalesRecipients(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        SpecificRuleApplied: Boolean;
    begin
        SpecificRuleApplied := ApplySalesRoutingRules(
            SalesHeader,
            DeliveryDocumentType,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);

        if ToRecipients.Count() = 0 then
            case DeliveryDocumentType of
                DeliveryDocumentType::"Order Confirmation",
                DeliveryDocumentType::"Prepayment Notice",
                DeliveryDocumentType::"Blanket Sales Order":
                    AddRecipientsFromText(ToRecipients, GetSalesOrderContactEmail(SalesHeader));
                DeliveryDocumentType::"Pick Ticket":
                    AddRecipientsFromText(ToRecipients, GetLocationEmail(SalesHeader."Location Code"));
            end;

        if not SpecificRuleApplied then begin
            AddSalesDefaultCcRecipients(SalesHeader, ToRecipients, CCRecipients);
            ApplySalesRoutingRules(
                SalesHeader,
                DeliveryDocumentType,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries);
        end;

        NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients);
    end;

    local procedure ApplySalesRoutingRules(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
        RuleApplied: Boolean;
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange("Delivery Document Type", DeliveryDocumentType);

        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if SalesRoutingRuleMatches(RoutingRule, SalesHeader, SpecificCustomerOnly) and
               RoutingRuleIsActive(RoutingRule, Today)
            then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRoutingRuleEntries, RoutingRule."Entry No.");
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure SalesRoutingRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; SalesHeader: Record "Sales Header"; SpecificCustomerOnly: Boolean): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);

        if SpecificCustomerOnly then begin
            if RoutingRule."Customer No." <> SalesHeader."Sell-to Customer No." then
                exit(false);
        end else
            if RoutingRule."Customer No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> SalesHeader."Location Code")
        then
            exit(false);

        exit(true);
    end;

    local procedure ApplyInvoiceRoutingRules(SalesInvoiceHeader: Record "Sales Invoice Header"; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
        RuleApplied: Boolean;
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::Invoice);

        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if InvoiceRoutingRuleMatches(RoutingRule, SalesInvoiceHeader, SpecificCustomerOnly) and
               RoutingRuleIsActive(RoutingRule, Today)
            then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRoutingRuleEntries, RoutingRule."Entry No.");
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure InvoiceRoutingRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; SalesInvoiceHeader: Record "Sales Invoice Header"; SpecificCustomerOnly: Boolean): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);

        if SpecificCustomerOnly then begin
            if RoutingRule."Customer No." <> SalesInvoiceHeader."Bill-to Customer No." then
                exit(false);
        end else
            if RoutingRule."Customer No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and
           (RoutingRule."Location Code" <> SalesInvoiceHeader."Location Code")
        then
            exit(false);

        exit(true);
    end;

    local procedure ApplyRoutingRule(RoutingRule: Record "GPI Document Routing Rule"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    begin
        if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then begin
            Clear(ToRecipients);
            Clear(CCRecipients);
            Clear(BCCRecipients);
        end;

        AddRecipientsFromText(ToRecipients, RoutingRule."To Addresses");
        AddRecipientsFromText(CCRecipients, RoutingRule."CC Addresses");
        AddRecipientsFromText(BCCRecipients, RoutingRule."BCC Addresses");
    end;

    local procedure RoutingRuleIsActive(RoutingRule: Record "GPI Document Routing Rule"; EvaluationDate: Date): Boolean
    begin
        if (RoutingRule."Effective Start Date" <> 0D) and
           (RoutingRule."Effective Start Date" > EvaluationDate)
        then
            exit(false);

        if (RoutingRule."Effective End Date" <> 0D) and
           (RoutingRule."Effective End Date" < EvaluationDate)
        then
            exit(false);

        exit(true);
    end;

    local procedure GetSalesOrderContactEmail(SalesHeader: Record "Sales Header"): Text
    var
        Contact: Record Contact;
    begin
        if SalesHeader."Sell-to Contact No." <> '' then
            if Contact.Get(SalesHeader."Sell-to Contact No.") then
                if Contact."E-Mail" <> '' then
                    exit(Contact."E-Mail");

        exit(SalesHeader."Sell-to E-Mail");
    end;

    local procedure GetCustomerPrimaryContactEmail(CustomerNo: Code[20]): Text
    var
        Customer: Record Customer;
        Contact: Record Contact;
    begin
        if not Customer.Get(CustomerNo) then
            exit('');

        if Customer."Primary Contact No." = '' then
            exit('');

        if Contact.Get(Customer."Primary Contact No.") then
            exit(Contact."E-Mail");

        exit('');
    end;

    local procedure GetLocationEmail(LocationCode: Code[10]): Text
    var
        Location: Record Location;
    begin
        if (LocationCode <> '') and Location.Get(LocationCode) then
            exit(Location."E-Mail");

        exit('');
    end;

    local procedure AddSalesDefaultCcRecipients(SalesHeader: Record "Sales Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text])
    begin
        AddCcRecipient(
            CCRecipients,
            GetSalespersonEmail(SalesHeader."Salesperson Code"),
            ToRecipients,
            UserId());
        AddCcRecipient(
            CCRecipients,
            GetSalespersonEmail(GetInsideSalespersonCode(SalesHeader)),
            ToRecipients,
            UserId());
    end;

    local procedure GetSalespersonEmail(SalespersonCode: Code[20]): Text
    var
        Salesperson: Record "Salesperson/Purchaser";
    begin
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            exit(Salesperson."E-Mail");

        exit('');
    end;

    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SourceRecordRef: RecordRef;
    begin
        SourceRecordRef.GetTable(SalesHeader);
        exit(FindInsideSalespersonCode(SourceRecordRef));
    end;

    local procedure GetInsideSalespersonCode(PurchaseHeader: Record "Purchase Header"): Code[20]
    var
        SourceRecordRef: RecordRef;
    begin
        SourceRecordRef.GetTable(PurchaseHeader);
        exit(FindInsideSalespersonCode(SourceRecordRef));
    end;

    local procedure FindInsideSalespersonCode(SourceRecordRef: RecordRef): Code[20]
    var
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
    begin
        for FieldIndex := 1 to SourceRecordRef.FieldCount do begin
            CandidateField := SourceRecordRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if IsInsideSalespersonField(CandidateIdentity) and
               (StrPos(CandidateIdentity, 'backup') = 0)
            then
                exit(CopyStr(Format(CandidateField.Value), 1, 20));
        end;

        exit('');
    end;

    local procedure IsInsideSalespersonField(FieldIdentity: Text): Boolean
    begin
        exit(
            (StrPos(FieldIdentity, 'inside salesperson') > 0) or
            (StrPos(FieldIdentity, 'inside sales') > 0) or
            (DelChr(FieldIdentity, '<>', ' ') = 'isr') or
            (StrPos(FieldIdentity, 'isr code') > 0));
    end;

    local procedure ResolveWarehouseDisplay(ItemNo: Code[20]; BaseQuantity: Decimal; var DisplayQuantity: Decimal; var DisplayUnitOfMeasureCode: Code[10])
    var
        Item: Record Item;
        ItemUnitOfMeasure: Record "Item Unit of Measure";
        WarehouseUnitOfMeasureCode: Code[10];
    begin
        if (ItemNo = '') or not Item.Get(ItemNo) then
            exit;

        WarehouseUnitOfMeasureCode := GetWarehouseUnitOfMeasureCode(Item);
        if WarehouseUnitOfMeasureCode = '' then
            exit;

        if not ItemUnitOfMeasure.Get(ItemNo, WarehouseUnitOfMeasureCode) then
            Error(
                'Item %1 uses warehouse unit of measure %2, but no Item Unit of Measure line exists for that code.',
                ItemNo,
                WarehouseUnitOfMeasureCode);

        if ItemUnitOfMeasure."Qty. per Unit of Measure" = 0 then
            Error(
                'Item %1 warehouse unit of measure %2 has a zero Qty. per Unit of Measure.',
                ItemNo,
                WarehouseUnitOfMeasureCode);

        DisplayQuantity := Round(
            BaseQuantity / ItemUnitOfMeasure."Qty. per Unit of Measure",
            0.00001);
        DisplayUnitOfMeasureCode := WarehouseUnitOfMeasureCode;
    end;

    local procedure GetWarehouseUnitOfMeasureCode(Item: Record Item): Code[10]
    var
        ItemRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
    begin
        ItemRef.GetTable(Item);
        for FieldIndex := 1 to ItemRef.FieldCount do begin
            CandidateField := ItemRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(CandidateIdentity, 'whse') > 0) and
               (StrPos(CandidateIdentity, 'unit of measure') > 0) and
               (StrPos(CandidateIdentity, 'code') > 0)
            then
                exit(CopyStr(DelChr(Format(CandidateField.Value), '<>', ' '), 1, 10));
        end;

        exit('');
    end;

    local procedure AppendRoutingRuleEntry(var AppliedRoutingRuleEntries: Text[250]; EntryNo: Integer)
    var
        EntryText: Text;
    begin
        EntryText := Format(EntryNo);
        if AppliedRoutingRuleEntries = '' then
            AppliedRoutingRuleEntries := CopyStr(EntryText, 1, MaxStrLen(AppliedRoutingRuleEntries))
        else
            AppliedRoutingRuleEntries := CopyStr(
                StrSubstNo('%1, %2', AppliedRoutingRuleEntries, EntryText),
                1,
                MaxStrLen(AppliedRoutingRuleEntries));
    end;

    local procedure AddRecipientsFromText(var Recipients: List of [Text]; RecipientText: Text)
    var
        RemainingText: Text;
        Recipient: Text;
        SeparatorPosition: Integer;
    begin
        RemainingText := ConvertStr(RecipientText, ',', ';');
        while RemainingText <> '' do begin
            SeparatorPosition := StrPos(RemainingText, ';');
            if SeparatorPosition = 0 then begin
                Recipient := RemainingText;
                RemainingText := '';
            end else begin
                Recipient := CopyStr(RemainingText, 1, SeparatorPosition - 1);
                RemainingText := CopyStr(RemainingText, SeparatorPosition + 1);
            end;

            Recipient := DelChr(Recipient, '<>', ' ');
            AddUniqueRecipient(Recipients, Recipient);
        end;
    end;

    local procedure AddUniqueRecipient(var Recipients: List of [Text]; EmailAddress: Text)
    var
        ExistingRecipient: Text;
        NormalizedEmail: Text;
    begin
        NormalizedEmail := LowerCase(DelChr(EmailAddress, '<>', ' '));
        if NormalizedEmail = '' then
            exit;

        foreach ExistingRecipient in Recipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit;

        Recipients.Add(DelChr(EmailAddress, '<>', ' '));
    end;

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; EmailAddress: Text; ToRecipients: List of [Text]; SenderAddress: Text)
    begin
        if EmailAddress = '' then
            exit;
        if IsRecipientInList(ToRecipients, LowerCase(EmailAddress)) then
            exit;
        if LowerCase(EmailAddress) = LowerCase(SenderAddress) then
            exit;

        AddUniqueRecipient(CCRecipients, EmailAddress);
    end;

    local procedure NormalizeRecipientLists(var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    var
        NewToRecipients: List of [Text];
        NewCCRecipients: List of [Text];
        NewBCCRecipients: List of [Text];
        Recipient: Text;
    begin
        foreach Recipient in ToRecipients do
            AddUniqueRecipient(NewToRecipients, Recipient);

        foreach Recipient in CCRecipients do
            if not IsRecipientInList(NewToRecipients, LowerCase(Recipient)) then
                AddUniqueRecipient(NewCCRecipients, Recipient);

        foreach Recipient in BCCRecipients do
            if not IsRecipientInList(NewToRecipients, LowerCase(Recipient)) and
               not IsRecipientInList(NewCCRecipients, LowerCase(Recipient))
            then
                AddUniqueRecipient(NewBCCRecipients, Recipient);

        ReplaceRecipientList(ToRecipients, NewToRecipients);
        ReplaceRecipientList(CCRecipients, NewCCRecipients);
        ReplaceRecipientList(BCCRecipients, NewBCCRecipients);
    end;

    local procedure ReplaceRecipientList(var TargetRecipients: List of [Text]; SourceRecipients: List of [Text])
    var
        Recipient: Text;
    begin
        Clear(TargetRecipients);
        foreach Recipient in SourceRecipients do
            TargetRecipients.Add(Recipient);
    end;

    local procedure IsRecipientInList(Recipients: List of [Text]; NormalizedEmail: Text): Boolean
    var
        ExistingRecipient: Text;
    begin
        foreach ExistingRecipient in Recipients do
            if NormalizedEmail = LowerCase(ExistingRecipient) then
                exit(true);

        exit(false);
    end;
}