codeunit 70526 "GPI Archive Task"
{
    TableNo = "GPI Document Delivery Log";

    Permissions =
        tabledata "GPI Document Delivery Log" = rm,
        tabledata "GPI SharePoint Archive Setup" = r;

    trigger OnRun()
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        if Rec.Status <> Rec.Status::Sent then
            exit;
        if Rec."Archive Status" = Rec."Archive Status"::Archived then
            exit;

        ArchiveMgt.ArchiveDeliveryLog(Rec);
    end;
}
