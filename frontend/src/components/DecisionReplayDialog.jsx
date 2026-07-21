import React, { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  History,
  Loader2,
  RefreshCw,
  Route,
  ShieldCheck,
  XCircle,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import api from "@/lib/api";

const formatLabel = (value) => {
  if (!value) return "—";
  return String(value)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const displayPath = (value) => {
  if (value === "" || value == null) return "Temp Folder";
  const path = String(value).replace(/^\/+/, "");
  return path ? `/${path}` : "Temp Folder";
};

function CandidateCard({ candidate }) {
  const accepted = candidate.status === "accepted";
  const rejected = candidate.status === "rejected";

  const detailParts = [
    candidate.method && formatLabel(candidate.method),
    candidate.details?.alias_source
      && `Alias: ${formatLabel(candidate.details.alias_source)}`,
    candidate.details?.score != null
      && `Score: ${candidate.details.score}`,
  ].filter(Boolean);

  return (
    <div
      className={`rounded-md border p-3 ${
        accepted
          ? "border-emerald-500/30 bg-emerald-500/5"
          : rejected
            ? "border-red-500/30 bg-red-500/5"
            : "border-border/50 bg-muted/10"
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-xs font-medium">
            {formatLabel(candidate.source)}
          </div>
          <div
            className="mt-1 truncate text-sm text-foreground"
            title={candidate.vendor_name}
          >
            {candidate.vendor_name || "No vendor name"}
          </div>
          {candidate.vendor_no && (
            <div className="mt-0.5 text-xs font-medium text-sky-400">
              {candidate.vendor_no}
            </div>
          )}
        </div>

        <Badge
          className={`shrink-0 px-1.5 py-0 text-[9px] ${
            accepted
              ? "bg-emerald-500/15 text-emerald-400"
              : rejected
                ? "bg-red-500/15 text-red-400"
                : "bg-zinc-500/15 text-zinc-400"
          }`}
        >
          {accepted && <CheckCircle2 className="mr-1 h-2.5 w-2.5" />}
          {rejected && <XCircle className="mr-1 h-2.5 w-2.5" />}
          {formatLabel(candidate.status)}
        </Badge>
      </div>

      <div className="mt-2 text-[10px] text-muted-foreground">
        {candidate.reason || "No reason recorded"}
      </div>

      {detailParts.length > 0 && (
        <div className="mt-1 text-[9px] text-muted-foreground/70">
          {detailParts.join(" · ")}
        </div>
      )}

      {candidate.authoritative && (
        <div className="mt-1 text-[9px] font-medium text-violet-400">
          Authoritative manual evidence
        </div>
      )}
    </div>
  );
}

function RoutingCard({
  title,
  icon: Icon,
  folder,
  reason,
  meta,
  tone = "text-muted-foreground",
}) {
  return (
    <div className="min-w-0 rounded-md border border-border/50 bg-muted/10 p-3">
      <div className={`flex items-center gap-1.5 text-xs font-medium ${tone}`}>
        <Icon className="h-3.5 w-3.5" />
        {title}
      </div>
      <div
        className="mt-2 break-words text-sm font-medium"
        title={folder}
      >
        {displayPath(folder)}
      </div>
      <div className="mt-1 min-h-[32px] text-[10px] text-muted-foreground">
        {reason || "No routing reason recorded"}
      </div>
      {meta && (
        <div className="mt-2 text-[9px] text-muted-foreground/70">
          {meta}
        </div>
      )}
    </div>
  );
}

function ValidationCheck({ check }) {
  const passed = Boolean(check.passed);

  return (
    <div className="flex items-start gap-2 rounded border border-border/40 px-2.5 py-2">
      {passed ? (
        <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
      ) : (
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-400" />
      )}
      <div className="min-w-0">
        <div className="text-xs font-medium">{formatLabel(check.check)}</div>
        <div className="mt-0.5 text-[10px] text-muted-foreground">
          {check.details || formatLabel(check.status)}
        </div>
      </div>
    </div>
  );
}

export default function DecisionReplayDialog({
  document,
  open,
  onOpenChange,
}) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [replay, setReplay] = useState(null);
  const [requestVersion, setRequestVersion] = useState(0);

  useEffect(() => {
    if (!open || !document?.id) return undefined;

    let cancelled = false;

    const loadReplay = async () => {
      setLoading(true);
      setError("");
      setReplay(null);

      try {
        const response = await api.get(
          `/documents/${encodeURIComponent(document.id)}/decision-replay`
        );

        if (!cancelled) {
          setReplay(response.data);
        }
      } catch (err) {
        if (!cancelled) {
          const detail =
            err.response?.data?.detail
            || err.message
            || "Unknown decision replay error";
          setError(`Failed to load decision replay: ${detail}`);
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    loadReplay();

    return () => {
      cancelled = true;
    };
  }, [open, document?.id, requestVersion]);

  const candidates = replay?.vendor_trace?.candidates || [];

  const acceptedCandidates = useMemo(
    () => candidates.filter((candidate) => candidate.status === "accepted"),
    [candidates]
  );

  const rejectedCandidates = useMemo(
    () => candidates.filter((candidate) => candidate.status === "rejected"),
    [candidates]
  );

  const resolution = replay?.vendor_trace?.resolution || {};
  const selected = resolution.selected || {};
  const evidence = replay?.document_evidence || {};
  const routing = replay?.current_rule_routing || {};
  const historical = replay?.historical_routing || {};
  const original = historical.original_suggestion || {};
  const finalFiling = historical.final_filing || {};
  const routingGate = historical.routing_gate_snapshot;
  const validationChecks =
    replay?.validation_trace?.local_safety_checks || [];

  const matchesFinal = routing.matches_historical_final;
  const noWrites = (replay?.writes?.performed || []).length === 0;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="grid h-[88vh] w-[94vw] max-w-6xl grid-rows-[auto_minmax(0,1fr)] gap-0 overflow-hidden p-0"
        data-testid="decision-replay-dialog"
      >
        <DialogHeader className="border-b border-border/60 px-6 py-4 pr-12">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <DialogTitle className="flex items-center gap-2">
                <ShieldCheck className="h-5 w-5 text-sky-400" />
                Decision Replay
              </DialogTitle>
              <DialogDescription className="mt-1 truncate">
                {replay?.file_name || document?.file_name || document?.id}
              </DialogDescription>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Badge className="bg-sky-500/15 text-sky-400">
                  Read-only local replay
                </Badge>
                {replay?.replay_version && (
                  <Badge className="bg-zinc-500/15 text-zinc-400">
                    {replay.replay_version}
                  </Badge>
                )}
                {noWrites && replay && (
                  <Badge className="bg-emerald-500/15 text-emerald-400">
                    <ShieldCheck className="mr-1 h-3 w-3" />
                    No writes performed
                  </Badge>
                )}
              </div>
            </div>

            <Button
              variant="outline"
              size="sm"
              className="mr-6 gap-1.5"
              disabled={loading}
              onClick={() => setRequestVersion((value) => value + 1)}
            >
              <RefreshCw
                className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
          </div>
        </DialogHeader>

        <div className="min-h-0 overflow-auto p-6">
          {loading ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Replaying document decisions...
            </div>
          ) : error ? (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {error}
            </div>
          ) : !replay ? (
            <div className="text-sm text-muted-foreground">
              No replay data loaded.
            </div>
          ) : (
            <div className="space-y-6">
              <section className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                <div className="rounded-md border border-border/50 bg-muted/10 p-3">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Extracted vendor
                  </div>
                  <div className="mt-1 text-sm font-medium">
                    {evidence.vendor_extracted || "No vendor extracted"}
                  </div>
                </div>

                <div className="rounded-md border border-border/50 bg-muted/10 p-3">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Safe resolution
                  </div>
                  <div className="mt-1 text-sm font-medium">
                    {selected.vendor_name || formatLabel(resolution.status)}
                  </div>
                  {selected.vendor_no && (
                    <div className="mt-0.5 text-xs text-sky-400">
                      {selected.vendor_no}
                    </div>
                  )}
                </div>

                <div className="rounded-md border border-border/50 bg-muted/10 p-3">
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Current route
                  </div>
                  <div className="mt-1 text-sm font-medium">
                    {routing.folder_path_display
                      || displayPath(routing.folder_path)}
                  </div>
                  <div className="mt-0.5 text-xs text-muted-foreground">
                    {formatLabel(routing.routing_status)}
                  </div>
                </div>

                <div
                  className={`rounded-md border p-3 ${
                    matchesFinal === false
                      ? "border-amber-500/30 bg-amber-500/5"
                      : "border-border/50 bg-muted/10"
                  }`}
                >
                  <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
                    Historical comparison
                  </div>
                  <div className="mt-1 flex items-center gap-1.5 text-sm font-medium">
                    {matchesFinal === true ? (
                      <>
                        <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                        Matches final filing
                      </>
                    ) : matchesFinal === false ? (
                      <>
                        <AlertTriangle className="h-4 w-4 text-amber-400" />
                        Rule differs from filing
                      </>
                    ) : (
                      <>
                        <Clock3 className="h-4 w-4 text-muted-foreground" />
                        No comparable filing
                      </>
                    )}
                  </div>
                </div>
              </section>

              <section>
                <div className="mb-3 flex items-center gap-2">
                  <ShieldCheck className="h-4 w-4 text-sky-400" />
                  <h3 className="text-sm font-semibold">Vendor evidence</h3>
                  <Badge className="bg-emerald-500/15 text-emerald-400">
                    {acceptedCandidates.length} accepted
                  </Badge>
                  <Badge className="bg-red-500/15 text-red-400">
                    {rejectedCandidates.length} rejected
                  </Badge>
                </div>

                <div className="grid gap-4 lg:grid-cols-2">
                  <div>
                    <div className="mb-2 text-xs font-medium text-emerald-400">
                      Accepted evidence
                    </div>
                    <div className="space-y-2">
                      {acceptedCandidates.length ? (
                        acceptedCandidates.map((candidate, index) => (
                          <CandidateCard
                            key={`${candidate.source}-${index}`}
                            candidate={candidate}
                          />
                        ))
                      ) : (
                        <div className="rounded border border-border/40 p-3 text-xs text-muted-foreground">
                          No evidence source was safely accepted.
                        </div>
                      )}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-xs font-medium text-red-400">
                      Rejected conflicting evidence
                    </div>
                    <div className="space-y-2">
                      {rejectedCandidates.length ? (
                        rejectedCandidates.map((candidate, index) => (
                          <CandidateCard
                            key={`${candidate.source}-${index}`}
                            candidate={candidate}
                          />
                        ))
                      ) : (
                        <div className="rounded border border-border/40 p-3 text-xs text-muted-foreground">
                          No conflicting evidence was detected.
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </section>

              <section>
                <div className="mb-3 flex items-center gap-2">
                  <Route className="h-4 w-4 text-violet-400" />
                  <h3 className="text-sm font-semibold">
                    Routing provenance
                  </h3>
                </div>

                <div className="grid items-stretch gap-2 lg:grid-cols-[1fr_auto_1fr_auto_1fr]">
                  <RoutingCard
                    title="Original suggestion"
                    icon={History}
                    folder={original.raw_folder_path}
                    reason={original.reason}
                    meta={[
                      original.capture_type
                        && formatLabel(original.capture_type),
                      original.source && formatLabel(original.source),
                    ].filter(Boolean).join(" · ")}
                    tone="text-sky-400"
                  />

                  <div className="hidden items-center justify-center lg:flex">
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  </div>

                  <RoutingCard
                    title="Current rule replay"
                    icon={Route}
                    folder={routing.folder_path}
                    reason={routing.routing_reason}
                    meta={[
                      routing.routing_status
                        && formatLabel(routing.routing_status),
                      routing.uses_vendor,
                      routing.uses_vendor_no,
                    ].filter(Boolean).join(" · ")}
                    tone={
                      matchesFinal === false
                        ? "text-amber-400"
                        : "text-violet-400"
                    }
                  />

                  <div className="hidden items-center justify-center lg:flex">
                    <ArrowRight className="h-4 w-4 text-muted-foreground" />
                  </div>

                  <RoutingCard
                    title="Final filing"
                    icon={CheckCircle2}
                    folder={finalFiling.raw_folder_path}
                    reason={
                      finalFiling.sharepoint_item_id
                        ? "Stored SharePoint filing"
                        : "No final filing recorded"
                    }
                    meta={finalFiling.filed_at}
                    tone="text-emerald-400"
                  />
                </div>

                {routingGate && (
                  <div className="mt-3 rounded-md border border-amber-500/20 bg-amber-500/5 p-3">
                    <div className="flex items-center gap-1.5 text-xs font-medium text-amber-400">
                      <History className="h-3.5 w-3.5" />
                      Post-filing routing gate snapshot
                    </div>
                    <div className="mt-1 text-xs">
                      {displayPath(routingGate.raw_folder_path)}
                    </div>
                    <div className="mt-1 text-[10px] text-muted-foreground">
                      {routingGate.reason}
                    </div>
                    <div className="mt-1 text-[9px] text-muted-foreground/70">
                      Non-comparable to the original filing decision
                    </div>
                  </div>
                )}
              </section>

              <section>
                <div className="mb-3 flex items-center gap-2">
                  <CheckCircle2 className="h-4 w-4 text-emerald-400" />
                  <h3 className="text-sm font-semibold">
                    Local safety checks
                  </h3>
                </div>

                <div className="grid gap-2 md:grid-cols-3">
                  {validationChecks.map((check) => (
                    <ValidationCheck key={check.check} check={check} />
                  ))}
                </div>
              </section>

              <section className="rounded-md border border-sky-500/20 bg-sky-500/5 p-4">
                <div className="flex items-center gap-2 text-sm font-medium text-sky-400">
                  <ShieldCheck className="h-4 w-4" />
                  Replay guardrails
                </div>
                <div className="mt-2 grid gap-1 text-xs text-muted-foreground sm:grid-cols-2 lg:grid-cols-5">
                  {Object.entries(replay.guardrails || {}).map(
                    ([key, value]) => (
                      <div key={key} className="flex items-center gap-1.5">
                        {value === false ? (
                          <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                        ) : (
                          <AlertTriangle className="h-3 w-3 text-amber-400" />
                        )}
                        {formatLabel(key)}
                      </div>
                    )
                  )}
                </div>
                <div className="mt-2 text-[10px] text-muted-foreground">
                  {replay.writes?.statement}
                </div>
              </section>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
