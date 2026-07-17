pageextension 70582 "GPI Delivery Log Open Orders" extends "GPI Document Delivery Log"
{
    layout
    {
        addlast(Content)
        {
            group(GPIOpenOrderStatusDetails)
            {
                Caption = 'Open Order Status Details';
                Visible = Rec."Delivery Document Type" = Rec."Delivery Document Type"::"Customer Open Order Status";

                field("Open Order As Of Date"; Rec."Open Order As Of Date")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Open Order Count"; Rec."Open Order Count")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Open Order Line Count"; Rec."Open Order Line Count")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Included Order Nos."; Rec."Included Order Nos.")
                {
                    ApplicationArea = All;
                    Editable = false;
                    MultiLine = true;
                }
            }
        }
    }
}
