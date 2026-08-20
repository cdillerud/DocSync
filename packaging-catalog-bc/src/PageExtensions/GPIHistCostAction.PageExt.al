pageextension 71101 "GPI Hist Cost Act" extends "GPI Pack Cost Calc"
{
    actions
    {
        addlast(Processing)
        {
            action(HistoricalCostEvidence)
            {
                ApplicationArea = All;
                Caption = 'Historical Cost Evidence';
                Image = History;
                Promoted = true;
                PromotedCategory = Process;

                trigger OnAction()
                var
                    Product: Record "GPI Pack Product";
                    HistCostPage: Page "GPI Hist Cost Evid";
                begin
                    Rec.TestField("Product No.");
                    Product.Get(Rec."Product No.");
                    Product.TestField("BC Item No.");
                    HistCostPage.SetItemNo(Product."BC Item No.");
                    HistCostPage.RunModal();
                end;
            }
        }
    }
}
