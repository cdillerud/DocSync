table 71005 "GPI Pack Price Rule"
{
    Caption = 'GPI Packaging Price Rule';
    DataClassification = CustomerContent;
    LookupPageId = "GPI Pack Price Rules";
    DrillDownPageId = "GPI Pack Price Rules";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Customer No."; Code[20])
        {
            Caption = 'Customer No.';
            TableRelation = Customer."No.";
            NotBlank = true;
        }
        field(3; "Customer Name"; Text[100])
        {
            Caption = 'Customer Name';
            FieldClass = FlowField;
            CalcFormula = lookup(Customer.Name where("No." = field("Customer No.")));
            Editable = false;
        }
        field(4; "Product No."; Code[20])
        {
            Caption = 'Gamer ID';
            TableRelation = "GPI Pack Product"."No.";
        }
        field(10; "Minimum Gross Margin %"; Decimal)
        {
            Caption = 'Minimum Gross Margin %';
            DecimalPlaces = 0 : 5;
            MinValue = 0;
            MaxValue = 99.99999;
        }
        field(11; "Special Sell Price"; Decimal)
        {
            Caption = 'Special Sell Price per Unit';
            AutoFormatType = 2;
            MinValue = 0;
        }
        field(12; "Lock Special Price"; Boolean)
        {
            Caption = 'Lock Special Price';
        }
        field(20; "Effective Date"; Date)
        {
            Caption = 'Effective Date';

            trigger OnValidate()
            begin
                ValidateDateRange();
            end;
        }
        field(21; "Expiration Date"; Date)
        {
            Caption = 'Expiration Date';

            trigger OnValidate()
            begin
                ValidateDateRange();
            end;
        }
        field(30; Notes; Text[250])
        {
            Caption = 'Notes';
        }
        field(31; Blocked; Boolean)
        {
            Caption = 'Blocked';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(CustomerProduct; "Customer No.", "Product No.", "Effective Date", "Entry No.")
        {
        }
    }

    local procedure ValidateDateRange()
    begin
        if ("Effective Date" <> 0D) and ("Expiration Date" <> 0D) and ("Expiration Date" < "Effective Date") then
            Error('Expiration Date cannot be earlier than Effective Date.');
    end;
}
