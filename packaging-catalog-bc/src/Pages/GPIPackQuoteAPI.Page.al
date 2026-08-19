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
