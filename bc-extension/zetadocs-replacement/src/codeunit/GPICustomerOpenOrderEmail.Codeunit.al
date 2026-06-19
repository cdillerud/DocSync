codeunit 70580 "GPI Customer Open Order Email"
{
    Permissions =
        tabledata Customer = r,
        tabledata Contact = r,
        tabledata "Sales Header" = r,
        tabledata "Sales Line" = r,
        tabledata "Salesperson/Purchaser" = r,
        tabledata "GPI Document Delivery Log" = rimd,
        tabledata "GPI Document Routing Rule" = r;

    procedure PreviewOpenOrderStatus(Customer: Record Customer)
    var
        TempBlob: Codeunit "Temp Blob";
        FileName: Text;
    begin
        ValidateCustomer(Customer);
        GenerateOpenOrderPdf(Customer, TempBlob);
        FileName := BuildAttachmentName(Customer."No.");

        if not File.ViewFromStream(TempBlob.CreateInStream(), FileName, true) then
            File.DownloadFromStream(
                TempBlob.CreateInStream(),
                'Download Open Order Status',
                '',
                'PDF files (*.pdf)|*.pdf',
                FileName);
    end;

    procedure OpenOpenOrderDraft(var Customer: Record Customer)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SenderEmailAccount: Record "Email Account" temporary;
        DeliveryLog: Record "GPI Document Delivery Log";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AttachmentInStream: InStream;
        AttachmentName: Text[250];
        Subject: Text;
        Body: Text;
        AppliedRuleEntries: Text[250];
        SenderEmailAddress: Text;
        EmailAction: Enum "Email Action";
        ErrorText: Text;
        OrderCount: Integer;
        LineCount: Integer;
        IncludedOrderNos: Text[2048];
    begin
        ValidateCustomer(Customer);
        SenderEmailAddress := Phase2EmailMgt.ResolveCurrentUserAccount(SenderEmailAccount);
        ResolveRecipients(
            Customer,
            SenderEmailAddress,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        if ToRecipients.Count() = 0 then
            Error(
                'No Open Order Status recipient was found for customer %1. Add a customer-specific routing rule, a primary-contact email, or an email to the Customer Card.',
                Customer."No.");

        GenerateOpenOrderPdf(Customer, TempBlob);
        CollectOpenOrderSummary(Customer."No.", OrderCount, LineCount, IncludedOrderNos);
        AttachmentName := CopyStr(BuildAttachmentName(Customer."No."), 1, MaxStrLen(AttachmentName));
        Subject := BuildSubject();
        Body := BuildBody(Customer);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::Customer,
            Customer.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            Customer,
            DeliveryLog.Status::Created,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            SenderEmailAccount,
            EmailMessage.GetId(),
            TempBlob,
            OrderCount,
            LineCount,
            IncludedOrderNos,
            '',
            false);
        Commit();

        if not TryOpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            Error('%1', ErrorText);
        end;

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    procedure SendOpenOrderBatch(var FilteredCustomers: Record Customer)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SenderEmailAccount: Record "Email Account" temporary;
        Customer: Record Customer;
        CustomerNos: List of [Code[20]];
        CustomerNo: Code[20];
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRuleEntries: Text[250];
        SenderEmailAddress: Text;
        ReadyCount: Integer;
        SentCount: Integer;
        FailedCount: Integer;
        MissingRecipientCount: Integer;
        NoOpenOrdersCount: Integer;
    begin
        SenderEmailAddress := Phase2EmailMgt.ResolveCurrentUserAccount(SenderEmailAccount);
        CollectCustomerNumbers(FilteredCustomers, CustomerNos);

        if CustomerNos.Count() = 0 then
            Error('No customers are included in the current selection or filter.');

        foreach CustomerNo in CustomerNos do
            if Customer.Get(CustomerNo) then
                if not HasOpenOrderData(CustomerNo) then
                    NoOpenOrdersCount += 1
                else begin
                    Clear(ToRecipients);
                    Clear(CCRecipients);
                    Clear(BCCRecipients);
                    Clear(AppliedRuleEntries);
                    ResolveRecipients(
                        Customer,
                        SenderEmailAddress,
                        ToRecipients,
                        CCRecipients,
                        BCCRecipients,
                        AppliedRuleEntries);
                    if ToRecipients.Count() = 0 then
                        MissingRecipientCount += 1
                    else
                        ReadyCount += 1;
                end;

        if ReadyCount = 0 then begin
            Message(
                'No Customer Open Order Status reports are ready to send. Missing recipient: %1. No outstanding item lines: %2.',
                MissingRecipientCount,
                NoOpenOrdersCount);
            exit;
        end;

        if not Confirm(
            'Send the filtered or selected Customer Open Order Status reports now?\Ready to send: %1\Missing recipient: %2\No outstanding item lines: %3\Repeat sends are allowed and will create new Delivery Log entries.',
            false,
            ReadyCount,
            MissingRecipientCount,
            NoOpenOrdersCount)
        then
            exit;

        foreach CustomerNo in CustomerNos do
            if Customer.Get(CustomerNo) and HasOpenOrderData(CustomerNo) then begin
                Clear(ToRecipients);
                Clear(CCRecipients);
                Clear(BCCRecipients);
                Clear(AppliedRuleEntries);
                ResolveRecipients(
                    Customer,
                    SenderEmailAddress,
                    ToRecipients,
                    CCRecipients,
                    BCCRecipients,
                    AppliedRuleEntries);
                if ToRecipients.Count() > 0 then
                    if SendOneOpenOrderStatus(Customer, SenderEmailAccount, SenderEmailAddress) then
                        SentCount += 1
                    else
                        FailedCount += 1;
            end;

        Message(
            'Customer Open Order Status batch complete. Sent: %1. Failed: %2. Missing recipient: %3. No outstanding item lines: %4.',
            SentCount,
            FailedCount,
            MissingRecipientCount,
            NoOpenOrdersCount);
    end;

    local procedure SendOneOpenOrderStatus(var Customer: Record Customer; SenderEmailAccount: Record "Email Account" temporary; SenderEmailAddress: Text): Boolean
    var
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        DeliveryLog: Record "GPI Document Delivery Log";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AttachmentInStream: InStream;
        AttachmentName: Text[250];
        Subject: Text;
        Body: Text;
        AppliedRuleEntries: Text[250];
        ErrorText: Text;
        SentSuccessfully: Boolean;
        OrderCount: Integer;
        LineCount: Integer;
        IncludedOrderNos: Text[2048];
    begin
        ResolveRecipients(
            Customer,
            SenderEmailAddress,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);
        if ToRecipients.Count() = 0 then
            exit(false);

        AttachmentName := CopyStr(BuildAttachmentName(Customer."No."), 1, MaxStrLen(AttachmentName));
        Subject := BuildSubject();
        Body := BuildBody(Customer);
        CollectOpenOrderSummary(Customer."No.", OrderCount, LineCount, IncludedOrderNos);

        ClearLastError();
        if not TryGenerateOpenOrderPdf(Customer, TempBlob) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := StrSubstNo('The Open Order Status report for customer %1 could not be rendered as a PDF.', Customer."No.");

            CreateDeliveryLog(
                DeliveryLog,
                Customer,
                DeliveryLog.Status::Failed,
                AttachmentName,
                Subject,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRuleEntries,
                SenderEmailAccount,
                EmptyGuid(),
                TempBlob,
                OrderCount,
                LineCount,
                IncludedOrderNos,
                ErrorText,
                true);
            Commit();
            exit(false);
        end;

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::Customer,
            Customer.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            Customer,
            DeliveryLog.Status::Created,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            SenderEmailAccount,
            EmailMessage.GetId(),
            TempBlob,
            OrderCount,
            LineCount,
            IncludedOrderNos,
            '',
            false);
        Commit();

        ClearLastError();
        if not TrySendOpenOrderEmail(EmailMessage, SenderEmailAccount, SentSuccessfully) then begin
            ErrorText := GetLastErrorText();
            if ErrorText = '' then
                ErrorText := 'Business Central returned an error while sending the Customer Open Order Status email.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;

        if not SentSuccessfully then begin
            ErrorText := 'Business Central did not confirm that the Customer Open Order Status email was sent.';
            UpdateDeliveryLogFailed(DeliveryLog, ErrorText);
            Commit();
            exit(false);
        end;

        UpdateDeliveryLogSent(DeliveryLog, EmailMessage);
        Commit();
        exit(true);
    end;

    local procedure ValidateCustomer(Customer: Record Customer)
    begin
        Customer.TestField("No.");
        if not HasOpenOrderData(Customer."No.") then
            Error('Customer %1 has no open Sales Order item lines with an outstanding quantity.', Customer."No.");
    end;

    local procedure GenerateOpenOrderPdf(Customer: Record Customer; var TempBlob: Codeunit "Temp Blob")
    begin
        if not TryGenerateOpenOrderPdf(Customer, TempBlob) then
            Error('%1', GetLastErrorText());
    end;

    [TryFunction]
    local procedure TryGenerateOpenOrderPdf(Customer: Record Customer; var TempBlob: Codeunit "Temp Blob")
    var
        CustomerCopy: Record Customer;
        CustomerRef: RecordRef;
        AttachmentOutStream: OutStream;
    begin
        CustomerCopy.SetRange("No.", Customer."No.");
        CustomerRef.GetTable(CustomerCopy);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(
            Report::"GPI Customer Open Orders",
            '',
            ReportFormat::Pdf,
            AttachmentOutStream,
            CustomerRef);

        if not TempBlob.HasValue() then
            Error('No PDF was generated for Customer Open Order Status %1.', Customer."No.");
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage, SenderEmailAccount);
    end;

    [TryFunction]
    local procedure TrySendOpenOrderEmail(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var SentSuccessfully: Boolean)
    var
        Email: Codeunit Email;
    begin
        SentSuccessfully := Email.Send(EmailMessage, SenderEmailAccount);
    end;

    local procedure HasOpenOrderData(CustomerNo: Code[20]): Boolean
    var
        SalesLine: Record "Sales Line";
    begin
        SalesLine.SetRange("Document Type", SalesLine."Document Type"::Order);
        SalesLine.SetRange("Sell-to Customer No.", CustomerNo);
        SalesLine.SetRange(Type, SalesLine.Type::Item);
        SalesLine.SetFilter("Outstanding Quantity", '>0');
        exit(not SalesLine.IsEmpty());
    end;

    local procedure CollectCustomerNumbers(var FilteredCustomers: Record Customer; var CustomerNos: List of [Code[20]])
    var
        Customer: Record Customer;
    begin
        Customer.Copy(FilteredCustomers);
        if Customer.FindSet() then
            repeat
                if not CustomerNos.Contains(Customer."No.") then
                    CustomerNos.Add(Customer."No.");
            until Customer.Next() = 0;
    end;

    local procedure CollectOpenOrderSummary(CustomerNo: Code[20]; var OrderCount: Integer; var LineCount: Integer; var IncludedOrderNos: Text[2048])
    var
        SalesLine: Record "Sales Line";
        OrderNos: List of [Code[20]];
        OrderNo: Code[20];
    begin
        Clear(OrderCount);
        Clear(LineCount);
        Clear(IncludedOrderNos);

        SalesLine.SetRange("Document Type", SalesLine."Document Type"::Order);
        SalesLine.SetRange("Sell-to Customer No.", CustomerNo);
        SalesLine.SetRange(Type, SalesLine.Type::Item);
        SalesLine.SetFilter("Outstanding Quantity", '>0');
        if SalesLine.FindSet() then
            repeat
                LineCount += 1;
                if not OrderNos.Contains(SalesLine."Document No.") then
                    OrderNos.Add(SalesLine."Document No.");
            until SalesLine.Next() = 0;

        OrderCount := OrderNos.Count();
        foreach OrderNo in OrderNos do begin
            if IncludedOrderNos <> '' then
                IncludedOrderNos += ', ';
            IncludedOrderNos := CopyStr(IncludedOrderNos + OrderNo, 1, MaxStrLen(IncludedOrderNos));
        end;
    end;

    local procedure ResolveRecipients(Customer: Record Customer; SenderEmailAddress: Text; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyRoutingRules(
            Customer,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries,
            ReplaceApplied);

        if ToRecipients.Count() = 0 then
            Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetPrimaryContactEmail(Customer."Primary Contact No."));
        if ToRecipients.Count() = 0 then
            Phase2EmailMgt.AddRecipientsFromText(ToRecipients, Customer."E-Mail");

        if not ReplaceApplied then
            AddDefaultSalesCcRecipients(Customer, ToRecipients, CCRecipients, SenderEmailAddress);

        if not SpecificRuleApplied then
            ApplyRoutingRules(
                Customer,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRuleEntries,
                ReplaceApplied);

        Phase2EmailMgt.NormalizeRecipientLists(ToRecipients, CCRecipients, BCCRecipients, SenderEmailAddress);
    end;

    local procedure ApplyRoutingRules(Customer: Record Customer; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingRule: Record "GPI Document Routing Rule";
        RuleApplied: Boolean;
    begin
        RoutingRule.SetCurrentKey(Enabled, "Delivery Document Type", Priority, "Entry No.");
        RoutingRule.SetRange(Enabled, true);
        RoutingRule.SetRange("Delivery Document Type", Enum::"GPI Delivery Document Type"::"Customer Open Order Status");
        if not RoutingRule.FindSet() then
            exit(false);

        repeat
            if RoutingRuleMatches(RoutingRule, Customer, SpecificCustomerOnly) and RoutingRuleIsActive(RoutingRule) then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRuleEntries, RoutingRule."Entry No.");
                if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then
                    ReplaceApplied := true;
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure RoutingRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; Customer: Record Customer; SpecificCustomerOnly: Boolean): Boolean
    begin
        if (RoutingRule."Vendor No." <> '') or (RoutingRule."Location Code" <> '') then
            exit(false);

        if SpecificCustomerOnly then
            exit(RoutingRule."Customer No." = Customer."No.");

        exit(RoutingRule."Customer No." = '');
    end;

    local procedure RoutingRuleIsActive(RoutingRule: Record "GPI Document Routing Rule"): Boolean
    begin
        if (RoutingRule."Effective Start Date" <> 0D) and (RoutingRule."Effective Start Date" > Today) then
            exit(false);
        if (RoutingRule."Effective End Date" <> 0D) and (RoutingRule."Effective End Date" < Today) then
            exit(false);
        exit(true);
    end;

    local procedure ApplyRoutingRule(RoutingRule: Record "GPI Document Routing Rule"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
    begin
        if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then begin
            Clear(ToRecipients);
            Clear(CCRecipients);
            Clear(BCCRecipients);
        end;

        Phase2EmailMgt.AddRecipientsFromText(ToRecipients, RoutingRule."To Addresses");
        Phase2EmailMgt.AddRecipientsFromText(CCRecipients, RoutingRule."CC Addresses");
        Phase2EmailMgt.AddRecipientsFromText(BCCRecipients, RoutingRule."BCC Addresses");
    end;

    local procedure AddDefaultSalesCcRecipients(Customer: Record Customer; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(Customer."Salesperson Code"), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(FindInsideSalespersonCode(Customer)), ToRecipients, SenderEmailAddress);
    end;

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; Address: Text; ToRecipients: List of [Text]; SenderEmailAddress: Text)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
    begin
        if Phase2EmailMgt.ContainsAddress(ToRecipients, Address) then
            exit;
        Phase2EmailMgt.AddUniqueRecipientExcept(CCRecipients, Address, SenderEmailAddress);
    end;

    local procedure GetPrimaryContactEmail(ContactNo: Code[20]): Text
    var
        Contact: Record Contact;
    begin
        if (ContactNo <> '') and Contact.Get(ContactNo) then
            exit(Contact."E-Mail");
        exit('');
    end;

    local procedure GetSalespersonEmail(SalespersonCode: Code[20]): Text
    var
        Salesperson: Record "Salesperson/Purchaser";
    begin
        if (SalespersonCode <> '') and Salesperson.Get(SalespersonCode) then
            exit(Salesperson."E-Mail");
        exit('');
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

    local procedure AppendRoutingRuleEntry(var AppliedRuleEntries: Text[250]; EntryNo: Integer)
    begin
        if AppliedRuleEntries = '' then
            AppliedRuleEntries := CopyStr(Format(EntryNo), 1, MaxStrLen(AppliedRuleEntries))
        else
            AppliedRuleEntries := CopyStr(AppliedRuleEntries + ',' + Format(EntryNo), 1, MaxStrLen(AppliedRuleEntries));
    end;

    local procedure BuildAttachmentName(CustomerNo: Code[20]): Text
    begin
        exit(StrSubstNo(
            'Open-Order-Status %1 %2.pdf',
            CustomerNo,
            Format(WorkDate(), 0, '<Year4>-<Month,2>-<Day,2>')));
    end;

    local procedure BuildSubject(): Text
    begin
        exit(StrSubstNo(
            'Open Order Status as of %1',
            Format(WorkDate(), 0, '<Month,2>/<Day,2>/<Year4>')));
    end;

    local procedure BuildBody(Customer: Record Customer): Text
    begin
        exit(StrSubstNo(
            '<p>Hello,</p><p>Please find attached the current open order status for %1 as of %2. The report includes warehouse and drop-ship item lines with remaining quantities.</p><p>Expected dates are estimates and may change. Please contact us with any questions.</p><p>Thank you,</p>',
            Customer.Name,
            Format(WorkDate(), 0, '<Month,2>/<Day,2>/<Year4>')));
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; Customer: Record Customer; InitialStatus: Enum "GPI Delivery Status"; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRuleEntries: Text[250]; SenderEmailAccount: Record "Email Account" temporary; EmailMessageId: Guid; TempBlob: Codeunit "Temp Blob"; OrderCount: Integer; LineCount: Integer; IncludedOrderNos: Text[2048]; ErrorText: Text; Completed: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryLog."Delivery Document Type"::"Customer Open Order Status";
        DeliveryLog.Status := InitialStatus;
        DeliveryLog."Customer No." := Customer."No.";
        DeliveryLog."Report ID" := Report::"GPI Customer Open Orders";
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessageId;
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::Customer;
        DeliveryLog."Source SystemId" := Customer.SystemId;
        DeliveryLog."Source Document Type" := 'Open Order Status';
        DeliveryLog."Source Document No." := Customer."No.";
        DeliveryLog."Source Party Type" := 'Customer';
        DeliveryLog."Source Party No." := Customer."No.";
        DeliveryLog."Open Order As Of Date" := WorkDate();
        DeliveryLog."Open Order Count" := OrderCount;
        DeliveryLog."Open Order Line Count" := LineCount;
        DeliveryLog."Included Order Nos." := IncludedOrderNos;
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Email Address" := CopyStr(SenderEmailAccount."Email Address", 1, MaxStrLen(DeliveryLog."Sender Email Address"));
        DeliveryLog."Sender Policy" := 'Current User';
        DeliveryLog."Routing Rule Entry Nos." := AppliedRuleEntries;
        DeliveryLog."Sender Account Name" := CopyStr(SenderEmailAccount.Name, 1, MaxStrLen(DeliveryLog."Sender Account Name"));
        DeliveryLog."Sender Connector" := CopyStr(Format(SenderEmailAccount.Connector), 1, MaxStrLen(DeliveryLog."Sender Connector"));
        DeliveryLog."Sender Account ID" := SenderEmailAccount."Account Id";
        DeliveryLog."Error Message" := CopyStr(ErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));

        if Completed then begin
            DeliveryLog."Completed Date/Time" := CurrentDateTime();
            DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        end;

        DeliveryLog.Insert(true);
        if TempBlob.HasValue() then begin
            TempBlob.CreateInStream(DocumentInStream);
            DeliveryLog."Document Content".CreateOutStream(DocumentOutStream);
            CopyStream(DocumentOutStream, DocumentInStream);
            DeliveryLog.Modify(true);
        end;
    end;

    local procedure UpdateDeliveryLogAfterEditor(var DeliveryLog: Record "GPI Document Delivery Log"; EmailMessage: Codeunit "Email Message"; EmailAction: Enum "Email Action")
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        FinalToRecipients: List of [Text];
        FinalCCRecipients: List of [Text];
        FinalBCCRecipients: List of [Text];
    begin
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"To", FinalToRecipients);
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"Cc", FinalCCRecipients);
        EmailMessage.GetRecipients(Enum::"Email Recipient Type"::"Bcc", FinalBCCRecipients);
        DeliveryLog."To Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(FinalToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(FinalCCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(FinalBCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(EmailMessage.GetSubject(), 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        Clear(DeliveryLog."Error Message");

        case EmailAction of
            Enum::"Email Action"::Sent:
                begin
                    DeliveryLog.Status := DeliveryLog.Status::Sent;
                    DeliveryLog."External Delivery ID" := CopyStr(EmailMessage.GetExternalId(), 1, MaxStrLen(DeliveryLog."External Delivery ID"));
                end;
            Enum::"Email Action"::"Saved As Draft":
                DeliveryLog.Status := DeliveryLog.Status::"Saved As Draft";
            Enum::"Email Action"::Discarded:
                DeliveryLog.Status := DeliveryLog.Status::Discarded;
        end;
        DeliveryLog.Modify(true);
    end;

    local procedure UpdateDeliveryLogSent(var DeliveryLog: Record "GPI Document Delivery Log"; EmailMessage: Codeunit "Email Message")
    begin
        DeliveryLog.Status := DeliveryLog.Status::Sent;
        DeliveryLog."External Delivery ID" := CopyStr(EmailMessage.GetExternalId(), 1, MaxStrLen(DeliveryLog."External Delivery ID"));
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        Clear(DeliveryLog."Error Message");
        DeliveryLog.Modify(true);
    end;

    local procedure UpdateDeliveryLogFailed(var DeliveryLog: Record "GPI Document Delivery Log"; ErrorText: Text)
    begin
        DeliveryLog.Status := DeliveryLog.Status::Failed;
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."Error Message" := CopyStr(ErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));
        DeliveryLog.Modify(true);
    end;
}
