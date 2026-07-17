codeunit 70551 "GPI Sales Return Email"
{
    procedure OpenAuthorizationDraft(var SalesHeader: Record "Sales Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidateSalesReturnOrder(SalesHeader);
        EnsureReleased(SalesHeader, 'Sales Return Authorization');

        Subject := StrSubstNo('Sales Return Authorization %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Your return has been authorized under Sales Return Order %1.</p><p>Please review the attached authorization and return instructions.</p><p>Thank you,</p>',
            SalesHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Sales-Return-Authorization %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Sales Return Authorization",
            Report::"GPI Sales Return Auth.",
            Subject,
            Body,
            AttachmentName,
            false);
    end;

    procedure OpenWarehouseNotificationDraft(var SalesHeader: Record "Sales Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidateSalesReturnOrder(SalesHeader);
        SalesHeader.TestField("Location Code");
        EnsureReleased(SalesHeader, 'Sales Return Warehouse Notification');

        Subject := StrSubstNo('Sales Return Warehouse Notification %1', SalesHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please prepare to receive the customer return for Sales Return Order %1 at Location %2.</p><p>The warehouse notification is attached.</p><p>Thank you,</p>',
            SalesHeader."No.",
            SalesHeader."Location Code");
        AttachmentName := CopyStr(StrSubstNo('Sales-Return-Warehouse-Notification %1.pdf', SalesHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
            Report::"GPI Sales Return WH Notice",
            Subject,
            Body,
            AttachmentName,
            true);
    end;

    procedure PreviewAuthorization(var SalesHeader: Record "Sales Header")
    begin
        ValidateSalesReturnOrder(SalesHeader);
        SalesHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Sales Return Auth.", true, false, SalesHeader);
    end;

    procedure PreviewWarehouseNotification(var SalesHeader: Record "Sales Header")
    begin
        ValidateSalesReturnOrder(SalesHeader);
        SalesHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Sales Return WH Notice", true, false, SalesHeader);
    end;

    local procedure OpenDraft(var SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250]; WarehouseDocument: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SenderEmailAccount: Record "Email Account" temporary;
        DeliveryLog: Record "GPI Document Delivery Log";
        SalesHeaderRef: RecordRef;
        AttachmentOutStream: OutStream;
        AttachmentInStream: InStream;
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRoutingRuleEntries: Text[250];
        SenderEmailAddress: Text;
        EmailAction: Enum "Email Action";
        EmailErrorText: Text;
    begin
        SenderEmailAddress := Phase2EmailMgt.ResolveCurrentUserAccount(SenderEmailAccount);

        if WarehouseDocument then
            ResolveWarehouseRecipients(
                SalesHeader,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries)
        else begin
            LineVisibilityMgt.ValidateSalesExternalDocument(SalesHeader);
            ResolveAuthorizationRecipients(
                SalesHeader,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                SenderEmailAddress);
        end;

        Phase2EmailMgt.NormalizeRecipientLists(
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            SenderEmailAddress);

        if ToRecipients.Count() = 0 then
            if WarehouseDocument then
                Error(
                    'No warehouse recipient was resolved for Location %1. Add an email to the Location Card or create a Sales Return Warehouse Notification routing rule.',
                    SalesHeader."Location Code")
            else
                Error(
                    'No customer recipient was resolved for Sales Return Order %1. Add a customer routing rule, a contact email, or an email to the Customer Card.',
                    SalesHeader."No.");

        SalesHeader.SetRecFilter();
        SalesHeaderRef.GetTable(SalesHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(ReportId, '', ReportFormat::Pdf, AttachmentOutStream, SalesHeaderRef);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Sales Header",
            SalesHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            SalesHeader,
            DeliveryDocumentType,
            ReportId,
            AttachmentName,
            Subject,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            EmailMessage,
            SenderEmailAccount,
            TempBlob,
            WarehouseDocument);

        DeliveryTransportMgt.CommitChanges();
        if not DeliveryTransportMgt.OpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction, EmailErrorText) then begin
            if EmailErrorText = '' then
                EmailErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, EmailErrorText);
            DeliveryTransportMgt.CommitChanges();
            Error('%1', EmailErrorText);
        end;

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    local procedure ValidateSalesReturnOrder(SalesHeader: Record "Sales Header")
    begin
        SalesHeader.TestField("Document Type", SalesHeader."Document Type"::"Return Order");
        SalesHeader.TestField("No.");
        SalesHeader.TestField("Sell-to Customer No.");
    end;

    local procedure EnsureReleased(SalesHeader: Record "Sales Header"; DocumentDescription: Text)
    begin
        if SalesHeader.Status <> SalesHeader.Status::Released then
            Error(
                '%1 for Sales Return Order %2 can be previewed while the order is %3, but it cannot be sent until the Sales Return Order is Released.',
                DocumentDescription,
                SalesHeader."No.",
                Format(SalesHeader.Status));
    end;

    local procedure ResolveAuthorizationRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; SenderEmailAddress: Text)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyCustomerRoutingRules(
            SalesHeader,
            Enum::"GPI Delivery Document Type"::"Sales Return Authorization",
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied);

        if ToRecipients.Count() = 0 then
            Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetCustomerRecipientEmail(SalesHeader));

        if not ReplaceApplied then
            AddDefaultSalesCcRecipients(SalesHeader, ToRecipients, CCRecipients, SenderEmailAddress);

        if not SpecificRuleApplied then
            ApplyCustomerRoutingRules(
                SalesHeader,
                Enum::"GPI Delivery Document Type"::"Sales Return Authorization",
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                ReplaceApplied);
    end;

    local procedure ResolveWarehouseRecipients(SalesHeader: Record "Sales Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetLocationEmail(SalesHeader."Location Code"));

        SpecificRuleApplied := ApplyLocationRoutingRules(
            SalesHeader."Location Code",
            Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied);

        if not SpecificRuleApplied then
            ApplyLocationRoutingRules(
                SalesHeader."Location Code",
                Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice",
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                ReplaceApplied);
    end;

    local procedure ApplyCustomerRoutingRules(SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificCustomerOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyCustomerRules(
            DeliveryDocumentType,
            SalesHeader."Sell-to Customer No.",
            SalesHeader."Location Code",
            SpecificCustomerOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

    local procedure ApplyLocationRoutingRules(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificLocationOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
    var
        RoutingResolver: Codeunit "GPI Routing Rule Resolver";
    begin
        exit(RoutingResolver.ApplyLocationRules(
            DeliveryDocumentType,
            LocationCode,
            SpecificLocationOnly,
            Today,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied));
    end;

    local procedure CustomerRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; SalesHeader: Record "Sales Header"; SpecificCustomerOnly: Boolean): Boolean
    begin
        if RoutingRule."Vendor No." <> '' then
            exit(false);

        if SpecificCustomerOnly then begin
            if RoutingRule."Customer No." <> SalesHeader."Sell-to Customer No." then
                exit(false);
        end else
            if RoutingRule."Customer No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and (RoutingRule."Location Code" <> SalesHeader."Location Code") then
            exit(false);

        exit(true);
    end;

    local procedure LocationRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; LocationCode: Code[10]; SpecificLocationOnly: Boolean): Boolean
    begin
        if (RoutingRule."Customer No." <> '') or (RoutingRule."Vendor No." <> '') then
            exit(false);

        if SpecificLocationOnly then
            exit(RoutingRule."Location Code" = LocationCode);

        exit(RoutingRule."Location Code" = '');
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

    local procedure AddDefaultSalesCcRecipients(SalesHeader: Record "Sales Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(SalesHeader."Salesperson Code"), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(GetInsideSalespersonCode(SalesHeader)), ToRecipients, SenderEmailAddress);
    end;

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; Address: Text; ToRecipients: List of [Text]; SenderEmailAddress: Text)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
    begin
        if Phase2EmailMgt.ContainsAddress(ToRecipients, Address) then
            exit;
        Phase2EmailMgt.AddUniqueRecipientExcept(CCRecipients, Address, SenderEmailAddress);
    end;

    local procedure GetCustomerRecipientEmail(SalesHeader: Record "Sales Header"): Text
    var
        Customer: Record Customer;
        Contact: Record Contact;
    begin
        if (SalesHeader."Sell-to Contact No." <> '') and Contact.Get(SalesHeader."Sell-to Contact No.") and (Contact."E-Mail" <> '') then
            exit(Contact."E-Mail");

        if not Customer.Get(SalesHeader."Sell-to Customer No.") then
            exit('');

        if (Customer."Primary Contact No." <> '') and Contact.Get(Customer."Primary Contact No.") and (Contact."E-Mail" <> '') then
            exit(Contact."E-Mail");

        exit(Customer."E-Mail");
    end;

    local procedure GetLocationEmail(LocationCode: Code[10]): Text
    var
        Location: Record Location;
    begin
        if Location.Get(LocationCode) then
            exit(Location."E-Mail");
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

    local procedure GetInsideSalespersonCode(SalesHeader: Record "Sales Header"): Code[20]
    var
        SalesHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        CandidateValue: Text;
    begin
        SalesHeaderRef.GetTable(SalesHeader);
        for FieldIndex := 1 to SalesHeaderRef.FieldCount do begin
            CandidateField := SalesHeaderRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if ((StrPos(FieldIdentity, 'inside salesperson') > 0) or
                (StrPos(FieldIdentity, 'inside sales') > 0) or
                (StrPos(FieldIdentity, 'isr') > 0)) and
               (StrPos(FieldIdentity, 'backup') = 0)
            then begin
                CandidateValue := Format(CandidateField.Value);
                exit(CopyStr(CandidateValue, 1, 20));
            end;
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
                AppliedRoutingRuleEntries + ',' + EntryText,
                1,
                MaxStrLen(AppliedRoutingRuleEntries));
    end;

    [TryFunction]
    local procedure TryOpenEmailEditor(EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; var EmailAction: Enum "Email Action")
    var
        Email: Codeunit Email;
    begin
        EmailAction := Email.OpenInEditorModally(EmailMessage, SenderEmailAccount);
    end;

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; SalesHeader: Record "Sales Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRoutingRuleEntries: Text[250]; EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; TempBlob: Codeunit "Temp Blob"; WarehouseDocument: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryDocumentType;
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Customer No." := SalesHeader."Sell-to Customer No.";
        DeliveryLog."Location Code" := SalesHeader."Location Code";
        DeliveryLog."Report ID" := ReportId;
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessage.GetId();
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Sales Header";
        DeliveryLog."Source SystemId" := SalesHeader.SystemId;
        DeliveryLog."Source Document Type" := CopyStr(Format(SalesHeader."Document Type"), 1, MaxStrLen(DeliveryLog."Source Document Type"));
        DeliveryLog."Source Document No." := SalesHeader."No.";
        if WarehouseDocument then begin
            DeliveryLog."Source Party Type" := 'Location';
            DeliveryLog."Source Party No." := SalesHeader."Location Code";
        end else begin
            DeliveryLog."Source Party Type" := 'Customer';
            DeliveryLog."Source Party No." := SalesHeader."Sell-to Customer No.";
        end;
        DeliveryLog."Sender User" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Sender User"));
        DeliveryLog."Sender Email Address" := CopyStr(SenderEmailAccount."Email Address", 1, MaxStrLen(DeliveryLog."Sender Email Address"));
        DeliveryLog."Sender Policy" := 'Current User';
        DeliveryLog."Routing Rule Entry Nos." := AppliedRoutingRuleEntries;
        DeliveryLog."Sender Account Name" := CopyStr(SenderEmailAccount.Name, 1, MaxStrLen(DeliveryLog."Sender Account Name"));
        DeliveryLog."Sender Connector" := CopyStr(Format(SenderEmailAccount.Connector), 1, MaxStrLen(DeliveryLog."Sender Connector"));
        DeliveryLog."Sender Account ID" := SenderEmailAccount."Account Id";
        DeliveryLog.Insert(true);

        TempBlob.CreateInStream(DocumentInStream);
        DeliveryLog."Document Content".CreateOutStream(DocumentOutStream);
        CopyStream(DocumentOutStream, DocumentInStream);
        DeliveryLog.Modify(true);
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

    local procedure UpdateDeliveryLogFailed(var DeliveryLog: Record "GPI Document Delivery Log"; EmailErrorText: Text)
    begin
        DeliveryLog.Status := DeliveryLog.Status::Failed;
        DeliveryLog."Completed Date/Time" := CurrentDateTime();
        DeliveryLog."Completed By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Completed By"));
        DeliveryLog."Error Message" := CopyStr(EmailErrorText, 1, MaxStrLen(DeliveryLog."Error Message"));
        DeliveryLog.Modify(true);
    end;
}

