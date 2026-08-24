codeunit 71105 "GPI Spiro Link Mgt"
{
    procedure SelectOpportunity(var Quote: Record "GPI Pack Quote")
    var
        Opportunity: Record "GPI Spiro Opp Cache";
        OpportunityPage: Page "GPI Spiro Opp Lookup";
    begin
        Quote.TestField("Customer No.");
        Quote.CalcFields("GPI Spiro Company ID", "GPI Spiro Company Name");

        if Quote."GPI Spiro Company ID" = '' then
            Error(
                'Customer %1 is not mapped to a Spiro company. Create or refresh the Spiro customer mapping first.',
                Quote."Customer No.");

        Opportunity.SetRange("Spiro Company ID", Quote."GPI Spiro Company ID");
        if Opportunity.IsEmpty() then
            Error(
                'No cached Spiro opportunities are available for %1 [%2]. Refresh the Spiro opportunity cache and try again.',
                Quote."GPI Spiro Company Name",
                Quote."GPI Spiro Company ID");

        OpportunityPage.SetTableView(Opportunity);
        OpportunityPage.LookupMode(true);
        if OpportunityPage.RunModal() <> Action::LookupOK then
            exit;

        OpportunityPage.GetRecord(Opportunity);
        LinkOpportunity(Quote, Opportunity);
    end;

    procedure RefreshLinkedOpportunity(var Quote: Record "GPI Pack Quote")
    var
        Opportunity: Record "GPI Spiro Opp Cache";
    begin
        Quote.TestField("Customer No.");
        Quote.TestField("GPI Spiro Opportunity ID");
        Quote.CalcFields("GPI Spiro Company ID", "GPI Spiro Company Name");

        if Quote."GPI Spiro Company ID" = '' then
            Error('The quote customer is not mapped to a Spiro company.');

        if not Opportunity.Get(Quote."GPI Spiro Opportunity ID") then
            Error(
                'Linked Spiro opportunity %1 is not present in the local opportunity cache. Refresh the Spiro opportunity cache first.',
                Quote."GPI Spiro Opportunity ID");

        if Opportunity."Spiro Company ID" <> Quote."GPI Spiro Company ID" then
            Error(
                'Linked Spiro opportunity %1 belongs to company %2, but this quote customer is currently mapped to company %3. Re-select or unlink the opportunity before continuing.',
                Opportunity."Spiro Opportunity ID",
                Opportunity."Spiro Company ID",
                Quote."GPI Spiro Company ID");

        ApplyOpportunitySnapshot(Quote, Opportunity, false);
    end;

    procedure UnlinkOpportunity(var Quote: Record "GPI Pack Quote")
    var
        ExistingName: Text[100];
        ExistingId: Text[100];
    begin
        Quote.TestField("GPI Spiro Opportunity ID");

        ExistingName := Quote."GPI Spiro Opp. Name";
        ExistingId := Quote."GPI Spiro Opportunity ID";

        if not Confirm(
            'Remove the Spiro opportunity link from this packaging quote? Current link: %1 [%2].',
            false,
            ExistingName,
            ExistingId)
        then
            exit;

        Clear(Quote."GPI Spiro Opportunity ID");
        Clear(Quote."GPI Spiro Opp. Name");
        Clear(Quote."GPI Spiro Contact ID");
        Clear(Quote."GPI Spiro Contact Name");
        Clear(Quote."GPI Spiro Stage");
        Clear(Quote."GPI Spiro Owner");
        Clear(Quote."GPI Spiro Assigned ISR");
        Clear(Quote."GPI Spiro Probability");
        Clear(Quote."GPI Spiro Est. Annual Volume");
        Clear(Quote."GPI Spiro Close Date");
        Clear(Quote."GPI Spiro Rating");
        Clear(Quote."GPI Spiro Opp. URL");
        Clear(Quote."GPI Spiro Synced At");
        Clear(Quote."GPI Spiro Synced By");
        Quote.Modify(true);
    end;

    procedure LinkOpportunity(var Quote: Record "GPI Pack Quote"; Opportunity: Record "GPI Spiro Opp Cache")
    var
        ChangingOpportunity: Boolean;
    begin
        Quote.TestField("Customer No.");
        Quote.CalcFields("GPI Spiro Company ID", "GPI Spiro Company Name");

        if Quote."GPI Spiro Company ID" = '' then
            Error('The quote customer is not mapped to a Spiro company.');

        if Opportunity."Spiro Company ID" <> Quote."GPI Spiro Company ID" then
            Error(
                'Spiro opportunity %1 belongs to company %2, but this quote customer is mapped to company %3.',
                Opportunity."Spiro Opportunity ID",
                Opportunity."Spiro Company ID",
                Quote."GPI Spiro Company ID");

        ChangingOpportunity :=
            (Quote."GPI Spiro Opportunity ID" <> '') and
            (Quote."GPI Spiro Opportunity ID" <> Opportunity."Spiro Opportunity ID");

        if ChangingOpportunity then
            if not Confirm(
                'This quote is currently linked to %1 [%2]. Replace that link with %3 [%4]?',
                false,
                Quote."GPI Spiro Opp. Name",
                Quote."GPI Spiro Opportunity ID",
                Opportunity."Opportunity Name",
                Opportunity."Spiro Opportunity ID")
            then
                exit;

        ApplyOpportunitySnapshot(Quote, Opportunity, ChangingOpportunity);
    end;

    local procedure ApplyOpportunitySnapshot(var Quote: Record "GPI Pack Quote"; Opportunity: Record "GPI Spiro Opp Cache"; ClearContact: Boolean)
    begin
        Quote."GPI Spiro Opportunity ID" := Opportunity."Spiro Opportunity ID";
        Quote."GPI Spiro Opp. Name" := Opportunity."Opportunity Name";
        Quote."GPI Spiro Stage" := Opportunity.Stage;
        Quote."GPI Spiro Owner" := Opportunity.Owner;
        Quote."GPI Spiro Assigned ISR" := Opportunity."Assigned ISR";
        Quote."GPI Spiro Probability" := Opportunity.Probability;
        Quote."GPI Spiro Est. Annual Volume" := Opportunity."Estimated Annual Volume";
        Quote."GPI Spiro Close Date" := Opportunity."Close Date";
        Quote."GPI Spiro Rating" := Opportunity.Rating;
        Quote."GPI Spiro Opp. URL" := Opportunity."Browser URL";

        if ClearContact then begin
            Clear(Quote."GPI Spiro Contact ID");
            Clear(Quote."GPI Spiro Contact Name");
        end;

        Quote."GPI Spiro Synced At" := CurrentDateTime();
        Quote."GPI Spiro Synced By" := CopyStr(UserId(), 1, MaxStrLen(Quote."GPI Spiro Synced By"));
        Quote.Modify(true);
    end;
}
