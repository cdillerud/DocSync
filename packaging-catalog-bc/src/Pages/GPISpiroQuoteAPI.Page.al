page 71106 "GPI Spiro Quote API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'spiroIntegration';
    APIVersion = 'v1.0';
    Caption = 'spiroQuoteLinks';
    EntityName = 'spiroQuoteLink';
    EntitySetName = 'spiroQuoteLinks';
    SourceTable = "GPI Pack Quote";
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
                field(quoteNo; Rec."Entry No.")
                {
                    Caption = 'Quote No.';
                    Editable = false;
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                    Editable = false;
                }
                field(customerName; Rec."Customer Name")
                {
                    Caption = 'Customer Name';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Quote Status';
                    Editable = false;
                }
                field(spiroCompanyId; Rec."GPI Spiro Company ID")
                {
                    Caption = 'Spiro Company ID';
                    Editable = false;
                }
                field(spiroCompanyName; Rec."GPI Spiro Company Name")
                {
                    Caption = 'Spiro Company Name';
                    Editable = false;
                }
                field(spiroOpportunityId; Rec."GPI Spiro Opportunity ID")
                {
                    Caption = 'Spiro Opportunity ID';
                }
                field(spiroOpportunityName; Rec."GPI Spiro Opp. Name")
                {
                    Caption = 'Spiro Opportunity Name';
                }
                field(spiroContactId; Rec."GPI Spiro Contact ID")
                {
                    Caption = 'Spiro Contact ID';
                }
                field(spiroContactName; Rec."GPI Spiro Contact Name")
                {
                    Caption = 'Spiro Contact Name';
                }
                field(spiroStage; Rec."GPI Spiro Stage")
                {
                    Caption = 'Spiro Stage';
                }
                field(spiroOwner; Rec."GPI Spiro Owner")
                {
                    Caption = 'Spiro Owner';
                }
                field(spiroOpportunityUrl; Rec."GPI Spiro Opp. URL")
                {
                    Caption = 'Spiro Opportunity URL';
                }
                field(spiroLastSyncedAt; Rec."GPI Spiro Synced At")
                {
                    Caption = 'Spiro Last Synced At';
                }
                field(spiroLastSyncedBy; Rec."GPI Spiro Synced By")
                {
                    Caption = 'Spiro Last Synced By';
                }
            }
        }
    }
}
