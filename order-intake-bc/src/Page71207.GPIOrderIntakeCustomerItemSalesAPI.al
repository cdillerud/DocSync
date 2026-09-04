/// <summary>
/// Read-only diagnostic API over Boyer table 50006 Customer Item Sales.
/// Used only to prove the carried-forward last-sale quantity, UOM, price, cost and location for an exact customer/item.
/// </summary>
page 71207 "GPI Order Intake CustItemSales"
{
    Caption = 'GPI Order Intake Customer Item Sales';
    PageType = API;
    APIPublisher = 'gpi';
    APIGroup = 'orderIntake';
    APIVersion = 'v1.0';
    EntityName = 'orderIntakeCustomerItemSale';
    EntitySetName = 'orderIntakeCustomerItemSales';
    SourceTable = "Customer Item Sales";
    ODataKeyFields = SystemId;
    InsertAllowed = false;
    ModifyAllowed = false;
    DeleteAllowed = false;
    Extensible = false;

    layout
    {
        area(Content)
        {
            repeater(CustomerItemSales)
            {
                field(id; Rec.SystemId)
                {
                    Caption = 'ID';
                    Editable = false;
                }
                field(sellToCustomerNumber; Rec."Sell-To Customer No.")
                {
                    Caption = 'Sell-To Customer No.';
                    Editable = false;
                }
                field(itemNumber; Rec."Item No.")
                {
                    Caption = 'Item No.';
                    Editable = false;
                }
                field(lastSoldDate; Rec."Last Sold Date")
                {
                    Caption = 'Last Sold Date';
                    Editable = false;
                }
                field(lastSoldQuantity; Rec."Last Sold Quantity")
                {
                    Caption = 'Last Sold Quantity';
                    Editable = false;
                }
                field(lastSoldUnitOfMeasureCode; Rec."Last Sold Unit of Measure Code")
                {
                    Caption = 'Last Sold Unit of Measure Code';
                    Editable = false;
                }
                field(lastUnitPrice; Rec."Last Unit Price")
                {
                    Caption = 'Last Unit Price';
                    Editable = false;
                }
                field(lastUnitCost; Rec."Last Unit Cost")
                {
                    Caption = 'Last Unit Cost';
                    Editable = false;
                }
                field(locationCode; Rec."Location Code")
                {
                    Caption = 'Location Code';
                    Editable = false;
                }
            }
        }
    }
}
