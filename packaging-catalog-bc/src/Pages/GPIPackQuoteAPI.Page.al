page 71012 "GPI Pack Quote API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingQuotes';
    APIVersion = 'v1.0';
    Caption = 'packagingQuotes';
    EntityName = 'packagingQuote';
    EntitySetName = 'packagingQuotes';
    SourceTable = "GPI Pack Quote";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = true;
    DeleteAllowed = true;
    DelayedInsert = true;
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
                field(quoteDate; Rec."Quote Date")
                {
                    Caption = 'Quote Date';
                }
                field(expirationDate; Rec."Expiration Date")
                {
                    Caption = 'Expiration Date';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'Customer Name';
                    Editable = false;
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                    Editable = false;
                }
                field(lineCount; Rec."Line Count")
                {
                    Caption = 'Line Count';
                    Editable = false;
                }
                field(approvalLineCount; Rec."Approval Line Count")
                {
                    Caption = 'Lines Requiring Approval';
                    Editable = false;
                }
                field(lastEvaluatedAt; Rec."Last Evaluated At")
                {
                    Caption = 'Last Evaluated At';
                    Editable = false;
                }
                field(lastEvaluatedBy; Rec."Last Evaluated By")
                {
                    Caption = 'Last Evaluated By';
                    Editable = false;
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'Notes';
                }
                field(decisionNote; Rec."Decision Note")
                {
                    Caption = 'Approval / Rejection Note';
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
                field(auditCount; Rec."Audit Count")
                {
                    Caption = 'Audit Entries';
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
                field(spiroContactId; Rec."GPI Spiro Contact ID")
                {
                    Caption = 'Spiro Contact ID';
                    Editable = false;
                }
                field(spiroContactName; Rec."GPI Spiro Contact Name")
                {
                    Caption = 'Spiro Contact Name';
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
                field(spiroProbability; Rec."GPI Spiro Probability")
                {
                    Caption = 'Spiro Probability';
                    Editable = false;
                }
                field(spiroEstimatedAnnualVolume; Rec."GPI Spiro Est. Annual Volume")
                {
                    Caption = 'Spiro Estimated Annual Volume';
                    Editable = false;
                }
                field(spiroCloseDate; Rec."GPI Spiro Close Date")
                {
                    Caption = 'Spiro Close Date';
                    Editable = false;
                }
                field(spiroRating; Rec."GPI Spiro Rating")
                {
                    Caption = 'Spiro Rating';
                    Editable = false;
                }
                field(spiroOpportunityUrl; Rec."GPI Spiro Opp. URL")
                {
                    Caption = 'Spiro Opportunity URL';
                    Editable = false;
                }
                field(spiroLastSyncedAt; Rec."GPI Spiro Synced At")
                {
                    Caption = 'Spiro Last Synced At';
                    Editable = false;
                }
                field(spiroPushStatus; Rec."GPI Spiro Push Status")
                {
                    Caption = 'Spiro Push Status';
                    Editable = false;
                }
                field(spiroLastPushedAt; Rec."GPI Spiro Last Pushed At")
                {
                    Caption = 'Spiro Last Pushed At';
                    Editable = false;
                }
                field(spiroPushMessage; Rec."GPI Spiro Push Message")
                {
                    Caption = 'Spiro Push Message';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    procedure evaluate(var ActionContext: WebServiceActionContext)
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
    begin
        QuoteMgt.EvaluateQuote(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure readyForReview(var ActionContext: WebServiceActionContext)
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
    begin
        QuoteMgt.SetReadyForReview(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure approve(var ActionContext: WebServiceActionContext)
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
    begin
        QuoteMgt.ApproveQuote(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure reject(var ActionContext: WebServiceActionContext)
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
    begin
        QuoteMgt.RejectQuote(Rec);
        SetActionResponse(ActionContext);
    end;

    [ServiceEnabled]
    procedure reopen(var ActionContext: WebServiceActionContext)
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
    begin
        QuoteMgt.ReopenQuote(Rec);
        SetActionResponse(ActionContext);
    end;

    local procedure SetActionResponse(var ActionContext: WebServiceActionContext)
    begin
        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"GPI Pack Quote API");
        ActionContext.AddEntityKey(Rec.FieldNo(SystemId), Rec.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Updated);
    end;
}
