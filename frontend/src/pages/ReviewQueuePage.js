import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter
} from '../components/ui/dialog';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '../components/ui/select';
import {
  ClipboardCheck, CheckCircle2, RefreshCw, Loader2,
  FileText, Pencil, ChevronDown, ChevronUp, ArrowRight,
  RotateCcw, GitCompare, Zap
} from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

function StatusBadge({ status }) {
  const styles = {
    pending: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
    approved: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
    corrected: 'bg-blue-500/15 text-blue-400 border-blue-500/30',
    bc_edited: 'bg-violet-500/15 text-violet-400 border-violet-500/30',
  };
  return (
    <Badge variant="outline" className={styles[status] || ''} data-testid={`status-${status}`}>
      {status === 'bc_edited' ? 'BC Edited' : status}
    </Badge>
  );
}

function ConfidenceBadge({ confidence }) {
  const styles = {
    high: 'bg-emerald-600 text-white',
    medium: 'bg-amber-600 text-white',
    low: 'bg-red-600 text-white',
  };
  return (
    <Badge className={styles[confidence] || 'bg-muted'} data-testid={`confidence-${confidence}`}>
      {confidence}
    </Badge>
  );
}

function CorrectionDialog({ open, onClose, onSubmit, docId }) {
  const [corrections, setCorrections] = useState([{ field: '', original: '', corrected: '', note: '' }]);
  const [submitting, setSubmitting] = useState(false);

  const addRow = () => setCorrections(prev => [...prev, { field: '', original: '', corrected: '', note: '' }]);
  const updateRow = (idx, key, val) => {
    setCorrections(prev => prev.map((r, i) => i === idx ? { ...r, [key]: val } : r));
  };
  const removeRow = (idx) => {
    if (corrections.length <= 1) return;
    setCorrections(prev => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {
    const valid = corrections.filter(c => c.field && c.corrected);
    if (valid.length === 0) {
      toast.error('Add at least one correction with a field name and corrected value');
      return;
    }
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue/${docId}/correct`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(valid),
      });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message);
        onSubmit();
      } else {
        toast.error(data.error || 'Failed to submit corrections');
      }
    } catch {
      toast.error('Network error');
    }
    setSubmitting(false);
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-2xl" data-testid="correction-dialog">
        <DialogHeader>
          <DialogTitle>Submit Corrections</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 max-h-[400px] overflow-y-auto">
          {corrections.map((c, i) => (
            <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] gap-2 items-start">
              <div>
                <label className="text-xs text-muted-foreground">Field</label>
                <Select value={c.field} onValueChange={(v) => updateRow(i, 'field', v)}>
                  <SelectTrigger data-testid={`correction-field-${i}`}><SelectValue placeholder="Select field" /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="line_item">Line Item/GL</SelectItem>
                    <SelectItem value="amount">Amount</SelectItem>
                    <SelectItem value="description">Description</SelectItem>
                    <SelectItem value="tax_code">Tax Code</SelectItem>
                    <SelectItem value="quantity">Quantity</SelectItem>
                    <SelectItem value="vendor_invoice_no">Vendor Invoice #</SelectItem>
                    <SelectItem value="posting_date">Posting Date</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-xs text-muted-foreground">AI Had</label>
                <Input placeholder="Original" value={c.original} onChange={e => updateRow(i, 'original', e.target.value)} data-testid={`correction-original-${i}`} />
              </div>
              <div>
                <label className="text-xs text-muted-foreground">Should Be</label>
                <Input placeholder="Corrected" value={c.corrected} onChange={e => updateRow(i, 'corrected', e.target.value)} data-testid={`correction-corrected-${i}`} />
              </div>
              <Button variant="ghost" size="icon" className="mt-5" onClick={() => removeRow(i)} disabled={corrections.length <= 1}>
                &times;
              </Button>
            </div>
          ))}
        </div>
        <Button variant="outline" size="sm" onClick={addRow} data-testid="add-correction-row">+ Add Correction</Button>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={handleSubmit} disabled={submitting} data-testid="submit-corrections-btn">
            {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : null}
            Submit Corrections
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function FeedbackDiffPanel({ corrections }) {
  if (!corrections || corrections.length === 0) return null;

  const typeLabels = {
    item_change: 'Item/GL Changed',
    description_change: 'Description Changed',
    amount_change: 'Amount Changed',
    quantity_change: 'Quantity Changed',
    tax_change: 'Tax Code Changed',
    line_addition: 'Line Added',
    line_deletion: 'Line Removed',
    structural: 'Structural Change',
  };

  const typeColors = {
    item_change: 'text-violet-400 border-violet-500/30',
    description_change: 'text-blue-400 border-blue-500/30',
    amount_change: 'text-amber-400 border-amber-500/30',
    quantity_change: 'text-amber-400 border-amber-500/30',
    tax_change: 'text-teal-400 border-teal-500/30',
    line_addition: 'text-emerald-400 border-emerald-500/30',
    line_deletion: 'text-rose-400 border-rose-500/30',
    structural: 'text-orange-400 border-orange-500/30',
  };

  return (
    <div className="col-span-full mt-2" data-testid="feedback-diff-panel">
      <div className="flex items-center gap-2 mb-2">
        <GitCompare className="w-3.5 h-3.5 text-violet-400" />
        <span className="text-xs font-medium text-violet-400">BC Feedback — {corrections.length} change(s) detected</span>
      </div>
      <div className="space-y-1">
        {corrections.map((c, i) => (
          <div key={i} className="flex items-center gap-2 bg-muted/50 rounded px-2 py-1 text-xs">
            <Badge variant="outline" className={`text-xs ${typeColors[c.type] || ''}`}>
              {typeLabels[c.type] || c.type}
            </Badge>
            {c.line_index !== undefined && (
              <span className="text-muted-foreground">Line {c.line_index + 1}:</span>
            )}
            <span className="text-rose-400 line-through">{String(c.original)}</span>
            <ArrowRight className="w-3 h-3 text-muted-foreground" />
            <span className="text-emerald-400">{String(c.corrected)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ReviewItem({ item, onRefresh }) {
  const [expanded, setExpanded] = useState(false);
  const [approving, setApproving] = useState(false);
  const [correcting, setCorrecting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [feedback, setFeedback] = useState(null);

  const handleApprove = async () => {
    setApproving(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue/${item.id}/approve`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        toast.success(data.message);
        onRefresh();
      } else {
        toast.error(data.error || 'Failed to approve');
      }
    } catch {
      toast.error('Network error');
    }
    setApproving(false);
  };

  const handleSyncFromBC = async () => {
    setSyncing(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue/${item.id}/sync-from-bc`, { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        if (data.changes_detected) {
          toast.success(`Changes detected: ${data.summary}`);
          setFeedback(data);
        } else {
          toast.info('No changes — draft matches BC');
        }
        onRefresh();
      } else {
        toast.error(data.error || 'Failed to sync from BC');
      }
    } catch {
      toast.error('Network error');
    }
    setSyncing(false);
  };

  const loadFeedback = async () => {
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue/${item.id}/feedback`);
      if (res.ok) {
        const data = await res.json();
        if (data.success) setFeedback(data);
      }
    } catch { /* ignore */ }
  };

  // Load feedback when expanding if corrections exist
  const handleExpand = () => {
    const next = !expanded;
    setExpanded(next);
    if (next && !feedback && (item.review_status === 'bc_edited' || item.review_status === 'corrected')) {
      loadFeedback();
    }
  };

  return (
    <>
      <div
        className="border border-border rounded-lg p-3 hover:bg-muted/30 transition-colors"
        data-testid={`review-item-${item.id}`}
      >
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0 flex-1">
            <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-mono text-sm font-medium truncate">{item.vendor_no}</span>
                {item.vendor_name && <span className="text-xs text-muted-foreground truncate">{item.vendor_name}</span>}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                <span>Inv: {item.invoice_number || 'N/A'}</span>
                <span>|</span>
                <span>${parseFloat(item.amount || 0).toLocaleString()}</span>
                {item.bc_record_no && (
                  <>
                    <span>|</span>
                    <span className="font-mono">BC# {item.bc_record_no}</span>
                  </>
                )}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <ConfidenceBadge confidence={item.confidence} />
            <StatusBadge status={item.review_status} />

            {/* Sync from BC button — available for pending and bc_edited drafts */}
            {(item.review_status === 'pending' || item.review_status === 'bc_edited') && (
              <Button size="sm" variant="outline" onClick={handleSyncFromBC} disabled={syncing} data-testid={`sync-bc-btn-${item.id}`}>
                {syncing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <RotateCcw className="w-3 h-3 mr-1" />}
                Sync BC
              </Button>
            )}

            {item.review_status === 'pending' && (
              <>
                <Button size="sm" variant="outline" onClick={() => setCorrecting(true)} data-testid={`correct-btn-${item.id}`}>
                  <Pencil className="w-3 h-3 mr-1" />Correct
                </Button>
                <Button size="sm" onClick={handleApprove} disabled={approving} data-testid={`approve-btn-${item.id}`}>
                  {approving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <CheckCircle2 className="w-3 h-3 mr-1" />}
                  Approve
                </Button>
              </>
            )}

            <Button size="icon" variant="ghost" onClick={handleExpand} data-testid={`expand-btn-${item.id}`}>
              {expanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
            </Button>
          </div>
        </div>

        {expanded && (
          <div className="mt-3 pt-3 border-t border-border/50 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs" data-testid={`details-${item.id}`}>
            <div>
              <span className="text-muted-foreground">Filename</span>
              <p className="font-medium truncate">{item.filename || 'N/A'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Invoice Date</span>
              <p className="font-medium">{item.invoice_date || 'N/A'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Drafted</span>
              <p className="font-medium">{item.drafted_at ? new Date(item.drafted_at).toLocaleString() : 'N/A'}</p>
            </div>
            <div>
              <span className="text-muted-foreground">Source</span>
              <p className="font-medium">{item.draft_source || 'N/A'}</p>
            </div>
            {item.reviewed_at && (
              <div>
                <span className="text-muted-foreground">Reviewed</span>
                <p className="font-medium">{new Date(item.reviewed_at).toLocaleString()} by {item.reviewed_by}</p>
              </div>
            )}
            {/* Manual corrections from Review Queue */}
            {item.corrections && item.corrections.length > 0 && (
              <div className="col-span-full">
                <span className="text-muted-foreground">Manual Corrections</span>
                <div className="mt-1 space-y-1">
                  {item.corrections.map((c, i) => (
                    <div key={i} className="flex items-center gap-2 bg-muted/50 rounded px-2 py-1">
                      <Badge variant="outline" className="text-xs">{c.field}</Badge>
                      <span className="text-rose-400 line-through">{c.original}</span>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <span className="text-emerald-400">{c.corrected}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {/* BC Feedback diff panel */}
            {feedback && feedback.corrections && feedback.corrections.length > 0 && (
              <FeedbackDiffPanel corrections={feedback.corrections} />
            )}
          </div>
        )}
      </div>

      <CorrectionDialog
        open={correcting}
        onClose={() => setCorrecting(false)}
        onSubmit={() => { setCorrecting(false); onRefresh(); }}
        docId={item.id}
      />
    </>
  );
}

export default function ReviewQueuePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('pending');
  const [batchSyncing, setBatchSyncing] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue?status_filter=${filter}`);
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  }, [filter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleBatchSync = async () => {
    setBatchSyncing(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/review-queue/sync-all`, { method: 'POST' });
      const result = await res.json();
      toast.success(
        `Synced ${result.processed} drafts: ${result.changes_found} with changes, ${result.no_changes} unchanged, ${result.errors} errors`
      );
      fetchData();
    } catch {
      toast.error('Batch sync failed');
    }
    setBatchSyncing(false);
  };

  return (
    <div className="p-4 space-y-5 max-w-[1400px] mx-auto" data-testid="review-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <ClipboardCheck className="w-6 h-6 text-blue-500" />
            Draft Review Queue
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Review, approve, or correct auto-drafted Purchase Invoices — corrections feed back into AI templates
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={handleBatchSync} disabled={batchSyncing} data-testid="batch-sync-btn">
            {batchSyncing ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Zap className="w-4 h-4 mr-1" />}
            Sync All from BC
          </Button>
          <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} data-testid="refresh-review-btn">
            <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} />Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="review-summary">
          <Card className="cursor-pointer hover:ring-1 ring-amber-500/50" onClick={() => setFilter('pending')}>
            <CardContent className="pt-3 pb-2 px-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Pending Review</p>
              <p className={`text-2xl font-bold ${filter === 'pending' ? 'text-amber-400' : ''}`}>{data.summary.pending}</p>
            </CardContent>
          </Card>
          <Card className="cursor-pointer hover:ring-1 ring-emerald-500/50" onClick={() => setFilter('approved')}>
            <CardContent className="pt-3 pb-2 px-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Approved</p>
              <p className={`text-2xl font-bold ${filter === 'approved' ? 'text-emerald-400' : ''}`}>{data.summary.approved}</p>
            </CardContent>
          </Card>
          <Card className="cursor-pointer hover:ring-1 ring-blue-500/50" onClick={() => setFilter('corrected')}>
            <CardContent className="pt-3 pb-2 px-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Corrected</p>
              <p className={`text-2xl font-bold ${filter === 'corrected' ? 'text-blue-400' : ''}`}>{data.summary.corrected}</p>
            </CardContent>
          </Card>
          <Card className="cursor-pointer hover:ring-1 ring-violet-500/50" onClick={() => setFilter('all')}>
            <CardContent className="pt-3 pb-2 px-4">
              <p className="text-xs text-muted-foreground uppercase tracking-wide">Total Drafted</p>
              <p className={`text-2xl font-bold ${filter === 'all' ? 'text-violet-400' : ''}`}>{data.summary.total}</p>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Queue Items */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <FileText className="w-4 h-4 text-blue-500" />
            {filter === 'all' ? 'All Drafts' : `${filter.charAt(0).toUpperCase() + filter.slice(1)} Drafts`}
            {data && <Badge variant="secondary" className="ml-1">{data.count}</Badge>}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center h-32" data-testid="review-loading">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : !data || data.items.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground" data-testid="review-empty">
              <ClipboardCheck className="w-10 h-10 mx-auto mb-2 opacity-40" />
              <p className="text-sm">
                {filter === 'pending' ? 'No drafts pending review. Auto-drafted PIs will appear here.' : `No ${filter} drafts found.`}
              </p>
            </div>
          ) : (
            <div className="space-y-2" data-testid="review-items-list">
              {data.items.map(item => (
                <ReviewItem key={item.id} item={item} onRefresh={fetchData} />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
