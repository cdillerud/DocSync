/// <summary>
/// Read-only diagnostic API over Business Central Item Unit of Measure records.
/// Used to prove the authoritative conversion between the item base UOM and sales UOM.
/// </summary>
page 71205 "GPI Order Intake Item UOM"
{
    Caption = 'GPI Order Intake Item Units of Measure';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeItemUnitOfMeasure';
    EntitySetName = 'orderIntakeItemUnitsOfMeasure';
    SourceTable = "Item Unit of Measure";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Units)
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
                field(code; Rec.Code)
                {
                    Caption = 'Code';
                    Editable = false;
                }
                field(quantityPerUnitOfMeasure; Rec."Qty. per Unit of Measure")
                {
                    Caption = 'Quantity per Unit of Measure';
                    Editable = false;
                }
                field(quantityRoundingPrecision; Rec."Qty. Rounding Precision")
                {
                    Caption = 'Quantity Rounding Precision';
                    Editable = false;
                }
            }
        }
    }
}
