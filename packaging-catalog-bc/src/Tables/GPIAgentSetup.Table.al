table 71130 "GPI Agent Setup"
{
    Caption = 'GPI Commercial Agent Setup';
    DataClassification = CustomerContent;

    fields
    {
        field(1; "Primary Key"; Code[10])
        {
            Caption = 'Primary Key';
        }
        field(10; "Low Margin Enabled"; Boolean)
        {
            Caption = 'Low Margin Agent Enabled';
        }
        field(11; "Low Margin Floor %"; Decimal)
        {
            Caption = 'Low Margin Hard Floor %';
            DecimalPlaces = 0 : 2;
            MinValue = 0;
            MaxValue = 100;
            InitValue = 20;
        }
        field(12; "Margin Variance Pts"; Decimal)
        {
            Caption = 'Margin Variance Threshold Points';
            DecimalPlaces = 0 : 2;
            MinValue = 0;
            MaxValue = 100;
            InitValue = 8;
        }
        field(20; "Cost Change Enabled"; Boolean)
        {
            Caption = 'Cost Change Agent Enabled';
        }
        field(21; "Cost Change Min %"; Decimal)
        {
            Caption = 'Cost Change Minimum %';
            DecimalPlaces = 0 : 2;
            MinValue = 0;
            InitValue = 2;
        }
        field(30; "Incorrect Item Enabled"; Boolean)
        {
            Caption = 'Incorrect Item Agent Enabled';
        }
        field(31; "Similarity Threshold %"; Decimal)
        {
            Caption = 'Similarity Threshold %';
            DecimalPlaces = 0 : 2;
            MinValue = 0;
            MaxValue = 100;
            InitValue = 85;
        }
        field(40; "Last Modified At"; DateTime)
        {
            Caption = 'Last Modified At';
            Editable = false;
        }
        field(41; "Last Modified By"; Text[100])
        {
            Caption = 'Last Modified By';
            Editable = false;
        }
    }

    keys
    {
        key(PK; "Primary Key")
        {
            Clustered = true;
        }
    }

    trigger OnInsert()
    begin
        if "Primary Key" = '' then
            "Primary Key" := 'SETUP';
        Touch();
    end;

    trigger OnModify()
    begin
        Touch();
    end;

    local procedure Touch()
    begin
        "Last Modified At" := CurrentDateTime();
        "Last Modified By" := CopyStr(UserId(), 1, MaxStrLen("Last Modified By"));
    end;
}
