import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  ExternalLink,
  FileText,
  FolderCheck,
  FolderSearch,
  Inbox,
  RefreshCw,
  Route,
  Search,
  ShieldCheck,
  Warehouse,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import api from "@/lib/api";

const KPI_SELECTOR = '[data-testid="stat-ingested-today"]';

const ROUTING_LABELS = {
  auto_routed: "Auto-routed",
  needs_review: "Needs review",
  unrouted: "Unrouted",
  filed: "Filed",
  manual_override: "Manual override",
  human_confirmed: "Human confirmed",
  suggested: "Suggested",
  assigned: "Assigned",
};

const ROUTING_COLORS = {
  auto_routed: "bg-emerald-500/15 text-emerald-400",
  filed: "bg-emerald-500/15 text-emerald-400",
  human_confirmed: "bg-sky-500/15 text-sky-400",
  manual_override: "bg-violet-500/15 text-violet-400",
  assigned: "bg-blue-500/15 text-blue-400",
  suggested: "bg-sky-500/15 text-sky-400",
  needs_review: "bg-amber-500/15 text-amber-400",
  unrouted: "bg-red-500/15 text-red-400",
};

const LANE_COLORS = {
  AP: "bg-blue-500/15 text-blue-400",
  Warehouse: "bg-violet-500/15 text-violet-400",
  Sales: "bg-emerald-500/15 text-emerald-400",
  Other: "bg-zinc-500/15 text-zinc-400",
};

const formatLabel = (value) => {
  if (!value) return "—";
  return String(value)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
};

const formatReceived = (value) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
};

const valueIncludes = (value, search) =>
  String(value || "").toLowerCase().includes(search);

function SummaryCard({ icon: Icon, label, value, tone = "text-foreground" }) {
  return (
    <div className="rounded-md border border-border/50 bg-muted/15 px-3 py-2">
      <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
        <Icon className={`h-3.5 w-3.5 ${tone}`} />
        {label}
      </div>
      <div className="mt-1 text-lg font-semibold tabular-nums">{value ?? 0}</div>
    </div>
  );
}

export default function TodayIntakeDrilldown() {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [payload, setPayload] = useState(null);
  const [lane, setLane] = useState("all");
  const [routing, setRouting] = useState("all");
  const [search, setSearch] = useState("");
  const boundNodes = useRef(new Map());

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.get("/dashboard/inbox-today", {
        params: { limit: 5000 },
      });
      setPayload(response.data);
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || "Unknown error";
      setError(`Failed to load today's intake: ${detail}`);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open) load();
  }, [open, load]);

  useEffect(() => {
    const bind = (node) => {
      if (!node || boundNodes.current.has(node)) return;

      const openDialog = () => setOpen(true);
      const handleKeyDown = (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          setOpen(true);
        }
      };

      node.setAttribute("role", "button");
      node.setAttribute("tabindex", "0");
      node.setAttribute("aria-label", "Open today's intake details");
      node.setAttribute("title", "Open today's classification and routing details");
      node.classList.add(
        "cursor-pointer",
        "rounded-md",
        "transition-colors",
        "hover:bg-muted/40",
        "focus:outline-none",
        "focus:ring-2",
        "focus:ring-primary/40",
        "-m-1",
        "p-1"
      );
      node.addEventListener("click", openDialog);
      node.addEventListener("keydown", handleKeyDown);
      boundNodes.current.set(node, { openDialog, handleKeyDown });
    };

    const bindVisibleKpi = () => document.querySelectorAll(KPI_SELECTOR).forEach(bind);
    bindVisibleKpi();

    const observer = new MutationObserver(bindVisibleKpi);
    observer.observe(document.body, { childList: true, subtree: true });

    return () => {
      observer.disconnect();
      boundNodes.current.forEach(({ openDialog, handleKeyDown }, node) => {
        node.removeEventListener("click", openDialog);
        node.removeEventListener("keydown", handleKeyDown);
      });
      boundNodes.current.clear();
    };
  }, []);

  const documents = payload?.documents || [];
  const normalizedSearch = search.trim().toLowerCase();
  const filteredDocuments = useMemo(() => {
    return documents.filter((doc) => {
      if (lane !== "all" && doc.lane !== lane) return false;
      if (routing !== "all" && doc.routing_status !== routing) return false;
      if (!normalizedSearch) return true;
      return [
        doc.file_name,
        doc.mailbox,
        doc.sender,
        doc.subject,
        doc.classification,
        doc.routing_status,
        doc.suggested_folder,
        doc.final_folder,
        doc.routing_reason,
        doc.vendor_or_customer,
        doc.status,
        doc.workflow_status,
      ].some((value) => valueIncludes(value, normalizedSearch));
    });
  }, [documents, lane, routing, normalizedSearch]);

  const openDocument = (doc) => {
    const classification = String(doc.classification || "").toLowerCase();
    const isSales = classification.includes("sales") || classification.includes("customer_po");
    const path = isSales
      ? `/review/${encodeURIComponent(doc.id)}`
      : `/documents/${encodeURIComponent(doc.id)}`;
    window.location.assign(path);
  };

  const summary = payload?.summary || {};

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="h-[88vh] w-[96vw] max-w-[96vw] grid-rows-[auto_auto_auto_minmax(0,1fr)] gap-0 overflow-hidden p-0">
        <DialogHeader className="border-b border-border/60 px-6 py-4 pr-12">
          <div className="flex items-start justify-between gap-4">
            <div>
              <DialogTitle className="flex items-center gap-2">
                <Inbox className="h-5 w-5 text-sky-400" />
                Today&apos;s Intake — Classification &amp; Routing
              </DialogTitle>
              <DialogDescription className="mt-1">
                {payload?.date || "Today"} · {payload?.timezone || "America/Chicago"} · excludes batch containers
              </DialogDescription>
            </div>
            <Button
              variant="outline"
              size="sm"
              className="mr-6 gap-1.5"
              onClick={load}
              disabled={loading}
              data-testid="today-drilldown-refresh"
            >
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </DialogHeader>

        <div className="grid grid-cols-2 gap-2 border-b border-border/40 px-6 py-3 sm:grid-cols-4 xl:grid-cols-7">
          <SummaryCard icon={Inbox} label="Received" value={summary.total} tone="text-sky-400" />
          <SummaryCard icon={FileText} label="AP" value={summary.ap} tone="text-blue-400" />
          <SummaryCard icon={Warehouse} label="Warehouse" value={summary.warehouse} tone="text-violet-400" />
          <SummaryCard icon={ShieldCheck} label="Auto-routed" value={summary.auto_routed} tone="text-emerald-400" />
          <SummaryCard icon={Clock3} label="Needs review" value={summary.needs_review} tone="text-amber-400" />
          <SummaryCard icon={AlertTriangle} label="Unrouted" value={summary.unrouted} tone="text-red-400" />
          <SummaryCard icon={FolderCheck} label="Filed" value={summary.filed} tone="text-emerald-400" />
        </div>

        <div className="flex flex-wrap items-center gap-2 border-b border-border/40 px-6 py-3">
          <div className="relative min-w-[260px] flex-1 max-w-md">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search file, mailbox, class, folder, reason..."
              className="h-8 pl-9 text-xs"
              data-testid="today-drilldown-search"
            />
          </div>

          <div className="flex items-center gap-1">
            {["all", "AP", "Warehouse", "Sales", "Other"].map((value) => (
              <Button
                key={value}
                variant={lane === value ? "default" : "outline"}
                size="sm"
                className="h-8 text-xs"
                onClick={() => setLane(value)}
              >
                {value === "all" ? "All lanes" : value}
              </Button>
            ))}
          </div>

          <select
            value={routing}
            onChange={(event) => setRouting(event.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs"
            data-testid="today-drilldown-routing-filter"
          >
            <option value="all">All routing</option>
            {Object.entries(ROUTING_LABELS).map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>

          <span className="ml-auto text-xs text-muted-foreground tabular-nums">
            Showing {filteredDocuments.length} of {payload?.total || 0}
          </span>
        </div>

        <div className="min-h-0 overflow-auto">
          {loading && !payload ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> Loading today&apos;s documents...
            </div>
          ) : error ? (
            <div className="m-6 rounded-md border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
              {error}
            </div>
          ) : filteredDocuments.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-sm text-muted-foreground">
              <FolderSearch className="mb-2 h-8 w-8 opacity-40" />
              No documents match the selected filters.
            </div>
          ) : (
            <table className="w-full min-w-[1420px] text-left text-xs">
              <thead className="sticky top-0 z-10 bg-background/95 backdrop-blur">
                <tr className="border-b border-border/60 text-muted-foreground">
                  <th className="px-4 py-2.5 font-medium">Received</th>
                  <th className="px-4 py-2.5 font-medium">Document</th>
                  <th className="px-4 py-2.5 font-medium">Mailbox / Lane</th>
                  <th className="px-4 py-2.5 font-medium">Classification</th>
                  <th className="px-4 py-2.5 font-medium">Routing</th>
                  <th className="px-4 py-2.5 font-medium">Suggested destination</th>
                  <th className="px-4 py-2.5 font-medium">Final destination</th>
                  <th className="px-4 py-2.5 font-medium">Workflow</th>
                  <th className="w-12 px-4 py-2.5"></th>
                </tr>
              </thead>
              <tbody>
                {filteredDocuments.map((doc) => (
                  <tr
                    key={doc.id}
                    className="cursor-pointer border-b border-border/30 align-top transition-colors hover:bg-muted/25"
                    onClick={() => openDocument(doc)}
                    data-testid={`today-doc-${doc.id}`}
                  >
                    <td className="whitespace-nowrap px-4 py-3 text-muted-foreground">
                      {formatReceived(doc.received_local || doc.received_utc)}
                    </td>
                    <td className="max-w-[260px] px-4 py-3">
                      <div className="flex items-start gap-2">
                        <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <div className="truncate font-medium text-foreground" title={doc.file_name}>
                            {doc.file_name}
                          </div>
                          <div className="mt-0.5 truncate text-[10px] text-muted-foreground" title={doc.vendor_or_customer || doc.sender}>
                            {doc.vendor_or_customer || doc.sender || "—"}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="max-w-[210px] px-4 py-3">
                      <div className="truncate text-foreground/90" title={doc.mailbox}>{doc.mailbox || "—"}</div>
                      {doc.mailbox_inferred && (
                        <div className="mt-0.5 text-[9px] text-muted-foreground">inferred from lane</div>
                      )}
                      <Badge className={`mt-1 px-1.5 py-0 text-[9px] ${LANE_COLORS[doc.lane] || LANE_COLORS.Other}`}>
                        {doc.lane}
                      </Badge>
                    </td>
                    <td className="max-w-[220px] px-4 py-3">
                      <div className="truncate font-medium" title={doc.classification}>{formatLabel(doc.classification)}</div>
                      <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                        <span>{doc.confidence_pct == null ? "No confidence" : `${doc.confidence_pct}% confidence`}</span>
                        {doc.classification_method && <span>· {formatLabel(doc.classification_method)}</span>}
                      </div>
                    </td>
                    <td className="max-w-[220px] px-4 py-3">
                      <Badge className={`px-1.5 py-0 text-[9px] ${ROUTING_COLORS[doc.routing_status] || ROUTING_COLORS.unrouted}`}>
                        {ROUTING_LABELS[doc.routing_status] || formatLabel(doc.routing_status)}
                      </Badge>
                      <div className="mt-1 line-clamp-2 text-[10px] text-muted-foreground" title={doc.routing_reason}>
                        {doc.routing_reason || doc.routing_source || "No routing reason recorded"}
                      </div>
                    </td>
                    <td className="max-w-[260px] px-4 py-3">
                      <div className="line-clamp-2 break-words text-foreground/85" title={doc.suggested_folder}>
                        {doc.suggested_folder || "—"}
                      </div>
                    </td>
                    <td className="max-w-[260px] px-4 py-3">
                      <div className="line-clamp-2 break-words text-foreground/85" title={doc.final_folder}>
                        {doc.final_folder || "—"}
                      </div>
                      {doc.filed && (
                        <div className="mt-1 flex items-center gap-1 text-[10px] text-emerald-400">
                          <CheckCircle2 className="h-3 w-3" /> Filed
                        </div>
                      )}
                    </td>
                    <td className="max-w-[180px] px-4 py-3">
                      <div className="truncate" title={doc.workflow_status || doc.status}>
                        {formatLabel(doc.workflow_status || doc.status)}
                      </div>
                      {doc.square9_stage && (
                        <div className="mt-1 flex items-center gap-1 text-[10px] text-muted-foreground">
                          <Route className="h-3 w-3" /> {formatLabel(doc.square9_stage)}
                        </div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <ExternalLink className="h-3.5 w-3.5 text-muted-foreground" />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
