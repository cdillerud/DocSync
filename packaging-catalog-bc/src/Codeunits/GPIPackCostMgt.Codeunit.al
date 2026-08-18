codeunit 71001 "GPI Pack Cost Mgt"
{
    procedure InitializeFromProduct(var Work: Record "GPI Pack Cost Work")
    var
        Product: Record "GPI Pack Product";
    begin
        Work.TestField("Product No.");
        Product.Get(Work."Product No.");

        Work."Vendor No." := Product."Vendor No.";
        Work."Vendor Location Code" := Product."Vendor Location Code";
        Work.Mode := Product."Transport Mode";
        Work.Quantity := Product."Full Load Quantity";
        Work."Gram Weight" := Product."Gram Weight";
        Work."No. of Pallets" := Product."No. of Pallets";
        Work."Unit Cost" := Product."Current Supplier Unit Cost";

        if Work."Calculation Date" = 0D then
            Work."Calculation Date" := WorkDate();

        ClearFreightRate(Work);
        Recalculate(Work);
    end;

    procedure ClearFreightRate(var Work: Record "GPI Pack Cost Work")
    begin
        Work."Use Freight Rate" := false;
        Work."Freight Rate Entry No." := 0;
        Work."Rate per CWT" := 0;
        Work."Minimum Charge" := 0;
        Work."Fuel Surcharge %" := 0;
        Work."Rate Freight Total" := 0;
        Recalculate(Work);
    end;

    procedure ApplyBestFreightRate(var Work: Record "GPI Pack Cost Work")
    var
        Rate: Record "GPI Pack Frt Rate";
    begin
        Work.TestField("Destination State");
        Work.TestField(Quantity);
        Work.TestField("Gram Weight");

        if not FindBestFreightRate(Work, Rate) then
            Error(
              'No active freight rate was found for vendor %1, FOB %2, destination %3, mode %4, and calculation date %5.',
              Work."Vendor No.", Work."Vendor Location Code", Work."Destination State", Format(Work.Mode), Work."Calculation Date");

        Work."Freight Rate Entry No." := Rate."Entry No.";
        Work."Rate per CWT" := Rate."Rate per CWT";
        Work."Minimum Charge" := Rate."Minimum Charge";
        Work."Fuel Surcharge %" := Rate."Fuel Surcharge %";
        Work."Use Freight Rate" := true;
        Recalculate(Work);
    end;

    procedure Recalculate(var Work: Record "GPI Pack Cost Work")
    var
        BaseFreight: Decimal;
    begin
        Work."Shipment CWT" := 0;
        if (Work.Quantity > 0) and (Work."Gram Weight" > 0) then
            Work."Shipment CWT" := Round(((Work.Quantity * Work."Gram Weight") / 453.59237) / 100, 0.00001, '=');

        if Work."Use Freight Rate" and (Work."Freight Rate Entry No." <> 0) then begin
            if Work."Shipment CWT" > 0 then begin
                BaseFreight := Work."Shipment CWT" * Work."Rate per CWT";
                if BaseFreight < Work."Minimum Charge" then
                    BaseFreight := Work."Minimum Charge";

                Work."Rate Freight Total" := Round(BaseFreight * (1 + (Work."Fuel Surcharge %" / 100)), 0.01, '=');
            end else
                Work."Rate Freight Total" := 0;

            Work."Domestic Freight Total" := Work."Rate Freight Total";
        end else
            Work."Domestic Freight Total" := Work."Manual Freight Total";

        Work."Tariff per Unit" := Round(Work."Unit Cost" * (Work."Tariff %" / 100), 0.00001, '=');

        if Work.Quantity > 0 then begin
            Work."Pallet Cost per Unit" := Round((Work."Pallet Cost per Pallet" * Work."No. of Pallets") / Work.Quantity, 0.00001, '=');
            Work."Domestic Frt per Unit" := Round(Work."Domestic Freight Total" / Work.Quantity, 0.00001, '=');
            Work."Intl Freight per Unit" := Round(Work."Intl Freight Total" / Work.Quantity, 0.00001, '=');
            Work."Customs per Unit" := Round(Work."Customs Total" / Work.Quantity, 0.00001, '=');
            Work."Delivery per Unit" := Round(Work."Delivery Charge Total" / Work.Quantity, 0.00001, '=');
        end else begin
            Work."Pallet Cost per Unit" := 0;
            Work."Domestic Frt per Unit" := 0;
            Work."Intl Freight per Unit" := 0;
            Work."Customs per Unit" := 0;
            Work."Delivery per Unit" := 0;
        end;

        Work."Landed Cost per Unit" :=
          Work."Unit Cost" +
          Work."Pallet Cost per Unit" +
          Work."Domestic Frt per Unit" +
          Work."Tariff per Unit" +
          Work."Intl Freight per Unit" +
          Work."Customs per Unit" +
          Work."Delivery per Unit";
    end;

    local procedure FindBestFreightRate(Work: Record "GPI Pack Cost Work"; var Rate: Record "GPI Pack Frt Rate"): Boolean
    begin
        if TryFindRate(Rate, Work, Work."Vendor No.", Work."Vendor Location Code", false, Work.Mode) then
            exit(true);
        if TryFindRate(Rate, Work, Work."Vendor No.", '', false, Work.Mode) then
            exit(true);
        if TryFindRate(Rate, Work, '', '', false, Work.Mode) then
            exit(true);

        if Work.Mode <> "GPI Pack Transport"::Any then begin
            if TryFindRate(Rate, Work, Work."Vendor No.", Work."Vendor Location Code", false, "GPI Pack Transport"::Any) then
                exit(true);
            if TryFindRate(Rate, Work, Work."Vendor No.", '', false, "GPI Pack Transport"::Any) then
                exit(true);
            if TryFindRate(Rate, Work, '', '', false, "GPI Pack Transport"::Any) then
                exit(true);
        end;

        if TryFindRate(Rate, Work, Work."Vendor No.", Work."Vendor Location Code", true, Work.Mode) then
            exit(true);
        if TryFindRate(Rate, Work, Work."Vendor No.", '', true, Work.Mode) then
            exit(true);
        if TryFindRate(Rate, Work, '', '', true, Work.Mode) then
            exit(true);

        if Work.Mode <> "GPI Pack Transport"::Any then begin
            if TryFindRate(Rate, Work, Work."Vendor No.", Work."Vendor Location Code", true, "GPI Pack Transport"::Any) then
                exit(true);
            if TryFindRate(Rate, Work, Work."Vendor No.", '', true, "GPI Pack Transport"::Any) then
                exit(true);
            if TryFindRate(Rate, Work, '', '', true, "GPI Pack Transport"::Any) then
                exit(true);
        end;

        exit(false);
    end;

    local procedure TryFindRate(var Rate: Record "GPI Pack Frt Rate"; Work: Record "GPI Pack Cost Work"; OriginVendorNo: Code[20]; OriginLocationCode: Code[20]; DefaultDestination: Boolean; ModeToFind: Enum "GPI Pack Transport"): Boolean
    var
        CalculationDate: Date;
    begin
        CalculationDate := Work."Calculation Date";
        if CalculationDate = 0D then
            CalculationDate := WorkDate();

        Rate.Reset();
        Rate.SetCurrentKey("Origin Vendor No.", "Origin Location Code", "Destination State", "Default Destination", Mode, "Effective Date");
        Rate.SetRange(Blocked, false);
        Rate.SetRange("Origin Vendor No.", OriginVendorNo);
        Rate.SetRange("Origin Location Code", OriginLocationCode);
        Rate.SetRange(Mode, ModeToFind);
        Rate.SetFilter("Effective Date", '..%1', CalculationDate);

        if DefaultDestination then begin
            Rate.SetRange("Default Destination", true);
            Rate.SetRange("Destination State", '');
        end else begin
            if Work."Destination State" = '' then
                exit(false);
            Rate.SetRange("Default Destination", false);
            Rate.SetRange("Destination State", Work."Destination State");
        end;

        exit(Rate.FindLast());
    end;
}
