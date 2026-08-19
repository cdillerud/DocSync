codeunit 71008 "GPI Pack Flow Mgt"
{
    procedure CreateQuoteFromProduct(ProductNo: Code[20]; var QuoteHeader: Record "GPI Pack Quote")
    var
        Product: Record "GPI Pack Product";
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        Product.Get(ProductNo);
        Product.CalcFields("BC Item Description");

        InitializeQuoteHeader(QuoteHeader, Product);
        QuoteHeader.Insert(true);

        QuoteLine.Init();
        QuoteLine."Quote Entry No." := QuoteHeader."Entry No.";
        QuoteLine.Validate("Product No.", Product."No.");
        if Product."BC Item Description" <> '' then
            QuoteLine.Description := CopyStr(Product."BC Item Description", 1, MaxStrLen(QuoteLine.Description));
        QuoteLine.Insert(true);
    end;

    procedure CreateQuoteFromCostWork(CostWorkEntryNo: Integer; var QuoteHeader: Record "GPI Pack Quote")
    var
        CostWork: Record "GPI Pack Cost Work";
        Product: Record "GPI Pack Product";
        QuoteLine: Record "GPI Pack Quote Line";
    begin
        CostWork.Get(CostWorkEntryNo);
        CostWork.TestField("Product No.");
        Product.Get(CostWork."Product No.");
        Product.CalcFields("BC Item Description");

        InitializeQuoteHeader(QuoteHeader, Product);
        QuoteHeader.Insert(true);

        QuoteLine.Init();
        QuoteLine."Quote Entry No." := QuoteHeader."Entry No.";
        QuoteLine.Validate("Cost Worksheet Entry No.", CostWork."Entry No.");
        if Product."BC Item Description" <> '' then
            QuoteLine.Description := CopyStr(Product."BC Item Description", 1, MaxStrLen(QuoteLine.Description));
        QuoteLine.Insert(true);
    end;

    local procedure InitializeQuoteHeader(var QuoteHeader: Record "GPI Pack Quote"; Product: Record "GPI Pack Product")
    var
        DescriptionText: Text[100];
    begin
        QuoteHeader.Init();
        QuoteHeader."Quote Date" := WorkDate();

        if Product."BC Item Description" <> '' then
            DescriptionText := CopyStr(Product."BC Item Description", 1, MaxStrLen(DescriptionText))
        else
            DescriptionText := CopyStr('Packaging quote for ' + Product."No.", 1, MaxStrLen(DescriptionText));

        QuoteHeader.Description := DescriptionText;
    end;
}
