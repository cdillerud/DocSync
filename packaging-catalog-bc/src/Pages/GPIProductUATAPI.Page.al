page 71022 "GPI Product UAT API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'packagingCompareUAT';
    APIVersion = 'v1.0';
    Caption = 'packagingProductsUAT';
    EntityName = 'packagingProductUAT';
    EntitySetName = 'packagingProductsUAT';
    SourceTable = "GPI Pack Product";
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
                field(productNo; Rec."No.")
                {
                    Caption = 'Gamer ID';
                }
                field(material; Rec.Material)
                {
                    Caption = 'Material';
                }
                field(style; Rec.Style)
                {
                    Caption = 'Style';
                }
                field(capacity; Rec.Capacity)
                {
                    Caption = 'Capacity';
                }
                field(capacityUom; Rec."Capacity UOM")
                {
                    Caption = 'Capacity UOM';
                }
                field(color; Rec.Color)
                {
                    Caption = 'Color';
                }
                field(bcItemNo; Rec."BC Item No.")
                {
                    Caption = 'BC Item No.';
                }
                field(vendorNo; Rec."Vendor No.")
                {
                    Caption = 'Vendor No.';
                }
                field(vendorLocationCode; Rec."Vendor Location Code")
                {
                    Caption = 'Vendor FOB Location';
                }
                field(transportMode; Rec."Transport Mode")
                {
                    Caption = 'Transport Mode';
                }
                field(fullLoadQuantity; Rec."Full Load Quantity")
                {
                    Caption = 'Full Load Quantity';
                }
                field(noOfPallets; Rec."No. of Pallets")
                {
                    Caption = 'No. of Pallets';
                }
                field(gramWeight; Rec."Gram Weight")
                {
                    Caption = 'Gram Weight';
                }
                field(currentSupplierUnitCost; Rec."Current Supplier Unit Cost")
                {
                    Caption = 'Current Supplier Unit Cost';
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
            Error('The packagingProductsUAT API is available only in a Business Central sandbox environment.');
    end;
}
