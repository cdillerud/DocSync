enum 71005 "GPI Quote Audit Type"
{
    Extensible = false;
    Caption = 'Packaging Quote Audit Type';

    value(0; Evaluated)
    {
        Caption = 'Evaluated';
    }
    value(1; "Ready Review")
    {
        Caption = 'Ready for Review';
    }
    value(2; Approved)
    {
        Caption = 'Approved';
    }
    value(3; Rejected)
    {
        Caption = 'Rejected';
    }
    value(4; Reopened)
    {
        Caption = 'Reopened';
    }
    value(5; "Pricing Changed")
    {
        Caption = 'Pricing Changed';
    }
    value(6; "Customer Changed")
    {
        Caption = 'Customer Changed';
    }
    value(7; "Quote Changed")
    {
        Caption = 'Quote Changed';
    }
}
