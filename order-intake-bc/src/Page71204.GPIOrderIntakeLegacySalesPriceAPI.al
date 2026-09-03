/// <summary>
/// Read-only diagnostic API over the legacy Business Central Sales Price table.
/// The table is obsolete in the base app but remains readable and can prove whether
/// historical/customer pricing still exists outside Price List Line.
/// </summary>
#pragma warning disable AL0432
page 71204 "GPI Order Intake SalesPrice"
{
    Caption = 'GPI Order Intake Legacy Sales Prices';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeLegacySalesPrice';
    EntitySetName = 'orderIntakeLegacySalesPrices';
    SourceTable = "Sales Price";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Prices)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(itemNumber; Rec."Item No.")
                {
                    Caption = 'Item Number';
                    Editable = false;
                }
                field(salesType; Rec."Sales Type")
                {
                    Caption = 'Sales Type';
                    Editable = false;
                }
                field(salesCode; Rec."Sales Code")
                {
                    Caption = 'Sales Code';
                    Editable = false;
                }
                field(currencyCode; Rec."Currency Code")
                {
                    Caption = 'Currency Code';
                    Editable = false;
                }
                field(startingDate; Rec."Starting Date")
                {
                    Caption = 'Starting Date';
                    Editable = false;
                }
                field(endingDate; Rec."Ending Date")
                {
                    Caption = 'Ending Date';
                    Editable = false;
                }
                field(minimumQuantity; Rec."Minimum Quantity")
                {
                    Caption = 'Minimum Quantity';
                    Editable = false;
                }
                field(unitOfMeasureCode; Rec."Unit of Measure Code")
                {
                    Caption = 'Unit of Measure Code';
                    Editable = false;
                }
                field(variantCode; Rec."Variant Code")
                {
                    Caption = 'Variant Code';
                    Editable = false;
                }
                field(unitPrice; Rec."Unit Price")
                {
                    Caption = 'Unit Price';
                    Editable = false;
                }
                field(priceIncludesVAT; Rec."Price Includes VAT")
                {
                    Caption = 'Price Includes VAT';
                    Editable = false;
                }
                field(allowLineDiscount; Rec."Allow Line Disc.")
                {
                    Caption = 'Allow Line Discount';
                    Editable = false;
                }
                field(allowInvoiceDiscount; Rec."Allow Invoice Disc.")
                {
                    Caption = 'Allow Invoice Discount';
                    Editable = false;
                }
            }
        }
    }
}
#pragma warning restore AL0432
