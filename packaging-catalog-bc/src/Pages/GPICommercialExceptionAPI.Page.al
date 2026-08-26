page 71123 "GPI Comm Ex API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'commercialExceptions';
    EntityName = 'commercialException';
    EntitySetName = 'commercialExceptions';
    SourceTable = "GPI Comm Exception";
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
                field(assignedTo; Rec."Assigned To") { Caption = 'Assigned To'; }
                field(summary; Rec.Summary) { Caption = 'Summary'; }
                field(finding; Rec.Finding) { Caption = 'Finding'; }
                field(recommendedAction; Rec."Recommended Action") { Caption = 'Recommended Action'; }
                field(decisionNote; Rec."Decision Note") { Caption = 'Decision Note'; }
                field(aiModel; Rec."AI Model") { Caption = 'AI Model'; }
                field(evaluationVersion; Rec."Evaluation Version") { Caption = 'Evaluation Version'; }
                field(correlationId; Rec."Correlation ID") { Caption = 'Correlation ID'; }
                field(createdAt; Rec."Created At") { Caption = 'Created At'; }
                field(updatedAt; Rec."Updated At") { Caption = 'Updated At'; }
                field(reviewedBy; Rec."Reviewed By") { Caption = 'Reviewed By'; }
                field(reviewedAt; Rec."Reviewed At") { Caption = 'Reviewed At'; }
                field(disposition; Rec.Disposition) { Caption = 'Disposition'; }
                field(falsePositive; Rec."False Positive") { Caption = 'False Positive'; }
                field(queueEntryNo; Rec."Queue Entry No.") { Caption = 'Queue Entry No.'; }
            }
        }
    }
}
