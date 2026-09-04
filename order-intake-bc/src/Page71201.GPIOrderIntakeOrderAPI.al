/// <summary>
/// Read-only custom API for Sales Orders created by the GPI Order Intake authority.
/// Version 0.1.0.11 adds current Sales Header date/shipping evidence only; write behavior is unchanged.
/// </summary>
page 71201 "GPI Order Intake Order API"
{
    Caption = 'GPI Order Intake Orders';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeOrder';
    EntitySetName = 'orderIntakeOrders';
    SourceTable = "Sales Header";
    SourceTableView = where("Document Type" = const(Order));
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Orders)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(number; Rec."No.")
                {
                    Caption = 'Number';
                    Editable = false;
                }
                field(customerNumber; Rec."Sell-to Customer No.")
                {
                    Caption = 'Customer Number';
                    Editable = false;
                }
                field(externalDocumentNumber; Rec."External Document No.")
                {
                    Caption = 'External Document Number';
                    Editable = false;
                }
                field(orderDate; Rec."Order Date")
                {
                    Caption = 'Order Date';
                    Editable = false;
                }
                field(documentDate; Rec."Document Date")
                {
                    Caption = 'Document Date';
                    Editable = false;
                }
                field(requestedDeliveryDate; Rec."Requested Delivery Date")
                {
                    Caption = 'Requested Delivery Date';
                    Editable = false;
                }
                field(promisedDeliveryDate; Rec."Promised Delivery Date")
                {
                    Caption = 'Promised Delivery Date';
                    Editable = false;
                }
                field(shipmentDate; Rec."Shipment Date")
                {
                    Caption = 'Shipment Date';
                    Editable = false;
                }
                field(shipToCode; Rec."Ship-to Code")
                {
                    Caption = 'Ship-to Code';
                    Editable = false;
                }
                field(shipToName; Rec."Ship-to Name")
                {
                    Caption = 'Ship-to Name';
                    Editable = false;
                }
                field(shipToAddressLine1; Rec."Ship-to Address")
                {
                    Caption = 'Ship-to Address';
                    Editable = false;
                }
                field(shipToAddressLine2; Rec."Ship-to Address 2")
                {
                    Caption = 'Ship-to Address 2';
                    Editable = false;
                }
                field(shipToCity; Rec."Ship-to City")
                {
                    Caption = 'Ship-to City';
                    Editable = false;
                }
                field(shipToCounty; Rec."Ship-to County")
                {
                    Caption = 'Ship-to County';
                    Editable = false;
                }
                field(shipToPostalCode; Rec."Ship-to Post Code")
                {
                    Caption = 'Ship-to Post Code';
                    Editable = false;
                }
                field(shipToCountryCode; Rec."Ship-to Country/Region Code")
                {
                    Caption = 'Ship-to Country/Region Code';
                    Editable = false;
                }
                field(shipmentMethodCode; Rec."Shipment Method Code")
                {
                    Caption = 'Shipment Method Code';
                    Editable = false;
                }
                field(shippingAgentCode; Rec."Shipping Agent Code")
                {
                    Caption = 'Shipping Agent Code';
                    Editable = false;
                }
                field(shippingAgentServiceCode; Rec."Shipping Agent Service Code")
                {
                    Caption = 'Shipping Agent Service Code';
                    Editable = false;
                }
                field(shippingTime; Rec."Shipping Time")
                {
                    Caption = 'Shipping Time';
                    Editable = false;
                }
                field(outboundWarehouseHandlingTime; Rec."Outbound Whse. Handling Time")
                {
                    Caption = 'Outbound Warehouse Handling Time';
                    Editable = false;
                }
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
                    Editable = false;
                }
                field(status; Rec.Status)
                {
                    Caption = 'Status';
                    Editable = false;
                }
                part(lines; "GPI Order Intake Line API")
                {
                    Caption = 'Lines';
                    EntityName = 'orderIntakeLine';
                    EntitySetName = 'orderIntakeLines';
                    SubPageLink = "Document Type" = field("Document Type"),
                                  "Document No." = field("No.");
                }
            }
        }
    }
}
