permissionset 50100 "GPI Hub Integration"
{
    Caption = 'GPI Hub Integration';
    Assignable = true;

    Permissions =
        // Tables
        table "GPI Document Link" = X,

        // Table Data
        tabledata "GPI Document Link" = RIMD,

        // Standard BC tables needed for record reading
        tabledata "Sales Header" = RIM,
        tabledata "Sales Line" = RIM,
        tabledata "Purchase Header" = RIM,
        tabledata Customer = RIM,
        tabledata Vendor = RIM,
        tabledata Company = R,

        // Codeunits
        codeunit "GPI Document Link Mgt" = X,

        // Pages
        page "GPI Document Link Factbox" = X,
        page "GPI Document Link List" = X,
        page "GPI Document Link Card" = X,
        page "GPI Document Link API" = X;
}
