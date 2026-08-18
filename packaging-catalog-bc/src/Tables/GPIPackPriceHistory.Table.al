table 71002 "GPI Pack Price Hist"
{
    Caption = 'GPI Packaging Price History';
    DataClassification = CustomerContent;
    DrillDownPageId = "GPI Pack Price Hist";

    fields
    {
        field(1; "Entry No."; Integer)
        {
            Caption = 'Entry No.';
            AutoIncrement = true;
        }
        field(2; "Product No."; Code[20])
        {
            Caption = 'Product No.';
            TableRelation = "GPI Pack Product"."No.";
        }
        field(3; "Vendor No."; Code[20])
        {
            Caption = 'Vendor No.';
            TableRelation = Vendor."No.";
        }
        field(4; "Vendor Location Code"; Code[20])
        {
            Caption = 'Vendor Location Code';
        }
        field(10; "Old Unit Cost"; Decimal)
        {
            Caption = 'Old Unit Cost';
            AutoFormatType = 2;
        }
        field(11; "New Unit Cost"; Decimal)
        {
            Caption = 'New Unit Cost';
            AutoFormatType = 2;
        }
        field(12; "Old Metric Ton Cost"; Decimal)
        {
            Caption = 'Old Metric Ton Cost';
            AutoFormatType = 2;
        }
        field(13; "New Metric Ton Cost"; Decimal)
        {
            Caption = 'New Metric Ton Cost';
            AutoFormatType = 2;
        }
        field(20; "Effective Date"; Date)
        {
            Caption = 'Effective Date';
        }
        field(21; Note; Text[250])
        {
            Caption = 'Note';
        }
        field(22; "Changed At"; DateTime)
        {
            Caption = 'Changed At';
        }
        field(23; "Changed By"; Guid)
        {
            Caption = 'Changed By';
        }
    }

    keys
    {
        key(PK; "Entry No.")
        {
            Clustered = true;
        }
        key(ProductDate; "Product No.", "Effective Date", "Entry No.")
        {
        }
    }
}
