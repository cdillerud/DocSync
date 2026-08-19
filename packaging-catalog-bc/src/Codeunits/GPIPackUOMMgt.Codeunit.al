codeunit 71009 "GPI Pack UOM Mgt"
{
    procedure ConvertQuoteLineUOM(var QuoteLine: Record "GPI Pack Quote Line"; OldUOMCode: Code[10])
    var
        QuoteMgt: Codeunit "GPI Pack Quote Mgt";
        OldQtyPerUOM: Decimal;
        NewQtyPerUOM: Decimal;
    begin
        if QuoteLine."UOM Code" = OldUOMCode then begin
            QuoteMgt.RecalculateLine(QuoteLine);
            exit;
        end;

        if (OldUOMCode = '') or (QuoteLine."UOM Code" = '') or (QuoteLine."BC Item No." = '') then begin
            QuoteMgt.RecalculateLine(QuoteLine);
            exit;
        end;

        OldQtyPerUOM := GetQtyPerUOM(QuoteLine."BC Item No.", OldUOMCode);
        NewQtyPerUOM := GetQtyPerUOM(QuoteLine."BC Item No.", QuoteLine."UOM Code");

        if Abs(OldQtyPerUOM - NewQtyPerUOM) < 0.00001 then begin
            QuoteMgt.RecalculateLine(QuoteLine);
            exit;
        end;

        if QuoteLine.Quantity > 0 then
            QuoteLine.Quantity := Round((QuoteLine.Quantity * OldQtyPerUOM) / NewQtyPerUOM, 0.00001, '=');

        if QuoteLine."Landed Cost per Unit" > 0 then
            QuoteLine."Landed Cost per Unit" := Round((QuoteLine."Landed Cost per Unit" * NewQtyPerUOM) / OldQtyPerUOM, 0.00001, '=');

        if QuoteLine."Proposed Sell Price" > 0 then
            QuoteLine."Proposed Sell Price" := Round((QuoteLine."Proposed Sell Price" * NewQtyPerUOM) / OldQtyPerUOM, 0.00001, '=');

        QuoteMgt.RecalculateLine(QuoteLine);
    end;

    procedure GetQtyPerUOM(ItemNo: Code[20]; UOMCode: Code[10]): Decimal
    var
        Item: Record Item;
        ItemUOM: Record "Item Unit of Measure";
    begin
        if ItemNo = '' then
            Error('BC Item No. is required before a quote UOM can be converted.');

        if UOMCode = '' then
            Error('UOM Code is required before a quote UOM can be converted.');

        Item.Get(ItemNo);

        if not ItemUOM.Get(ItemNo, UOMCode) then begin
            if UOMCode = Item."Base Unit of Measure" then
                exit(1);

            Error('Item %1 does not have Unit of Measure %2.', ItemNo, UOMCode);
        end;

        if ItemUOM."Qty. per Unit of Measure" <= 0 then
            Error('Item %1 / UOM %2 has an invalid Qty. per Unit of Measure.', ItemNo, UOMCode);

        exit(ItemUOM."Qty. per Unit of Measure");
    end;
}
