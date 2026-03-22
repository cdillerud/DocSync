import React, { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Checkbox } from "@/components/ui/checkbox";
import { toast } from "sonner";
import { 
  Search, Filter, RefreshCw, FileText, Clock, CheckCircle2, 
  AlertCircle, Archive, ChevronRight, Inbox, FileCheck, Play, Trash2, Brain, Truck,
  CalendarDays, ShoppingCart, Receipt, Package, FolderInput
} from "lucide-react";

const INTEL_STATUS_CONFIG = {
  completed: { label: 'Resolved', cls: 'bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300' },
  ambiguous: { label: 'Ambiguous', cls: 'bg-amber-100 text-amber-700 border-amber-200 dark:bg-amber-900/30 dark:text-amber-300' },
  pending: { label: 'Pending', cls: 'bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300' },
  failed: { label: 'Failed', cls: 'bg-red-100 text-red-700 border-red-200 dark:bg-red-900/30 dark:text-red-300' },
  retry_scheduled: { label: 'Retry', cls: 'bg-orange-100 text-orange-700 border-orange-200 dark:bg-orange-900/30 dark:text-orange-300' },
  not_run: { label: 'Not Run', cls: 'bg-gray-100 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400' },
};
import api, { bulkResubmitDocuments, bulkDeleteDocuments, deleteDocument, bulkFileAndClear, batchAutoResolve, triggerAutoResolve } from "@/lib/api";
import BatchFreightClassifyDialog from "@/components/BatchFreightClassifyDialog";

// Document types and their display names (fallback labels for known types)
const DOC_TYPE_LABELS = {
  // AI classification types (canonical)
  AP_Invoice: "AP Invoice",
  AR_Invoice: "AR Invoice",
  Remittance: "Remittance",
  Freight_Document: "Freight Doc",
  Sales_Order: "Sales Order",
  Sales_PO: "Sales PO",
  Sales_Quote: "Sales Quote",
  Order_Confirmation: "Order Confirm",
  Purchase_Order: "Purchase Order",
  Warehouse_Receipt: "Warehouse Receipt",
  Warehouse_Document: "Warehouse Doc",
  Inventory_Report: "Inventory Report",
  Shipping_Document: "Shipping Doc",
  Quality_Issue: "Quality Issue",
  Inspection_Form: "Inspection Form",
  Return_Request: "Return Request",
  Unknown_Document: "Unknown",
  // Legacy BC-style types (fallback)
  AP_INVOICE: "AP Invoice",
  SALES_ORDER: "Sales Order",
  SALES_INVOICE: "Sales Invoice",
  PURCHASE_ORDER: "Purchase Order",
  PURCHASE_INVOICE: "Purchase Invoice",
  SALES_CREDIT_MEMO: "Sales Credit",
  PURCHASE_CREDIT_MEMO: "Purchase Credit",
  STATEMENT: "Statement",
  QUALITY_DOC: "Quality Doc",
  OTHER: "Other",
  Other: "Other",
  REMITTANCE: "Remittance",
  Credit_Memo: "Credit Memo",
  BOL: "BOL",
  Packing_List: "Packing List",
};

const getTypeLabel = (type) => DOC_TYPE_LABELS[type] || type;

// Workflow statuses (fallback labels for known statuses)
const STATUS_LABELS = {
  captured: "Captured",
  received: "Received",
  Received: "Received",
  classified: "Classified",
  Classified: "Classified",
  extracted: "Extracted",
  NeedsReview: "Needs Review",
  needs_review: "Needs Review",
  pending_review: "Pending Review",
  vendor_pending: "Vendor Pending",
  bc_validation_pending: "BC Validation",
  ready_for_approval: "Ready for Approval",
  approved: "Approved",
  ValidationPassed: "Validation Passed",
  Validated: "Validated",
  validated: "Validated",
  LinkedToBC: "Linked to BC",
  rejected: "Rejected",
  exported: "Exported",
  Completed: "Completed",
  completed: "Completed",
  FileMissing: "File Missing",
  file_missing: "File Missing",
  Posted: "Posted",
  posted: "Posted",
  Archived: "Archived",
  archived: "Archived",
  Exception: "Exception",
  StoredInSP: "Stored in SP",
};

const getStatusLabel = (status) => STATUS_LABELS[status] || status;

const getStatusBadge = (status) => {
  const label = getStatusLabel(status);
  const lower = (status || "").toLowerCase();
  const colorClass = lower.includes("complete") || lower.includes("posted") || lower.includes("approved") || lower.includes("exported") || lower === "validated" || lower === "validationpassed"
    ? "bg-green-500/20 text-green-400"
    : lower.includes("exception") || lower.includes("rejected") || lower.includes("fail")
    ? "bg-red-500/20 text-red-400"
    : lower.includes("review") || lower.includes("pending") || lower.includes("vendor")
    ? "bg-yellow-500/20 text-yellow-400"
    : lower.includes("classif") || lower.includes("extract") || lower.includes("linked")
    ? "bg-blue-500/20 text-blue-400"
    : "bg-gray-500/20 text-gray-400";
  return <Badge className={colorClass}>{label}</Badge>;
};

const getTypeBadge = (docType) => {
  const label = getTypeLabel(docType || "Unknown");
  const lower = (docType || "").toLowerCase();
  const colorClass = lower.includes("ap") || lower.includes("purchase")
    ? "bg-blue-500/20 text-blue-400"
    : lower.includes("sales") || lower.includes("order_confirm")
    ? "bg-green-500/20 text-green-400"
    : lower.includes("credit") || lower.includes("remittance")
    ? "bg-orange-500/20 text-orange-400"
    : lower.includes("ship") || lower.includes("freight") || lower.includes("bol") || lower.includes("pack")
    ? "bg-purple-500/20 text-purple-400"
    : lower.includes("quality")
    ? "bg-teal-500/20 text-teal-400"
    : "bg-gray-500/20 text-gray-400";
  return <Badge className={colorClass}>{label}</Badge>;
};

export default function UnifiedQueuePage() {
  const navigate = useNavigate();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);
  const [stats, setStats] = useState({ total: 0, by_status: {}, by_type: {} });
  
  // Filters
  const [docTypeFilter, setDocTypeFilter] = useState("ALL");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState("pending");
  const [workflowCategory, setWorkflowCategory] = useState("all");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [showCleared, setShowCleared] = useState(false);  // Toggle for auto-cleared docs
  const [queueCounts, setQueueCounts] = useState({ total_all: 0, auto_cleared: 0, pending_review: 0, completed: 0 });
  const [filterOptions, setFilterOptions] = useState({ types: [], statuses: [] });

  // Workflow category presets
  const WORKFLOW_CATEGORIES = {
    all: { label: "All Documents", types: [] },
    ap: { label: "AP Workflow", types: ["AP_Invoice", "AP_INVOICE", "Purchase_Order", "PURCHASE_ORDER", "Remittance", "REMITTANCE", "Credit_Memo", "PURCHASE_CREDIT_MEMO"] },
    sales: { label: "Sales Workflow", types: ["Sales_Order", "SALES_ORDER", "Sales_PO", "Sales_Quote", "Order_Confirmation", "SALES_INVOICE", "SALES_CREDIT_MEMO"] },
    ops: { label: "Operations", types: ["Freight_Document", "Shipping_Document", "Warehouse_Receipt", "Warehouse_Document", "Quality_Issue", "Inspection_Form", "BOL", "Packing_List"] },
  };
  
  // Selection for bulk actions
  const [selectedDocs, setSelectedDocs] = useState(new Set());
  const [bulkProcessing, setBulkProcessing] = useState(false);
  const [freightDialogOpen, setFreightDialogOpen] = useState(false);

  const fetchDocuments = useCallback(async () => {
    setLoading(true);
    try {
      // Build query params
      const params = new URLSearchParams();
      if (docTypeFilter !== "ALL") params.append("document_type", docTypeFilter);
      if (searchQuery) params.append("search", searchQuery);
      if (dateFrom) params.append("date_from", dateFrom);
      if (dateTo) params.append("date_to", dateTo);
      
      // Use new queue_view and include_cleared params
      if (activeTab === "pending") {
        params.append("queue_view", "true");
        params.append("include_cleared", showCleared ? "true" : "false");
      } else if (activeTab === "completed") {
        params.append("queue_view", "false");
        params.append("status", "Completed");
        params.append("include_cleared", "true");
      } else if (activeTab === "all") {
        params.append("queue_view", "false");
        params.append("include_cleared", "true");
      }
      
      if (statusFilter !== "ALL") params.append("status", statusFilter);
      
      const response = await api.get(`/documents?${params.toString()}`);
      let docs = response.data.documents || [];

      // Client-side workflow category filtering
      if (workflowCategory !== "all") {
        const allowedTypes = WORKFLOW_CATEGORIES[workflowCategory]?.types || [];
        if (allowedTypes.length > 0) {
          docs = docs.filter(d => {
            const dt = d.document_type || d.doc_type || "";
            return allowedTypes.includes(dt);
          });
        }
      }

      setDocuments(docs);
      setSelectedDocs(new Set()); // Clear selection on refresh
      
      // Update counts
      if (response.data.counts) {
        setQueueCounts(response.data.counts);
      }
      // Update dynamic filter options
      if (response.data.filter_options) {
        setFilterOptions(response.data.filter_options);
      }
    } catch (err) {
      console.error("Failed to fetch documents:", err);
      toast.error("Failed to load documents");
    } finally {
      setLoading(false);
    }
  }, [docTypeFilter, statusFilter, searchQuery, activeTab, showCleared, workflowCategory, dateFrom, dateTo]);

  const fetchStats = useCallback(async () => {
    try {
      const response = await api.get("/dashboard/stats");
      setStats({
        total: response.data.total_documents || 0,
        by_status: response.data.by_status || {},
        by_type: response.data.by_type || {}
      });
    } catch (err) {
      console.error("Failed to fetch stats:", err);
    }
  }, []);

  useEffect(() => {
    fetchDocuments();
    fetchStats();
  }, [fetchDocuments, fetchStats]);

  // Selection handlers
  const toggleSelectAll = () => {
    if (selectedDocs.size === documents.length) {
      setSelectedDocs(new Set());
    } else {
      setSelectedDocs(new Set(documents.map(d => d.id)));
    }
  };

  const toggleSelect = (docId) => {
    const newSelected = new Set(selectedDocs);
    if (newSelected.has(docId)) {
      newSelected.delete(docId);
    } else {
      newSelected.add(docId);
    }
    setSelectedDocs(newSelected);
  };

  // Bulk retry handler
  const handleBulkRetry = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`Retry validation for ${selectedDocs.size} document(s)? This will re-run classification and BC validation.`)) return;
    
    setBulkProcessing(true);
    try {
      const results = await bulkResubmitDocuments([...selectedDocs]);
      toast.success(`Retried ${results.success.length} documents. ${results.failed.length} failed.`);
      if (results.failed.length > 0) {
        console.error('Failed retries:', results.failed);
      }
      setSelectedDocs(new Set());
      fetchDocuments();
      fetchStats();
    } catch (err) {
      toast.error('Bulk retry failed: ' + err.message);
    } finally {
      setBulkProcessing(false);
    }
  };

  // Bulk delete handler
  const handleBulkDelete = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`Delete ${selectedDocs.size} document(s)? This action cannot be undone.`)) return;
    
    setBulkProcessing(true);
    try {
      const results = await bulkDeleteDocuments([...selectedDocs]);
      toast.success(`Deleted ${results.success.length} documents. ${results.failed.length} failed.`);
      if (results.failed.length > 0) {
        console.error('Failed deletes:', results.failed);
      }
      setSelectedDocs(new Set());
      fetchDocuments();
      fetchStats();
    } catch (err) {
      toast.error('Bulk delete failed: ' + err.message);
    } finally {
      setBulkProcessing(false);
    }
  };

  // Bulk file handler — route selected docs to their destination folders
  const handleBulkFile = async () => {
    if (selectedDocs.size === 0) return;
    if (!window.confirm(`File ${selectedDocs.size} document(s) to their destination folders? This will route them to SharePoint and mark as completed.`)) return;
    
    setBulkProcessing(true);
    try {
      const res = await bulkFileAndClear([...selectedDocs]);
      const results = res.data || res;
      toast.success(`Filed ${results.success?.length || 0} documents. ${results.failed?.length || 0} failed.`);
      if (results.failed?.length > 0) {
        console.error('Failed filings:', results.failed);
        results.failed.forEach(f => {
          toast.error(`Failed: ${f.doc_id} — ${f.error}`);
        });
      }
      setSelectedDocs(new Set());
      fetchDocuments();
      fetchStats();
    } catch (err) {
      toast.error('Bulk file failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setBulkProcessing(false);
    }
  };

  // Bulk ref intel handler — run reference intelligence on selected docs (or all not_run)
  const handleBulkRefIntel = async () => {
    const useSelected = selectedDocs.size > 0;
    const msg = useSelected
      ? `Run Reference Intelligence on ${selectedDocs.size} selected document(s)?`
      : 'Run Reference Intelligence on ALL documents with "Not Run" status?';
    if (!window.confirm(msg)) return;

    setBulkProcessing(true);
    try {
      if (useSelected) {
        // Trigger per-doc for selected
        let ok = 0, fail = 0;
        for (const docId of selectedDocs) {
          try {
            await triggerAutoResolve(docId);
            ok++;
          } catch {
            fail++;
          }
        }
        toast.success(`Queued ${ok} documents for ref intel. ${fail} failed.`);
      } else {
        // Batch all not_run
        const res = await batchAutoResolve('not_run', 500);
        const data = res.data || res;
        toast.success(`Queued ${data.enqueued || 0} documents for ref intel.`);
      }
      setSelectedDocs(new Set());
      // Delay refresh slightly so the worker has time to start
      setTimeout(() => { fetchDocuments(); fetchStats(); }, 3000);
    } catch (err) {
      toast.error('Ref intel failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setBulkProcessing(false);
    }
  };

  // Single delete handler
  const handleSingleDelete = async (e, docId, fileName) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${fileName}"? This action cannot be undone.`)) return;
    
    try {
      await deleteDocument(docId);
      toast.success('Document deleted');
      fetchDocuments();
      fetchStats();
    } catch (err) {
      toast.error('Delete failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleRefresh = () => {
    fetchDocuments();
    fetchStats();
    toast.success("Queue refreshed");
  };

  const pendingCount = queueCounts.pending_review || 0;
  const completedCount = queueCounts.completed || 0;

  return (
    <div className="space-y-6" data-testid="unified-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Document Queue</h1>
          <p className="text-muted-foreground">
            Manage all documents across workflows
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Bulk Actions */}
          {selectedDocs.size > 0 && (
            <div className="flex items-center gap-2 mr-2 px-3 py-1.5 bg-primary/10 rounded-lg">
              <span className="text-sm font-medium">{selectedDocs.size} selected</span>
              <Button 
                variant="default" 
                size="sm"
                onClick={handleBulkRetry}
                disabled={bulkProcessing}
                data-testid="bulk-retry-btn"
              >
                {bulkProcessing ? (
                  <RefreshCw className="w-3 h-3 mr-1 animate-spin" />
                ) : (
                  <Play className="w-3 h-3 mr-1" />
                )}
                Retry
              </Button>
              <Button 
                variant="destructive" 
                size="sm"
                onClick={handleBulkDelete}
                disabled={bulkProcessing}
                data-testid="bulk-delete-btn"
              >
                <Trash2 className="w-3 h-3 mr-1" />
                Delete
              </Button>
              <Button 
                variant="ghost" 
                size="sm"
                onClick={() => setSelectedDocs(new Set())}
              >
                Clear
              </Button>
            </div>
          )}
          <Button onClick={() => setFreightDialogOpen(true)} variant="outline" size="sm" data-testid="batch-freight-btn">
            <Truck className="h-4 w-4 mr-2" />
            Freight G/L
          </Button>
          <Button onClick={handleRefresh} variant="outline" size="sm">
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Quick Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-muted-foreground" />
              <div>
                <div className="text-2xl font-bold">{queueCounts.total_all || stats.total}</div>
                <div className="text-xs text-muted-foreground">Total Documents</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Clock className="h-5 w-5 text-yellow-500" />
              <div>
                <div className="text-2xl font-bold">{queueCounts.pending_review || pendingCount}</div>
                <div className="text-xs text-muted-foreground">Pending Review</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card className="bg-green-500/10 border-green-500/30">
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="h-5 w-5 text-green-500" />
              <div>
                <div className="text-2xl font-bold text-green-400">{queueCounts.auto_cleared || 0}</div>
                <div className="text-xs text-green-400/70">Auto-Cleared</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Archive className="h-5 w-5 text-blue-500" />
              <div>
                <div className="text-2xl font-bold">{completedCount}</div>
                <div className="text-xs text-muted-foreground">Completed</div>
              </div>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center gap-2">
              <Inbox className="h-5 w-5 text-purple-500" />
              <div>
                <div className="text-2xl font-bold">{filterOptions.types.length}</div>
                <div className="text-xs text-muted-foreground">Document Types</div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Workflow Category Selector */}
      <div className="flex items-center gap-2" data-testid="workflow-category-bar">
        {Object.entries(WORKFLOW_CATEGORIES).map(([key, { label }]) => {
          const icons = { all: FileText, ap: Receipt, sales: ShoppingCart, ops: Package };
          const Icon = icons[key] || FileText;
          return (
            <Button
              key={key}
              variant={workflowCategory === key ? "default" : "outline"}
              size="sm"
              onClick={() => setWorkflowCategory(key)}
              data-testid={`workflow-${key}`}
              className="gap-1.5"
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </Button>
          );
        })}
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex flex-wrap gap-4 items-center">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Filters:</span>
            </div>
            
            <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
              <SelectTrigger className="w-[180px]" data-testid="filter-doc-type">
                <SelectValue placeholder="Document Type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Types</SelectItem>
                {filterOptions.types.map(({ value, count }) => (
                  <SelectItem key={value} value={value}>
                    {getTypeLabel(value)} ({count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={statusFilter} onValueChange={setStatusFilter}>
              <SelectTrigger className="w-[180px]" data-testid="filter-status">
                <SelectValue placeholder="Status" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All Status</SelectItem>
                {filterOptions.statuses.map(({ value, count }) => (
                  <SelectItem key={value} value={value}>
                    {getStatusLabel(value)} ({count})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <div className="flex-1 max-w-sm">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search documents..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-10"
                  data-testid="search-input"
                />
              </div>
            </div>
          </div>

          {/* Second row: date range + toggles */}
          <div className="flex flex-wrap gap-4 items-center mt-3 pt-3 border-t border-border/50">
            <div className="flex items-center gap-2">
              <CalendarDays className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm text-muted-foreground">Date Range:</span>
            </div>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              className="text-xs h-8 px-2 bg-muted/40 border border-border rounded-md font-mono"
              data-testid="date-from-input"
            />
            <span className="text-xs text-muted-foreground">to</span>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              className="text-xs h-8 px-2 bg-muted/40 border border-border rounded-md font-mono"
              data-testid="date-to-input"
            />
            {(dateFrom || dateTo) && (
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => { setDateFrom(""); setDateTo(""); }} data-testid="clear-dates-btn">
                Clear dates
              </Button>
            )}

            <div className="flex items-center gap-2 ml-auto px-3 py-1.5 bg-muted/50 rounded-lg">
              <Checkbox 
                id="show-cleared"
                checked={showCleared}
                onCheckedChange={setShowCleared}
                data-testid="show-cleared-toggle"
              />
              <label 
                htmlFor="show-cleared" 
                className="text-sm text-muted-foreground cursor-pointer"
              >
                Show auto-cleared ({queueCounts.auto_cleared || 0})
              </label>
            </div>

            <Button
              variant="default"
              size="sm"
              className="h-8 gap-1.5"
              onClick={handleBulkFile}
              disabled={selectedDocs.size === 0 || bulkProcessing}
              data-testid="bulk-file-btn"
            >
              {bulkProcessing ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <FolderInput className="w-3.5 h-3.5" />
              )}
              File ({selectedDocs.size})
            </Button>

            <Button
              variant="outline"
              size="sm"
              className="h-8 gap-1.5"
              onClick={handleBulkRefIntel}
              disabled={bulkProcessing}
              data-testid="bulk-ref-intel-btn"
            >
              {bulkProcessing ? (
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              ) : (
                <Brain className="w-3.5 h-3.5" />
              )}
              {selectedDocs.size > 0 ? `Ref Intel (${selectedDocs.size})` : 'Run Ref Intel'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Tabs and Table */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="pending" data-testid="tab-pending">
            <Clock className="h-4 w-4 mr-2" />
            Pending ({pendingCount})
          </TabsTrigger>
          <TabsTrigger value="completed" data-testid="tab-completed">
            <FileCheck className="h-4 w-4 mr-2" />
            Completed ({completedCount})
          </TabsTrigger>
          <TabsTrigger value="all" data-testid="tab-all">
            All ({queueCounts.total_all || stats.total})
          </TabsTrigger>
        </TabsList>

        <TabsContent value={activeTab} className="mt-4">
          <Card>
            <CardContent className="p-0">
              {loading ? (
                <div className="p-8 text-center text-muted-foreground">
                  Loading documents...
                </div>
              ) : documents.length === 0 ? (
                <div className="p-8 text-center text-muted-foreground">
                  No documents found
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="w-10 pl-4">
                        <Checkbox 
                          checked={documents.length > 0 && selectedDocs.size === documents.length}
                          onCheckedChange={toggleSelectAll}
                          data-testid="select-all-checkbox"
                        />
                      </TableHead>
                      <TableHead>Document</TableHead>
                      <TableHead>Type</TableHead>
                      <TableHead>Status</TableHead>
                      <TableHead>Ref Intel</TableHead>
                      <TableHead>Freight GL</TableHead>
                      <TableHead>Validation</TableHead>
                      <TableHead>Routing</TableHead>
                      <TableHead>Source</TableHead>
                      <TableHead>Created</TableHead>
                      <TableHead className="w-20">Actions</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.map((doc) => (
                      <TableRow 
                        key={doc.id} 
                        className={`cursor-pointer hover:bg-muted/50 ${selectedDocs.has(doc.id) ? 'bg-primary/5' : ''}`}
                        onClick={() => navigate(`/documents/${doc.id}`)}
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
                          <div className="flex items-center gap-2">
                            <FileText className="h-4 w-4 text-muted-foreground" />
                            <div>
                              <div className="font-medium truncate max-w-[200px] flex items-center gap-1">
                                {doc.file_name || "Unnamed"}
                                {doc.auto_cleared && (
                                  <Badge className="ml-1 bg-green-500/20 text-green-400 text-[10px] px-1 py-0">
                                    AUTO
                                  </Badge>
                                )}
                              </div>
                              {doc.extracted_fields?.invoice_number && (
                                <div className="text-xs text-muted-foreground">
                                  #{doc.extracted_fields.invoice_number}
                                </div>
                              )}
                            </div>
                          </div>
                        </TableCell>
                        <TableCell>{getTypeBadge(doc.document_type || doc.doc_type)}</TableCell>
                        <TableCell>{getStatusBadge(doc.status || doc.workflow_status)}</TableCell>
                        <TableCell data-testid={`ref-intel-${doc.id}`}>
                          {(() => {
                            const st = doc.reference_intelligence_status || 'not_run';
                            const cfg = INTEL_STATUS_CONFIG[st] || INTEL_STATUS_CONFIG.not_run;
                            const score = doc.reference_intelligence_best_score;
                            return (
                              <div className="flex items-center gap-1.5">
                                <Badge variant="outline" className={`text-[10px] border ${cfg.cls}`}>
                                  {st === 'pending' && <RefreshCw className="w-2.5 h-2.5 mr-0.5 animate-spin" />}
                                  {cfg.label}
                                </Badge>
                                {score != null && (
                                  <span className="text-[10px] text-muted-foreground font-mono">{(score * 100).toFixed(0)}%</span>
                                )}
                              </div>
                            );
                          })()}
                        </TableCell>
                        <TableCell data-testid={`freight-gl-${doc.id}`}>
                          {(() => {
                            const fgl = doc.freight_gl_classification;
                            if (!fgl || !fgl.is_freight) return <span className="text-[10px] text-muted-foreground">-</span>;
                            const dirCls = {
                              inbound: 'bg-blue-500/20 text-blue-400',
                              outbound: 'bg-emerald-500/20 text-emerald-400',
                              transfer: 'bg-purple-500/20 text-purple-400',
                            }[fgl.direction] || 'bg-gray-500/20 text-gray-400';
                            return (
                              <div className="flex flex-col gap-0.5">
                                <Badge className={`${dirCls} text-[10px] px-1.5 py-0 w-fit`}>
                                  {fgl.direction || '?'}
                                </Badge>
                                {fgl.gl_number && (
                                  <span className="font-mono text-[10px] text-muted-foreground">{fgl.gl_number}</span>
                                )}
                              </div>
                            );
                          })()}
                        </TableCell>
                        <TableCell data-testid={`validation-state-${doc.id}`}>
                          {(() => {
                            const vs = doc.validation_state || doc.ap_validation_result?.validation_state;
                            if (!vs || vs === 'pending') return <span className="text-[10px] text-muted-foreground">-</span>;
                            const vCls = {
                              pass: 'bg-emerald-500/20 text-emerald-400',
                              warning: 'bg-amber-500/20 text-amber-400',
                              fail: 'bg-red-500/20 text-red-400',
                            }[vs] || 'bg-gray-500/20 text-gray-400';
                            return (
                              <Badge className={`${vCls} text-[10px] px-1.5 py-0 w-fit`}>
                                {vs === 'pass' ? 'pass' : vs === 'warning' ? 'warn' : 'fail'}
                              </Badge>
                            );
                          })()}
                        </TableCell>
                        <TableCell data-testid={`routing-${doc.id}`}>
                          {(() => {
                            const svr = doc.stable_vendor_routing;
                            if (!svr || !svr.routing) return <span className="text-[10px] text-muted-foreground">-</span>;
                            const rCls = {
                              auto_ready: 'bg-emerald-500/20 text-emerald-400',
                              low_priority_review: 'bg-sky-500/20 text-sky-400',
                              manual_review: 'bg-gray-500/20 text-gray-400',
                            }[svr.routing] || 'bg-gray-500/20 text-gray-400';
                            const rLabel = {
                              auto_ready: 'Auto',
                              low_priority_review: 'Low',
                              manual_review: 'Manual',
                            }[svr.routing] || svr.routing;
                            return (
                              <Badge className={`${rCls} text-[10px] px-1.5 py-0 w-fit`}>
                                {rLabel}
                              </Badge>
                            );
                          })()}
                        </TableCell>
                        <TableCell>
                          <span className="text-sm text-muted-foreground">
                            {doc.source || "unknown"}
                          </span>
                        </TableCell>
                        <TableCell>
                          <span className="text-sm text-muted-foreground">
                            {doc.created_utc ? new Date(doc.created_utc).toLocaleDateString() : "-"}
                          </span>
                        </TableCell>
                        <TableCell onClick={(e) => e.stopPropagation()}>
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              className="h-8 w-8 text-muted-foreground hover:text-destructive"
                              onClick={(e) => handleSingleDelete(e, doc.id, doc.file_name)}
                              data-testid={`delete-doc-${doc.id}`}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                            <ChevronRight className="h-4 w-4 text-muted-foreground" />
                          </div>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* Batch Freight Classification Dialog */}
      <BatchFreightClassifyDialog
        open={freightDialogOpen}
        onOpenChange={setFreightDialogOpen}
        selectedIds={selectedDocs.size > 0 ? [...selectedDocs] : null}
        totalInQueue={documents.length}
        onComplete={() => { fetchDocuments(); fetchStats(); }}
      />
    </div>
  );
}
