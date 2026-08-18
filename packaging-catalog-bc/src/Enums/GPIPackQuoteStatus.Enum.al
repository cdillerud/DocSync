enum 71002 "GPI Pack Quote Stat"
{
    Extensible = true;
    Caption = 'Packaging Quote Status';

    value(0; Draft)
    {
        Caption = 'Draft';
    }
    value(1; Ready)
    {
        Caption = 'Ready for Review';
    }
    value(2; Approved)
    {
        Caption = 'Approved';
    }
    value(3; Expired)
    {
        Caption = 'Expired';
    }
}
