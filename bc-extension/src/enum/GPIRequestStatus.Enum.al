enum 50103 "GPI Request Status"
{
    Extensible = true;
    Caption = 'GPI Request Status';

    value(0; Pending)
    {
        Caption = 'Pending';
    }
    value(1; Created)
    {
        Caption = 'Created';
    }
    value(2; "Already Exists")
    {
        Caption = 'Already Exists';
    }
    value(3; Failed)
    {
        Caption = 'Failed';
    }
    value(4; "Validation Error")
    {
        Caption = 'Validation Error';
    }
}
