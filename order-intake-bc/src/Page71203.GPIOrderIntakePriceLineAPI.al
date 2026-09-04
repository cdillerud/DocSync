/// <summary>
/// Read-only diagnostic API over Business Central Price List Line records.
/// Phase-0 purpose: identify the BC price source that should apply to an Order Intake line.
/// No insert, modify, or delete operations are exposed.
/// </summary>
page 71203 "GPI Order Intake Price API"
{
    Caption = 'GPI Order Intake Price Lines';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakePriceLine';
    EntitySetName = 'orderIntakePriceLines';
    SourceTable = "Price List Line";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(PriceLines)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(priceListCode; Rec."Price List Code")
                {
                    Caption = 'Price List Code';
                    Editable = false;
                }
                field(lineNumber; Rec."Line No.")
                {
                    Caption = 'Line Number';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                    Editable = false;
                }
                field(priceType; Rec."Price Type")
                {
                    Caption = 'Price Type';
                    Editable = false;
                }
                field(sourceGroup; Rec."Source Group")
                {
                    Caption = 'Source Group';
                    Editable = false;
                }
                field(sourceType; Rec."Source Type")
                {
                    Caption = 'Source Type';
                    Editable = false;
                }
                field(sourceNumber; Rec."Source No.")
                {
                    Caption = 'Source Number';
                    Editable = false;
                }
                field(parentSourceNumber; Rec."Parent Source No.")
                {
                    Caption = 'Parent Source Number';
                    Editable = false;
                }
                field(assetType; Rec."Asset Type")
                {
                    Caption = 'Asset Type';
                    Editable = false;
                }
                field(assetNumber; Rec."Asset No.")
                {
                    Caption = 'Asset Number';
                    Editable = false;
                }
                field(productNumber; Rec."Product No.")
                {
                    Caption = 'Product Number';
                    Editable = false;
                }
                field(variantCode; Rec."Variant Code")
                {
                    Caption = 'Variant Code';
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
                field(amountType; Rec."Amount Type")
                {
                    Caption = 'Amount Type';
                    Editable = false;
                }
                field(unitPrice; Rec."Unit Price")
                {
                    Caption = 'Unit Price';
                    Editable = false;
                }
                field(lineDiscountPercent; Rec."Line Discount %")
                {
                    Caption = 'Line Discount Percent';
                    Editable = false;
                }
                field(allowLineDiscount; Rec."Allow Line Disc.")
                {
                    Caption = 'Allow Line Discount';
                    Editable = false;
                }
            }
        }
    }
}
