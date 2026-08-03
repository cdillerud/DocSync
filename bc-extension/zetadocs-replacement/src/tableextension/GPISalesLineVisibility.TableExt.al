tableextension 70518 "GPI Sales Line Visibility" extends "Sales Line"
{
    fields
    {
        field(70510; "GPI Document Visibility"; Enum "GPI Document Visibility")
        {
            Caption = 'Document Visibility';
            DataClassification = CustomerContent;
            InitValue = "All Documents";

            trigger OnValidate()
            var
                VisibilityMgt: Codeunit "GPI Line Visibility Mgt.";
            begin
                VisibilityMgt.ValidateFinancialLineVisibility("Line Amount", "GPI Document Visibility");
            end;
        }
    }
}
