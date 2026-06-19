codeunit 70550 "GPI Phase 2 Email Mgt."
{
    procedure ResolveCurrentUserAccount(var TempEmailAccount: Record "Email Account" temporary): Text
    var
        EmailAccountMgt: Codeunit "Email Account";
        SenderEmailAddress: Text;
    begin
        SenderEmailAddress := NormalizeAddress(UserId());
        if not LooksLikeEmail(SenderEmailAddress) then
            SenderEmailAddress := FindCurrentUserSetupEmail();

        if not LooksLikeEmail(SenderEmailAddress) then
            Error(
                'The current Business Central user %1 does not have a usable email address. Add the user email to User Setup before sending this document.',
                UserId());

        Clear(TempEmailAccount);
        EmailAccountMgt.GetAllAccounts(TempEmailAccount);
        if TempEmailAccount.FindSet() then
            repeat
                if SameAddress(TempEmailAccount."Email Address", SenderEmailAddress) then
                    exit(SenderEmailAddress);
            until TempEmailAccount.Next() = 0;

        Error(
            'No Business Central Email Account is registered for the current user %1. Add %2 in Email Accounts before sending this document.',
            UserId(),
            SenderEmailAddress);
    end;

    procedure AddRecipientsFromText(var Recipients: List of [Text]; Addresses: Text)
    var
        Address: Text;
        DelimiterPosition: Integer;
    begin
        Addresses := ConvertStr(Addresses, ',', ';');
        while Addresses <> '' do begin
            DelimiterPosition := StrPos(Addresses, ';');
            if DelimiterPosition = 0 then begin
                Address := Addresses;
                Clear(Addresses);
            end else begin
                Address := CopyStr(Addresses, 1, DelimiterPosition - 1);
                Addresses := CopyStr(Addresses, DelimiterPosition + 1);
            end;
            AddUniqueRecipient(Recipients, Address);
        end;
    end;

    procedure AddUniqueRecipient(var Recipients: List of [Text]; Address: Text)
    begin
        Address := NormalizeAddress(Address);
        if not LooksLikeEmail(Address) then
            exit;
        if ContainsAddress(Recipients, Address) then
            exit;
        Recipients.Add(Address);
    end;

    procedure AddUniqueRecipientExcept(var Recipients: List of [Text]; Address: Text; ExcludedAddress: Text)
    begin
        Address := NormalizeAddress(Address);
        if SameAddress(Address, ExcludedAddress) then
            exit;
        AddUniqueRecipient(Recipients, Address);
    end;

    procedure NormalizeRecipientLists(var ToRecipients: List of [Text]; var CCRecipients: List of [Text]; var BCCRecipients: List of [Text]; SenderEmailAddress: Text)
    var
        NormalizedTo: List of [Text];
        NormalizedCC: List of [Text];
        NormalizedBCC: List of [Text];
        Recipient: Text;
    begin
        foreach Recipient in ToRecipients do
            AddUniqueRecipientExcept(NormalizedTo, Recipient, SenderEmailAddress);

        foreach Recipient in CCRecipients do
            if not ContainsAddress(NormalizedTo, Recipient) then
                AddUniqueRecipientExcept(NormalizedCC, Recipient, SenderEmailAddress);

        foreach Recipient in BCCRecipients do
            if not ContainsAddress(NormalizedTo, Recipient) and not ContainsAddress(NormalizedCC, Recipient) then
                AddUniqueRecipientExcept(NormalizedBCC, Recipient, SenderEmailAddress);

        ToRecipients := NormalizedTo;
        CCRecipients := NormalizedCC;
        BCCRecipients := NormalizedBCC;
    end;

    procedure ContainsAddress(Recipients: List of [Text]; Address: Text): Boolean
    var
        ExistingAddress: Text;
    begin
        foreach ExistingAddress in Recipients do
            if SameAddress(ExistingAddress, Address) then
                exit(true);
        exit(false);
    end;

    procedure JoinRecipients(Recipients: List of [Text]): Text
    var
        Recipient: Text;
        JoinedRecipients: Text;
    begin
        foreach Recipient in Recipients do begin
            if JoinedRecipients <> '' then
                JoinedRecipients += '; ';
            JoinedRecipients += Recipient;
        end;
        exit(JoinedRecipients);
    end;

    procedure SameAddress(FirstAddress: Text; SecondAddress: Text): Boolean
    begin
        exit(LowerCase(NormalizeAddress(FirstAddress)) = LowerCase(NormalizeAddress(SecondAddress)));
    end;

    local procedure FindCurrentUserSetupEmail(): Text
    var
        UserSetupRef: RecordRef;
    begin
        UserSetupRef.Open(Database::"User Setup");
        if not UserSetupRef.FindSet() then
            exit('');

        repeat
            if RecordMatchesCurrentUser(UserSetupRef) then
                exit(FindEmailValue(UserSetupRef));
        until UserSetupRef.Next() = 0;

        exit('');
    end;

    local procedure RecordMatchesCurrentUser(UserSetupRef: RecordRef): Boolean
    var
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
    begin
        for FieldIndex := 1 to UserSetupRef.FieldCount do begin
            CandidateField := UserSetupRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if StrPos(FieldIdentity, 'user id') > 0 then
                exit(LowerCase(Format(CandidateField.Value)) = LowerCase(UserId()));
        end;
        exit(false);
    end;

    local procedure FindEmailValue(UserSetupRef: RecordRef): Text
    var
        CandidateField: FieldRef;
        FieldIndex: Integer;
        FieldIdentity: Text;
        CandidateValue: Text;
    begin
        for FieldIndex := 1 to UserSetupRef.FieldCount do begin
            CandidateField := UserSetupRef.FieldIndex(FieldIndex);
            FieldIdentity := LowerCase(CandidateField.Name + ' ' + CandidateField.Caption);
            if (StrPos(FieldIdentity, 'email') > 0) or (StrPos(FieldIdentity, 'e-mail') > 0) then begin
                CandidateValue := NormalizeAddress(Format(CandidateField.Value));
                if LooksLikeEmail(CandidateValue) then
                    exit(CandidateValue);
            end;
        end;
        exit('');
    end;

    local procedure NormalizeAddress(Address: Text): Text
    begin
        exit(DelChr(Address, '<>', ' '));
    end;

    local procedure LooksLikeEmail(Address: Text): Boolean
    begin
        exit((Address <> '') and (StrPos(Address, '@') > 1));
    end;
}
