codeunit 70570 "GPI Transfer Email"
{
    procedure OpenPickListDraft(var TransferHeader: Record "Transfer Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidateTransferOrder(TransferHeader);
        EnsureReleased(TransferHeader, 'Transfer Pick List');

        Subject := StrSubstNo('Transfer Pick List %1', TransferHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please pick and prepare the items on Transfer Order %1 for shipment from Location %2 to Location %3.</p><p>The transfer pick list is attached.</p><p>Thank you,</p>',
            TransferHeader."No.",
            TransferHeader."Transfer-from Code",
            TransferHeader."Transfer-to Code");
        AttachmentName := CopyStr(StrSubstNo('Transfer-Pick-List %1.pdf', TransferHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            TransferHeader,
            Enum::"GPI Delivery Document Type"::"Transfer Pick List",
            Report::"GPI Transfer Pick List",
            Subject,
            Body,
            AttachmentName,
            TransferHeader."Transfer-from Code");
    end;

    procedure OpenReceiptNoticeDraft(var TransferHeader: Record "Transfer Header")
    var
        Subject: Text;
        Body: Text;
        AttachmentName: Text[250];
    begin
        ValidateTransferOrder(TransferHeader);
        EnsureReleased(TransferHeader, 'Transfer Receipt Notification');

        Subject := StrSubstNo('Transfer Receipt Notification %1', TransferHeader."No.");
        Body := StrSubstNo(
            '<p>Hello,</p><p>Please prepare to receive the items on Transfer Order %1 from Location %2 into Location %3.</p><p>The transfer receipt notification is attached.</p><p>Thank you,</p>',
            TransferHeader."No.",
            TransferHeader."Transfer-from Code",
            TransferHeader."Transfer-to Code");
        AttachmentName := CopyStr(StrSubstNo('Transfer-Receipt-Notification %1.pdf', TransferHeader."No."), 1, MaxStrLen(AttachmentName));

        OpenDraft(
            TransferHeader,
            Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice",
            Report::"GPI Transfer Receipt Notice",
            Subject,
            Body,
            AttachmentName,
            TransferHeader."Transfer-to Code");
    end;

    procedure PreviewPickList(var TransferHeader: Record "Transfer Header")
    begin
        ValidateTransferOrder(TransferHeader);
        TransferHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Transfer Pick List", true, false, TransferHeader);
    end;

    procedure PreviewReceiptNotice(var TransferHeader: Record "Transfer Header")
    begin
        ValidateTransferOrder(TransferHeader);
        TransferHeader.SetRecFilter();
        Report.RunModal(Report::"GPI Transfer Receipt Notice", true, false, TransferHeader);
    end;

    local procedure OpenDraft(var TransferHeader: Record "Transfer Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; Subject: Text; Body: Text; AttachmentName: Text[250]; RecipientLocationCode: Code[10])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DeliveryTransportMgt: Codeunit "GPI Delivery Transport Mgt.";
        TempBlob: Codeunit "Temp Blob";
        EmailMessage: Codeunit "Email Message";
        Email: Codeunit Email;
        SenderEmailAccount: Record "Email Account" temporary;
        DeliveryLog: Record "GPI Document Delivery Log";
        TransferHeaderRef: RecordRef;
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

        ResolveLocationRecipients(
            RecipientLocationCode,
            DeliveryDocumentType,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries);

        Phase2EmailMgt.NormalizeRecipientLists(
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            SenderEmailAddress);

        if ToRecipients.Count() = 0 then
            Error(
                'No recipient was resolved for Location %1. Add an email to the Location Card or create a %2 routing rule.',
                RecipientLocationCode,
                Format(DeliveryDocumentType));

        TransferHeader.SetRecFilter();
        TransferHeaderRef.GetTable(TransferHeader);
        TempBlob.CreateOutStream(AttachmentOutStream);
        Report.SaveAs(ReportId, '', ReportFormat::Pdf, AttachmentOutStream, TransferHeaderRef);

        EmailMessage.Create(ToRecipients, Subject, Body, true, CCRecipients, BCCRecipients);
        TempBlob.CreateInStream(AttachmentInStream);
        EmailMessage.AddAttachment(AttachmentName, 'application/pdf', AttachmentInStream);
        Email.AddRelation(
            EmailMessage,
            Database::"Transfer Header",
            TransferHeader.SystemId,
            Enum::"Email Relation Type"::"Primary Source",
            Enum::"Email Relation Origin"::"Compose Context");

        CreateDeliveryLog(
            DeliveryLog,
            TransferHeader,
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
            RecipientLocationCode);

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

    local procedure ValidateTransferOrder(TransferHeader: Record "Transfer Header")
    begin
        TransferHeader.TestField("No.");
        TransferHeader.TestField("Transfer-from Code");
        TransferHeader.TestField("Transfer-to Code");
        if TransferHeader."Transfer-from Code" = TransferHeader."Transfer-to Code" then
            Error(
                'Transfer Order %1 has the same transfer-from and transfer-to location. Select two different locations before generating transfer documents.',
                TransferHeader."No.");
    end;

    local procedure EnsureReleased(TransferHeader: Record "Transfer Header"; DocumentDescription: Text)
    begin
        if TransferHeader.Status <> TransferHeader.Status::Released then
            Error(
                '%1 for Transfer Order %2 can be previewed while the order is %3, but it cannot be sent until the Transfer Order is Released.',
                DocumentDescription,
                TransferHeader."No.",
                Format(TransferHeader.Status));
    end;

    local procedure ResolveLocationRecipients(LocationCode: Code[10]; DeliveryDocumentType: Enum "GPI Delivery Document Type"; var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; var AppliedRoutingRuleEntries: Text[250])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        SpecificRuleApplied: Boolean;
        ReplaceApplied: Boolean;
    begin
        Phase2EmailMgt.AddRecipientsFromText(ToRecipients, GetLocationEmail(LocationCode));

        SpecificRuleApplied := ApplyLocationRoutingRules(
            LocationCode,
            DeliveryDocumentType,
            true,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRoutingRuleEntries,
            ReplaceApplied);

        if not SpecificRuleApplied then
            ApplyLocationRoutingRules(
                LocationCode,
                DeliveryDocumentType,
                false,
                ToRecipients,
                CCRecipients,
                BCCRecipients,
                AppliedRoutingRuleEntries,
                ReplaceApplied);
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

    local procedure GetLocationEmail(LocationCode: Code[10]): Text
    var
        Location: Record Location;
    begin
        if Location.Get(LocationCode) then
            exit(Location."E-Mail");
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

    local procedure CreateDeliveryLog(var DeliveryLog: Record "GPI Document Delivery Log"; TransferHeader: Record "Transfer Header"; DeliveryDocumentType: Enum "GPI Delivery Document Type"; ReportId: Integer; AttachmentName: Text[250]; Subject: Text; ToRecipients: List of [Text]; CCRecipients: List of [Text]; BCCRecipients: List of [Text]; AppliedRoutingRuleEntries: Text[250]; EmailMessage: Codeunit "Email Message"; SenderEmailAccount: Record "Email Account" temporary; TempBlob: Codeunit "Temp Blob"; RecipientLocationCode: Code[10])
    var
        Phase2EmailMgt: Codeunit "GPI Phase 2 Email Mgt.";
        DocumentInStream: InStream;
        DocumentOutStream: OutStream;
    begin
        DeliveryLog.Init();
        DeliveryLog."Delivery Document Type" := DeliveryDocumentType;
        DeliveryLog.Status := DeliveryLog.Status::Created;
        DeliveryLog."Location Code" := RecipientLocationCode;
        DeliveryLog."Report ID" := ReportId;
        DeliveryLog."Attachment Filename" := AttachmentName;
        DeliveryLog."To Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(ToRecipients), 1, MaxStrLen(DeliveryLog."To Recipients"));
        DeliveryLog."CC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(CCRecipients), 1, MaxStrLen(DeliveryLog."CC Recipients"));
        DeliveryLog."BCC Recipients" := CopyStr(Phase2EmailMgt.JoinRecipients(BCCRecipients), 1, MaxStrLen(DeliveryLog."BCC Recipients"));
        DeliveryLog.Subject := CopyStr(Subject, 1, MaxStrLen(DeliveryLog.Subject));
        DeliveryLog."Email Message ID" := EmailMessage.GetId();
        DeliveryLog."Created Date/Time" := CurrentDateTime();
        DeliveryLog."Created By" := CopyStr(UserId(), 1, MaxStrLen(DeliveryLog."Created By"));
        DeliveryLog."Source Table ID" := Database::"Transfer Header";
        DeliveryLog."Source SystemId" := TransferHeader.SystemId;
        DeliveryLog."Source Document Type" := 'Transfer Order';
        DeliveryLog."Source Document No." := TransferHeader."No.";
        DeliveryLog."Source Party Type" := 'Location';
        DeliveryLog."Source Party No." := RecipientLocationCode;
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
