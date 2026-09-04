/// <summary>
/// Read-only diagnostic API over posted Sales Invoice Line history.
/// Used to reconstruct the Boyer Customer Item Sales rolling state and retained customer item-reference evidence.
/// </summary>
page 71208 "GPI Order Intake InvLine Hist"
{
    Caption = 'GPI Order Intake Sales Invoice Line History';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeSalesInvoiceLineHistory';
    EntitySetName = 'orderIntakeSalesInvoiceLineHistories';
    SourceTable = "Sales Invoice Line";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(History)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(documentNumber; Rec."Document No.")
                {
                    Caption = 'Document No.';
                    Editable = false;
                }
                field(lineNumber; Rec."Line No.")
                {
                    Caption = 'Line No.';
                    Editable = false;
                }
                field(sellToCustomerNumber; Rec."Sell-to Customer No.")
                {
                    Caption = 'Sell-to Customer No.';
                    Editable = false;
                }
                field(itemNumber; Rec."No.")
                {
                    Caption = 'No.';
                    Editable = false;
                }
                field(description; Rec.Description)
                {
                    Caption = 'Description';
                    Editable = false;
                }
                field(shipmentDate; Rec."Shipment Date")
                {
                    Caption = 'Shipment Date';
                    Editable = false;
                }
                field(quantity; Rec.Quantity)
                {
                    Caption = 'Quantity';
                    Editable = false;
                }
                field(unitOfMeasureCode; Rec."Unit of Measure Code")
                {
                    Caption = 'Unit of Measure Code';
                    Editable = false;
                }
                field(unitPrice; Rec."Unit Price")
                {
                    Caption = 'Unit Price';
                    Editable = false;
                }
                field(unitCost; Rec."Unit Cost")
                {
                    Caption = 'Unit Cost';
                    Editable = false;
                }
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
                    Editable = false;
                }
                field(itemReferenceNumber; Rec."Item Reference No.")
                {
                    Caption = 'Item Reference No.';
                    Editable = false;
                }
                field(itemReferenceUnitOfMeasure; Rec."Item Reference Unit of Measure")
                {
                    Caption = 'Item Reference Unit of Measure';
                    Editable = false;
                }
                field(itemReferenceType; Rec."Item Reference Type")
                {
                    Caption = 'Item Reference Type';
                    Editable = false;
                }
                field(itemReferenceTypeNumber; Rec."Item Reference Type No.")
                {
                    Caption = 'Item Reference Type No.';
                    Editable = false;
                }
                field(systemCreatedAt; Rec.SystemCreatedAt)
                {
                    Caption = 'System Created At';
                    Editable = false;
                }
            }
        }
    }
}
