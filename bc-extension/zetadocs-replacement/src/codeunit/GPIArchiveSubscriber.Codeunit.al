codeunit 70517 "GPI Archive Subscriber"
{
    SingleInstance = true;

    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    var
        ArchiveMgt: Codeunit "GPI SharePoint Archive";
        CommittedLogEntry: Record "GPI Document Delivery Log";
    begin
        if ArchiveInProgress then
            exit;
        if Rec.Status <> Rec.Status::Sent then
            exit;
        if xRec.Status = xRec.Status::Sent then
            exit;

        ArchiveInProgress := true;

        // Commit the completed email delivery before starting external file storage.
        // This prevents the SharePoint upload from being left in Pending while the
        // email editor transaction is still finishing.
        Commit();

        if CommittedLogEntry.Get(Rec."Entry No.") then begin
            ArchiveMgt.ArchiveDeliveryLog(CommittedLogEntry);
            Commit();
        end;

        ArchiveInProgress := false;
    end;

    var
        ArchiveInProgress: Boolean;
}
