codeunit 70517 "GPI Archive Subscriber"
{
    [EventSubscriber(ObjectType::Table, Database::"GPI Document Delivery Log", 'OnAfterModifyEvent', '', false, false)]
    local procedure DeliveryLogOnAfterModify(var Rec: Record "GPI Document Delivery Log"; var xRec: Record "GPI Document Delivery Log"; RunTrigger: Boolean)
    begin
        // Only queue from an intentional Modify(true), such as completing the email
        // editor. Archive status updates use Modify(false) and must not create another
        // background task.
        if not RunTrigger then
            exit;
        if Rec.Status <> Rec.Status::Sent then
            exit;
        if Rec."Archive Status" = Rec."Archive Status"::Archived then
            exit;

        if not TaskScheduler.CanCreateTask() then begin
            Rec."Archive Status" := Rec."Archive Status"::Failed;
            Rec."Last Archive Error" := CopyStr(
                'Business Central could not schedule the automatic SharePoint archive task. Use Retry SharePoint Archive or contact your administrator.',
                1,
                MaxStrLen(Rec."Last Archive Error"));
            Rec.Modify(false);
            exit;
        end;

        // The scheduled task is committed with the delivery transaction and then runs
        // in a separate background session. This keeps SharePoint I/O out of the modal
        // email editor transaction.
        TaskScheduler.CreateTask(
            Codeunit::"GPI Archive Task",
            0,
            true,
            CompanyName(),
            CurrentDateTime(),
            Rec.RecordId);
    end;
}
