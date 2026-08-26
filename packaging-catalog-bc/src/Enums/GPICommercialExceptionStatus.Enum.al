enum 71121 "GPI Comm Ex Status"
{
    Extensible = true;
    Caption = 'GPI Commercial Exception Status';

    value(0; New)
    {
        Caption = 'New';
    }
    value(10; Investigating)
    {
        Caption = 'Investigating';
    }
    value(20; "Needs Review")
    {
        Caption = 'Needs Review';
    }
    value(30; Confirmed)
    {
        Caption = 'Confirmed';
    }
    value(40; Dismissed)
    {
        Caption = 'Dismissed';
    }
    value(50; Corrected)
    {
        Caption = 'Corrected';
    }
    value(60; Closed)
    {
        Caption = 'Closed';
    }
}
