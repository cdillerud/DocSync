codeunit 71131 "GPI Agent Trigger"
{
    [EventSubscriber(ObjectType::Table, Database::"GPI Pack Product", 'OnAfterModifyEvent', '', false, false)]
    local procedure OnPackProductModified(var Rec: Record "GPI Pack Product"; var xRec: Record "GPI Pack Product"; RunTrigger: Boolean)
    var
        Setup: Record "GPI Agent Setup";
        AgentMgt: Codeunit "GPI Comm Agent Mgt";
        IdempotencyKey: Text[100];
    begin
        if not IsSandbox() then
            exit;
        if not GetSetup(Setup) or not Setup."Cost Change Enabled" then
            exit;
        if Rec."Current Supplier Unit Cost" = xRec."Current Supplier Unit Cost" then
            exit;
        if Rec."BC Item No." = '' then
            exit;

        IdempotencyKey := CopyStr(
            StrSubstNo(
                'CC:%1:%2:%3',
                Rec."No.",
                Format(xRec."Current Supplier Unit Cost", 0, 9),
                Format(Rec."Current Supplier Unit Cost", 0, 9)),
            1,
            MaxStrLen(IdempotencyKey));

        AgentMgt.Enqueue(
            "GPI Comm Agent Type"::"Cost Change",
            'PackagingProduct',
            Rec.SystemId,
            Rec."No.",
            '',
            Rec."BC Item No.",
            'PackagingProduct',
            Rec."No.",
            70,
            IdempotencyKey);
    end;

    [EventSubscriber(ObjectType::Table, Database::"Sales Line", 'OnAfterInsertEvent', '', false, false)]
    local procedure OnSalesLineInserted(var Rec: Record "Sales Line"; RunTrigger: Boolean)
    begin
        EnqueueIncorrectItem(Rec);
    end;

    [EventSubscriber(ObjectType::Table, Database::"Sales Line", 'OnAfterModifyEvent', '', false, false)]
    local procedure OnSalesLineModified(var Rec: Record "Sales Line"; var xRec: Record "Sales Line"; RunTrigger: Boolean)
    begin
        if (Rec.Type = xRec.Type) and (Rec."No." = xRec."No.") and
           (Rec."Sell-to Customer No." = xRec."Sell-to Customer No.")
        then
            exit;

        EnqueueIncorrectItem(Rec);
    end;

    [EventSubscriber(ObjectType::Table, Database::"Sales Invoice Line", 'OnAfterInsertEvent', '', false, false)]
    local procedure OnSalesInvoiceLineInserted(var Rec: Record "Sales Invoice Line"; RunTrigger: Boolean)
    var
        Setup: Record "GPI Agent Setup";
        AgentMgt: Codeunit "GPI Comm Agent Mgt";
        IdempotencyKey: Text[100];
    begin
        if not IsSandbox() then
            exit;
        if not GetSetup(Setup) or not Setup."Low Margin Enabled" then
            exit;
        if Rec.Type <> Rec.Type::Item then
            exit;
        if (Rec."No." = '') or (Rec."Sell-to Customer No." = '') then
            exit;

        IdempotencyKey := CopyStr(
            StrSubstNo('LM:%1:%2', Rec."Document No.", Rec."Line No."),
            1,
            MaxStrLen(IdempotencyKey));

        AgentMgt.Enqueue(
            "GPI Comm Agent Type"::"Low Margin",
            'PostedSalesInvoiceLine',
            Rec.SystemId,
            StrSubstNo('%1:%2', Rec."Document No.", Rec."Line No."),
            Rec."Sell-to Customer No.",
            Rec."No.",
            'SalesInvoice',
            Rec."Document No.",
            80,
            IdempotencyKey);
    end;

    local procedure EnqueueIncorrectItem(SalesLine: Record "Sales Line")
    var
        Setup: Record "GPI Agent Setup";
        AgentMgt: Codeunit "GPI Comm Agent Mgt";
        IdempotencyKey: Text[100];
    begin
        if not IsSandbox() then
            exit;
        if not GetSetup(Setup) or not Setup."Incorrect Item Enabled" then
            exit;
        if SalesLine."Document Type" <> SalesLine."Document Type"::Order then
            exit;
        if SalesLine.Type <> SalesLine.Type::Item then
            exit;
        if (SalesLine."No." = '') or (SalesLine."Sell-to Customer No." = '') then
            exit;

        IdempotencyKey := CopyStr(
            StrSubstNo(
                'II:%1:%2:%3',
                SalesLine."Document No.",
                SalesLine."Line No.",
                SalesLine."No."),
            1,
            MaxStrLen(IdempotencyKey));

        AgentMgt.Enqueue(
            "GPI Comm Agent Type"::"Incorrect Item",
            'SalesOrderLine',
            SalesLine.SystemId,
            StrSubstNo('%1:%2', SalesLine."Document No.", SalesLine."Line No."),
            SalesLine."Sell-to Customer No.",
            SalesLine."No.",
            'SalesOrder',
            SalesLine."Document No.",
            60,
            IdempotencyKey);
    end;

    local procedure GetSetup(var Setup: Record "GPI Agent Setup"): Boolean
    begin
        exit(Setup.Get('SETUP'));
    end;

    local procedure IsSandbox(): Boolean
    var
        EnvironmentInformation: Codeunit "Environment Information";
    begin
        exit(EnvironmentInformation.IsSandbox());
    end;
}
