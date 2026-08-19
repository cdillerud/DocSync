page 71014 "GPI Guard UAT API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingQuoteUAT';
    APIVersion = 'v1.0';
    Caption = 'pricingGuardrailsUAT';
    EntityName = 'pricingGuardrailUAT';
    EntitySetName = 'pricingGuardrailsUAT';
    SourceTable = "GPI Pricing Guard";
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
                field(entryNo; Rec."Entry No.")
                {
                    Caption = 'Entry No.';
                    Editable = false;
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

    trigger OnOpenPage()
    begin
        EnsureSandbox();
    end;

    trigger OnInsertRecord(BelowxRec: Boolean): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    trigger OnModifyRecord(): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    trigger OnDeleteRecord(): Boolean
    begin
        EnsureSandbox();
        exit(true);
    end;

    local procedure EnsureSandbox()
    var
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        if not EnvironmentInformation.IsSandbox() then
            Error('The pricingGuardrailsUAT API is available only in a Business Central sandbox environment.');
    end;
}
