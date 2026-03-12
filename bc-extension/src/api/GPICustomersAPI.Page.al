page 50114 "GPI Customers API"
{
    Caption = 'GPI Customers API';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'integration';
    APIVersion = 'v1.0';
    EntitySetName = 'customerRequests';
    EntityName = 'customerRequest';
    SourceTable = "GPI Customer Request";
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
                field(name; Rec."Name")
                {
                    Caption = 'Name';
                }
                field(address; Rec."Address")
                {
                    Caption = 'Address';
                }
                field(city; Rec."City")
                {
                    Caption = 'City';
                }
                field(stateCode; Rec."State Code")
                {
                    Caption = 'State Code';
                }
                field(postalCode; Rec."Postal Code")
                {
                    Caption = 'Postal Code';
                }
                field(countryCode; Rec."Country Code")
                {
                    Caption = 'Country Code';
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
        CustomerMgt: Codeunit "GPI Customer Mgt";
        ResultRecordNo: Code[20];
        ResultSystemID: Guid;
        ResultStatus: Text[50];
        ResultSuccess: Boolean;
        ResultErrorMsg: Text[2048];
    begin
        CustomerMgt.CreateCustomer(
            Rec."Idempotency Key",
            Rec."Source System",
            Rec."Source Document ID",
            Rec."Name",
            Rec."Address",
            Rec."City",
            Rec."State Code",
            Rec."Postal Code",
            Rec."Country Code",
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
        exit(false);
    end;
}
