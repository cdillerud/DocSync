/// <summary>
/// Read-only diagnostic API over Business Central Ship-to Address records.
/// Used to resolve customer-stated ship-to evidence separately from BC Location.
/// </summary>
page 71210 "GPI Order Intake Ship-To"
{
    Caption = 'GPI Order Intake Ship-to Addresses';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeShipToAddress';
    EntitySetName = 'orderIntakeShipToAddresses';
    SourceTable = "Ship-to Address";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(ShipTos)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(customerNumber; Rec."Customer No.")
                {
                    Caption = 'Customer No.';
                    Editable = false;
                }
                field(code; Rec.Code)
                {
                    Caption = 'Code';
                    Editable = false;
                }
                field(name; Rec.Name)
                {
                    Caption = 'Name';
                    Editable = false;
                }
                field(name2; Rec."Name 2")
                {
                    Caption = 'Name 2';
                    Editable = false;
                }
                field(addressLine1; Rec.Address)
                {
                    Caption = 'Address';
                    Editable = false;
                }
                field(addressLine2; Rec."Address 2")
                {
                    Caption = 'Address 2';
                    Editable = false;
                }
                field(city; Rec.City)
                {
                    Caption = 'City';
                    Editable = false;
                }
                field(state; Rec.County)
                {
                    Caption = 'State / County';
                    Editable = false;
                }
                field(postalCode; Rec."Post Code")
                {
                    Caption = 'Post Code';
                    Editable = false;
                }
                field(countryCode; Rec."Country/Region Code")
                {
                    Caption = 'Country/Region Code';
                    Editable = false;
                }
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
                    Editable = false;
                }
                field(shipmentMethodCode; Rec."Shipment Method Code")
                {
                    Caption = 'Shipment Method Code';
                    Editable = false;
                }
            }
        }
    }
}
