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
        '/api/sales/order-intake/review?limit=200&refresh_missing=false'
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
        result.bcDocumentNumber
          ? `Business Central draft ${result.bcDocumentNumber} created`
          : 'Business Central draft created'
      );
      await refreshCurrent();
    } catch (error) {
      toast.error(`Draft creation blocked: ${error.message}`);
    } finally {
      setActionLoading(false);
    }
  };

  const sourceUrl =
    sourceDocument.sharepoint_url ||
    sourceDocument.web_url ||
    sourceDocument.source_url;

  return (
    <div className="space-y-5 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-3">
            <ClipboardCheck className="h-7 w-7 text-blue-500" />
            <h1 className="text-3xl font-bold tracking-tight">Sales Order Review</h1>
          </div>
          <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
            Review extracted customer purchase orders before creating Business Central
            drafts.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            className={
              mode.write_enabled
                ? 'bg-red-100 text-red-800'
                : 'bg-amber-100 text-amber-800'
            }
          >
            <ShieldCheck className="mr-1 h-4 w-4" />
            {mode.write_enabled ? 'Write Mode' : 'Shadow Mode'}
          </Badge>
          <Button
            variant="outline"
            onClick={() => loadQueue(true)}
            disabled={loadingQueue || actionLoading}
          >
            <RefreshCw
              className={`mr-2 h-4 w-4 ${loadingQueue ? 'animate-spin' : ''}`}
            />
            Refresh Queue
          </Button>
        </div>
      </div>

      {!mode.write_enabled && (
        <div className="rounded-lg border border-amber-400/70 bg-amber-50/5 p-4">
          <div className="flex gap-3">
            <ShieldCheck className="mt-0.5 h-5 w-5 text-amber-500" />
            <div>
              <p className="font-semibold">Business Central writes are disabled.</p>
              <p className="mt-1 text-sm text-muted-foreground">
                Preflight, approval, rejection, and queue persistence remain active. A
                draft cannot be created unless every deterministic validation passes.
              </p>
            </div>
          </div>
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(320px,0.95fr)_minmax(0,1.65fr)]">
        <Card className="min-h-[640px]">
          <CardHeader>
            <CardTitle>Review Queue</CardTitle>
            <CardDescription>
              {documents.length} customer-order document
              {documents.length === 1 ? '' : 's'}
            </CardDescription>
            <div className="relative pt-2">
              <Search className="absolute left-3 top-5 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-9"
                placeholder="Search customer, PO, or file"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {loadingQueue ? (
              <div className="flex h-32 items-center justify-center">
                <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
              </div>
            ) : filteredDocuments.length === 0 ? (
              <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
                No sales-order documents matched this queue.
              </div>
            ) : (
              filteredDocuments.map((item) => (
                <button
                  key={item.document_id}
                  type="button"
                  onClick={() => setSelectedId(item.document_id)}
                  className={`w-full rounded-lg border p-3 text-left transition ${
                    selectedId === item.document_id
                      ? 'border-blue-500 bg-blue-500/10'
                      : 'border-border hover:border-blue-400/70 hover:bg-muted/40'
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-medium">
                        {item.customer_name || item.file_name || item.document_id}
                      </p>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {item.file_name || 'Unnamed document'}
                      </p>
                    </div>
                    {statusBadge(item)}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-muted-foreground">
                    <span>PO: {item.customer_po_number || '-'}</span>
                    <span className="text-right">{formatDate(item.created_utc)}</span>
                  </div>
                </button>
              ))
            )}
          </CardContent>
        </Card>

        <Card className="min-h-[640px]">
          {!selectedId ? (
            <CardContent className="flex h-[640px] flex-col items-center justify-center text-muted-foreground">
              <FileText className="mb-4 h-10 w-10" />
              <p>Select a document from the review queue.</p>
            </CardContent>
          ) : loadingDetail ? (
            <CardContent className="flex h-[640px] items-center justify-center">
              <Loader2 className="h-7 w-7 animate-spin text-blue-500" />
            </CardContent>
          ) : !detail ? (
            <CardContent className="flex h-[640px] flex-col items-center justify-center text-muted-foreground">
              <AlertTriangle className="mb-4 h-10 w-10 text-amber-500" />
              <p>The selected order could not be loaded.</p>
            </CardContent>
          ) : (
            <>
              <CardHeader>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <CardTitle>
                      {candidate.customerName ||
                        sourceDocument.customer_name_extracted ||
                        sourceDocument.file_name ||
                        'Customer Order'}
                    </CardTitle>
                    <CardDescription className="mt-1">
                      {sourceDocument.file_name || selectedId}
                    </CardDescription>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {statusBadge({
                      ...sourceDocument,
                      ...preflight,
                      bc_create_ready: preflight.can_create,
                    })}
                    {sourceUrl && (
                      <Button asChild size="sm" variant="outline">
                        <a href={sourceUrl} target="_blank" rel="noreferrer">
                          <ExternalLink className="mr-2 h-4 w-4" />
                          Source
                        </a>
                      </Button>
                    )}
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-5">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <div className="rounded-lg border p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Customer No.
                    </p>
                    <p className="mt-1 font-medium">{candidate.customerNumber || '-'}</p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Customer PO
                    </p>
                    <p className="mt-1 font-medium">
                      {candidate.externalDocumentNumber || '-'}
                    </p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Confidence
                    </p>
                    <p className="mt-1 font-medium">
                      {preflight.confidence == null
                        ? '-'
                        : `${Math.round(preflight.confidence * 100)}%`}
                    </p>
                  </div>
                  <div className="rounded-lg border p-3">
                    <p className="text-xs uppercase tracking-wide text-muted-foreground">
                      Review Status
                    </p>
                    <p className="mt-1 font-medium">
                      {sourceDocument.review_status || 'needs_review'}
                    </p>
                  </div>
                </div>

                {errors.length > 0 && (
                  <div className="rounded-lg border border-red-500/50 bg-red-500/5 p-4">
                    <div className="mb-3 flex items-center gap-2 font-semibold text-red-500">
                      <XCircle className="h-5 w-5" />
                      Blocking validation errors
                    </div>
                    <div className="space-y-2">
                      {errors.map((error, index) => (
                        <div key={`${error.code}-${index}`} className="text-sm">
                          <span className="font-medium">{error.code}</span>
                          <span className="text-muted-foreground">: {error.message}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {warnings.length > 0 && (
                  <div className="rounded-lg border border-amber-500/50 bg-amber-500/5 p-4">
                    <div className="mb-3 flex items-center gap-2 font-semibold text-amber-500">
                      <AlertTriangle className="h-5 w-5" />
                      Warnings
                    </div>
                    <div className="space-y-2">
                      {warnings.map((warning, index) => (
                        <div key={`${warning.code}-${index}`} className="text-sm">
                          <span className="font-medium">{warning.code}</span>
                          <span className="text-muted-foreground">
                            : {warning.message}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div>
                  <div className="mb-3 flex items-center justify-between">
                    <div>
                      <h3 className="font-semibold">Order Lines</h3>
                      <p className="text-sm text-muted-foreground">
                        Deterministic item mappings prepared for Business Central.
                      </p>
                    </div>
                    <Badge variant="outline">{lines.length} lines</Badge>
                  </div>
                  <div className="overflow-x-auto rounded-lg border">
                    <table className="w-full min-w-[720px] text-sm">
                      <thead className="bg-muted/50 text-left">
                        <tr>
                          <th className="px-3 py-2">Line</th>
                          <th className="px-3 py-2">Item</th>
                          <th className="px-3 py-2">Description</th>
                          <th className="px-3 py-2 text-right">Quantity</th>
                          <th className="px-3 py-2">UOM</th>
                          <th className="px-3 py-2 text-right">Unit Price</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lines.length === 0 ? (
                          <tr>
                            <td
                              colSpan={6}
                              className="px-3 py-8 text-center text-muted-foreground"
                            >
                              No mapped order lines are available.
                            </td>
                          </tr>
                        ) : (
                          lines.map((line, index) => (
                            <tr key={`${line.lineNumber || index}`} className="border-t">
                              <td className="px-3 py-2">{line.lineNumber || index + 1}</td>
                              <td className="px-3 py-2 font-medium">
                                {line.itemNumber || '-'}
                              </td>
                              <td className="px-3 py-2">
                                {line.description || line.sourceDescription || '-'}
                              </td>
                              <td className="px-3 py-2 text-right">
                                {line.quantity ?? '-'}
                              </td>
                              <td className="px-3 py-2">{line.unitOfMeasure || '-'}</td>
                              <td className="px-3 py-2 text-right">
                                {line.unitPrice == null ? '-' : line.unitPrice}
                              </td>
                            </tr>
                          ))
                        )}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="flex flex-wrap gap-2 border-t pt-4">
                  <Button
                    variant="outline"
                    onClick={rerunPreflight}
                    disabled={actionLoading}
                  >
                    {actionLoading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <RefreshCw className="mr-2 h-4 w-4" />
                    )}
                    Rerun Preflight
                  </Button>
                  <Button
                    variant="outline"
                    onClick={() => setApproveOpen(true)}
                    disabled={actionLoading}
                  >
                    <CheckCircle2 className="mr-2 h-4 w-4" />
                    Approve
                  </Button>
                  <Button
                    variant="destructive"
                    onClick={() => setRejectOpen(true)}
                    disabled={actionLoading}
                  >
                    <XCircle className="mr-2 h-4 w-4" />
                    Reject
                  </Button>
                  <Button
                    onClick={createDraft}
                    disabled={
                      actionLoading ||
                      !mode.write_enabled ||
                      !preflight.can_create ||
                      sourceDocument.review_status === 'rejected'
                    }
                  >
                    {actionLoading ? (
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    ) : (
                      <ClipboardCheck className="mr-2 h-4 w-4" />
                    )}
                    Create BC Draft
                  </Button>
                </div>
              </CardContent>
            </>
          )}
        </Card>
      </div>

      <Dialog open={approveOpen} onOpenChange={setApproveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve sales-order candidate</DialogTitle>
            <DialogDescription>
              Approval is persisted and deterministic preflight is rerun. Shadow mode
              will still prevent any Business Central write.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Optional approval note"
            value={approvalNote}
            onChange={(event) => setApprovalNote(event.target.value)}
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
              Record why this order must not proceed to Business Central.
            </DialogDescription>
          </DialogHeader>
          <Textarea
            placeholder="Rejection reason"
            value={rejectionReason}
            onChange={(event) => setRejectionReason(event.target.value)}
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
