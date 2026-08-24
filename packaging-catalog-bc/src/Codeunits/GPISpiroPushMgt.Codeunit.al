codeunit 71106 "GPI Spiro Push Mgt"
{
    procedure QueueQuoteLink(var Quote: Record "GPI Pack Quote")
    var
        PushQueue: Record "GPI Spiro Push Queue";
        ExistingQueue: Record "GPI Spiro Push Queue";
    begin
        Quote.TestField("GPI Spiro Opportunity ID");

        ExistingQueue.SetRange("Quote No.", Quote."Entry No.");
        ExistingQueue.SetRange(Status, 'Queued');
        if ExistingQueue.FindFirst() then
            Error('Packaging Quote %1 already has a queued Spiro writeback request.', Quote."Entry No.");

        if not Confirm(
            'Queue the Business Central link for Packaging Quote %1 to Spiro opportunity %2? The external Spiro integration worker will perform the write.',
            false,
            Quote."Entry No.",
            Quote."GPI Spiro Opportunity ID")
        then
            exit;

        PushQueue.Init();
        PushQueue."Quote No." := Quote."Entry No.";
        PushQueue."Spiro Opportunity ID" := Quote."GPI Spiro Opportunity ID";
        PushQueue.Status := 'Queued';
        PushQueue."Requested At" := CurrentDateTime();
        PushQueue."Requested By" := CopyStr(UserId(), 1, MaxStrLen(PushQueue."Requested By"));
        PushQueue.Message := 'Queued from Business Central for external Spiro writeback.';
        PushQueue.Insert(true);

        Quote."GPI Spiro Push Status" := 'Queued';
        Quote."GPI Spiro Push Message" := CopyStr(
            StrSubstNo('Queued request %1 for external Spiro writeback.', PushQueue."Entry No."),
            1,
            MaxStrLen(Quote."GPI Spiro Push Message"));
        Quote.Modify(true);
    end;
}