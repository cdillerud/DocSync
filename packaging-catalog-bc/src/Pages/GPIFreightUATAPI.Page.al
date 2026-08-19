page 71023 "GPI Freight UAT API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingCompareUAT';
    APIVersion = 'v1.0';
    Caption = 'freightRatesUAT';
    EntityName = 'freightRateUAT';
    EntitySetName = 'freightRatesUAT';
    SourceTable = "GPI Pack Frt Rate";
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
                field(originVendorNo; Rec."Origin Vendor No.")
                {
                    Caption = 'Origin Vendor No.';
                }
                field(originLocationCode; Rec."Origin Location Code")
                {
                    Caption = 'Origin Location Code';
                }
                field(destinationState; Rec."Destination State")
                {
                    Caption = 'Destination State';
                }
                field(defaultDestination; Rec."Default Destination")
                {
                    Caption = 'Default Destination';
                }
                field(mode; Rec.Mode)
                {
                    Caption = 'Mode';
                }
                field(ratePerCwt; Rec."Rate per CWT")
                {
                    Caption = 'Rate per CWT';
                }
                field(minimumCharge; Rec."Minimum Charge")
                {
                    Caption = 'Minimum Charge';
                }
                field(fuelSurchargePct; Rec."Fuel Surcharge %")
                {
                    Caption = 'Fuel Surcharge %';
                }
                field(effectiveDate; Rec."Effective Date")
                {
                    Caption = 'Effective Date';
                }
                field(notes; Rec.Notes)
                {
                    Caption = 'Notes';
                }
                field(blocked; Rec.Blocked)
                {
                    Caption = 'Blocked';
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
            Error('The freightRatesUAT API is available only in a Business Central sandbox environment.');
    end;
}
