codeunit 71004 "GPI Quote Hist Mgt"
{
    Permissions =
        tabledata "Sales Invoice Header" = R,
        tabledata "Sales Invoice Line" = R;

    procedure EvaluateHistory(var QuoteLine: Record "GPI Pack Quote Line"; QuoteHeader: Record "GPI Pack Quote")
    var
        AsOfDate: Date;
        CustomerLines: Integer;
        CustomerMedian: Decimal;
        CustomerLatestDate: Date;
        AllCustomerLines: Integer;
        AllCustomerMedian: Decimal;
        AllCustomerLatestDate: Date;
        CustomerSampleSize: Integer;
        AllCustomerSampleSize: Integer;
        MessageText: Text[250];
    begin
        ClearHistory(QuoteLine);

        if (QuoteHeader."Customer No." = '') or
           (QuoteLine."BC Item No." = '') or
           (QuoteLine."UOM Code" = '') or
           (QuoteLine."Proposed Sell Price" <= 0)
        then
            exit;

        AsOfDate := QuoteHeader."Quote Date";
        if AsOfDate = 0D then
            AsOfDate := WorkDate();

        BuildHistory(
            QuoteHeader."Customer No.",
            QuoteLine."BC Item No.",
            QuoteLine."UOM Code",
            AsOfDate,
            CustomerLines,
            CustomerMedian,
            CustomerLatestDate);

        BuildHistory(
            '',
            QuoteLine."BC Item No.",
            QuoteLine."UOM Code",
            AsOfDate,
            AllCustomerLines,
            AllCustomerMedian,
            AllCustomerLatestDate);

        QuoteLine."Customer Hist Lines" := CustomerLines;
        QuoteLine."Customer Hist Median" := CustomerMedian;
        QuoteLine."Customer Hist Last Date" := CustomerLatestDate;
        QuoteLine."All Cust Hist Lines" := AllCustomerLines;
        QuoteLine."All Cust Hist Median" := AllCustomerMedian;

        if CustomerMedian > 0 then
            QuoteLine."Customer Hist Var %" := Round(
                ((QuoteLine."Proposed Sell Price" - CustomerMedian) / CustomerMedian) * 100,
                0.00001,
                '=');

        CustomerSampleSize := CustomerLines;
        if CustomerSampleSize > 5 then
            CustomerSampleSize := 5;

        AllCustomerSampleSize := AllCustomerLines;
        if AllCustomerSampleSize > 5 then
            AllCustomerSampleSize := 5;

        if CustomerLines < 3 then
            MessageText := CopyStr(
                StrSubstNo(
                    'Customer history has %1 exact customer/item/UOM posted lines; at least 3 are required to trigger review. All-customer exact history has %2 lines with recent-%3 median %4. All-customer history is context only.',
                    CustomerLines,
                    AllCustomerLines,
                    AllCustomerSampleSize,
                    AllCustomerMedian),
                1,
                MaxStrLen(MessageText))
        else
            MessageText := CopyStr(
                StrSubstNo(
                    'Customer history has %1 exact customer/item/UOM posted lines; recent-%2 median %3; proposed sell is %4%% versus that median. All-customer exact history has %5 lines with recent-%6 median %7. History is review evidence only and never sets a replacement price.',
                    CustomerLines,
                    CustomerSampleSize,
                    CustomerMedian,
                    QuoteLine."Customer Hist Var %",
                    AllCustomerLines,
                    AllCustomerSampleSize,
                    AllCustomerMedian),
                1,
                MaxStrLen(MessageText));

        QuoteLine."History Message" := MessageText;
    end;

    procedure IsBelowCustomerHistory(QuoteLine: Record "GPI Pack Quote Line"): Boolean
    begin
        exit(
            (QuoteLine."Customer Hist Lines" >= 3) and
            (QuoteLine."Customer Hist Median" > 0) and
            (QuoteLine."Customer Hist Var %" <= -7.5));
    end;

    procedure IsAboveCustomerHistory(QuoteLine: Record "GPI Pack Quote Line"): Boolean
    begin
        exit(
            (QuoteLine."Customer Hist Lines" >= 3) and
            (QuoteLine."Customer Hist Median" > 0) and
            (QuoteLine."Customer Hist Var %" >= 15));
    end;

    procedure ClearHistory(var QuoteLine: Record "GPI Pack Quote Line")
    begin
        QuoteLine."Customer Hist Lines" := 0;
        QuoteLine."Customer Hist Median" := 0;
        QuoteLine."Customer Hist Var %" := 0;
        QuoteLine."Customer Hist Last Date" := 0D;
        QuoteLine."All Cust Hist Lines" := 0;
        QuoteLine."All Cust Hist Median" := 0;
        QuoteLine."History Message" := '';
    end;

    local procedure BuildHistory(CustomerNo: Code[20]; ItemNo: Code[20]; UOMCode: Code[10]; AsOfDate: Date; var TotalLines: Integer; var RecentMedian: Decimal; var LatestPostingDate: Date)
    var
        SalesHeader: Record "Sales Invoice Header";
        SalesLine: Record "Sales Invoice Line";
        RecentDates: array[5] of Date;
        RecentDocs: array[5] of Code[20];
        RecentLineNos: array[5] of Integer;
        RecentPrices: array[5] of Decimal;
        RecentCount: Integer;
    begin
        TotalLines := 0;
        RecentMedian := 0;
        LatestPostingDate := 0D;

        SalesHeader.Reset();
        if CustomerNo <> '' then
            SalesHeader.SetRange("Sell-to Customer No.", CustomerNo);
        if AsOfDate <> 0D then
            SalesHeader.SetFilter("Posting Date", '..%1', AsOfDate);

        if SalesHeader.FindSet() then
            repeat
                SalesLine.Reset();
                SalesLine.SetRange("Document No.", SalesHeader."No.");
                SalesLine.SetRange(Type, SalesLine.Type::Item);
                SalesLine.SetRange("No.", ItemNo);
                SalesLine.SetRange("Unit of Measure Code", UOMCode);
                SalesLine.SetFilter(Quantity, '>0');
                SalesLine.SetFilter("Unit Price", '>0');

                if SalesLine.FindSet() then
                    repeat
                        TotalLines := TotalLines + 1;
                        if SalesHeader."Posting Date" > LatestPostingDate then
                            LatestPostingDate := SalesHeader."Posting Date";

                        AddRecentPrice(
                            RecentDates,
                            RecentDocs,
                            RecentLineNos,
                            RecentPrices,
                            RecentCount,
                            SalesHeader."Posting Date",
                            SalesHeader."No.",
                            SalesLine."Line No.",
                            SalesLine."Unit Price");
                    until SalesLine.Next() = 0;
            until SalesHeader.Next() = 0;

        RecentMedian := CalculateMedian(RecentPrices, RecentCount);
    end;

    local procedure AddRecentPrice(var Dates: array[5] of Date; var Docs: array[5] of Code[20]; var LineNos: array[5] of Integer; var Prices: array[5] of Decimal; var Count: Integer; PostingDate: Date; DocNo: Code[20]; LineNo: Integer; UnitPrice: Decimal)
    var
        Index: Integer;
        OldestIndex: Integer;
    begin
        if Count < 5 then begin
            Count := Count + 1;
            Index := Count;
            Dates[Index] := PostingDate;
            Docs[Index] := DocNo;
            LineNos[Index] := LineNo;
            Prices[Index] := UnitPrice;
            exit;
        end;

        OldestIndex := 1;
        for Index := 2 to 5 do
            if IsEarlier(Dates[Index], Docs[Index], LineNos[Index], Dates[OldestIndex], Docs[OldestIndex], LineNos[OldestIndex]) then
                OldestIndex := Index;

        if not IsLater(PostingDate, DocNo, LineNo, Dates[OldestIndex], Docs[OldestIndex], LineNos[OldestIndex]) then
            exit;

        Dates[OldestIndex] := PostingDate;
        Docs[OldestIndex] := DocNo;
        LineNos[OldestIndex] := LineNo;
        Prices[OldestIndex] := UnitPrice;
    end;

    local procedure IsEarlier(Date1: Date; Doc1: Code[20]; Line1: Integer; Date2: Date; Doc2: Code[20]; Line2: Integer): Boolean
    begin
        if Date1 <> Date2 then
            exit(Date1 < Date2);
        if Doc1 <> Doc2 then
            exit(Doc1 < Doc2);
        exit(Line1 < Line2);
    end;

    local procedure IsLater(Date1: Date; Doc1: Code[20]; Line1: Integer; Date2: Date; Doc2: Code[20]; Line2: Integer): Boolean
    begin
        if Date1 <> Date2 then
            exit(Date1 > Date2);
        if Doc1 <> Doc2 then
            exit(Doc1 > Doc2);
        exit(Line1 > Line2);
    end;

    local procedure CalculateMedian(Prices: array[5] of Decimal; Count: Integer): Decimal
    var
        SortedPrices: array[5] of Decimal;
        Index: Integer;
        CompareIndex: Integer;
        TempPrice: Decimal;
    begin
        if Count = 0 then
            exit(0);

        for Index := 1 to Count do
            SortedPrices[Index] := Prices[Index];

        for Index := 1 to Count - 1 do
            for CompareIndex := Index + 1 to Count do
                if SortedPrices[CompareIndex] < SortedPrices[Index] then begin
                    TempPrice := SortedPrices[Index];
                    SortedPrices[Index] := SortedPrices[CompareIndex];
                    SortedPrices[CompareIndex] := TempPrice;
                end;

        if (Count mod 2) = 1 then
            exit(Round(SortedPrices[(Count + 1) div 2], 0.00001, '='));

        exit(Round((SortedPrices[Count div 2] + SortedPrices[(Count div 2) + 1]) / 2, 0.00001, '='));
    end;
}
