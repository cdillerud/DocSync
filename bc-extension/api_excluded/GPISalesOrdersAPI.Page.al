page 50112 "GPI Sales Orders API"
{
    Caption = 'GPI Sales Orders API';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'integration';
    APIVersion = 'v1.0';
    EntitySetName = 'salesOrderRequests';
    EntityName = 'salesOrderRequest';
    SourceTable = "GPI Sales Order Request";
    DelayedInsert = true;
    ODataKeyFields = SystemId;

    layout
    {
        area(Content)
        {
            repeater(Requests)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                    Editable = false;
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
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                }
                field(externalDocumentNo; Rec."External Document No.")
                {
                    Caption = 'External Document No.';
                }
                field(orderDate; Rec."Order Date")
                {
                    Caption = 'Order Date';
                }
                field(resultRecordNo; Rec."Result Record No.")
                {
                    Caption = 'Result Record No.';
                    Editable = false;
                }
                field(resultSystemId; Rec."Result System ID")
                {
                    Caption = 'Result System ID';
                    Editable = false;
                }
                field(resultStatus; Rec."Result Status")
                {
                    Caption = 'Result Status';
                    Editable = false;
                }
                field(resultSuccess; Rec."Result Success")
                {
                    Caption = 'Result Success';
                    Editable = false;
                }
                field(errorMessage; Rec."Error Message")
                {
                    Caption = 'Error Message';
                    Editable = false;
                }
                field(createdDateTime; Rec."Created DateTime")
                {
                    Caption = 'Created DateTime';
                    Editable = false;
                }
            }
        }
    }

    trigger OnInsertRecord(BelowxRec: Boolean): Boolean
    var
        SalesOrderMgt: Codeunit "GPI Sales Order Mgt";
        ResultRecordNo: Code[20];
        ResultSystemID: Guid;
        ResultStatus: Text[50];
        ResultSuccess: Boolean;
        ResultErrorMsg: Text[2048];
    begin
        SalesOrderMgt.CreateSalesOrder(
            Rec."Idempotency Key",
            Rec."Source System",
            Rec."Source Document ID",
            Rec."Transaction ID",
            Rec."Customer No.",
            Rec."External Document No.",
            Rec."Order Date",
            ResultRecordNo,
            ResultSystemID,
            ResultStatus,
            ResultSuccess,
            ResultErrorMsg
        );

        Rec."Result Record No." := ResultRecordNo;
        Rec."Result System ID" := ResultSystemID;
        Rec."Result Status" := ResultStatus;
        Rec."Result Success" := ResultSuccess;
        Rec."Error Message" := ResultErrorMsg;

        Rec.Insert(true);
        exit(false); // We already inserted
    end;
}
