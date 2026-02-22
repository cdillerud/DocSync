/**
 * APWorkflowsPage - Dedicated AP Invoice Workflow Management
 * 
 * A focused view for AP team members to manage AP_INVOICE documents
 * through their workflow stages. Uses the generic queue API and
 * reusable components to enable future expansion to other doc types.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { toast } from 'sonner';
import { 
  RefreshCw, Filter, Building2, Receipt, TrendingUp, 
  CheckCircle, XCircle, User, AlertTriangle, ArrowRight,
  Search, Calendar, DollarSign, FileText
} from 'lucide-react';

import { WorkflowQueue } from '@/components/WorkflowQueue';
import { DocumentDetailPanel } from '@/components/DocumentDetailPanel';
import {
  DOC_TYPES,
  AP_WORKFLOW_STATUSES,
  AP_QUEUE_CONFIG,
  AP_PRIMARY_QUEUES,
  AP_SECONDARY_QUEUES,
  SOURCE_SYSTEMS,
  SOURCE_SYSTEM_LABELS,
  getQueueConfig,
} from '@/lib/workflowConstants';
import {
  getWorkflowStatusCounts,
  getAPDashboardMetrics,
  setVendor,
  updateFields,
  overrideBcValidation,
  startApproval,
  approveDocument,
  rejectDocument,
  exportDocument,
} from '@/lib/api';

// Summary card component
function SummaryCard({ title, value, description, icon: Icon, color = 'bg-primary' }) {
  return (
    <Card data-testid={`summary-card-${title.toLowerCase().replace(/\s+/g, '-')}`}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-2xl font-bold">{value}</p>
            {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
          </div>
          <div className={`p-3 rounded-lg ${color}`}>
            <Icon className="h-5 w-5 text-white" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Queue count badge for tabs
function QueueBadge({ status, count }) {
  const config = getQueueConfig(status);
  return (
    <Badge 
      variant="secondary" 
      className={`ml-2 ${count > 0 ? config.textColor : 'text-muted-foreground'}`}
    >
      {count}
    </Badge>
  );
}

// Set Vendor Dialog
function SetVendorDialog({ document, open, onOpenChange, onComplete }) {
  const [vendorNo, setVendorNo] = useState('');
  const [vendorName, setVendorName] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (document) {
      setVendorName(document.vendor_raw || document.extracted_fields?.vendor || '');
      setVendorNo('');
    }
  }, [document]);

  const handleSubmit = async () => {
    if (!vendorNo.trim()) {
      toast.error('Vendor number is required');
      return;
    }
    setLoading(true);
    try {
      await setVendor(document.id, vendorNo.trim(), vendorName.trim(), 'ap_user');
      toast.success('Vendor assigned successfully');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to set vendor');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="set-vendor-dialog">
        <DialogHeader>
          <DialogTitle>Assign Vendor</DialogTitle>
          <DialogDescription>
            Link this invoice to a Business Central vendor
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="p-3 rounded-lg bg-muted">
            <p className="text-xs text-muted-foreground mb-1">Extracted Vendor Name</p>
            <p className="font-medium">{document?.vendor_raw || document?.extracted_fields?.vendor || 'Not detected'}</p>
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendorNo">BC Vendor Number *</Label>
            <Input
              id="vendorNo"
              value={vendorNo}
              onChange={(e) => setVendorNo(e.target.value)}
              placeholder="e.g., V10001"
              data-testid="vendor-no-input"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="vendorName">Vendor Display Name</Label>
            <Input
              id="vendorName"
              value={vendorName}
              onChange={(e) => setVendorName(e.target.value)}
              placeholder="Vendor display name"
              data-testid="vendor-name-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={loading} data-testid="set-vendor-submit">
            {loading ? 'Assigning...' : 'Assign Vendor'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Override BC Validation Dialog
function OverrideValidationDialog({ document, open, onOpenChange, onComplete }) {
  const [reason, setReason] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    if (!reason.trim()) {
      toast.error('Override reason is required');
      return;
    }
    setLoading(true);
    try {
      await overrideBcValidation(document.id, reason.trim(), 'ap_user');
      toast.success('Validation override applied');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to override validation');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="override-validation-dialog">
        <DialogHeader>
          <DialogTitle>Override BC Validation</DialogTitle>
          <DialogDescription>
            Allow this document to proceed despite validation issues
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          {document?.validation_errors?.length > 0 && (
            <div className="p-3 rounded-lg bg-red-500/10">
              <p className="text-xs text-red-400 mb-2 font-medium">Validation Errors:</p>
              {document.validation_errors.map((err, i) => (
                <p key={i} className="text-sm text-red-400">• {err}</p>
              ))}
            </div>
          )}
          <div className="space-y-2">
            <Label htmlFor="override-reason">Override Reason *</Label>
            <Textarea
              id="override-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Explain why this validation should be overridden..."
              data-testid="override-reason-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="destructive" onClick={handleSubmit} disabled={loading} data-testid="override-submit">
            {loading ? 'Applying...' : 'Override & Continue'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Approval Dialog
function ApprovalDialog({ document, open, onOpenChange, onComplete }) {
  const [action, setAction] = useState('approve');
  const [comment, setComment] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async () => {
    setLoading(true);
    try {
      if (action === 'approve') {
        await approveDocument(document.id, comment.trim(), 'ap_user');
        toast.success('Document approved');
      } else {
        if (!comment.trim()) {
          toast.error('Rejection reason is required');
          setLoading(false);
          return;
        }
        await rejectDocument(document.id, comment.trim(), 'ap_user');
        toast.success('Document rejected');
      }
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || `Failed to ${action} document`);
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="approval-dialog">
        <DialogHeader>
          <DialogTitle>Review & Decide</DialogTitle>
          <DialogDescription>
            Approve or reject: {document?.invoice_number_clean || document?.file_name}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 py-4">
          <div className="grid grid-cols-2 gap-4 text-sm p-3 rounded-lg bg-muted">
            <div>
              <span className="text-muted-foreground">Vendor:</span>
              <p className="font-medium">{document?.vendor_name || document?.vendor_raw || '-'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Amount:</span>
              <p className="font-medium">
                {document?.amount_float ? `$${document.amount_float.toLocaleString()}` : '-'}
              </p>
            </div>
          </div>
          
          <div className="flex gap-2">
            <Button
              type="button"
              variant={action === 'approve' ? 'default' : 'outline'}
              onClick={() => setAction('approve')}
              className="flex-1"
              data-testid="action-approve-btn"
            >
              <CheckCircle className="mr-2 h-4 w-4" /> Approve
            </Button>
            <Button
              type="button"
              variant={action === 'reject' ? 'destructive' : 'outline'}
              onClick={() => setAction('reject')}
              className="flex-1"
              data-testid="action-reject-btn"
            >
              <XCircle className="mr-2 h-4 w-4" /> Reject
            </Button>
          </div>
          
          <div className="space-y-2">
            <Label>
              {action === 'approve' ? 'Comment (optional)' : 'Rejection Reason *'}
            </Label>
            <Textarea
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              placeholder={action === 'approve' ? 'Optional notes...' : 'Reason for rejection...'}
              data-testid="approval-comment-input"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            variant={action === 'approve' ? 'default' : 'destructive'}
            onClick={handleSubmit}
            disabled={loading}
            data-testid="approval-submit"
          >
            {loading ? 'Processing...' : action === 'approve' ? 'Approve' : 'Reject'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// Export Dialog
function ExportDialog({ document, open, onOpenChange, onComplete }) {
  const [loading, setLoading] = useState(false);

  const handleExport = async () => {
    setLoading(true);
    try {
      await exportDocument(document.id, 'BC', 'ap_user');
      toast.success('Document exported successfully');
      onComplete();
      onOpenChange(false);
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to export document');
    }
    setLoading(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="export-dialog">
        <DialogHeader>
          <DialogTitle>Export to Business Central</DialogTitle>
          <DialogDescription>
            Mark this document as exported to BC
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <div className="p-4 rounded-lg bg-muted space-y-2">
            <p><span className="text-muted-foreground">Invoice:</span> {document?.invoice_number_clean || '-'}</p>
            <p><span className="text-muted-foreground">Vendor:</span> {document?.vendor_name || document?.vendor_raw || '-'}</p>
            <p><span className="text-muted-foreground">Amount:</span> {document?.amount_float ? `$${document.amount_float.toLocaleString()}` : '-'}</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={handleExport} disabled={loading} data-testid="export-submit">
            {loading ? 'Exporting...' : 'Export to BC'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

export default function APWorkflowsPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  
  // State
  const [activeTab, setActiveTab] = useState(searchParams.get('status') || AP_WORKFLOW_STATUSES.VENDOR_PENDING);
  const [statusCounts, setStatusCounts] = useState({});
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  
  // Filters
  const [vendorSearch, setVendorSearch] = useState('');
  const [sourceSystem, setSourceSystem] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [amountMin, setAmountMin] = useState('');
  const [amountMax, setAmountMax] = useState('');
  
  // Selected document & dialogs
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);
  const [vendorDialogOpen, setVendorDialogOpen] = useState(false);
  const [overrideDialogOpen, setOverrideDialogOpen] = useState(false);
  const [approvalDialogOpen, setApprovalDialogOpen] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);

  // Fetch status counts
  const fetchStatusCounts = useCallback(async () => {
    try {
      const res = await getWorkflowStatusCounts();
      setStatusCounts(res.data.status_counts || {});
    } catch (err) {
      console.error('Failed to fetch status counts:', err);
    }
  }, []);

  // Fetch AP metrics
  const fetchMetrics = useCallback(async () => {
    try {
      const res = await getAPDashboardMetrics();
      const apData = res.data.by_type?.AP_INVOICE || null;
      setMetrics(apData);
    } catch (err) {
      console.error('Failed to fetch metrics:', err);
    }
  }, []);

  useEffect(() => {
    fetchStatusCounts();
    fetchMetrics();
  }, [fetchStatusCounts, fetchMetrics]);

  // Update URL when tab changes
  useEffect(() => {
    setSearchParams({ status: activeTab });
  }, [activeTab, setSearchParams]);

  const handleRefreshAll = () => {
    setLoading(true);
    fetchStatusCounts();
    fetchMetrics();
    setRefreshTrigger(t => t + 1);
    setTimeout(() => setLoading(false), 500);
  };

  const handleActionComplete = () => {
    handleRefreshAll();
  };

  // Build filters object for queue API
  const buildFilters = () => {
    const filters = {};
    if (vendorSearch.trim()) filters.vendor = vendorSearch.trim();
    if (sourceSystem !== 'all') filters.source_system = sourceSystem;
    if (dateFrom) filters.date_from = dateFrom;
    if (dateTo) filters.date_to = dateTo;
    if (amountMin) filters.amount_min = parseFloat(amountMin);
    if (amountMax) filters.amount_max = parseFloat(amountMax);
    return filters;
  };

  const handleDocumentSelect = (doc) => {
    setSelectedDoc(doc);
    setDetailPanelOpen(true);
  };

  const handleOpenAction = (doc, actionType) => {
    setSelectedDoc(doc);
    setDetailPanelOpen(false);
    
    switch (actionType) {
      case 'set-vendor':
        setVendorDialogOpen(true);
        break;
      case 'override':
        setOverrideDialogOpen(true);
        break;
      case 'approve':
        setApprovalDialogOpen(true);
        break;
      case 'export':
        setExportDialogOpen(true);
        break;
      default:
        break;
    }
  };

  // Row actions per queue status
  const getRowActions = (status) => {
    switch (status) {
      case AP_WORKFLOW_STATUSES.VENDOR_PENDING:
        return [
          { id: 'set-vendor', label: 'Set Vendor', icon: User, action: (doc) => handleOpenAction(doc, 'set-vendor') }
        ];
      case AP_WORKFLOW_STATUSES.BC_VALIDATION_FAILED:
        return [
          { id: 'override', label: 'Override Validation', icon: AlertTriangle, action: (doc) => handleOpenAction(doc, 'override') }
        ];
      case AP_WORKFLOW_STATUSES.READY_FOR_APPROVAL:
      case AP_WORKFLOW_STATUSES.APPROVAL_IN_PROGRESS:
        return [
          { id: 'approve', label: 'Approve/Reject', icon: CheckCircle, action: (doc) => handleOpenAction(doc, 'approve') }
        ];
      case AP_WORKFLOW_STATUSES.APPROVED:
        return [
          { id: 'export', label: 'Export to BC', icon: ArrowRight, action: (doc) => handleOpenAction(doc, 'export') }
        ];
      default:
        return [];
    }
  };

  // Panel actions based on selected document status
  const getPanelActions = () => {
    if (!selectedDoc) return [];
    
    const status = selectedDoc.workflow_status;
    switch (status) {
      case AP_WORKFLOW_STATUSES.VENDOR_PENDING:
        return [{ label: 'Set Vendor', icon: User, action: () => handleOpenAction(selectedDoc, 'set-vendor') }];
      case AP_WORKFLOW_STATUSES.BC_VALIDATION_FAILED:
        return [{ label: 'Override', icon: AlertTriangle, variant: 'destructive', action: () => handleOpenAction(selectedDoc, 'override') }];
      case AP_WORKFLOW_STATUSES.READY_FOR_APPROVAL:
      case AP_WORKFLOW_STATUSES.APPROVAL_IN_PROGRESS:
        return [{ label: 'Review', icon: CheckCircle, action: () => handleOpenAction(selectedDoc, 'approve') }];
      case AP_WORKFLOW_STATUSES.APPROVED:
        return [{ label: 'Export', icon: ArrowRight, action: () => handleOpenAction(selectedDoc, 'export') }];
      default:
        return [];
    }
  };

  // Calculate summary metrics
  const totalAP = metrics?.total || 0;
  const activeQueueCount = metrics?.active_queue_count || 
    AP_PRIMARY_QUEUES.reduce((sum, status) => sum + (statusCounts[status] || 0), 0);
  const vendorExtractionRate = metrics?.extraction?.vendor?.rate 
    ? Math.round(metrics.extraction.vendor.rate * 100) 
    : 0;
  const exportedCount = statusCounts[AP_WORKFLOW_STATUSES.EXPORTED] || 0;
  const exportRate = totalAP > 0 ? Math.round((exportedCount / totalAP) * 100) : 0;

  const hasActiveFilters = vendorSearch || sourceSystem !== 'all' || dateFrom || dateTo || amountMin || amountMax;

  const clearFilters = () => {
    setVendorSearch('');
    setSourceSystem('all');
    setDateFrom('');
    setDateTo('');
    setAmountMin('');
    setAmountMax('');
  };

  return (
    <div className="space-y-6" data-testid="ap-workflows-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">AP Workflows</h1>
          <p className="text-muted-foreground">Manage AP Invoice documents through approval workflow</p>
        </div>
        <Button onClick={handleRefreshAll} variant="outline" disabled={loading} data-testid="refresh-all">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard
          title="Total AP Invoices"
          value={totalAP.toLocaleString()}
          icon={Receipt}
          color="bg-blue-500"
        />
        <SummaryCard
          title="Active Queue"
          value={activeQueueCount.toLocaleString()}
          description="Documents needing action"
          icon={FileText}
          color="bg-yellow-500"
        />
        <SummaryCard
          title="Vendor Extraction"
          value={`${vendorExtractionRate}%`}
          description="Auto-detected vendors"
          icon={Building2}
          color="bg-green-500"
        />
        <SummaryCard
          title="Export Rate"
          value={`${exportRate}%`}
          description={`${exportedCount} exported`}
          icon={TrendingUp}
          color="bg-emerald-500"
        />
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Filters</span>
            </div>
            
            <div className="flex-1 grid grid-cols-2 md:grid-cols-6 gap-3">
              {/* Vendor Search */}
              <div className="relative col-span-2">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search vendor..."
                  value={vendorSearch}
                  onChange={(e) => setVendorSearch(e.target.value)}
                  className="pl-9"
                  data-testid="vendor-search"
                />
              </div>
              
              {/* Source System */}
              <Select value={sourceSystem} onValueChange={setSourceSystem}>
                <SelectTrigger data-testid="source-system-filter">
                  <SelectValue placeholder="Source" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sources</SelectItem>
                  {Object.entries(SOURCE_SYSTEM_LABELS).map(([key, label]) => (
                    <SelectItem key={key} value={key}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              
              {/* Date From */}
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                placeholder="From date"
                data-testid="date-from"
              />
              
              {/* Date To */}
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                placeholder="To date"
                data-testid="date-to"
              />
              
              {/* Amount Range (combined) */}
              <div className="flex gap-1 items-center">
                <Input
                  type="number"
                  placeholder="Min $"
                  value={amountMin}
                  onChange={(e) => setAmountMin(e.target.value)}
                  className="w-20"
                  data-testid="amount-min"
                />
                <span className="text-muted-foreground">-</span>
                <Input
                  type="number"
                  placeholder="Max $"
                  value={amountMax}
                  onChange={(e) => setAmountMax(e.target.value)}
                  className="w-20"
                  data-testid="amount-max"
                />
              </div>
            </div>
            
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} data-testid="clear-filters">
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Queue Tabs */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Workflow Queues</CardTitle>
          <CardDescription>Documents grouped by workflow status</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-6 flex flex-wrap h-auto gap-1">
              {AP_PRIMARY_QUEUES.map((status) => {
                const config = getQueueConfig(status);
                return (
                  <TabsTrigger
                    key={status}
                    value={status}
                    className="flex items-center"
                    data-testid={`tab-${status}`}
                  >
                    {config.shortLabel}
                    <QueueBadge status={status} count={statusCounts[status] || 0} />
                  </TabsTrigger>
                );
              })}
              
              {/* Secondary queues in a separate group */}
              <div className="ml-2 pl-2 border-l border-border flex gap-1">
                {AP_SECONDARY_QUEUES.slice(0, 2).map((status) => {
                  const config = getQueueConfig(status);
                  return (
                    <TabsTrigger
                      key={status}
                      value={status}
                      className="flex items-center opacity-70"
                      data-testid={`tab-${status}`}
                    >
                      {config.shortLabel}
                      <QueueBadge status={status} count={statusCounts[status] || 0} />
                    </TabsTrigger>
                  );
                })}
              </div>
            </TabsList>

            {/* Render queue content for each status */}
            {[...AP_PRIMARY_QUEUES, ...AP_SECONDARY_QUEUES].map((status) => (
              <TabsContent key={status} value={status}>
                <WorkflowQueue
                  docType={DOC_TYPES.AP_INVOICE}
                  status={status}
                  filters={buildFilters()}
                  rowActions={getRowActions(status)}
                  onDocumentSelect={handleDocumentSelect}
                  refreshTrigger={refreshTrigger}
                />
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      {/* Document Detail Panel */}
      <DocumentDetailPanel
        document={selectedDoc}
        open={detailPanelOpen}
        onOpenChange={setDetailPanelOpen}
        actions={getPanelActions()}
        onNavigateToFull={(id) => navigate(`/documents/${id}`)}
      />

      {/* Action Dialogs */}
      <SetVendorDialog
        document={selectedDoc}
        open={vendorDialogOpen}
        onOpenChange={setVendorDialogOpen}
        onComplete={handleActionComplete}
      />
      <OverrideValidationDialog
        document={selectedDoc}
        open={overrideDialogOpen}
        onOpenChange={setOverrideDialogOpen}
        onComplete={handleActionComplete}
      />
      <ApprovalDialog
        document={selectedDoc}
        open={approvalDialogOpen}
        onOpenChange={setApprovalDialogOpen}
        onComplete={handleActionComplete}
      />
      <ExportDialog
        document={selectedDoc}
        open={exportDialogOpen}
        onOpenChange={setExportDialogOpen}
        onComplete={handleActionComplete}
      />
    </div>
  );
}
