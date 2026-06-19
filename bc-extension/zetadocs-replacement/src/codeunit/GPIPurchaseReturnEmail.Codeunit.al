codeunit 70560 "GPI Purchase Return Email"
{
    procedure OpenVendorReturnDraft(var PurchaseHeader: Record "Purchase Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidatePurchaseReturnOrder(PurchaseHeader);
        EnsureReleased(PurchaseHeader, 'Purchase Return Order');

        Subject := StrSubstNo('Purchase Return Order %1', PurchaseHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please find attached Purchase Return Order %1 for the items being returned to you.</p><p>Please review the return details and advise if additional authorization or shipping instructions are required.</p><p>Thank you,</p>',
            PurchaseHeader."No.");
        AttachmentName := CopyStr(StrSubstNo('Purchase-Return-Order %1.pdf', PurchaseHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            PurchaseHeader,
            Enum::"GPI Delivery Document Type"::"Purchase Return Order",
            Report::"GPI Purchase Return Order",
            Subject,
            Body,
            AttachmentName,
            false);
    end;

    procedure OpenPickTicketDraft(var PurchaseHeader: Record "Purchase Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidatePurchaseReturnOrder(PurchaseHeader);
        PurchaseHeader.TestField("Location Code");
        EnsureReleased(PurchaseHeader, 'Purchase Return Pick Ticket');

        Subject := StrSubstNo('Purchase Return Pick Ticket %1', PurchaseHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please pick and prepare the items on Purchase Return Order %1 for shipment from Location %2.</p><p>The pick ticket is attached.</p><p>Thank you,</p>',
            PurchaseHeader."No.",
            PurchaseHeader."Location Code");
        AttachmentName := CopyStr(StrSubstNo('Purchase-Return-Pick-Ticket %1.pdf', PurchaseHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            PurchaseHeader,
            Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
            Report::"GPI Purchase Return Pick",
            Subject,
            Body,
            AttachmentName,
            true);
    end;

    procedure PreviewVendorReturn(var PurchaseHeader: Record "Purchase Header")
    begin
        ValidatePurchaseReturnOrder(PurchaseHeader);
        PurchaseHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Purchase Return Order", true, false, PurchaseHeader);
    end;

    procedure PreviewPickTicket(var PurchaseHeader: Record "Purchase Header")
    begin
        ValidatePurchaseReturnOrder(PurchaseHeader);
        PurchaseHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Purchase Return Pick", true, false, PurchaseHeader);
    end;

    local procedure OpenDraft(var PurchaseHeader: Record "Purchase Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250]; WarehouseDocument: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        LineVisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SenderEmailAccount: Record "Email Account" temporary;
        DeliveryLog: Record "GPI Document Delivery Log";
        Vendor: Record Vendor;
        PurchaseHeaderRef: RecordRef;
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
                PurchaseHeader,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries)
        else begin
            LineVisibilityMgt.ValidatePurchaseExternalDocument(PurchaseHeader);
            ResolveVendorRecipients(
                PurchaseHeader,
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
                    'No warehouse recipient was resolved for Location %1. Add an email to the Location Card or create a Purchase Return Pick Ticket routing rule.',
                    PurchaseHeader."Location Code")
            else
                Error(
                    'No vendor recipient was resolved for Purchase Return Order %1. Add a vendor routing rule, a document contact email, or an email to the Vendor Card.',
                    PurchaseHeader."No.");

        PurchaseHeader.SetRecFilter();
        PurchaseHeaderRef.GetTable(PurchaseHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(ReportId, '', ReportFormat::Pdf, AttachmentOutStream, PurchaseHeaderRef);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Purchase Header",
            PurchaseHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        if Vendor.Get(PurchaseHeader."Buy-from Vendor No.") then
            Email.AddRelation(
                EmailMessage,
                Database::Vendor,
                Vendor.SystemId,
                Enum::"Email Relation Type"::"Related Entity",
                Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            PurchaseHeader,
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

        Commit();
        if not TryOpenEmailEditor(EmailMessage, SenderEmailAccount, EmailAction) then begin
            EmailErrorText := GetLastErrorText();
            if EmailErrorText = '' then
                EmailErrorText := 'The Business Central email editor returned an unexpected error.';

            UpdateDeliveryLogFailed(DeliveryLog, EmailErrorText);
            Commit();
            Error('%1', EmailErrorText);
        end;

        UpdateDeliveryLogAfterEditor(DeliveryLog, EmailMessage, EmailAction);
    end;

    local procedure ValidatePurchaseReturnOrder(PurchaseHeader: Record "Purchase Header")
    begin
        PurchaseHeader.TestField("Document Type", PurchaseHeader."Document Type"::"Return Order");
        PurchaseHeader.TestField("No.");
        PurchaseHeader.TestField("Buy-from Vendor No.");
    end;

    local procedure EnsureReleased(PurchaseHeader: Record "Purchase Header"; DocumentDescription: Text)
    begin
        if PurchaseHeader.Status <> PurchaseHeader.Status::Released then
            Error(
                '%1 for Purchase Return Order %2 can be previewed while the order is %3, but it cannot be sent until the Purchase Return Order is Released.',
                DocumentDescription,
                PurchaseHeader."No.",
                Format(PurchaseHeader.Status));
    end;

    local procedure ResolveVendorRecipients(PurchaseHeader: Record "Purchase Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; SenderEmailAddress: Text)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        SpecificRuleApplied := ApplyVendorRoutingRules(
            PurchaseHeader,
            Enum::"GPI Delivery Document Type"::"Purchase Return Order",
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied);

        if ToRecipients.Count() = 0 then
            Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetVendorRecipientEmail(PurchaseHeader));

        if not ReplaceApplied then
            AddDefaultSalesCcRecipients(PurchaseHeader, ToRecipients, CCRecipients, SenderEmailAddress);

        if not SpecificRuleApplied then
            ApplyVendorRoutingRules(
                PurchaseHeader,
                Enum::"GPI Delivery Document Type"::"Purchase Return Order",
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                ReplaceApplied);
    end;

    local procedure ResolveWarehouseRecipients(PurchaseHeader: Record "Purchase Header"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetLocationEmail(PurchaseHeader."Location Code"));

        SpecificRuleApplied := ApplyLocationRoutingRules(
            PurchaseHeader."Location Code",
            Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied);

        if not SpecificRuleApplied then
            ApplyLocationRoutingRules(
                PurchaseHeader."Location Code",
                Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket",
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                ReplaceApplied);
    end;

    local procedure ApplyVendorRoutingRules(PurchaseHeader: Record "Purchase Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificVendorOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
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
            if VendorRuleMatches(RoutingRule, PurchaseHeader, SpecificVendorOnly) and RoutingRuleIsActive(RoutingRule) then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRoutingRuleEntries, RoutingRule."Entry No.");
                if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then
                    ReplaceApplied := true;
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure ApplyLocationRoutingRules(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; SpecificLocationOnly: Boolean; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250]; var ReplaceApplied: Boolean): Boolean
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
            if LocationRuleMatches(RoutingRule, LocationCode, SpecificLocationOnly) and RoutingRuleIsActive(RoutingRule) then begin
                ApplyRoutingRule(RoutingRule, ToRecipients, CCRecipients, BCCRecipients);
                AppendRoutingRuleEntry(AppliedRoutingRuleEntries, RoutingRule."Entry No.");
                if RoutingRule."Recipient Action" = RoutingRule."Recipient Action"::Replace then
                    ReplaceApplied := true;
                RuleApplied := true;
            end;
        until RoutingRule.Next() = 0;

        exit(RuleApplied);
    end;

    local procedure VendorRuleMatches(RoutingRule: Record "GPI Document Routing Rule"; PurchaseHeader: Record "Purchase Header"; SpecificVendorOnly: Boolean): Boolean
    begin
        if RoutingRule."Customer No." <> '' then
            exit(false);

        if SpecificVendorOnly then begin
            if RoutingRule."Vendor No." <> PurchaseHeader."Buy-from Vendor No." then
                exit(false);
        end else
            if RoutingRule."Vendor No." <> '' then
                exit(false);

        if (RoutingRule."Location Code" <> '') and (RoutingRule."Location Code" <> PurchaseHeader."Location Code") then
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

    local procedure AddDefaultSalesCcRecipients(PurchaseHeader: Record "Purchase Header"; ToRecipients: List of [Text]; var CCRecipients: List of [Text]; SenderEmailAddress: Text)
    begin
        AddCcRecipient(CCRecipients, GetSalespersonEmail(FindSalespersonCode(PurchaseHeader, false)), ToRecipients, SenderEmailAddress);
        AddCcRecipient(CCRecipients, GetSalespersonEmail(FindSalespersonCode(PurchaseHeader, true)), ToRecipients, SenderEmailAddress);
    end;

    local procedure AddCcRecipient(var CCRecipients: List of [Text]; Address: Text; ToRecipients: List of [Text]; SenderEmailAddress: Text)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
    begin
        if Phase2EmailMgt.ContainsAddress(ToRecipients, Address) then
            exit;
        Phase2EmailMgt.AddUniqueRecipientExcept(CCRecipients, Address, SenderEmailAddress);
    end;

    local procedure GetVendorRecipientEmail(PurchaseHeader: Record "Purchase Header"): Text
    var
        Vendor: Record Vendor;
        Contact: Record Contact;
    begin
        if (PurchaseHeader."Buy-from Contact No." <> '') and Contact.Get(PurchaseHeader."Buy-from Contact No.") and (Contact."E-Mail" <> '') then
            exit(Contact."E-Mail");

        if not Vendor.Get(PurchaseHeader."Buy-from Vendor No.") then
            exit('');

        if (Vendor."Primary Contact No." <> '') and Contact.Get(Vendor."Primary Contact No.") and (Contact."E-Mail" <> '') then
            exit(Contact."E-Mail");

        exit(Vendor."E-Mail");
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

    local procedure FindSalespersonCode(PurchaseHeader: Record "Purchase Header"; InsideSales: Boolean): Code[20]
    var
        PurchaseHeaderRef: RecordRef;
        CandidateField: FieldRef;
        FieldIndex: Integer;
        CandidateIdentity: Text;
        CandidateValue: Text;
        IsInsideSalesField: Boolean;
    begin
        PurchaseHeaderRef.GetTable(PurchaseHeader);

        for FieldIndex := 1 to PurchaseHeaderRef.FieldCount do begin
            CandidateField := PurchaseHeaderRef.FieldIndex(FieldIndex);
            CandidateIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            IsInsideSalesField :=
                (StrPos(CandidateIdentity, 'inside salesperson') > 0) or
                (StrPos(CandidateIdentity, 'inside sales') > 0) or
                (StrPos(CandidateIdentity, 'isr') > 0);

            if (StrPos(CandidateIdentity, 'salesperson') > 0) and
               (StrPos(CandidateIdentity, 'backup') = 0) and
               (StrPos(CandidateIdentity, 'purchaser') = 0) and
               (IsInsideSalesField = InsideSales)
            then begin
                CandidateValue := DelChr(Format(CandidateField.Value), '<>', ' ');
                if CandidateValue <> '' then
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

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; PurchaseHeader: Record "Purchase Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRoutingRuleEntries: Text[250]; EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; TempBlob: Codeunit "Temp Blob"; WarehouseDocument: Boolean)
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryDocumentType;
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Location Code" := PurchaseHeader."Location Code";
        DeliveryLog."Report ID" := ReportId;
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessage.GetId();
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Purchase Header";
        DeliveryLog."Source SystemId" := PurchaseHeader.SystemId;
        DeliveryLog."Source Document Type" := CopyStr(Format(PurchaseHeader."Document Type"), 1, MaxStrLen(DeliveryLog."Source Document Type"));
        DeliveryLog."Source Document No." := PurchaseHeader."No.";
        if WarehouseDocument then begin
            DeliveryLog."Source Party Type" := 'Location';
            DeliveryLog."Source Party No." := PurchaseHeader."Location Code";
        end else begin
            DeliveryLog."Source Party Type" := 'Vendor';
            DeliveryLog."Source Party No." := PurchaseHeader."Buy-from Vendor No.";
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
