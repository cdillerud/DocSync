codeunit 71005 "GPI Pack Compare Mgt"
{
    procedure InitializeCandidate(var CompareLine: Record "GPI Pack Comp Line")
    var
        CompareHeader: Record "GPI Pack Compare";
        Product: Record "GPI Pack Product";
    begin
        ClearCalculatedFields(CompareLine);

        if CompareLine."Product No." = '' then begin
            ClearSourceFields(CompareLine);
            exit;
        end;

        Product.Get(CompareLine."Product No.");
        CopyProductSource(Product, CompareLine, true);

        if CompareHeader.Get(CompareLine."Compare Entry No.") then begin
            CompareLine."Pallet Cost per Pallet" := CompareHeader."Pallet Cost per Pallet";
            CompareLine."Tariff %" := CompareHeader."Tariff %";
            CompareLine."Intl Freight Total" := CompareHeader."Intl Freight Total";
            CompareLine."Customs Total" := CompareHeader."Customs Total";
            CompareLine."Delivery Total" := CompareHeader."Delivery Total";
        end;
    end;

    procedure AddMatchingCandidates(var CompareHeader: Record "GPI Pack Compare")
    var
        ReferenceProduct: Record "GPI Pack Product";
        Product: Record "GPI Pack Product";
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareHeader.TestField("Reference Product No.");
        ReferenceProduct.Get(CompareHeader."Reference Product No.");
        if ReferenceProduct.Blocked then
            Error('Reference product %1 is blocked.', ReferenceProduct."No.");

        Product.SetRange(Blocked, false);
        Product.SetRange(Material, ReferenceProduct.Material);
        Product.SetRange(Style, ReferenceProduct.Style);
        Product.SetRange(Capacity, ReferenceProduct.Capacity);
        Product.SetRange("Capacity UOM", ReferenceProduct."Capacity UOM");
        Product.SetRange(Color, ReferenceProduct.Color);

        if Product.FindSet() then
            repeat
                CompareLine.Reset();
                CompareLine.SetRange("Compare Entry No.", CompareHeader."Entry No.");
                CompareLine.SetRange("Product No.", Product."No.");
                if CompareLine.IsEmpty() then begin
                    CompareLine.Init();
                    CompareLine."Compare Entry No." := CompareHeader."Entry No.";
                    CompareLine."Product No." := Product."No.";
                    InitializeCandidate(CompareLine);
                    CompareLine.Insert(true);
                end;
            until Product.Next() = 0;

        CompareHeader."Last Calculated At" := 0DT;
        CompareHeader."Last Calculated By" := '';
        CompareHeader.Modify(false);
    end;

    procedure ApplyHeaderDefaults(var CompareHeader: Record "GPI Pack Compare")
    var
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareLine.SetRange("Compare Entry No.", CompareHeader."Entry No.");
        if CompareLine.FindSet(true) then
            repeat
                CompareLine."Pallet Cost per Pallet" := CompareHeader."Pallet Cost per Pallet";
                CompareLine."Tariff %" := CompareHeader."Tariff %";
                CompareLine."Intl Freight Total" := CompareHeader."Intl Freight Total";
                CompareLine."Customs Total" := CompareHeader."Customs Total";
                CompareLine."Delivery Total" := CompareHeader."Delivery Total";
                ClearCalculatedFields(CompareLine);
                CompareLine.Modify(false);
            until CompareLine.Next() = 0;

        CompareHeader."Last Calculated At" := 0DT;
        CompareHeader."Last Calculated By" := '';
        CompareHeader.Modify(false);
    end;

    procedure CalculateComparison(var CompareHeader: Record "GPI Pack Compare")
    var
        CompareLine: Record "GPI Pack Comp Line";
    begin
        CompareHeader.TestField("Reference Product No.");
        CompareHeader.TestField("Destination State");

        CompareLine.SetRange("Compare Entry No.", CompareHeader."Entry No.");
        if not CompareLine.FindSet(true) then
            Error('Add at least one candidate before calculating the comparison.');

        repeat
            CalculateCandidate(CompareHeader, CompareLine);
            CompareLine.Modify(false);
        until CompareLine.Next() = 0;

        RankCandidates(CompareHeader."Entry No.");

        CompareHeader."Last Calculated At" := CurrentDateTime();
        CompareHeader."Last Calculated By" := CopyStr(UserId(), 1, MaxStrLen(CompareHeader."Last Calculated By"));
        CompareHeader.Modify(false);
    end;

    procedure CalculateCandidate(CompareHeader: Record "GPI Pack Compare"; var CompareLine: Record "GPI Pack Comp Line")
    var
        Product: Record "GPI Pack Product";
        Work: Record "GPI Pack Cost Work" temporary;
        CostMgt: Codeunit "GPI Pack Cost Mgt";
    begin
        ClearCalculatedFields(CompareLine);

        if CompareLine."Product No." = '' then begin
            SetIncomplete(CompareLine, 'Gamer ID is required.');
            exit;
        end;

        if not Product.Get(CompareLine."Product No.") then begin
            SetIncomplete(CompareLine, 'Packaging product was not found.');
            exit;
        end;

        CopyProductSource(Product, CompareLine, false);

        if Product.Blocked then begin
            SetIncomplete(CompareLine, 'Packaging product is blocked.');
            exit;
        end;

        if CompareLine."Vendor No." = '' then begin
            SetIncomplete(CompareLine, 'Vendor No. is required before this option can be ranked.');
            exit;
        end;

        if CompareLine.Quantity <= 0 then begin
            SetIncomplete(CompareLine, 'Comparison quantity must be greater than zero.');
            exit;
        end;

        if CompareLine."Gram Weight" <= 0 then begin
            SetIncomplete(CompareLine, 'Gram Weight must be greater than zero.');
            exit;
        end;

        if CompareLine."Supplier Unit Cost" <= 0 then begin
            SetIncomplete(CompareLine, 'Supplier Unit Cost must be greater than zero.');
            exit;
        end;

        Work.Init();
        Work."Product No." := CompareLine."Product No.";
        Work."Calculation Date" := CompareHeader."Comparison Date";
        if Work."Calculation Date" = 0D then
            Work."Calculation Date" := WorkDate();
        Work."Vendor No." := CompareLine."Vendor No.";
        Work."Vendor Location Code" := CompareLine."Vendor Location Code";
        Work."Destination State" := CompareHeader."Destination State";
        Work.Mode := CompareLine.Mode;
        Work.Quantity := CompareLine.Quantity;
        Work."Gram Weight" := CompareLine."Gram Weight";
        Work."No. of Pallets" := CompareLine."No. of Pallets";
        Work."Unit Cost" := CompareLine."Supplier Unit Cost";
        Work."Pallet Cost per Pallet" := CompareLine."Pallet Cost per Pallet";
        Work."Tariff %" := CompareLine."Tariff %";
        Work."Intl Freight Total" := CompareLine."Intl Freight Total";
        Work."Customs Total" := CompareLine."Customs Total";
        Work."Delivery Charge Total" := CompareLine."Delivery Total";
        Work."Target Gross Margin %" := CompareHeader."Target Gross Margin %";

        CostMgt.Recalculate(Work);
        CompareLine."Shipment CWT" := Work."Shipment CWT";

        if not CostMgt.TryApplyBestFreightRate(Work) then begin
            SetIncomplete(
                CompareLine,
                CopyStr(
                    StrSubstNo(
                        'No active freight rate was found for vendor %1, FOB %2, destination %3, mode %4, and comparison date %5. This option is not ranked.',
                        CompareLine."Vendor No.",
                        CompareLine."Vendor Location Code",
                        CompareHeader."Destination State",
                        Format(CompareLine.Mode),
                        Work."Calculation Date"),
                    1,
                    MaxStrLen(CompareLine."Incomplete Reason")));
            exit;
        end;

        CopyWorkResults(Work, CompareLine);
        CompareLine."Is Complete" := true;
        CompareLine."Incomplete Reason" := '';
        CompareLine."Calculated At" := CurrentDateTime();
    end;

    local procedure CopyProductSource(Product: Record "GPI Pack Product"; var CompareLine: Record "GPI Pack Comp Line"; ResetQuantity: Boolean)
    begin
        CompareLine."BC Item No." := Product."BC Item No.";
        CompareLine."Vendor No." := Product."Vendor No.";
        CompareLine."Vendor Location Code" := Product."Vendor Location Code";
        CompareLine.Mode := Product."Transport Mode";
        CompareLine."Gram Weight" := Product."Gram Weight";
        CompareLine."Supplier Unit Cost" := Product."Current Supplier Unit Cost";

        if ResetQuantity or (CompareLine.Quantity <= 0) then
            CompareLine.Quantity := Product."Full Load Quantity";
        if ResetQuantity or (CompareLine."No. of Pallets" <= 0) then
            CompareLine."No. of Pallets" := Product."No. of Pallets";
    end;

    local procedure ClearSourceFields(var CompareLine: Record "GPI Pack Comp Line")
    begin
        CompareLine."BC Item No." := '';
        CompareLine."Vendor No." := '';
        CompareLine."Vendor Location Code" := '';
        CompareLine.Mode := "GPI Pack Transport"::Any;
        CompareLine.Quantity := 0;
        CompareLine."Gram Weight" := 0;
        CompareLine."No. of Pallets" := 0;
        CompareLine."Supplier Unit Cost" := 0;
    end;

    local procedure ClearCalculatedFields(var CompareLine: Record "GPI Pack Comp Line")
    begin
        CompareLine."Shipment CWT" := 0;
        CompareLine."Freight Rate Entry No." := 0;
        CompareLine."Rate per CWT" := 0;
        CompareLine."Minimum Charge" := 0;
        CompareLine."Fuel Surcharge %" := 0;
        CompareLine."Domestic Freight Total" := 0;
        CompareLine."Domestic Frt per Unit" := 0;
        CompareLine."Pallet Cost per Unit" := 0;
        CompareLine."Tariff per Unit" := 0;
        CompareLine."Intl Freight per Unit" := 0;
        CompareLine."Customs per Unit" := 0;
        CompareLine."Delivery per Unit" := 0;
        CompareLine."Landed Cost per Unit" := 0;
        CompareLine."Suggested Sell Price" := 0;
        CompareLine.Rank := 0;
        CompareLine."Cost Above Best" := 0;
        CompareLine."Is Complete" := false;
        CompareLine."Incomplete Reason" := '';
        CompareLine."Calculated At" := 0DT;
    end;

    local procedure SetIncomplete(var CompareLine: Record "GPI Pack Comp Line"; ReasonText: Text)
    begin
        CompareLine."Is Complete" := false;
        CompareLine.Rank := 0;
        CompareLine."Cost Above Best" := 0;
        CompareLine."Landed Cost per Unit" := 0;
        CompareLine."Suggested Sell Price" := 0;
        CompareLine."Incomplete Reason" := CopyStr(ReasonText, 1, MaxStrLen(CompareLine."Incomplete Reason"));
        CompareLine."Calculated At" := CurrentDateTime();
    end;

    local procedure CopyWorkResults(Work: Record "GPI Pack Cost Work"; var CompareLine: Record "GPI Pack Comp Line")
    begin
        CompareLine."Shipment CWT" := Work."Shipment CWT";
        CompareLine."Freight Rate Entry No." := Work."Freight Rate Entry No.";
        CompareLine."Rate per CWT" := Work."Rate per CWT";
        CompareLine."Minimum Charge" := Work."Minimum Charge";
        CompareLine."Fuel Surcharge %" := Work."Fuel Surcharge %";
        CompareLine."Domestic Freight Total" := Work."Domestic Freight Total";
        CompareLine."Domestic Frt per Unit" := Work."Domestic Frt per Unit";
        CompareLine."Pallet Cost per Unit" := Work."Pallet Cost per Unit";
        CompareLine."Tariff per Unit" := Work."Tariff per Unit";
        CompareLine."Intl Freight per Unit" := Work."Intl Freight per Unit";
        CompareLine."Customs per Unit" := Work."Customs per Unit";
        CompareLine."Delivery per Unit" := Work."Delivery per Unit";
        CompareLine."Landed Cost per Unit" := Work."Landed Cost per Unit";
        CompareLine."Suggested Sell Price" := Work."Suggested Sell Price";
    end;

    local procedure RankCandidates(CompareEntryNo: Integer)
    var
        CompareLine: Record "GPI Pack Comp Line";
        BestCost: Decimal;
        NextRank: Integer;
    begin
        CompareLine.SetRange("Compare Entry No.", CompareEntryNo);
        if CompareLine.FindSet(true) then
            repeat
                CompareLine.Rank := 0;
                CompareLine."Cost Above Best" := 0;
                CompareLine.Modify(false);
            until CompareLine.Next() = 0;

        CompareLine.Reset();
        CompareLine.SetCurrentKey("Compare Entry No.", "Is Complete", "Landed Cost per Unit", "Line No.");
        CompareLine.SetRange("Compare Entry No.", CompareEntryNo);
        CompareLine.SetRange("Is Complete", true);
        if not CompareLine.FindSet(true) then
            exit;

        BestCost := CompareLine."Landed Cost per Unit";
        NextRank := 1;
        repeat
            CompareLine.Rank := NextRank;
            CompareLine."Cost Above Best" := Round(CompareLine."Landed Cost per Unit" - BestCost, 0.00001, '=');
            CompareLine.Modify(false);
            NextRank := NextRank + 1;
        until CompareLine.Next() = 0;
    end;
}
