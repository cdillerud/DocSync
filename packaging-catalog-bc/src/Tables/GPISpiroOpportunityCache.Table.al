table 71105 "GPI Spiro Opp Cache"
{
    Caption = 'GPI Spiro Opportunity Cache';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Spiro Opp Lookup";
    DrillDownPageId = "GPI Spiro Opp Lookup";

    fields
    {
        field(1; "Spiro Opportunity ID"; Text[100])
        {
            Caption = 'Spiro Opportunity ID';
        }
        field(2; "Spiro Company ID"; Text[100])
        {
            Caption = 'Spiro Company ID';
        }
        field(3; "Spiro Company Name"; Text[100])
        {
            Caption = 'Spiro Company Name';
        }
        field(4; "Opportunity Name"; Text[100])
        {
            Caption = 'Opportunity Name';
        }
        field(5; Stage; Text[50])
        {
            Caption = 'Stage';
        }
        field(6; Owner; Text[100])
        {
            Caption = 'Owner';
        }
        field(7; "Browser URL"; Text[250])
        {
            Caption = 'Browser URL';
        }
        field(8; "Refreshed At"; DateTime)
        {
            Caption = 'Refreshed At';
        }
        field(9; "Refreshed By"; Text[100])
        {
            Caption = 'Refreshed By';
        }        field(10; "Assigned ISR"; Text[100])
        {
            Caption = 'Assigned ISR';
        }
        field(11; Probability; Decimal)
        {
            Caption = 'Probability';
            DecimalPlaces = 0 : 5;
        }
        field(12; "Estimated Annual Volume"; Decimal)
        {
            Caption = 'Estimated Annual Volume';
            DecimalPlaces = 0 : 5;
        }
        field(13; "Close Date"; Date)
        {
            Caption = 'Close Date';
        }
        field(14; Rating; Text[50])
        {
            Caption = 'Rating';
        }
    }

    keys
    {
        key(PK; "Spiro Opportunity ID")
        {
            Clustered = true;
        }
        key(Company; "Spiro Company ID", "Opportunity Name")
        {
        }
    }

    trigger OnInsert()
    begin
        StampRefreshMetadata();
    end;

    trigger OnModify()
    begin
        StampRefreshMetadata();
    end;

    local procedure StampRefreshMetadata()
    begin
        if "Refreshed At" = 0DT then
            "Refreshed At" := CurrentDateTime();
        if "Refreshed By" = '' then
            "Refreshed By" := CopyStr(UserId(), 1, MaxStrLen("Refreshed By"));
    end;
}
