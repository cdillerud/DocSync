pageextension 71101 "GPI Pack Prod Docs" extends "GPI Pack Prod Card"
{
    layout
    {
        modify("Product Drawing")
        {
            Visible = false;
        }
        modify("Drawing File Name")
        {
            Visible = false;
        }
        addlast(Documents)
        {
            field("Document Count"; Rec."Document Count")
            {
                ApplicationArea = All;
                ToolTip = 'Shows the number of files stored for this packaging product.';
            }
        }
        addafter(Documents)
        {
            part(ProductDocuments; "GPI Pack Doc Part")
            {
                ApplicationArea = All;
                Caption = 'Product Documents';
                SubPageLink = "Product No." = field("No.");
            }
        }
    }

    actions
    {
        addlast(Processing)
        {
            action(OpenProductDocuments)
            {
                ApplicationArea = All;
                Caption = 'Product Documents';
                Promoted = true;
                PromotedCategory = Process;
                RunObject = page "GPI Pack Doc List";
                RunPageLink = "Product No." = field("No.");
            }
        }
    }
}
