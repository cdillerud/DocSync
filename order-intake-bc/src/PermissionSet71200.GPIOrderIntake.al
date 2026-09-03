/// <summary>
/// Minimal permission set for the Phase-0 GPI Order Intake authority and read-only pricing/event diagnostics.
/// Does not grant release, shipment, invoicing or posting permissions.
/// </summary>
permissionset 71200 "GPI ORDER INTAKE"
{
    Assignable = true;
    Caption = 'GPI Order Intake';

    Permissions =
        tabledata Customer = R,
        tabledata Item = R,
        tabledata "Item Unit of Measure" = R,
        tabledata Location = R,
        tabledata "Price List Line" = R,
        tabledata "Sales Price" = R,
        tabledata "Sales Price Access" = R,
        tabledata "Event Subscription" = R,
        tabledata "Customer Item Sales" = R,
        tabledata "Sales Header" = RIM,
        tabledata "Sales Line" = RIM,
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R,
        codeunit "GPI Order Intake Authority" = X,
        page "GPI Order Intake Cust API" = X,
        page "GPI Order Intake Order API" = X,
        page "GPI Order Intake Line API" = X,
        page "GPI Order Intake Price API" = X,
        page "GPI Order Intake SalesPrice" = X,
        page "GPI Order Intake Item UOM" = X,
        page "GPI Order Intake Event Subs" = X,
        page "GPI Order Intake CustItemSales" = X,
        page "GPI Order Intake InvLine Hist" = X;
}
