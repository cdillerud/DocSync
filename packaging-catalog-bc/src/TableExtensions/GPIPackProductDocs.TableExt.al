tableextension 71101 "GPI Pack Prod Docs" extends "GPI Pack Product"
{
    fields
    {
        field(71101; "Document Count"; Integer)
        {
            Caption = 'Product Documents';
            FieldClass = FlowField;
            CalcFormula = count("GPI Pack Product Doc" where("Product No." = field("No.")));
            Editable = false;
        }
    }

    trigger OnBeforeDelete()
    var
        ProductDoc: Record "GPI Pack Product Doc";
    begin
        ProductDoc.SetRange("Product No.", Rec."No.");
        if not ProductDoc.IsEmpty() then
            ProductDoc.DeleteAll(true);
    end;
}
