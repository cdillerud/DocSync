/// <summary>
/// Read-only diagnostic API over Business Central Item Reference records.
/// Customer/vendor reference numbers remain Business Central-owned mapping evidence.
/// </summary>
page 71209 "GPI Order Intake Item Ref"
{
    Caption = 'GPI Order Intake Item References';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeItemReference';
    EntitySetName = 'orderIntakeItemReferences';
    SourceTable = "Item Reference";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(References)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(itemNumber; Rec."Item No.")
                {
                    Caption = 'Item No.';
                    Editable = false;
                }
                field(variantCode; Rec."Variant Code")
                {
                    Caption = 'Variant Code';
                    Editable = false;
                }
                field(unitOfMeasureCode; Rec."Unit of Measure")
                {
                    Caption = 'Unit of Measure';
                    Editable = false;
                }
                field(referenceType; Rec."Reference Type")
                {
                    Caption = 'Reference Type';
                    Editable = false;
                }
                field(referenceTypeNumber; Rec."Reference Type No.")
                {
                    Caption = 'Reference Type No.';
                    Editable = false;
                }
                field(referenceNumber; Rec."Reference No.")
                {
                    Caption = 'Reference No.';
                    Editable = false;
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                    Editable = false;
                }
                field(description2; Rec."Description 2")
                {
                    Caption = 'Description 2';
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
            }
        }
    }
}
