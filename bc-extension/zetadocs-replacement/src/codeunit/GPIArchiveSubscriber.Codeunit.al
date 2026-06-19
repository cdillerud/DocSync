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
        if Rec."Archive Status" = Rec."Archive Status"::Archived then
            exit;

        ArchiveInProgress := true;

        // Commit the completed email delivery before starting external file storage.
        // Re-read the committed entry and archive any sent document that has not yet
        // reached Archived status. Do not depend on xRec because Business Central can
        // surface the current status there during modal email completion.
        Commit();

        if CommittedLogEntry.Get(Rec."Entry No.") then begin
            if (CommittedLogEntry.Status = CommittedLogEntry.Status::Sent) and
               (CommittedLogEntry."Archive Status" <> CommittedLogEntry."Archive Status"::Archived)
            then begin
                ArchiveMgt.ArchiveDeliveryLog(CommittedLogEntry);
                Commit();
            end;
        end;

        ArchiveInProgress := false;
    end;

    var
        ArchiveInProgress: Boolean;
}
