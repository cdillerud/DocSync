codeunit 71000 "GPI Packaging Catalog Mgt."
{
    Permissions = tabledata "GPI Pack Price History" = I;

    procedure CalculateMetricTonCost(UnitCost: Decimal; GramWeight: Decimal): Decimal
    begin
        if (UnitCost <= 0) or (GramWeight <= 0) then
            exit(0);

        exit(Round((1000000 / GramWeight) * UnitCost, 0.01, '='));
    end;

    procedure RecalculateMetricTonCost(var Product: Record "GPI Packaging Product")
    var
        NewMetricTonCost: Decimal;
    begin
        NewMetricTonCost := CalculateMetricTonCost(Product."Current Supplier Unit Cost", Product."Gram Weight");
        if Product."Metric Ton Cost" = NewMetricTonCost then
            exit;

        Product."Metric Ton Cost" := NewMetricTonCost;
        Product.Modify(true);
    end;

    procedure LogPriceChange(Product: Record "GPI Packaging Product"; OldProduct: Record "GPI Packaging Product")
    var
        PriceHistory: Record "GPI Pack Price History";
        EffectiveDate: Date;
    begin
        if (Product."Current Supplier Unit Cost" = OldProduct."Current Supplier Unit Cost") and
           (Product."Metric Ton Cost" = OldProduct."Metric Ton Cost")
        then
            exit;

        EffectiveDate := Product."Price Effective Date";
        if EffectiveDate = 0D then
            EffectiveDate := WorkDate();

        PriceHistory.Init();
        PriceHistory."Product No." := Product."No.";
        PriceHistory."Vendor No." := Product."Vendor No.";
        PriceHistory."Vendor Location Code" := Product."Vendor Location Code";
        PriceHistory."Old Unit Cost" := OldProduct."Current Supplier Unit Cost";
        PriceHistory."New Unit Cost" := Product."Current Supplier Unit Cost";
        PriceHistory."Old Metric Ton Cost" := OldProduct."Metric Ton Cost";
        PriceHistory."New Metric Ton Cost" := Product."Metric Ton Cost";
        PriceHistory."Effective Date" := EffectiveDate;
        PriceHistory.Note := Product."Price Change Note";
        PriceHistory."Changed At" := CurrentDateTime();
        PriceHistory."Changed By" := UserSecurityId();
        PriceHistory.Insert(true);
    end;
}
