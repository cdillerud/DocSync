page 50116 "GPI Integration Log API"
{
    Caption = 'GPI Integration Log API';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'integration';
    APIVersion = 'v1.0';
    EntitySetName = 'integrationLogs';
    EntityName = 'integrationLog';
    SourceTable = "GPI Integration Log";
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    ODataKeyFields = SystemId;

    layout
    {
        area(Content)
        {
            repeater(Logs)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                }
                field(idempotencyKey; Rec."Idempotency Key")
                {
                    Caption = 'Idempotency Key';
                }
                field(sourceSystem; Rec."Source System")
                {
                    Caption = 'Source System';
                }
                field(sourceDocumentId; Rec."Source Document ID")
                {
                    Caption = 'Source Document ID';
                }
                field(transactionId; Rec."Transaction ID")
                {
                    Caption = 'Transaction ID';
                }
                field(recordType; Rec."Record Type")
                {
                    Caption = 'Record Type';
                }
                field(requestStatus; Rec."Request Status")
                {
                    Caption = 'Request Status';
                }
                field(success; Rec.Success)
                {
                    Caption = 'Success';
                }
                field(bcRecordNo; Rec."BC Record No.")
                {
                    Caption = 'BC Record No.';
                }
                field(bcSystemId; Rec."BC System ID")
                {
                    Caption = 'BC System ID';
                }
                field(idempotencyStatus; Rec."Idempotency Status")
                {
                    Caption = 'Idempotency Status';
                }
                field(errorMessage; Rec."Error Message")
                {
                    Caption = 'Error Message';
                }
                field(createdDateTime; Rec."Created DateTime")
                {
                    Caption = 'Created DateTime';
                }
                field(createdByIntegration; Rec."Created By Integration")
                {
                    Caption = 'Created By Integration';
                }
                field(processingDurationMs; Rec."Processing Duration MS")
                {
                    Caption = 'Processing Duration (ms)';
                }
            }
        }
    }
}
