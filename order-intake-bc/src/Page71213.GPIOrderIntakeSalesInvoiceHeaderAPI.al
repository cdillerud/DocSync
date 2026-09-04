/// <summary>
/// Read-only diagnostic API over posted Sales Invoice Header history.
/// Used to join posted invoice lines back to customer PO/reference and ship-to context.
/// </summary>
page 71213 "GPI Order Intake InvHdr Hist"
{
    Caption = 'GPI Order Intake Sales Invoice Header History';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeSalesInvoiceHeaderHistory';
    EntitySetName = 'orderIntakeSalesInvoiceHeaderHistories';
    SourceTable = "Sales Invoice Header";
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
                field(documentNumber; Rec."No.")
                {
                    Caption = 'No.';
                    Editable = false;
                }
                field(sellToCustomerNumber; Rec."Sell-to Customer No.")
                {
                    Caption = 'Sell-to Customer No.';
                    Editable = false;
                }
                field(orderNumber; Rec."Order No.")
                {
                    Caption = 'Order No.';
                    Editable = false;
                }
                field(externalDocumentNumber; Rec."External Document No.")
                {
                    Caption = 'External Document No.';
                    Editable = false;
                }
                field(yourReference; Rec."Your Reference")
                {
                    Caption = 'Your Reference';
                    Editable = false;
                }
                field(orderDate; Rec."Order Date")
                {
                    Caption = 'Order Date';
                    Editable = false;
                }
                field(postingDate; Rec."Posting Date")
                {
                    Caption = 'Posting Date';
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
                field(shipToState; Rec."Ship-to County")
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
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
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
