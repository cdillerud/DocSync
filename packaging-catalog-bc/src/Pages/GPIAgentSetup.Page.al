page 71130 "GPI Agent Setup"
{
    PageType = Card;
    SourceTable = "GPI Agent Setup";
    ApplicationArea = All;
    UsageCategory = Administration;
    Caption = 'Commercial Agent Setup';

    layout
    {
        area(Content)
        {
            group(Agents)
            {
                field("Low Margin Enabled"; Rec."Low Margin Enabled") { ApplicationArea = All; }
                field("Low Margin Floor %"; Rec."Low Margin Floor %") { ApplicationArea = All; }
                field("Margin Variance Pts"; Rec."Margin Variance Pts") { ApplicationArea = All; }
                field("Cost Change Enabled"; Rec."Cost Change Enabled") { ApplicationArea = All; }
                field("Cost Change Min %"; Rec."Cost Change Min %") { ApplicationArea = All; }
                field("Incorrect Item Enabled"; Rec."Incorrect Item Enabled") { ApplicationArea = All; }
                field("Similarity Threshold %"; Rec."Similarity Threshold %") { ApplicationArea = All; }
            }
            group(Audit)
            {
                field("Last Modified At"; Rec."Last Modified At") { ApplicationArea = All; }
                field("Last Modified By"; Rec."Last Modified By") { ApplicationArea = All; }
            }
        }
    }

    trigger OnOpenPage()
    begin
        EnsureSandbox();
        EnsureSetup();
    end;

    local procedure EnsureSetup()
    begin
        if Rec.Get('SETUP') then
            exit;

        Rec.Init();
        Rec."Primary Key" := 'SETUP';
        Rec.Insert(true);
    end;

    local procedure EnsureSandbox()
    var
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        if not EnvironmentInformation.IsSandbox() then
            Error('Commercial Agent Setup is currently available only in a Business Central sandbox environment.');
    end;
}
