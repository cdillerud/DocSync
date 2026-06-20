permissionsetextension 70580 "GPI CUSTOMER OPEN ORDERS" extends "GPI DOC EMAIL"
{
    Permissions =
        tabledata Customer = r,
        tabledata Contact = r,
        tabledata "Sales Header" = r,
        tabledata "Sales Line" = r,
        tabledata "Purchase Line" = r,
        tabledata "Salesperson/Purchaser" = r,
        codeunit "GPI Customer Open Order Email" = X,
        report "GPI Customer Open Orders" = X;
}
