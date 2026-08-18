page 71006 "GPI Pack Cost Calc"
{
    PageType = Card;
    SourceTable = "GPI Pack Cost Work";
    ApplicationArea = All;
    UsageCategory = Tasks;
    Caption = 'GPI Packaging Landed Cost Calculator';

    layout
    {
        area(Content)
        {
            group(General)
            {
                field("Entry No."; Rec."Entry No.")
                {
                    ApplicationArea = All;
                    Editable = false;
                }
                field("Product No."; Rec."Product No.")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.InitializeFromProduct(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Calculation Date"; Rec."Calculation Date")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.ClearFreightRate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Vendor No."; Rec."Vendor No.")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        Rec."Vendor Location Code" := '';
                        CostMgt.ClearFreightRate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Vendor Name"; Rec."Vendor Name")
                {
                    ApplicationArea = All;
                }
                field("Vendor Location Code"; Rec."Vendor Location Code")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.ClearFreightRate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("FOB City"; Rec."FOB City")
                {
                    ApplicationArea = All;
                }
                field("FOB State/Province"; Rec."FOB State/Province")
                {
                    ApplicationArea = All;
                }
                field("Destination State"; Rec."Destination State")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.ClearFreightRate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field(Mode; Rec.Mode)
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.ClearFreightRate(Rec);
                        CurrPage.Update(false);
                    end;
                }
            }
            group(Shipment)
            {
                field(Quantity; Rec.Quantity)
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Gram Weight"; Rec."Gram Weight")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Shipment CWT"; Rec."Shipment CWT")
                {
                    ApplicationArea = All;
                }
                field("No. of Pallets"; Rec."No. of Pallets")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Unit Cost"; Rec."Unit Cost")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Pallet Cost per Pallet"; Rec."Pallet Cost per Pallet")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Pallet Cost per Unit"; Rec."Pallet Cost per Unit")
                {
                    ApplicationArea = All;
                }
            }
            group(Freight)
            {
                field("Use Freight Rate"; Rec."Use Freight Rate")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Freight Rate Entry No."; Rec."Freight Rate Entry No.")
                {
                    ApplicationArea = All;
                }
                field("Rate per CWT"; Rec."Rate per CWT")
                {
                    ApplicationArea = All;
                }
                field("Minimum Charge"; Rec."Minimum Charge")
                {
                    ApplicationArea = All;
                }
                field("Fuel Surcharge %"; Rec."Fuel Surcharge %")
                {
                    ApplicationArea = All;
                }
                field("Rate Freight Total"; Rec."Rate Freight Total")
                {
                    ApplicationArea = All;
                }
                field("Manual Freight Total"; Rec."Manual Freight Total")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Domestic Freight Total"; Rec."Domestic Freight Total")
                {
                    ApplicationArea = All;
                }
                field("Domestic Frt per Unit"; Rec."Domestic Frt per Unit")
                {
                    ApplicationArea = All;
                }
            }
            group(International)
            {
                field("Tariff %"; Rec."Tariff %")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Tariff per Unit"; Rec."Tariff per Unit")
                {
                    ApplicationArea = All;
                }
                field("Intl Freight Total"; Rec."Intl Freight Total")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Intl Freight per Unit"; Rec."Intl Freight per Unit")
                {
                    ApplicationArea = All;
                }
                field("Customs Total"; Rec."Customs Total")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Customs per Unit"; Rec."Customs per Unit")
                {
                    ApplicationArea = All;
                }
                field("Delivery Charge Total"; Rec."Delivery Charge Total")
                {
                    ApplicationArea = All;

                    trigger OnValidate()
                    begin
                        CostMgt.Recalculate(Rec);
                        CurrPage.Update(false);
                    end;
                }
                field("Delivery per Unit"; Rec."Delivery per Unit")
                {
                    ApplicationArea = All;
                }
            }
            group(Results)
            {
                field("Landed Cost per Unit"; Rec."Landed Cost per Unit")
                {
                    ApplicationArea = All;
                    Style = Strong;
                }
            }
        }
    }

    actions
    {
        area(Processing)
        {
            action(FindFreightRate)
            {
                ApplicationArea = All;
                Caption = 'Find Best Freight Rate';
                Image = Calculate;

                trigger OnAction()
                begin
                    CostMgt.ApplyBestFreightRate(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(Recalculate)
            {
                ApplicationArea = All;
                Caption = 'Recalculate';
                Image = Refresh;

                trigger OnAction()
                begin
                    CostMgt.Recalculate(Rec);
                    CurrPage.Update(false);
                end;
            }
            action(FreightRates)
            {
                ApplicationArea = All;
                Caption = 'Freight Rates';
                RunObject = page "GPI Pack Frt Rates";
            }
        }
    }

    var
        CostMgt: Codeunit "GPI Pack Cost Mgt";
}
