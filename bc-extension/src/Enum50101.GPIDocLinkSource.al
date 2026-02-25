/// <summary>
/// Enum 50101 "GPI Doc Link Source"
/// Defines the source that created the document link.
/// </summary>
enum 50101 "GPI Doc Link Source"
{
    Extensible = true;
    Caption = 'GPI Document Link Source';

    value(0; "GPIHub")
    {
        Caption = 'GPI Hub';
    }
    value(1; "Manual")
    {
        Caption = 'Manual';
    }
}
