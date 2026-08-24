page 71109 "GPI Spiro Push Q API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'spiroIntegration';
    APIVersion = 'v1.0';
    Caption = 'spiroPushRequests';
    EntityName = 'spiroPushRequest';
    EntitySetName = 'spiroPushRequests';
    SourceTable = "GPI Spiro Push Queue";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = true;
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
                    Caption = 'Entry No.';
                    Editable = false;
                }
                field(quoteNo; Rec."Quote No.")
                {
                    Caption = 'Quote No.';
                    Editable = false;
                }
                field(spiroOpportunityId; Rec."Spiro Opportunity ID")
                {
                    Caption = 'Spiro Opportunity ID';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                }
                field(requestedAt; Rec."Requested At")
                {
                    Caption = 'Requested At';
                    Editable = false;
                }
                field(requestedBy; Rec."Requested By")
                {
                    Caption = 'Requested By';
                    Editable = false;
                }
                field(processedAt; Rec."Processed At")
                {
                    Caption = 'Processed At';
                }
                field(message; Rec.Message)
                {
                    Caption = 'Message';
                }                field(attemptCount; Rec."Attempt Count")
                {
                    Caption = 'Attempt Count';
                }
                field(lastAttemptAt; Rec."Last Attempt At")
                {
                    Caption = 'Last Attempt At';
                }
                field(nextAttemptAt; Rec."Next Attempt At")
                {
                    Caption = 'Next Attempt At';
                }
                field(lastError; Rec."Last Error")
                {
                    Caption = 'Last Error';
                }
                field(workerId; Rec."Worker ID")
                {
                    Caption = 'Worker ID';
                }
            }
        }
    }
}