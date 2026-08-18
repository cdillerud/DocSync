query 71001 "GPI Item Cost Ctx"
{
    QueryType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialGuardrails';
    APIVersion = 'v1.0';
    Caption = 'itemCostContexts';
    EntityName = 'itemCostContext';
    EntitySetName = 'itemCostContexts';
    DataAccessIntent = ReadOnly;

    elements
    {
        dataitem(Item; Item)
        {
            column(itemNo; "No.") { }
            column(description; Description) { }
            column(baseUnitOfMeasure; "Base Unit of Measure") { }
            column(unitCost; "Unit Cost") { }
            column(blocked; Blocked) { }
            column(vendorNo; "Vendor No.") { }
            column(vendorItemNo; "Vendor Item No.") { }

            dataitem(ItemUnitOfMeasure; "Item Unit of Measure")
            {
                DataItemLink = "Item No." = Item."No.";
                SqlJoinType = LeftOuterJoin;

                column(uomCode; Code) { }
                column(qtyPerUnitOfMeasure; "Qty. per Unit of Measure") { }
            }
        }
    }
}
