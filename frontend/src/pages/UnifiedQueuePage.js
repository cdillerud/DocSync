import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import {
  Search, RefreshCw, FileText, ChevronRight, Trash2, Play,
  Receipt, ShoppingCart, Inbox, FolderInput, Brain,
  TrendingUp, ShieldCheck, AlertTriangle, Clock, CheckCircle2,
  RotateCcw, Layers, ChevronDown, ChevronUp, BarChart3,
  User, FileQuestion, Ban, Copy, Zap, XCircle,
} from "lucide-react";
import api, { bulkResubmitDocuments, bulkDeleteDocuments, deleteDocument, bulkFileAndClear, batchAutoResolve, triggerAutoResolve } from "@/lib/api";

// ── Type / Status display helpers ──

const TYPE_LABELS = {
  AP_Invoice: "AP Invoice", AP_INVOICE: "AP Invoice",
  Purchase_Order: "Purchase Order", PURCHASE_ORDER: "Purchase Order",
  Remittance: "Remittance", REMITTANCE: "Remittance",
  Credit_Memo: "Credit Memo", PURCHASE_CREDIT_MEMO: "Purchase Credit",
  Sales_Order: "Sales Order", SALES_ORDER: "Sales Order",
  Sales_PO: "Sales PO", Sales_Quote: "Sales Quote",
  Order_Confirmation: "Order Confirm", SALES_INVOICE: "Sales Invoice",
  Freight_Document: "Freight Doc", Shipping_Document: "Shipping Doc",
  Warehouse_Receipt: "Warehouse", BOL: "BOL", Packing_List: "Packing List",
  Unknown_Document: "Unknown", Other: "Other", PurchaseOrder: "Purchase Order",
};

const STATUS_LABELS = {
  captured: "Captured", received: "Received", Received: "Received",
  classified: "Classified", Classified: "Classified",
  extracted: "Extracted", processed: "Processed",
  NeedsReview: "Needs Review", needs_review: "Needs Review",
  pending_review: "Pending Review", vendor_pending: "Vendor Pending",
  bc_validation_pending: "BC Validation",
  ready_for_approval: "Ready", approved: "Approved",
  ValidationPassed: "Validated", Validated: "Validated", validated: "Validated",
  LinkedToBC: "Linked to BC",
  rejected: "Rejected", exported: "Exported",
  Completed: "Completed", completed: "Completed",
  AutoFiled: "Auto-Filed", auto_filed: "Auto-Filed",
  bounds_review: "Qty Review",
  Posted: "Posted", posted: "Posted",
  Archived: "Archived", archived: "Archived",
  Exception: "Exception", batch_parent: "Batch",
  auto_approved: "Approved",
  ReadyForPost: "Ready to Post", ready_for_post: "Ready to Post",
  Failed: "Failed",
};

const getStatusColor = (status) => {
  const s = (status || "").toLowerCase();
  if (s.includes("ready_for_post") || s === "readyforpost") return "bg-emerald-500/15 text-emerald-400";
  if (s.includes("complete") || s.includes("posted") || s.includes("approved") || s.includes("exported") || s === "validated" || s === "validationpassed") return "bg-emerald-500/15 text-emerald-400";
  if (s.includes("bounds") || s.includes("exception") || s.includes("rejected") || s.includes("fail")) return "bg-red-500/15 text-red-400";
  if (s.includes("review") || s.includes("pending") || s.includes("vendor")) return "bg-amber-500/15 text-amber-400";
  if (s.includes("classif") || s.includes("extract") || s.includes("linked") || s.includes("captured")) return "bg-sky-500/15 text-sky-400";
  return "bg-zinc-500/15 text-zinc-400";
};

const getTypeColor = (type) => {
  const t = (type || "").toLowerCase();
  if (t.includes("ap") || t.includes("purchase")) return "bg-blue-500/15 text-blue-400";
  if (t.includes("sales") || t.includes("order_confirm")) return "bg-emerald-500/15 text-emerald-400";
  if (t.includes("credit") || t.includes("remittance")) return "bg-orange-500/15 text-orange-400";
  if (t.includes("freight") || t.includes("ship") || t.includes("bol") || t.includes("pack")) return "bg-violet-500/15 text-violet-400";
  return "bg-zinc-500/15 text-zinc-400";
};

// Workflow categories for tab filtering
const AP_TYPES = ["AP_Invoice", "AP_INVOICE", "Purchase_Order", "PURCHASE_ORDER", "Remittance", "REMITTANCE", "Credit_Memo", "PURCHASE_CREDIT_MEMO"];
const SALES_TYPES = ["Sales_Order", "SALES_ORDER", "Sales_PO", "Sales_Quote", "Order_Confirmation", "SALES_INVOICE", "SALES_CREDIT_MEMO", "PurchaseOrder", "Purchase_Order"];

// Terminal statuses — docs that are "done"
const TERMINAL_STATUSES = ["Completed", "Posted", "Archived", "completed", "posted", "archived",
  "exported", "auto_filed", "AutoFiled", "Validated", "validated", "ValidationPassed",
  "ReadyForPost", "ready_for_post", "LinkedToBC", "Exception", "exception"];
const DONE_WORKFLOW_STATUSES = ["completed", "exported", "validation_passed", "processed", "exception_review", "po_pending"];

function isTerminal(doc) {
  const s = (doc.status || "").toLowerCase();
  const ws = (doc.workflow_status || "").toLowerCase();
  if (s === "batch_parent") return false; // containers, not processed work
  return TERMINAL_STATUSES.some(t => t.toLowerCase() === s) ||
         DONE_WORKFLOW_STATUSES.some(t => t.toLowerCase() === ws) ||
         doc.auto_cleared === true;
}

export default function UnifiedQueuePage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [selectedDocs, setSelectedDocs] = useState(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [counts, setCounts] = useState({ all: 0, accounting: 0, sales: 0, processed: 0, batches: 0, exceptions: 0, po_pending: 0 });
  const [stats, setStats] = useState(null);
  const [reprocessing, setReprocessing] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [metricsOpen, setMetricsOpen] = useState(false);

  // ── Fetch Inbox Stats ──
  useEffect(() => {
    let cancelled = false;
    const fetchStats = async () => {
      try {
        const res = await api.get('/dashboard/inbox-stats');
        if (!cancelled) setStats(res.data);
      } catch { /* silent — stats are non-critical */ }
    };
    const fetchMetrics = async () => {
      try {
        const res = await api.get('/dashboard/inbox-metrics');
        if (!cancelled) setMetrics(res.data);
      } catch { /* silent */ }
    };
    fetchStats();
    fetchMetrics();
    const interval = setInterval(() => { fetchStats(); fetchMetrics(); }, 60000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // ── Fetch Documents ──
  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      const isProcessedTab = activeTab === "processed";
      const isBatchesTab = activeTab === "batches";
      const isExceptionsTab = activeTab === "exceptions";
      const isPoPendingTab = activeTab === "po_pending";
      const params = new URLSearchParams();
      if (searchQuery) params.append("search", searchQuery);
      params.append("limit", "500");

      if (isExceptionsTab) {
        const exRes = await api.get(`/readiness/exception-queue?limit=500`);
        setDocuments(exRes.data.documents || []);
        setSelectedDocs(new Set());
        setLoading(false);
        return;
      }

      if (isPoPendingTab) {
        const poRes = await api.get(`/readiness/po-pending?limit=500`);
        setDocuments(poRes.data.documents || []);
        setSelectedDocs(new Set());
        setLoading(false);
        return;
      }

      if (isProcessedTab || isBatchesTab) {
        // Show all docs, then filter client-side
        params.append("queue_view", "false");
        params.append("include_cleared", "true");
      } else {
        // Active work: hide completed/exported/archived
        params.append("queue_view", "true");
        params.append("include_cleared", "false");
      }

      // Tab-level type filtering
      if (activeTab === "accounting") {
        params.append("document_types", AP_TYPES.join(","));
      } else if (activeTab === "sales") {
        params.append("document_types", SALES_TYPES.join(","));
      }

      const response = await api.get(`/documents?${params.toString()}`);
      let docs = response.data.documents || [];

      if (isProcessedTab) {
        docs = docs.filter(isTerminal);
      } else if (isBatchesTab) {
        docs = docs.filter(d => d.status === "batch_parent");
      }

      setDocuments(docs);
      setSelectedDocs(new Set());

      // Fetch counts for all tabs (only when on "all" tab to avoid excessive calls)
      if (activeTab === "all") {
        const activeDocs = docs;
        const apCount = activeDocs.filter(d => AP_TYPES.includes(d.document_type || d.doc_type)).length;
        const salesCount = activeDocs.filter(d => SALES_TYPES.includes(d.document_type || d.doc_type)).length;
        const processedCount = response.data.counts?.completed || 0;
        // Fetch batch count and exception count
        try {
          const [batchRes, exRes, poRes] = await Promise.all([
            api.get('/documents?limit=0&queue_view=false&include_cleared=true&status=batch_parent'),
            api.get('/readiness/exception-queue?limit=0'),
            api.get('/readiness/po-pending?limit=0'),
          ]);
          setCounts({
            all: activeDocs.length, accounting: apCount, sales: salesCount,
            processed: processedCount, batches: batchRes.data.total || 0,
            exceptions: exRes.data.total || 0, po_pending: poRes.data.total || 0,
          });
        } catch {
          setCounts({ all: activeDocs.length, accounting: apCount, sales: salesCount, processed: processedCount, batches: 0, exceptions: 0, po_pending: 0 });
        }
      }
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [searchQuery, activeTab]);

  useEffect(() => { fetchDocuments(); }, [fetchDocuments]);

  // ── Selection ──
  const toggleSelectAll = () => {
    setSelectedDocs(prev => prev.size === documents.length ? new Set() : new Set(documents.map(d => d.id)));
  };
  const toggleSelect = (docId) => {
    setSelectedDocs(prev => {
      const next = new Set(prev);
      next.has(docId) ? next.delete(docId) : next.add(docId);
      return next;
    });
  };

  // ── Bulk Actions (preserved from original — no logic changes) ──
  const handleBulkRetry = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`Retry ${selectedDocs.size} document(s)?`)) return;
    setBulkProcessing(true);
    try {
      const results = await bulkResubmitDocuments([...selectedDocs]);
      toast.success(`Retried ${results.success.length}. ${results.failed.length} failed.`);
      setSelectedDocs(new Set());
      fetchDocuments();
    } catch (err) { toast.error('Retry failed: ' + err.message); }
    finally { setBulkProcessing(false); }
  };

  const handleBulkDelete = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`Delete ${selectedDocs.size} document(s)?`)) return;
    setBulkProcessing(true);
    try {
      const results = await bulkDeleteDocuments([...selectedDocs]);
      toast.success(`Deleted ${results.success.length}. ${results.failed.length} failed.`);
      setSelectedDocs(new Set());
      fetchDocuments();
    } catch (err) { toast.error('Delete failed: ' + err.message); }
    finally { setBulkProcessing(false); }
  };

  const handleBulkFile = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`File ${selectedDocs.size} document(s)?`)) return;
    setBulkProcessing(true);
    try {
      const res = await bulkFileAndClear([...selectedDocs]);
      const results = res.data || res;
      toast.success(`Filed ${results.success?.length || 0}. ${results.failed?.length || 0} failed.`);
      setSelectedDocs(new Set());
      fetchDocuments();
    } catch (err) { toast.error('File failed: ' + (err.response?.data?.detail || err.message)); }
    finally { setBulkProcessing(false); }
  };

  const handleBulkRefIntel = async () => {
    const useSelected = selectedDocs.size > 0;
    const msg = useSelected ? `Run Ref Intel on ${selectedDocs.size} docs?` : 'Run Ref Intel on all unprocessed docs?';
    if (!window.confirm(msg)) return;
    setBulkProcessing(true);
    try {
      if (useSelected) {
        let ok = 0;
        for (const docId of selectedDocs) { try { await triggerAutoResolve(docId); ok++; } catch {} }
        toast.success(`Queued ${ok} docs for ref intel.`);
      } else {
        const res = await batchAutoResolve('not_run', 500);
        toast.success(`Queued ${(res.data || res).enqueued || 0} docs.`);
      }
      setSelectedDocs(new Set());
      setTimeout(fetchDocuments, 3000);
    } catch (err) { toast.error('Ref intel failed'); }
    finally { setBulkProcessing(false); }
  };

  const handleSingleDelete = async (e, docId, fileName) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${fileName}"?`)) return;
    try { await deleteDocument(docId); toast.success('Deleted'); fetchDocuments(); }
    catch (err) { toast.error('Delete failed'); }
  };

  // ── Helpers ──
  const getVendorOrCustomer = (doc) => {
    return doc.vendor_canonical || doc.customer_name ||
      doc.extracted_fields?.vendor_name || doc.extracted_fields?.customer_name ||
      doc.extracted_fields?.customer || doc.extracted_fields?.vendor ||
      doc.normalized_fields?.vendor_name || doc.normalized_fields?.customer_name || '';
  };

  const getDocStatus = (doc) => {
    if (doc.bounds_alert) return 'bounds_review';
    return doc.workflow_status || doc.status || 'received';
  };

  const handleReprocessBatch = async (e, docId) => {
    e.stopPropagation();
    if (reprocessing) return;
    setReprocessing(docId);
    try {
      const res = await api.post(`/documents/${docId}/reprocess-batch`);
      toast.success(`Re-processing started: ${res.data.page_count} pages through full pipeline`);
      // Poll for completion
      const pollInterval = setInterval(async () => {
        try {
          const statusRes = await api.get(`/documents/${docId}/split-status`);
          if (statusRes.data.split_complete) {
            clearInterval(pollInterval);
            setReprocessing(null);
            toast.success('Batch re-processing complete');
            fetchDocuments();
          }
        } catch { /* continue polling */ }
      }, 5000);
      // Stop polling after 5 minutes
      setTimeout(() => { clearInterval(pollInterval); setReprocessing(null); }, 300000);
    } catch (err) {
      toast.error(`Re-process failed: ${err.response?.data?.detail || err.message}`);
      setReprocessing(null);
    }
  };

  const hasSelections = selectedDocs.size > 0;

  // ── Render ──
  return (
    <div className="space-y-5" data-testid="unified-queue-page">
      {/* ─── Search + Actions Bar ─── */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by name, vendor, PO#..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-10 h-9 bg-muted/30 border-border/50"
            data-testid="search-input"
          />
        </div>
        <div className="flex items-center gap-1.5 ml-auto">
          {hasSelections && (
            <div className="flex items-center gap-1.5 mr-2 px-2.5 py-1 bg-primary/10 rounded-md">
              <span className="text-xs font-medium">{selectedDocs.size} selected</span>
              <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => setSelectedDocs(new Set())} data-testid="clear-selection">
                <RefreshCw className="w-3 h-3" />
              </Button>
            </div>
          )}
          {hasSelections && (
            <>
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" onClick={handleBulkRetry} disabled={bulkProcessing} data-testid="bulk-retry-btn">
                <Play className="w-3 h-3" /> Retry
              </Button>
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" onClick={handleBulkFile} disabled={bulkProcessing} data-testid="bulk-file-btn">
                <FolderInput className="w-3 h-3" /> File
              </Button>
              <Button variant="outline" size="sm" className="h-8 text-xs gap-1" onClick={handleBulkRefIntel} disabled={bulkProcessing} data-testid="bulk-ref-intel-btn">
                <Brain className="w-3 h-3" /> Ref Intel
              </Button>
              <Button variant="destructive" size="sm" className="h-8 text-xs gap-1" onClick={handleBulkDelete} disabled={bulkProcessing} data-testid="bulk-delete-btn">
                <Trash2 className="w-3 h-3" /> Delete
              </Button>
              <div className="w-px h-6 bg-border mx-1" />
            </>
          )}
          <Button variant="ghost" size="sm" className="h-8 text-xs gap-1" onClick={() => { fetchDocuments(); toast.success("Refreshed"); }} data-testid="refresh-btn">
            <RefreshCw className="w-3.5 h-3.5" /> Refresh
          </Button>
        </div>
      </div>

      {/* ─── Inline Stats Strip ─── */}
      {stats && (
        <div className="flex items-center gap-6 px-1 py-2 text-xs" data-testid="inbox-stats-strip">
          <div className="flex items-center gap-1.5" data-testid="stat-ingested-today">
            <TrendingUp className="w-3.5 h-3.5 text-sky-400" />
            <span className="text-muted-foreground">Today</span>
            <span className="font-semibold text-foreground">{stats.ingested_today}</span>
            <span className="text-muted-foreground/60">({stats.avg_daily_7d}/d avg)</span>
          </div>
          <div className="w-px h-4 bg-border/40" />
          <div className="flex items-center gap-1.5" data-testid="stat-auto-rate">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-muted-foreground">Auto-validated</span>
            <span className="font-semibold text-foreground">{stats.auto_validation_rate}%</span>
          </div>
          <div className="w-px h-4 bg-border/40" />
          <div className="flex items-center gap-1.5" data-testid="stat-pending">
            <Clock className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-muted-foreground">Pending review</span>
            <span className="font-semibold text-foreground">{stats.pending_review}</span>
          </div>
          {stats.bounds_alerts > 0 && (
            <>
              <div className="w-px h-4 bg-border/40" />
              <div className="flex items-center gap-1.5" data-testid="stat-bounds-alerts">
                <AlertTriangle className="w-3.5 h-3.5 text-red-400" />
                <span className="text-muted-foreground">Qty alerts</span>
                <span className="font-semibold text-red-400">{stats.bounds_alerts}</span>
              </div>
            </>
          )}
          <div className="w-px h-4 bg-border/40" />
          <div className="flex items-center gap-1.5" data-testid="stat-ai-confidence">
            <span className="text-muted-foreground">AI confidence</span>
            <span className="font-semibold text-foreground">{stats.avg_ai_confidence}%</span>
          </div>
          <div className="w-px h-4 bg-border/40" />
          <button
            onClick={() => setMetricsOpen(p => !p)}
            className="flex items-center gap-1 text-muted-foreground hover:text-foreground transition-colors"
            data-testid="toggle-inbox-metrics"
          >
            <BarChart3 className="w-3.5 h-3.5" />
            <span>Details</span>
            {metricsOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
        </div>
      )}

      {/* ─── Inbox Metrics Panel (Collapsible) ─── */}
      {metricsOpen && metrics && (
        <div className="grid grid-cols-5 gap-4 px-1 pb-3 text-xs animate-in fade-in slide-in-from-top-2 duration-200" data-testid="inbox-metrics-panel">
          {/* By Status */}
          <div className="space-y-1.5" data-testid="metrics-by-status">
            <div className="font-medium text-muted-foreground flex items-center gap-1"><Zap className="w-3 h-3" /> By Status</div>
            {Object.entries(metrics.by_status || {}).map(([s, c]) => (
              <div key={s} className="flex items-center justify-between gap-2">
                <span className="truncate text-foreground/80">{STATUS_LABELS[s] || s}</span>
                <span className="font-mono font-semibold text-foreground tabular-nums">{c}</span>
              </div>
            ))}
            {Object.keys(metrics.by_status || {}).length === 0 && <span className="text-muted-foreground/50">None</span>}
          </div>

          {/* By Type */}
          <div className="space-y-1.5" data-testid="metrics-by-type">
            <div className="font-medium text-muted-foreground flex items-center gap-1"><FileText className="w-3 h-3" /> By Type</div>
            {Object.entries(metrics.by_type || {}).map(([t, c]) => (
              <div key={t} className="flex items-center justify-between gap-2">
                <span className="truncate text-foreground/80">{TYPE_LABELS[t] || t}</span>
                <span className="font-mono font-semibold text-foreground tabular-nums">{c}</span>
              </div>
            ))}
            {Object.keys(metrics.by_type || {}).length === 0 && <span className="text-muted-foreground/50">None</span>}
          </div>

          {/* By Age */}
          <div className="space-y-1.5" data-testid="metrics-by-age">
            <div className="font-medium text-muted-foreground flex items-center gap-1"><Clock className="w-3 h-3" /> By Age</div>
            {[
              { key: "lt_1h", label: "< 1 hour", color: "text-emerald-400" },
              { key: "1h_24h", label: "1h – 24h", color: "text-sky-400" },
              { key: "24h_3d", label: "1 – 3 days", color: "text-amber-400" },
              { key: "gt_3d", label: "> 3 days", color: "text-red-400" },
            ].map(({ key, label, color }) => (
              <div key={key} className="flex items-center justify-between gap-2">
                <span className={`truncate ${color}`}>{label}</span>
                <span className="font-mono font-semibold text-foreground tabular-nums">{metrics.by_age?.[key] || 0}</span>
              </div>
            ))}
          </div>

          {/* By Vendor */}
          <div className="space-y-1.5" data-testid="metrics-by-vendor">
            <div className="font-medium text-muted-foreground flex items-center gap-1"><User className="w-3 h-3" /> Top Vendors</div>
            {(metrics.by_vendor || []).slice(0, 5).map((v, i) => (
              <div key={i} className="flex items-center justify-between gap-2">
                <span className="truncate text-foreground/80 max-w-[120px]">{v.vendor}</span>
                <span className="font-mono font-semibold text-foreground tabular-nums">{v.count}</span>
              </div>
            ))}
            {(metrics.by_vendor || []).length === 0 && <span className="text-muted-foreground/50">None</span>}
          </div>

          {/* By Blocker */}
          <div className="space-y-1.5" data-testid="metrics-by-blocker">
            <div className="font-medium text-muted-foreground flex items-center gap-1"><Ban className="w-3 h-3" /> Blockers</div>
            {[
              { key: "no_vendor", label: "No vendor", icon: User, color: "text-red-400" },
              { key: "no_extraction", label: "No extraction", icon: FileQuestion, color: "text-red-400" },
              { key: "low_confidence", label: "Low confidence", icon: AlertTriangle, color: "text-amber-400" },
              { key: "validation_failed", label: "Validation fail", icon: XCircle, color: "text-amber-400" },
              { key: "no_po", label: "No PO#", icon: FileText, color: "text-sky-400" },
              { key: "duplicate_flag", label: "Possible dupe", icon: Copy, color: "text-sky-400" },
            ].map(({ key, label, icon: Icon, color }) => {
              const val = metrics.by_blocker?.[key] || 0;
              if (val === 0) return null;
              return (
                <div key={key} className="flex items-center justify-between gap-2">
                  <span className={`flex items-center gap-1 truncate ${color}`}><Icon className="w-3 h-3 shrink-0" />{label}</span>
                  <span className="font-mono font-semibold text-foreground tabular-nums">{val}</span>
                </div>
              );
            })}
            {Object.values(metrics.by_blocker || {}).filter(v => typeof v === 'number' && v > 0).length === 0 && (
              <span className="text-emerald-400">All clear</span>
            )}
          </div>
        </div>
      )}

      {/* ─── Tabs: All | Accounting | Sales | Processed ─── */}
      <div className="flex items-center gap-1 border-b border-border/60">
        {[
          { key: "all", label: "All", icon: Inbox, count: counts.all },
          { key: "accounting", label: "Accounting", icon: Receipt, count: counts.accounting },
          { key: "sales", label: "Sales", icon: ShoppingCart, count: counts.sales },
          { key: "processed", label: "Processed", icon: CheckCircle2, count: counts.processed },
          { key: "batches", label: "Batches", icon: Layers, count: counts.batches },
          { key: "exceptions", label: "Exceptions", icon: AlertTriangle, count: counts.exceptions, accent: true },
          { key: "po_pending", label: "PO Pending", icon: Clock, count: counts.po_pending, accent: counts.po_pending > 0 },
        ].map(({ key, label, icon: Icon, count, accent }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            data-testid={`tab-${key}`}
            className={`flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border/60'
            }`}
          >
            <Icon className="w-3.5 h-3.5" />
            {label}
            {count > 0 && (
              <span className={`text-[10px] px-1.5 py-0 rounded-full ${
                accent && count > 0 ? 'bg-red-500/15 text-red-400' :
                activeTab === key ? 'bg-primary/15 text-primary' : 'bg-muted text-muted-foreground'
              }`}>
                {count}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ─── Document Table ─── */}
      <div className="rounded-lg border border-border/60 overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-muted-foreground text-sm">Loading...</div>
        ) : documents.length === 0 ? (
          <div className="p-12 text-center text-muted-foreground text-sm">
            <Inbox className="w-8 h-8 mx-auto mb-2 opacity-30" />
            No documents found
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/20 hover:bg-muted/20">
                <TableHead className="w-10 pl-4">
                  <Checkbox
                    checked={documents.length > 0 && selectedDocs.size === documents.length}
                    onCheckedChange={toggleSelectAll}
                    data-testid="select-all-checkbox"
                  />
                </TableHead>
                <TableHead className="font-medium">Document</TableHead>
                <TableHead className="font-medium">Vendor / Customer</TableHead>
                <TableHead className="font-medium">Type</TableHead>
                <TableHead className="font-medium">Status</TableHead>
                <TableHead className="font-medium">Date</TableHead>
                <TableHead className="w-16"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {documents.map((doc) => {
                const status = getDocStatus(doc);
                const docType = doc.document_type || doc.doc_type || "Unknown";
                const entity = getVendorOrCustomer(doc);
                return (
                  <TableRow
                    key={doc.id}
                    className={`cursor-pointer transition-colors hover:bg-muted/30 ${selectedDocs.has(doc.id) ? 'bg-primary/5' : ''}`}
                    onClick={() => {
                      // Sales POs → review page, everything else → document detail
                      const isSalesPO = SALES_TYPES.includes(docType);
                      navigate(isSalesPO ? `/review/${encodeURIComponent(doc.id)}` : `/documents/${encodeURIComponent(doc.id)}`);
                    }}
                    data-testid={`doc-row-${doc.id}`}
                  >
                    <TableCell className="pl-4" onClick={(e) => e.stopPropagation()}>
                      <Checkbox
                        checked={selectedDocs.has(doc.id)}
                        onCheckedChange={() => toggleSelect(doc.id)}
                        data-testid={`select-doc-${doc.id}`}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <FileText className="h-4 w-4 text-muted-foreground shrink-0" />
                        <div className="min-w-0">
                          <div className="font-medium text-sm truncate max-w-[220px] flex items-center gap-1.5">
                            {doc.file_name || "Unnamed"}
                            {doc.auto_cleared && (
                              <Badge className="bg-emerald-500/15 text-emerald-400 text-[9px] px-1 py-0 shrink-0">AUTO</Badge>
                            )}
                            {doc.bounds_alert && (
                              <Badge className="bg-red-500/15 text-red-400 text-[9px] px-1 py-0 shrink-0" data-testid={`bounds-flag-${doc.id}`}>QTY ALERT</Badge>
                            )}
                            {doc.status === "batch_parent" && doc.batch_children_count > 0 && (
                              <Badge className="bg-sky-500/15 text-sky-400 text-[9px] px-1 py-0 shrink-0">{doc.batch_children_count} pages</Badge>
                            )}
                          </div>
                          {doc.extracted_fields?.invoice_number && (
                            <div className="text-[11px] text-muted-foreground font-mono">
                              #{doc.extracted_fields.invoice_number}
                            </div>
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <span className="text-sm truncate block max-w-[180px]">{entity || "—"}</span>
                    </TableCell>
                    <TableCell>
                      <Badge className={`${getTypeColor(docType)} text-[10px] px-1.5 py-0`}>
                        {TYPE_LABELS[docType] || docType}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge className={`${getStatusColor(status)} text-[10px] px-1.5 py-0`}>
                        {STATUS_LABELS[status] || status}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-muted-foreground">
                        {doc.created_utc ? new Date(doc.created_utc).toLocaleDateString() : "—"}
                      </span>
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center gap-0.5">
                        {doc.status === "batch_parent" && (
                          <Button
                            variant="ghost" size="icon"
                            className="h-7 w-7 text-muted-foreground hover:text-sky-400"
                            onClick={(e) => handleReprocessBatch(e, doc.id)}
                            disabled={reprocessing === doc.id}
                            title="Re-process through full pipeline"
                            data-testid={`reprocess-batch-${doc.id}`}
                          >
                            <RotateCcw className={`h-3.5 w-3.5 ${reprocessing === doc.id ? 'animate-spin' : ''}`} />
                          </Button>
                        )}
                        <Button
                          variant="ghost" size="icon"
                          className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => handleSingleDelete(e, doc.id, doc.file_name)}
                          data-testid={`delete-doc-${doc.id}`}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50" />
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </div>
    </div>
  );
}
