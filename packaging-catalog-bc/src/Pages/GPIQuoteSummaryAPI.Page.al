page 71032 "GPI Quote Sum API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingQuotes';
    APIVersion = 'v1.0';
    Caption = 'packagingQuoteSummaries';
    EntityName = 'packagingQuoteSummary';
    EntitySetName = 'packagingQuoteSummaries';
    SourceTable = "GPI Pack Quote";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Quote No.';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                    Editable = false;
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                    Editable = false;
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'Customer Name';
                    Editable = false;
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                    Editable = false;
                }
                field(lineCount; Rec."Line Count")
                {
                    Caption = 'Line Count';
                    Editable = false;
                }
                field(approvalLineCount; Rec."Approval Line Count")
                {
                    Caption = 'Pricing Exception Line Count';
                    Editable = false;
                }
                field(totalLandedCost; Rec."Total Landed Cost")
                {
                    Caption = 'Total Landed Cost';
                    Editable = false;
                }
                field(totalSell; Rec."Total Sell")
                {
                    Caption = 'Total Proposed Sell';
                    Editable = false;
                }
                field(grossProfitTotal; Rec."Gross Profit Total")
                {
                    Caption = 'Gross Profit Total';
                    Editable = false;
                }
                field(grossMarginPct; GrossMarginPct)
                {
                    Caption = 'Overall Gross Margin %';
                    Editable = false;
                }
                field(hasPricingExceptions; HasPricingExceptions)
                {
                    Caption = 'Has Pricing Exceptions';
                    Editable = false;
                }
                field(decisionNoteRequired; DecisionNoteRequired)
                {
                    Caption = 'Decision Note Required';
                    Editable = false;
                }
                field(primaryPricingExceptionStatus; PrimaryExceptionStatus)
                {
                    Caption = 'Primary Pricing Exception Status';
                    Editable = false;
                }
                field(primaryPricingExceptionMessage; PrimaryExceptionMessage)
                {
                    Caption = 'Primary Pricing Exception Message';
                    Editable = false;
                }
                field(primaryApprover; PrimaryApprover)
                {
                    Caption = 'Primary Approver';
                    Editable = false;
                }
                field(decisionNote; Rec."Decision Note")
                {
                    Caption = 'Decision Note';
                    Editable = false;
                }
                field(decisionAt; Rec."Decision At")
                {
                    Caption = 'Decision At';
                    Editable = false;
                }
                field(decisionBy; Rec."Decision By")
                {
                    Caption = 'Decision By';
                    Editable = false;
                }
                field(lastEvaluatedAt; Rec."Last Evaluated At")
                {
                    Caption = 'Last Evaluated At';
                    Editable = false;
                }
                field(readyForCustomerPresentation; ReadyForCustomerPresentation)
                {
                    Caption = 'Ready for Customer Presentation';
                    Editable = false;
                }
                field(customerEmailReady; CustomerEmailReady)
                {
                    Caption = 'Customer Email Ready';
                    Editable = false;
                }
                field(spiroCompanyId; Rec."GPI Spiro Company ID")
                {
                    Caption = 'Spiro Company ID';
                    Editable = false;
                }
                field(spiroCompanyName; Rec."GPI Spiro Company Name")
                {
                    Caption = 'Spiro Company Name';
                    Editable = false;
                }
                field(spiroOpportunityId; Rec."GPI Spiro Opportunity ID")
                {
                    Caption = 'Spiro Opportunity ID';
                    Editable = false;
                }
                field(spiroOpportunityName; Rec."GPI Spiro Opp. Name")
                {
                    Caption = 'Spiro Opportunity Name';
                    Editable = false;
                }
                field(spiroStage; Rec."GPI Spiro Stage")
                {
                    Caption = 'Spiro Stage';
                    Editable = false;
                }
                field(spiroOwner; Rec."GPI Spiro Owner")
                {
                    Caption = 'Spiro Owner';
                    Editable = false;
                }
                field(spiroAssignedIsr; Rec."GPI Spiro Assigned ISR")
                {
                    Caption = 'Spiro Assigned ISR';
                    Editable = false;
                }
                field(spiroPushStatus; Rec."GPI Spiro Push Status")
                {
                    Caption = 'Spiro Push Status';
                    Editable = false;
                }
                field(recommendedNextAction; RecommendedNextAction)
                {
                    Caption = 'Recommended Next Action';
                    Editable = false;
                }
            }
        }
    }

    trigger OnAfterGetRecord()
    begin
        BuildSummary();
    end;

    var
        GrossMarginPct: Decimal;
        HasPricingExceptions: Boolean;
        DecisionNoteRequired: Boolean;
        ReadyForCustomerPresentation: Boolean;
        CustomerEmailReady: Boolean;
        PrimaryExceptionStatus: Text[100];
        PrimaryExceptionMessage: Text[250];
        PrimaryApprover: Text[100];
        RecommendedNextAction: Text[250];

    local procedure BuildSummary()
    var
        QuoteLine: Record "GPI Pack Quote Line";
        Customer: Record Customer;
    begin
        Rec.CalcFields(
            "Customer Name",
            "Line Count",
            "Approval Line Count",
            "Total Landed Cost",
            "Total Sell",
            "Gross Profit Total",
            "GPI Spiro Company ID",
            "GPI Spiro Company Name");

        GrossMarginPct := 0;
        if Rec."Total Sell" <> 0 then
            GrossMarginPct := (Rec."Gross Profit Total" / Rec."Total Sell") * 100;

        HasPricingExceptions := Rec."Approval Line Count" > 0;

        DecisionNoteRequired :=
            (Rec.Status = "GPI Pack Quote Stat"::Ready) and
            HasPricingExceptions and
            (Rec."Decision Note" = '');

        ReadyForCustomerPresentation :=
            Rec.Status = "GPI Pack Quote Stat"::Approved;

        CustomerEmailReady := false;
        if ReadyForCustomerPresentation and
           (Rec."Customer No." <> '') and
           Customer.Get(Rec."Customer No.")
        then
            CustomerEmailReady := Customer."E-Mail" <> '';

        Clear(PrimaryExceptionStatus);
        Clear(PrimaryExceptionMessage);
        Clear(PrimaryApprover);

        QuoteLine.SetRange("Quote Entry No.", Rec."Entry No.");
        QuoteLine.SetRange("Needs Approval", true);

        if QuoteLine.FindFirst() then begin
            PrimaryExceptionStatus :=
                CopyStr(Format(QuoteLine."Guardrail Status"), 1, MaxStrLen(PrimaryExceptionStatus));
            PrimaryExceptionMessage :=
                CopyStr(QuoteLine."Guardrail Message", 1, MaxStrLen(PrimaryExceptionMessage));
            PrimaryApprover :=
                CopyStr(QuoteLine."Guardrail Approver", 1, MaxStrLen(PrimaryApprover));
        end;

        RecommendedNextAction := BuildRecommendedNextAction();
    end;

    local procedure BuildRecommendedNextAction(): Text[250]
    begin
        case Rec.Status of
            "GPI Pack Quote Stat"::Draft:
                begin
                    if Rec."Line Count" = 0 then
                        exit('Add at least one quote line before evaluating the quote.');

                    exit('Evaluate the quote and move it to Ready for Review.');
                end;

            "GPI Pack Quote Stat"::Ready:
                begin
                    if DecisionNoteRequired then
                        exit('Review pricing exceptions, enter a decision note, then approve or reject the quote.');

                    if HasPricingExceptions then
                        exit('Review the documented pricing exceptions, then approve or reject the quote.');

                    exit('Quote is Ready for Review; approve or reject it.');
                end;

            "GPI Pack Quote Stat"::Approved:
                begin
                    if CustomerEmailReady then
                        exit('Quote is approved and ready to prepare the customer email.');

                    exit('Quote is approved; add a customer email address before preparing the customer email.');
                end;

            "GPI Pack Quote Stat"::Rejected:
                exit('Quote is rejected. Reopen it to Draft if changes are required.');

            "GPI Pack Quote Stat"::Expired:
                exit('Quote is expired. Reopen it to Draft before re-evaluation.');
        end;

        exit('Review the quote status before continuing.');
    end;
}
