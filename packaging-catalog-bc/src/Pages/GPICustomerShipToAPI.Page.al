page 71133 "GPI Cust ShipTo API"
{
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialAgents';
    APIVersion = 'v1.0';
    Caption = 'customerShipTos';
    EntityName = 'customerShipTo';
    EntitySetName = 'customerShipTos';
    SourceTable = "Ship-to Address";
    ODataKeyFields = SystemId;
    DataAccessIntent = ReadOnly;
    Editable = false;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(General)
            {
                field(id; Rec.SystemId) { Caption = 'Id'; Editable = false; }
                field(customerNo; Rec."Customer No.") { Caption = 'Customer No.'; Editable = false; }
                field(code; Rec.Code) { Caption = 'Ship-to Code'; Editable = false; }
                field(name; Rec.Name) { Caption = 'Name'; Editable = false; }
                field(name2; Rec."Name 2") { Caption = 'Name 2'; Editable = false; }
                field(address; Rec.Address) { Caption = 'Address'; Editable = false; }
                field(address2; Rec."Address 2") { Caption = 'Address 2'; Editable = false; }
                field(city; Rec.City) { Caption = 'City'; Editable = false; }
                field(state; Rec.County) { Caption = 'State / County'; Editable = false; }
                field(postalCode; Rec."Post Code") { Caption = 'Post Code'; Editable = false; }
                field(countryRegionCode; Rec."Country/Region Code") { Caption = 'Country/Region Code'; Editable = false; }
                field(contact; Rec.Contact) { Caption = 'Contact'; Editable = false; }
                field(phoneNo; Rec."Phone No.") { Caption = 'Phone No.'; Editable = false; }
                field(email; Rec."E-Mail") { Caption = 'E-Mail'; Editable = false; }
                field(shipmentMethodCode; Rec."Shipment Method Code") { Caption = 'Shipment Method Code'; Editable = false; }
                field(shippingAgentCode; Rec."Shipping Agent Code") { Caption = 'Shipping Agent Code'; Editable = false; }
                field(shippingAgentServiceCode; Rec."Shipping Agent Service Code") { Caption = 'Shipping Agent Service Code'; Editable = false; }
                field(locationCode; Rec."Location Code") { Caption = 'Location Code'; Editable = false; }
                field(taxAreaCode; Rec."Tax Area Code") { Caption = 'Tax Area Code'; Editable = false; }
                field(taxLiable; Rec."Tax Liable") { Caption = 'Tax Liable'; Editable = false; }
                field(lastDateModified; Rec."Last Date Modified") { Caption = 'Last Date Modified'; Editable = false; }
                field(systemModifiedAt; Rec.SystemModifiedAt) { Caption = 'System Modified At'; Editable = false; }
            }
        }
    }
}