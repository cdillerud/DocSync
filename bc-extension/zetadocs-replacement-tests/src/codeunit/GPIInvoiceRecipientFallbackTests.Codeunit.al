codeunit 70719 "GPI Invoice Recipient Tests"
{
    Subtype = Test;

    Permissions =
        tabledata Customer = rimd,
        tabledata Contact = rimd,
        tabledata "GPI Document Routing Rule" = rimd;

    [Test]
    procedure PostedInvoiceFallsBackToCustomerCardEmail()
    var
        Customer: Record Customer;
        SalesInvoiceHeader: Record "Sales Invoice Header" temporary;
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRuleEntries: Text[250];
        CustomerNo: Code[20];
    begin
        DeleteInvoiceRoutingRules();
        CustomerNo := NewCode('INV');

        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'Invoice Card Email Test';
        Customer."E-Mail" := 'customer.card@example.com';
        Customer.Insert(false);

        SalesInvoiceHeader."Bill-to Customer No." := CustomerNo;

        DocumentPolicy.ResolvePostedInvoiceRecipients(
            SalesInvoiceHeader,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        AssertSingleRecipient(
            ToRecipients,
            'customer.card@example.com',
            'The posted invoice recipient did not fall back to the Customer Card E-Mail field.');
    end;

    [Test]
    procedure PostedInvoicePrimaryContactEmailTakesPrecedence()
    var
        Customer: Record Customer;
        Contact: Record Contact;
        SalesInvoiceHeader: Record "Sales Invoice Header" temporary;
        DocumentPolicy: Codeunit "GPI Document Policy Mgt.";
        ToRecipients: List of [Text];
        CCRecipients: List of [Text];
        BCCRecipients: List of [Text];
        AppliedRuleEntries: Text[250];
        CustomerNo: Code[20];
        ContactNo: Code[20];
    begin
        DeleteInvoiceRoutingRules();
        CustomerNo := NewCode('INV');
        ContactNo := NewCode('CON');

        Contact.Init();
        Contact."No." := ContactNo;
        Contact.Name := 'Invoice Primary Contact Test';
        Contact."E-Mail" := 'primary.contact@example.com';
        Contact.Insert(false);

        Customer.Init();
        Customer."No." := CustomerNo;
        Customer.Name := 'Invoice Primary Contact Customer';
        Customer."Primary Contact No." := ContactNo;
        Customer."E-Mail" := 'customer.card@example.com';
        Customer.Insert(false);

        SalesInvoiceHeader."Bill-to Customer No." := CustomerNo;

        DocumentPolicy.ResolvePostedInvoiceRecipients(
            SalesInvoiceHeader,
            ToRecipients,
            CCRecipients,
            BCCRecipients,
            AppliedRuleEntries);

        AssertSingleRecipient(
            ToRecipients,
            'primary.contact@example.com',
            'The Customer Card E-Mail field incorrectly replaced the primary-contact email.');
    end;

    local procedure DeleteInvoiceRoutingRules()
    var
        RoutingRule: Record "GPI Document Routing Rule";
    begin
        RoutingRule.SetRange(
            "Delivery Document Type",
            Enum::"GPI Delivery Document Type"::Invoice);
        RoutingRule.DeleteAll(false);
    end;

    local procedure AssertSingleRecipient(Recipients: List of [Text]; Expected: Text; FailureMessage: Text)
    begin
        if Recipients.Count() <> 1 then
            Error(
                '%1 Expected one recipient but received %2.',
                FailureMessage,
                Recipients.Count());

        if Recipients.Get(1) <> Expected then
            Error(
                '%1 Expected "%2" but received "%3".',
                FailureMessage,
                Expected,
                Recipients.Get(1));
    end;

    local procedure NewCode(Prefix: Text): Code[20]
    begin
        exit(CopyStr(Prefix + DelChr(Format(CreateGuid()), '=', '{}-'), 1, 20));
    end;
}