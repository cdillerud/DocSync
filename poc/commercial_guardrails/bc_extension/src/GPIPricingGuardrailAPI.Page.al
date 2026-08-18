page 70695 "GPI Pricing Guardrail API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialGuardrails';
    APIVersion = 'v1.0';
    Caption = 'pricingGuardrails';
    EntityName = 'pricingGuardrail';
    EntitySetName = 'pricingGuardrails';
    SourceTable = "GPI Pricing Guardrail";
    SourceTableView = where(Enabled = const(true));
    ODataKeyFields = SystemId;
    InsertAllowed = false;
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
                field(id; Rec.SystemId)
                {
                    Caption = 'Id';
                }
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                }
                field(enabled; Rec.Enabled)
                {
                    Caption = 'Enabled';
                }
                field(customerNo; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                }
                field(itemNo; Rec."Item No.")
                {
                    Caption = 'Item No.';
                }
                field(ruleType; Rec."Rule Type")
                {
                    Caption = 'Rule Type';
                }
                field(lockedSellPrice; Rec."Locked Sell Price")
                {
                    Caption = 'Locked Sell Price';
                }
                field(effectiveFrom; Rec."Effective From")
                {
                    Caption = 'Effective From';
                }
                field(effectiveTo; Rec."Effective To")
                {
                    Caption = 'Effective To';
                }
                field(approver; Rec.Approver)
                {
                    Caption = 'Approver';
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'Notes';
                }
            }
        }
    }
}
