page 71127 "GPI Agent Ex API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgentWrite';
    APIVersion = 'v1.0';
    Caption = 'commercialAgentExceptionWrite';
    EntityName = 'commercialAgentExceptionWrite';
    EntitySetName = 'commercialAgentExceptionWrites';
    SourceTable = "GPI Comm Exception";
    ODataKeyFields = SystemId;
    InsertAllowed = true;
    ModifyAllowed = false;
    DeleteAllowed = false;
    DelayedInsert = true;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Caption = 'Id'; Editable = false; }
                field(entryNo; Rec."Entry No.") { Caption = 'Entry No.'; Editable = false; }
                field(agentType; Rec."Agent Type") { Caption = 'Agent Type'; }
                field(detectedAt; Rec."Detected At") { Caption = 'Detected At'; }
                field(sourceType; Rec."Source Type") { Caption = 'Source Type'; }
                field(sourceSystemId; Rec."Source SystemId") { Caption = 'Source SystemId'; }
                field(sourceKey; Rec."Source Key") { Caption = 'Source Key'; }
                field(customerNo; Rec."Customer No.") { Caption = 'Customer No.'; }
                field(itemNo; Rec."Item No.") { Caption = 'Item No.'; }
                field(documentType; Rec."Document Type") { Caption = 'Document Type'; }
                field(documentNo; Rec."Document No.") { Caption = 'Document No.'; }
                field(severity; Rec.Severity) { Caption = 'Severity'; }
                field(riskScore; Rec."Risk Score") { Caption = 'Risk Score'; }
                field(confidenceScore; Rec."Confidence Score") { Caption = 'Confidence Score'; }
                field(status; Rec.Status) { Caption = 'Status'; }
                field(summary; Rec.Summary) { Caption = 'Summary'; }
                field(finding; Rec.Finding) { Caption = 'Finding'; }
                field(recommendedAction; Rec."Recommended Action") { Caption = 'Recommended Action'; }
                field(aiModel; Rec."AI Model") { Caption = 'AI Model'; }
                field(evaluationVersion; Rec."Evaluation Version") { Caption = 'Evaluation Version'; }
                field(correlationId; Rec."Correlation ID") { Caption = 'Correlation ID'; }
                field(queueEntryNo; Rec."Queue Entry No.") { Caption = 'Queue Entry No.'; }
                field(createdAt; Rec."Created At") { Caption = 'Created At'; }
                field(updatedAt; Rec."Updated At") { Caption = 'Updated At'; }
            }
        }
    }
}
