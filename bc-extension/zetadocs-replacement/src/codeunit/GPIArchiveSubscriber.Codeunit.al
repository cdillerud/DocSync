codeunit 70517 "GPI Archive Subscriber"
{
    SingleInstance = true;

    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
    begin
        if ArchiveInProgress then
            exit;
        if Rec.Status <> Rec.Status::Sent then
            exit;
        if xRec.Status = xRec.Status::Sent then
            exit;

        ArchiveInProgress := true;
        ArchiveMgt.ArchiveDeliveryLog(Rec);
        ArchiveInProgress := false;
    end;

    var
        ArchiveInProgress: Boolean;
}
