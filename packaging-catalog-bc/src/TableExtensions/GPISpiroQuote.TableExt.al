tableextension 71102 "GPI Spiro Quote" extends "GPI Pack Quote"
{
    fields
    {
        field(71120; "GPI Spiro Company ID"; Text[100])
        {
            Caption = 'Spiro Company ID';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Spiro Cust Map"."Spiro Company ID" where("BC Customer No." = field("Customer No.")));
            Editable = false;
        }
        field(71121; "GPI Spiro Company Name"; Text[100])
        {
            Caption = 'Spiro Company Name';
            FieldClass = FlowField;
            CalcFormula = lookup("GPI Spiro Cust Map"."Spiro Company Name" where("BC Customer No." = field("Customer No.")));
            Editable = false;
        }
        field(71122; "GPI Spiro Opportunity ID"; Text[100])
        {
            Caption = 'Spiro Opportunity ID';
        }
        field(71123; "GPI Spiro Opp. Name"; Text[100])
        {
            Caption = 'Spiro Opportunity Name';
        }
        field(71124; "GPI Spiro Contact ID"; Text[100])
        {
            Caption = 'Spiro Contact ID';
        }
        field(71125; "GPI Spiro Contact Name"; Text[100])
        {
            Caption = 'Spiro Contact Name';
        }
        field(71126; "GPI Spiro Stage"; Text[50])
        {
            Caption = 'Spiro Stage';
        }
        field(71127; "GPI Spiro Owner"; Text[100])
        {
            Caption = 'Spiro Owner';
        }
        field(71128; "GPI Spiro Opp. URL"; Text[250])
        {
            Caption = 'Spiro Opportunity URL';
        }
        field(71129; "GPI Spiro Synced At"; DateTime)
        {
            Caption = 'Spiro Last Synced At';
        }
        field(71130; "GPI Spiro Synced By"; Text[100])
        {
            Caption = 'Spiro Last Synced By';
        }
    }
}
