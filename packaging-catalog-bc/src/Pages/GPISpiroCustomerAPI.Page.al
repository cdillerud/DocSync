page 71105 "GPI Spiro Cust API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'spiroIntegration';
    APIVersion = 'v1.0';
    Caption = 'spiroCustomerMaps';
    EntityName = 'spiroCustomerMap';
    EntitySetName = 'spiroCustomerMaps';
    SourceTable = "GPI Spiro Cust Map";
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
                field(bcCustomerNo; Rec."BC Customer No.")
                {
                    Caption = 'BC Customer No.';
                }
                field(bcCustomerSystemId; Rec."BC Customer SystemId")
                {
                    Caption = 'BC Customer SystemId';
                    Editable = false;
                }
                field(bcCustomerName; Rec."BC Customer Name")
                {
                    Caption = 'BC Customer Name';
                    Editable = false;
                }
                field(spiroCompanyId; Rec."Spiro Company ID")
                {
                    Caption = 'Spiro Company ID';
                }
                field(spiroCompanyName; Rec."Spiro Company Name")
                {
                    Caption = 'Spiro Company Name';
                }
                field(spiroCompanyUrl; Rec."Spiro Company URL")
                {
                    Caption = 'Spiro Company URL';
                }
                field(lastSyncedAt; Rec."Last Synced At")
                {
                    Caption = 'Last Synced At';
                    Editable = false;
                }
                field(lastSyncedBy; Rec."Last Synced By")
                {
                    Caption = 'Last Synced By';
                    Editable = false;
                }
            }
        }
    }
}
