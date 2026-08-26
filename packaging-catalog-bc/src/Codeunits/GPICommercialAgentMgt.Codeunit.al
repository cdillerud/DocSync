codeunit 71120 "GPI Commercial Agent Mgt"
{
    procedure Enqueue(AgentType: Enum "GPI Commercial Agent Type"; SourceType: Text[50]; SourceSystemId: Guid; SourceKey: Text[100]; CustomerNo: Code[20]; ItemNo: Code[20]; DocumentType: Text[30]; DocumentNo: Code[20]; Priority: Integer; IdempotencyKey: Text[100]): Integer
    var
        Queue: Record "GPI Commercial Agent Queue";
        ExistingQueue: Record "GPI Commercial Agent Queue";
    begin
        if IdempotencyKey <> '' then begin
            ExistingQueue.SetRange("Agent Type", AgentType);
            ExistingQueue.SetRange("Idempotency Key", IdempotencyKey);
            ExistingQueue.SetFilter(Status, '%1|%2', ExistingQueue.Status::Pending, ExistingQueue.Status::Processing);
            if ExistingQueue.FindFirst() then
                exit(ExistingQueue."Entry No.");
        end;

        Queue.Init();
        Queue."Agent Type" := AgentType;
        Queue."Source Type" := SourceType;
        Queue."Source SystemId" := SourceSystemId;
        Queue."Source Key" := SourceKey;
        Queue."Customer No." := CustomerNo;
        Queue."Item No." := ItemNo;
        Queue."Document Type" := DocumentType;
        Queue."Document No." := DocumentNo;
        Queue.Status := Queue.Status::Pending;
        Queue.Priority := Priority;
        Queue."Requested At" := CurrentDateTime();
        Queue."Next Attempt At" := CurrentDateTime();
        Queue."Max Attempts" := 3;
        Queue."Correlation ID" := CreateGuid();
        Queue."Idempotency Key" := IdempotencyKey;
        Queue."Requested By" := CopyStr(UserId(), 1, MaxStrLen(Queue."Requested By"));
        Queue.Insert(true);

        exit(Queue."Entry No.");
    end;

    procedure TryStartNext(var Queue: Record "GPI Commercial Agent Queue"): Boolean
    var
        Candidate: Record "GPI Commercial Agent Queue";
    begin
        Candidate.SetCurrentKey(Status, Priority, "Requested At");
        Candidate.SetRange(Status, Candidate.Status::Pending);
        Candidate.SetFilter("Attempt Count", '<%1', Candidate."Max Attempts");
        Candidate.SetFilter("Next Attempt At", '..%1', CurrentDateTime());
        Candidate.Ascending(false);

        if not Candidate.FindSet(true) then
            exit(false);

        repeat
            Candidate.Status := Candidate.Status::Processing;
            Candidate."Started At" := CurrentDateTime();
            Candidate."Attempt Count" += 1;
            Candidate.Modify(true);
            Queue := Candidate;
            exit(true);
        until Candidate.Next() = 0;

        exit(false);
    end;

    procedure CreateException(Queue: Record "GPI Commercial Agent Queue"; Severity: Integer; RiskScore: Decimal; ConfidenceScore: Decimal; Summary: Text[250]; Finding: Text[2048]; RecommendedAction: Text[2048]; AIModel: Text[100]; EvaluationVersion: Code[20]; var CommercialException: Record "GPI Commercial Exception")
    begin
        CommercialException.Init();
        CommercialException."Agent Type" := Queue."Agent Type";
        CommercialException."Detected At" := CurrentDateTime();
        CommercialException."Source Type" := Queue."Source Type";
        CommercialException."Source SystemId" := Queue."Source SystemId";
        CommercialException."Source Key" := Queue."Source Key";
        CommercialException."Customer No." := Queue."Customer No.";
        CommercialException."Item No." := Queue."Item No.";
        CommercialException."Document Type" := Queue."Document Type";
        CommercialException."Document No." := Queue."Document No.";
        CommercialException.Severity := ClampInteger(Severity, 0, 100);
        CommercialException."Risk Score" := ClampDecimal(RiskScore, 0, 100);
        CommercialException."Confidence Score" := ClampDecimal(ConfidenceScore, 0, 100);
        CommercialException.Status := CommercialException.Status::New;
        CommercialException.Summary := Summary;
        CommercialException.Finding := Finding;
        CommercialException."Recommended Action" := RecommendedAction;
        CommercialException."AI Model" := AIModel;
        CommercialException."Evaluation Version" := EvaluationVersion;
        CommercialException."Correlation ID" := Queue."Correlation ID";
        CommercialException."Queue Entry No." := Queue."Entry No.";
        CommercialException."Created At" := CurrentDateTime();
        CommercialException."Updated At" := CurrentDateTime();
        CommercialException.Insert(true);
    end;

    procedure AddEvidence(ExceptionEntryNo: Integer; EvidenceType: Text[50]; SourceSystem: Text[30]; SourceRecordType: Text[50]; SourceSystemId: Guid; Metric: Code[50]; CurrentValue: Text[250]; ComparisonValue: Text[250]; Variance: Decimal; Unit: Code[20]; Weight: Decimal; Explanation: Text[1024]; Provenance: Text[250])
    var
        Evidence: Record "GPI Commercial Evidence";
        CommercialException: Record "GPI Commercial Exception";
    begin
        CommercialException.Get(ExceptionEntryNo);

        Evidence.Init();
        Evidence."Exception Entry No." := ExceptionEntryNo;
        Evidence."Evidence Type" := EvidenceType;
        Evidence."Source System" := SourceSystem;
        Evidence."Source Record Type" := SourceRecordType;
        Evidence."Source SystemId" := SourceSystemId;
        Evidence.Metric := Metric;
        Evidence."Current Value" := CurrentValue;
        Evidence."Comparison Value" := ComparisonValue;
        Evidence.Variance := Variance;
        Evidence.Unit := Unit;
        Evidence.Weight := ClampDecimal(Weight, 0, 100);
        Evidence.Explanation := Explanation;
        Evidence.Provenance := Provenance;
        Evidence."Captured At" := CurrentDateTime();
        Evidence.Insert(true);
    end;

    procedure MarkCompleted(var Queue: Record "GPI Commercial Agent Queue"; ExceptionEntryNo: Integer)
    begin
        Queue.Status := Queue.Status::Completed;
        Queue."Completed At" := CurrentDateTime();
        Queue."Exception Entry No." := ExceptionEntryNo;
        Clear(Queue."Last Error");
        Queue.Modify(true);
    end;

    procedure MarkFailed(var Queue: Record "GPI Commercial Agent Queue"; ErrorText: Text)
    begin
        Queue."Last Error" := CopyStr(ErrorText, 1, MaxStrLen(Queue."Last Error"));
        if Queue."Attempt Count" >= Queue."Max Attempts" then
            Queue.Status := Queue.Status::Failed
        else begin
            Queue.Status := Queue.Status::Pending;
            Queue."Next Attempt At" := CurrentDateTime();
        end;
        Queue.Modify(true);
    end;

    procedure RecordReview(var CommercialException: Record "GPI Commercial Exception"; NewStatus: Enum "GPI Commercial Ex Status"; Disposition: Text[50]; DecisionNote: Text[2048]; FalsePositive: Boolean)
    begin
        CommercialException.Status := NewStatus;
        CommercialException.Disposition := Disposition;
        CommercialException."Decision Note" := DecisionNote;
        CommercialException."False Positive" := FalsePositive;
        CommercialException."Reviewed By" := CopyStr(UserId(), 1, MaxStrLen(CommercialException."Reviewed By"));
        CommercialException."Reviewed At" := CurrentDateTime();
        CommercialException."Updated At" := CurrentDateTime();
        CommercialException.Modify(true);
    end;

    local procedure ClampInteger(Value: Integer; Minimum: Integer; Maximum: Integer): Integer
    begin
        if Value < Minimum then
            exit(Minimum);
        if Value > Maximum then
            exit(Maximum);
        exit(Value);
    end;

    local procedure ClampDecimal(Value: Decimal; Minimum: Decimal; Maximum: Decimal): Decimal
    begin
        if Value < Minimum then
            exit(Minimum);
        if Value > Maximum then
            exit(Maximum);
        exit(Value);
    end;
}
