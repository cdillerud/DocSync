page 71129 "GPI Agent Queue API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgentWrite';
    APIVersion = 'v1.0';
    Caption = 'commercialAgentQueueWrite';
    EntityName = 'commercialAgentQueueWrite';
    EntitySetName = 'commercialAgentQueueWrites';
    SourceTable = "GPI Comm Agent Queue";
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
                field(id; Rec.SystemId) { Caption = 'Id'; Editable = false; }
                field(entryNo; Rec."Entry No.") { Caption = 'Entry No.'; Editable = false; }
                field(status; Rec.Status) { Caption = 'Status'; }
                field(startedAt; Rec."Started At") { Caption = 'Started At'; }
                field(completedAt; Rec."Completed At") { Caption = 'Completed At'; }
                field(attemptCount; Rec."Attempt Count") { Caption = 'Attempt Count'; }
                field(nextAttemptAt; Rec."Next Attempt At") { Caption = 'Next Attempt At'; }
                field(exceptionEntryNo; Rec."Exception Entry No.") { Caption = 'Exception Entry No.'; }
                field(lastError; Rec."Last Error") { Caption = 'Last Error'; }
                field(correlationId; Rec."Correlation ID") { Caption = 'Correlation ID'; Editable = false; }
            }
        }
    }
}
