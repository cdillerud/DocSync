/// <summary>
/// Enum 50100 "GPI Doc Link Type"
/// Defines the type of BC document that a SharePoint link is attached to.
/// </summary>
enum 50100 "GPI Doc Link Type"
{
    Extensible = true;
    Caption = 'GPI Document Link Type';

    value(0; "Purchase Invoice")
    {
        Caption = 'Purchase Invoice';
    }
    value(1; "Posted Purchase Invoice")
    {
        Caption = 'Posted Purchase Invoice';
    }
    value(2; "Sales Invoice")
    {
        Caption = 'Sales Invoice';
    }
    value(3; "Posted Sales Invoice")
    {
        Caption = 'Posted Sales Invoice';
    }
}
