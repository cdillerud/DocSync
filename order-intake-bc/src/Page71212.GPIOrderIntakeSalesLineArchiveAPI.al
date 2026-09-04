/// <summary>
/// Read-only diagnostic API over archived Sales Line versions.
/// Used to prove the customer item reference retained on historical Sales Orders.
/// </summary>
page 71212 "GPI Order Intake SalesLineArc"
{
    Caption = 'GPI Order Intake Sales Line Archive';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeSalesLineArchive';
    EntitySetName = 'orderIntakeSalesLineArchives';
    SourceTable = "Sales Line Archive";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Archive)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(documentType; Rec."Document Type")
                {
                    Caption = 'Document Type';
                    Editable = false;
                }
                field(documentNumber; Rec."Document No.")
                {
                    Caption = 'Document No.';
                    Editable = false;
                }
                field(documentNumberOccurrence; Rec."Doc. No. Occurrence")
                {
                    Caption = 'Doc. No. Occurrence';
                    Editable = false;
                }
                field(versionNumber; Rec."Version No.")
                {
                    Caption = 'Version No.';
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
                field(type; Rec.Type)
                {
                    Caption = 'Type';
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
                field(lineAmount; Rec."Line Amount")
                {
                    Caption = 'Line Amount';
                    Editable = false;
                }
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
                    Editable = false;
                }
                field(shipmentDate; Rec."Shipment Date")
                {
                    Caption = 'Shipment Date';
                    Editable = false;
                }
                field(requestedDeliveryDate; Rec."Requested Delivery Date")
                {
                    Caption = 'Requested Delivery Date';
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
