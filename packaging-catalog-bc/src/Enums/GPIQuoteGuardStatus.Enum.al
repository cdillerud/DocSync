enum 71004 "GPI Quote Guard Stat"
{
    Extensible = false;
    Caption = 'Packaging Quote Guardrail Status';

    value(0; "Not Evaluated")
    {
        Caption = 'Not Evaluated';
    }
    value(1; "Within Policy")
    {
        Caption = 'Within Policy';
    }
    value(2; "Special Pricing")
    {
        Caption = 'Special Pricing Protected';
    }
    value(3; "Fixed Price Match")
    {
        Caption = 'Fixed Price Match';
    }
    value(4; "Fixed Price Conflict")
    {
        Caption = 'Fixed Price Conflict';
    }
    value(5; "Below Target Margin")
    {
        Caption = 'Below Target Margin';
    }
    value(6; "Approval Required")
    {
        Caption = 'Approval Required';
    }
    value(7; "Missing Cost")
    {
        Caption = 'Missing Landed Cost';
    }
}
