page 71125 "GPI Comm Queue API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'commercialAgentQueue';
    EntityName = 'commercialAgentQueueEntry';
    EntitySetName = 'commercialAgentQueueEntries';
    SourceTable = "GPI Comm Agent Queue";
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
                field(id; Rec.SystemId) { Caption = 'Id'; }
                field(entryNo; Rec."Entry No.") { Caption = 'Entry No.'; }
                field(agentType; Rec."Agent Type") { Caption = 'Agent Type'; }
                field(sourceType; Rec."Source Type") { Caption = 'Source Type'; }
                field(sourceSystemId; Rec."Source SystemId") { Caption = 'Source SystemId'; }
                field(sourceKey; Rec."Source Key") { Caption = 'Source Key'; }
                field(customerNo; Rec."Customer No.") { Caption = 'Customer No.'; }
                field(itemNo; Rec."Item No.") { Caption = 'Item No.'; }
                field(documentType; Rec."Document Type") { Caption = 'Document Type'; }
                field(documentNo; Rec."Document No.") { Caption = 'Document No.'; }
                field(status; Rec.Status) { Caption = 'Status'; }
                field(priority; Rec.Priority) { Caption = 'Priority'; }
                field(requestedAt; Rec."Requested At") { Caption = 'Requested At'; }
                field(startedAt; Rec."Started At") { Caption = 'Started At'; }
                field(completedAt; Rec."Completed At") { Caption = 'Completed At'; }
                field(attemptCount; Rec."Attempt Count") { Caption = 'Attempt Count'; }
                field(maxAttempts; Rec."Max Attempts") { Caption = 'Max Attempts'; }
                field(nextAttemptAt; Rec."Next Attempt At") { Caption = 'Next Attempt At'; }
                field(exceptionEntryNo; Rec."Exception Entry No.") { Caption = 'Exception Entry No.'; }
                field(lastError; Rec."Last Error") { Caption = 'Last Error'; }
                field(correlationId; Rec."Correlation ID") { Caption = 'Correlation ID'; }
                field(idempotencyKey; Rec."Idempotency Key") { Caption = 'Idempotency Key'; }
                field(requestedBy; Rec."Requested By") { Caption = 'Requested By'; }
                field(previousValue; Rec."Previous Value") { Caption = 'Previous Value'; }
                field(currentValue; Rec."Current Value") { Caption = 'Current Value'; }
            }
        }
    }
}
