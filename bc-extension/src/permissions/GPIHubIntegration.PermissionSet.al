permissionset 50100 "GPI Hub Integration"
{
    Caption = 'GPI Hub Integration';
    Assignable = true;

    Permissions =
        // Tables
        table "GPI Document Link" = X,
        table "GPI Integration Log" = X,
        table "GPI Sales Order Request" = X,
        table "GPI Purch. Invoice Request" = X,
        table "GPI Customer Request" = X,
        table "GPI Vendor Request" = X,

        // Table Data
        tabledata "GPI Document Link" = RIMD,
        tabledata "GPI Integration Log" = RIMD,
        tabledata "GPI Sales Order Request" = RIMD,
        tabledata "GPI Purch. Invoice Request" = RIMD,
        tabledata "GPI Customer Request" = RIMD,
        tabledata "GPI Vendor Request" = RIMD,

        // Standard BC tables needed for record creation
        tabledata "Sales Header" = RIM,
        tabledata "Sales Line" = RIM,
        tabledata "Purchase Header" = RIM,
        tabledata Customer = RIM,
        tabledata Vendor = RIM,
        tabledata Company = R,

        // Codeunits
        codeunit "GPI Integration Mgt" = X,
        codeunit "GPI Sales Order Mgt" = X,
        codeunit "GPI Purchase Invoice Mgt" = X,
        codeunit "GPI Customer Mgt" = X,
        codeunit "GPI Vendor Mgt" = X,

        // Pages
        page "GPI Document Link Factbox" = X,
        page "GPI Document Link List" = X,
        page "GPI Document Link Card" = X,
        page "GPI Document Link API" = X,
        page "GPI Companies API" = X,
        page "GPI Sales Orders API" = X,
        page "GPI Purchase Invoices API" = X,
        page "GPI Customers API" = X,
        page "GPI Vendors API" = X,
        page "GPI Integration Log API" = X;
}
