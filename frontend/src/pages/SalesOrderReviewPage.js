import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  ExternalLink,
  FileText,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
  XCircle,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '../components/ui/card';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '../components/ui/dialog';
import { Input } from '../components/ui/input';
import { Textarea } from '../components/ui/textarea';
import { useAuth } from '../context/AuthContext';

const API = process.env.REACT_APP_BACKEND_URL || '';

async function apiRequest(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
    ...options,
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = payload.detail || payload;
    const message =
      typeof detail === 'string'
        ? detail
        : detail.message || `Request failed with HTTP ${response.status}`;
    const error = new Error(message);
    error.status = response.status;
    error.detail = detail;
    throw error;
  }
  return payload;
}

function statusBadge(item) {
  if (item?.bc_posting_status === 'created') {
    return <Badge className="bg-emerald-100 text-emerald-800">Created</Badge>;
  }
  if (item?.bc_create_ready) {
    return <Badge className="bg-emerald-100 text-emerald-800">Ready</Badge>;
  }
  if (item?.review_status === 'rejected') {
    return <Badge variant="destructive">Rejected</Badge>;
  }
  return <Badge className="bg-amber-100 text-amber-800">Needs Review</Badge>;
}

function formatDate(value) {
  if (!value) return '-';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export default function SalesOrderReviewPage() {
  const { user } = useAuth();
  const reviewerName = user?.display_name || user?.username || 'Reviewer';

  const [mode, setMode] = useState({ mode: 'shadow', write_enabled: false });
  const [documents, setDocuments] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loadingQueue, setLoadingQueue] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [actionLoading, setActionLoading] = useState(false);
  const [search, setSearch] = useState('');
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const [approvalNote, setApprovalNote] = useState('');
  const [rejectionReason, setRejectionReason] = useState('');

  const loadMode = useCallback(async () => {
    const data = await apiRequest('/api/sales/order-intake/status');
    setMode(data);
  }, []);

  const loadQueue = useCallback(async (preserveSelection = true) => {
    setLoadingQueue(true);
    try {
      const data = await apiRequest(
        '/api/sales/order-intake/review?limit=200&refresh_missing=true'
      );
      const nextDocuments = data.documents || [];
      setMode({ mode: data.mode, write_enabled: data.write_enabled });
      setDocuments(nextDocuments);
      setSelectedId((current) => {
        if (
          preserveSelection &&
          current &&
          nextDocuments.some((item) => item.document_id === current)
        ) {
          return current;
        }
        return nextDocuments[0]?.document_id || null;
      });
    } catch (error) {
      toast.error(`Could not load sales-order review queue: ${error.message}`);
    } finally {
      setLoadingQueue(false);
    }
  }, []);

  const loadDetail = useCallback(async (documentId) => {
    if (!documentId) {
      setDetail(null);
      return;
    }
    setLoadingDetail(true);
    try {
      const data = await apiRequest(
        `/api/sales/order-intake/${encodeURIComponent(documentId)}`
      );
      setDetail(data);
    } catch (error) {
      toast.error(`Could not load order candidate: ${error.message}`);
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  useEffect(() => {
    Promise.all([loadMode(), loadQueue(false)]).catch(() => {});
  }, [loadMode, loadQueue]);

  useEffect(() => {
    loadDetail(selectedId);
  }, [loadDetail, selectedId]);

  const filteredDocuments = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return documents;
    return documents.filter((item) =>
      [
        item.file_name,
        item.customer_name,
        item.customer_number,
        item.customer_po_number,
        item.document_id,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term))
    );
  }, [documents, search]);

  const preflight = detail?.preflight || {};
  const candidate = preflight.candidate || {};
  const sourceDocument = detail?.document || {};
  const errors = preflight.errors || [];
  const warnings = preflight.warnings || [];
  const lines = candidate.lines || [];

  const refreshCurrent = async () => {
    await loadQueue(true);
    await loadDetail(selectedId);
  };

  const rerunPreflight = async () => {
    if (!selectedId) return;
    setActionLoading(true);
    try {
      await apiRequest(
        `/api/sales/order-intake/${encodeURIComponent(selectedId)}/preflight`,
        { method: 'POST' }
      );
      toast.success('Preflight completed');
      await refreshCurrent();
    } catch (error) {
      toast.error(`Preflight failed: ${error.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const approve = async () => {
    if (!selectedId) return;
    setActionLoading(true);
    try {
      await apiRequest(
        `/api/sales/order-intake/${encodeURIComponent(selectedId)}/approve`,
        {
          method: 'POST',
          body: JSON.stringify({
            reviewer: reviewerName,
            note: approvalNote || null,
          }),
        }
      );
      setApproveOpen(false);
      setApprovalNote('');
      toast.success('Sales-order candidate approved');
      await refreshCurrent();
    } catch (error) {
      toast.error(`Approval failed: ${error.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const reject = async () => {
    if (!selectedId || !rejectionReason.trim()) return;
    setActionLoading(true);
    try {
      await apiRequest(
        `/api/sales/order-intake/${encodeURIComponent(selectedId)}/reject`,
        {
          method: 'POST',
          body: JSON.stringify({
            reviewer: reviewerName,
            reason: rejectionReason.trim(),
          }),
        }
      );
      setRejectOpen(false);
      setRejectionReason('');
      toast.success('Sales-order candidate rejected');
      await refreshCurrent();
    } catch (error) {
      toast.error(`Rejection failed: ${error.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const createDraft = async () => {
    if (!selectedId) return;
    setActionLoading(true);
    try {
      const result = await apiRequest(
        `/api/sales/order-intake/${encodeURIComponent(selectedId)}/create-draft`,
        { method: 'POST' }
      );
      toast.success(
        `BC draft ${result.bcDocumentNumber || result.bcDocumentId} created`
      );
      await refreshCurrent();
    } catch (error) {
      if (error.detail?.status === 'shadow_mode') {
        toast.info('Candidate passed preflight, but BC writes are disabled');
      } else {
        toast.error(`Draft creation blocked: ${error.message}`);
      }
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div className="mx-auto max-w-[1600px] space-y-6" data-testid="sales-order-review-page">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="flex items-center gap-2 text-2xl font-bold tracking-tight">
            <ClipboardCheck className="h-6 w-6 text-primary" />
            Sales Order Review
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Review extracted customer purchase orders before creating Business Central drafts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="outline"
            className={
              mode.write_enabled
                ? 'border-red-300 bg-red-100 text-red-800'
                : 'border-amber-300 bg-amber-100 text-amber-800'
            }
          >
            <ShieldCheck className="mr-1 h-3.5 w-3.5" />
            {mode.write_enabled ? 'BC Write Mode' : 'Shadow Mode'}
          </Badge>
          <Button
            variant="outline"
            onClick={() => loadQueue(true)}
            disabled={loadingQueue || actionLoading}
          >
            <RefreshCw className={`mr-2 h-4 w-4 ${loadingQueue ? 'animate-spin' : ''}`} />
            Refresh Queue
          </Button>
        </div>
      </div>

      <Card className="border-amber-300/60 bg-amber-50/40 dark:bg-amber-950/10">
        <CardContent className="flex items-start gap-3 p-4">
          <ShieldCheck className="mt-0.5 h-5 w-5 text-amber-600" />
          <div>
            <p className="text-sm font-medium">
              {mode.write_enabled
                ? 'Business Central draft creation is enabled.'
                : 'Business Central writes are disabled.'}
            </p>
            <p className="mt-1 text-xs text-muted-foreground">
              Preflight, approval, rejection, and queue persistence remain active. A draft cannot be created unless every deterministic validation passes.
            </p>
          </div>
        </CardContent>
      </Card>

      <div className="grid min-h-[650px] gap-6 xl:grid-cols-[360px_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <CardHeader className="border-b pb-4">
            <CardTitle className="text-lg">Review Queue</CardTitle>
            <CardDescription>{documents.length} customer-order documents</CardDescription>
            <div className="relative pt-2">
              <Search className="absolute left-3 top-1/2 mt-1 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search customer, PO, or file"
                className="pl-9"
              />
            </div>
          </CardHeader>
          <CardContent className="max-h-[730px] overflow-y-auto p-0">
            {loadingQueue ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="h-6 w-6 animate-spin text-primary" />
              </div>
            ) : filteredDocuments.length === 0 ? (
              <div className="p-8 text-center text-sm text-muted-foreground">
                No matching sales orders.
              </div>
            ) : (
              filteredDocuments.map((item) => (
                <button
                  type="button"
                  key={item.document_id}
                  onClick={() => setSelectedId(item.document_id)}
                  className={`w-full border-b p-4 text-left transition-colors hover:bg-muted/50 ${
                    selectedId === item.document_id ? 'bg-primary/5' : ''
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold">
                        {item.customer_name || 'Unresolved customer'}
                      </p>
                      <p className="truncate text-xs text-muted-foreground">
                        {item.customer_po_number || 'No customer PO'}
                      </p>
                    </div>
                    {statusBadge(item)}
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-2 text-xs text-muted-foreground">
                    <span className="truncate">{item.file_name || item.document_id}</span>
                    <span className="shrink-0">{formatDate(item.created_utc)}</span>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <div className="space-y-6">
          {loadingDetail ? (
            <Card>
              <CardContent className="flex min-h-[400px] items-center justify-center">
                <Loader2 className="h-7 w-7 animate-spin text-primary" />
              </CardContent>
            </Card>
          ) : !detail ? (
            <Card>
              <CardContent className="flex min-h-[400px] flex-col items-center justify-center text-muted-foreground">
                <FileText className="mb-3 h-12 w-12 opacity-30" />
                Select a document from the review queue.
              </CardContent>
            </Card>
          ) : (
            <>
              <Card>
                <CardHeader>
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        {preflight.can_create ? (
                          <CheckCircle2 className="h-5 w-5 text-emerald-600" />
                        ) : (
                          <AlertTriangle className="h-5 w-5 text-amber-600" />
                        )}
                        {candidate.customerName || 'Unresolved customer'}
                      </CardTitle>
                      <CardDescription className="mt-1">
                        {sourceDocument.file_name || selectedId}
                      </CardDescription>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="outline"
                        onClick={rerunPreflight}
                        disabled={actionLoading}
                      >
                        <RefreshCw className="mr-2 h-4 w-4" />
                        Rerun Preflight
                      </Button>
                      <Button
                        variant="outline"
                        onClick={() => setRejectOpen(true)}
                        disabled={actionLoading}
                        className="border-red-300 text-red-700 hover:bg-red-50"
                      >
                        <XCircle className="mr-2 h-4 w-4" />
                        Reject
                      </Button>
                      <Button
                        onClick={() => setApproveOpen(true)}
                        disabled={actionLoading}
                      >
                        <CheckCircle2 className="mr-2 h-4 w-4" />
                        Approve
                      </Button>
                    </div>
                  </div>
                </CardHeader>
                <CardContent className="space-y-5">
                  <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">BC Customer</p>
                      <p className="mt-1 font-mono text-sm font-semibold">
                        {candidate.customerNumber || 'Not resolved'}
                      </p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Customer PO</p>
                      <p className="mt-1 text-sm font-semibold">
                        {candidate.externalDocumentNumber || 'Missing'}
                      </p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Confidence</p>
                      <p className="mt-1 text-sm font-semibold">
                        {Math.round((candidate.classificationConfidence || 0) * 100)}%
                      </p>
                    </div>
                    <div className="rounded-lg border p-3">
                      <p className="text-xs text-muted-foreground">Review Status</p>
                      <p className="mt-1 text-sm font-semibold capitalize">
                        {candidate.reviewStatus || sourceDocument.review_status || 'Not reviewed'}
                      </p>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-3 text-sm">
                    <span className="text-muted-foreground">Source:</span>
                    {candidate.sharepointUrl ? (
                      <a
                        href={candidate.sharepointUrl}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 font-medium text-primary hover:underline"
                      >
                        Open SharePoint document
                        <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    ) : (
                      <span className="font-medium text-red-600">Not archived in SharePoint</span>
                    )}
                  </div>
                </CardContent>
              </Card>

              {(errors.length > 0 || warnings.length > 0) && (
                <Card className="border-amber-300/70">
                  <CardHeader>
                    <CardTitle className="text-lg">Preflight Findings</CardTitle>
                    <CardDescription>
                      Resolve every error before Business Central draft creation.
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="space-y-2">
                    {errors.map((issue, index) => (
                      <div
                        key={`${issue.code}-${index}`}
                        className="flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-3 dark:bg-red-950/20"
                      >
                        <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-red-600" />
                        <div>
                          <p className="text-sm font-medium text-red-800 dark:text-red-300">
                            {issue.code}
                          </p>
                          <p className="text-xs text-red-700 dark:text-red-400">
                            {issue.message}
                          </p>
                        </div>
                      </div>
                    ))}
                    {warnings.map((issue, index) => (
                      <div
                        key={`${issue.code}-${index}`}
                        className="flex items-start gap-3 rounded-md border border-amber-200 bg-amber-50 p-3 dark:bg-amber-950/20"
                      >
                        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                        <div>
                          <p className="text-sm font-medium">{issue.code}</p>
                          <p className="text-xs text-muted-foreground">{issue.message}</p>
                        </div>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader>
                  <CardTitle className="text-lg">Order Lines</CardTitle>
                  <CardDescription>{lines.length} extracted line items</CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b text-left text-muted-foreground">
                          <th className="pb-3 font-medium">Line</th>
                          <th className="pb-3 font-medium">Customer SKU</th>
                          <th className="pb-3 font-medium">BC Item</th>
                          <th className="pb-3 font-medium">Description</th>
                          <th className="pb-3 text-right font-medium">Quantity</th>
                          <th className="pb-3 font-medium">UOM</th>
                          <th className="pb-3 font-medium">Mapping</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lines.map((line, index) => (
                          <tr key={`${line.source_line_number || index}`} className="border-b">
                            <td className="py-3">{line.source_line_number || index + 1}</td>
                            <td className="py-3 font-mono text-xs">
                              {line.customerItemNumber || '-'}
                            </td>
                            <td className="py-3 font-mono text-xs font-semibold">
                              {line.itemNumber || <span className="text-red-600">Unresolved</span>}
                            </td>
                            <td className="max-w-[240px] truncate py-3">
                              {line.description || '-'}
                            </td>
                            <td className="py-3 text-right font-mono">
                              {line.quantity ?? '-'}
                            </td>
                            <td className="py-3">{line.unitOfMeasureCode || '-'}</td>
                            <td className="py-3">
                              <Badge
                                variant="outline"
                                className={
                                  line.mappingStatus === 'approved'
                                    ? 'border-emerald-300 bg-emerald-50 text-emerald-800'
                                    : 'border-amber-300 bg-amber-50 text-amber-800'
                                }
                              >
                                {line.mappingStatus || 'Not set'}
                              </Badge>
                            </td>
                          </tr>
                        ))}
                        {lines.length === 0 && (
                          <tr>
                            <td colSpan={7} className="py-10 text-center text-muted-foreground">
                              No order lines were extracted.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>

              <Card className={preflight.can_create ? 'border-emerald-300/70' : ''}>
                <CardContent className="flex flex-col gap-4 p-5 lg:flex-row lg:items-center lg:justify-between">
                  <div>
                    <p className="font-medium">
                      {preflight.can_create
                        ? 'Candidate passed deterministic preflight.'
                        : 'Candidate is blocked by preflight errors.'}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      {mode.write_enabled
                        ? 'BC draft creation is available after approval.'
                        : 'Shadow mode is active, so no BC document can be created.'}
                    </p>
                  </div>
                  <Button
                    onClick={createDraft}
                    disabled={!preflight.can_create || !mode.write_enabled || actionLoading}
                    className="min-w-44"
                  >
                    {actionLoading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ClipboardCheck className="mr-2 h-4 w-4" />
                    )}
                    Create BC Draft
                  </Button>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      </div>

      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve sales-order candidate</DialogTitle>
            <DialogDescription>
              Approval is recorded as {reviewerName}. Preflight will rerun immediately.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={approvalNote}
            onChange={(event) => setApprovalNote(event.target.value)}
            placeholder="Optional review note"
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveOpen(false)}>
              Cancel
            </Button>
            <Button onClick={approve} disabled={actionLoading}>
              Approve Candidate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject sales-order candidate</DialogTitle>
            <DialogDescription>
              Explain why this document cannot proceed. The reason is retained with the document.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            value={rejectionReason}
            onChange={(event) => setRejectionReason(event.target.value)}
            placeholder="Rejection reason"
            rows={4}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={reject}
              disabled={actionLoading || !rejectionReason.trim()}
            >
              Reject Candidate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
