codeunit 70718 "GPI UAT Sample Pack Tests"
{
    Subtype = Test;
    Permissions =
        tabledata Customer = rimd,
        tabledata Vendor = rimd,
        tabledata Item = rimd,
        tabledata Location = rimd,
        tabledata "Sales Header" = rimd,
        tabledata "Sales Line" = rimd,
        tabledata "Purchase Header" = rimd,
        tabledata "Purchase Line" = rimd,
        tabledata "Transfer Header" = rimd,
        tabledata "Transfer Line" = rimd,
        tabledata "GPI Document Delivery Log" = rimd;

    [Test]
    procedure SamplePackCreatesSevenReviewablePdfs()
    var
        SamplePack: Codeunit "GPI UAT Sample Pack";
        DeliveryLog: Record "GPI Document Delivery Log";
        PackId: Text[50];
        CountedEntries: Integer;
    begin
        PackId := SamplePack.GenerateSamplePack(false);

        DeliveryLog.SetRange("External Delivery ID", PackId);
        if not DeliveryLog.FindSet() then
            Error('The UAT sample pack did not create any Delivery Log entries.');

        repeat
            CountedEntries += 1;
            if DeliveryLog.Status <> DeliveryLog.Status::Ready then
                Error('UAT sample entry %1 is not Ready.', DeliveryLog."Entry No.");
            if DeliveryLog."Sender Policy" <> 'UAT Sample Pack' then
                Error('UAT sample entry %1 is missing the sample-pack marker.', DeliveryLog."Entry No.");
            if DeliveryLog."Attachment Filename" = '' then
                Error('UAT sample entry %1 has no attachment filename.', DeliveryLog."Entry No.");
            if CopyStr(DeliveryLog."Source Document No.", 1, 3) <> 'UAT' then
                Error('UAT sample entry %1 is not linked to a UAT source record.', DeliveryLog."Entry No.");

            DeliveryLog.CalcFields("Document Content");
            if not DeliveryLog."Document Content".HasValue then
                Error('UAT sample entry %1 has no stored PDF.', DeliveryLog."Entry No.");
        until DeliveryLog.Next() = 0;

        if CountedEntries <> 7 then
            Error('Expected 7 UAT sample PDFs but received %1.', CountedEntries);

        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Sales Return Authorization");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Sales Return Warehouse Notice");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Purchase Return Order");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Purchase Return Pick Ticket");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Transfer Pick List");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Transfer Receipt Notice");
        AssertDocumentTypeExists(PackId, Enum::"GPI Delivery Document Type"::"Customer Open Order Status");
    end;

    local procedure AssertDocumentTypeExists(PackId: Text[50]; DocumentType: Enum "GPI Delivery Document Type")
    var
        DeliveryLog: Record "GPI Document Delivery Log";
    begin
        DeliveryLog.SetRange("External Delivery ID", PackId);
        DeliveryLog.SetRange("Delivery Document Type", DocumentType);
        if DeliveryLog.IsEmpty() then
            Error('The UAT sample pack did not create %1.', DocumentType);
    end;
}
