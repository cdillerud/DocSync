query 71002 "GPI Item Cost Evid"
{
    QueryType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialGuardrails';
    APIVersion = 'v1.0';
    EntityName = 'itemValueEvidence';
    EntitySetName = 'itemValueEvidence';
    Caption = 'GPI Item Value Evidence';

    elements
    {
        dataitem(ValueEntry; "Value Entry")
        {
            column(entryNo; "Entry No.")
            {
            }
            column(itemNo; "Item No.")
            {
            }
            column(postingDate; "Posting Date")
            {
            }
            column(documentNo; "Document No.")
            {
            }
            column(documentLineNo; "Document Line No.")
            {
            }
            column(itemLedgerEntryNo; "Item Ledger Entry No.")
            {
            }
            column(itemChargeNo; "Item Charge No.")
            {
            }
            column(valuedQuantity; "Valued Quantity")
            {
            }
            column(invoicedQuantity; "Invoiced Quantity")
            {
            }
            column(costPerUnit; "Cost per Unit")
            {
            }
            column(costAmountActual; "Cost Amount (Actual)")
            {
            }
            column(costAmountExpected; "Cost Amount (Expected)")
            {
            }
            column(purchaseAmountActual; "Purchase Amount (Actual)")
            {
            }
        }
    }
}
