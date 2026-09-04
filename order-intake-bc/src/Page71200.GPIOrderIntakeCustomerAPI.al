/// <summary>
/// Customer-bound custom API for the Phase-0 GPI Order Intake authority.
/// Endpoint: /api/gpi/orderIntake/v1.0/companies({companyId})/orderIntakeCustomers
/// Bound action: Microsoft.NAV.createValidatedDraft
/// Version 0.1.0.1 adds read-only customer pricing-context fields.
/// </summary>
page 71200 "GPI Order Intake Cust API"
{
    Caption = 'GPI Order Intake Customers';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeCustomer';
    EntitySetName = 'orderIntakeCustomers';
    SourceTable = Customer;
    ODataKeyFields = SystemId;
    DelayedInsert = true;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(Customers)
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
                field(displayName; Rec.Name)
                {
                    Caption = 'Display Name';
                    Editable = false;
                }
                field(billToCustomerNumber; Rec."Bill-to Customer No.")
                {
                    Caption = 'Bill-to Customer Number';
                    Editable = false;
                }
                field(customerPriceGroup; Rec."Customer Price Group")
                {
                    Caption = 'Customer Price Group';
                    Editable = false;
                }
                field(customerDiscountGroup; Rec."Customer Disc. Group")
                {
                    Caption = 'Customer Discount Group';
                    Editable = false;
                }
                field(currencyCode; Rec."Currency Code")
                {
                    Caption = 'Currency Code';
                    Editable = false;
                }
                field(priceCalculationMethod; Rec."Price Calculation Method")
                {
                    Caption = 'Price Calculation Method';
                    Editable = false;
                }
            }
        }
    }

    [ServiceEnabled]
    [Scope('Cloud')]
    procedure CreateValidatedDraft(
        var ActionContext: WebServiceActionContext;
        itemNumber: Code[20];
        quantity: Decimal;
        unitOfMeasureCode: Code[10];
        locationCode: Code[10];
        orderDate: Date;
        shipmentDate: Date;
        externalDocumentNumber: Code[35])
    var
        Authority: Codeunit "GPI Order Intake Authority";
        SalesHeader: Record "Sales Header";
        SalesLine: Record "Sales Line";
    begin
        Authority.CreateValidatedDraft(
            Rec."No.",
            itemNumber,
            quantity,
            unitOfMeasureCode,
            locationCode,
            orderDate,
            shipmentDate,
            externalDocumentNumber,
            SalesHeader,
            SalesLine);

        ActionContext.SetObjectType(ObjectType::Page);
        ActionContext.SetObjectId(Page::"GPI Order Intake Order API");
        ActionContext.AddEntityKey(SalesHeader.FieldNo(SystemId), SalesHeader.SystemId);
        ActionContext.SetResultCode(WebServiceActionResultCode::Created);
    end;
}
