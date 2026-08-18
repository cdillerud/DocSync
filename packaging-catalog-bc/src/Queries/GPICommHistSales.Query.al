query 71000 "GPI Comm Hist Sales"
{
    QueryType = API;
    APIPublisher = 'gpi';
    APIGroup = 'commercialGuardrails';
    APIVersion = 'v1.0';
    Caption = 'historicalSalesLines';
    EntityName = 'historicalSalesLine';
    EntitySetName = 'historicalSalesLines';
    DataAccessIntent = ReadOnly;

    elements
    {
        dataitem(SalesInvoiceHeader; "Sales Invoice Header")
        {
            column(invoiceNo; "No.")
            {
            }
            column(postingDate; "Posting Date")
            {
            }
            column(orderNo; "Order No.")
            {
            }
            column(customerNo; "Sell-to Customer No.")
            {
            }
            column(customerName; "Sell-to Customer Name")
            {
            }
            column(salespersonCode; "Salesperson Code")
            {
            }

            dataitem(SalesInvoiceLine; "Sales Invoice Line")
            {
                DataItemLink = "Document No." = SalesInvoiceHeader."No.";
                SqlJoinType = InnerJoin;

                column(lineNo; "Line No.")
                {
                }
                column(lineType; Type)
                {
                }
                column(itemNo; "No.")
                {
                }
                column(description; Description)
                {
                }
                column(quantity; Quantity)
                {
                }
                column(quantityBase; "Quantity (Base)")
                {
                }
                column(unitOfMeasureCode; "Unit of Measure Code")
                {
                }
                column(unitCostLCY; "Unit Cost (LCY)")
                {
                }
                column(unitPrice; "Unit Price")
                {
                }
                column(lineAmount; Amount)
                {
                }
            }
        }
    }
}
