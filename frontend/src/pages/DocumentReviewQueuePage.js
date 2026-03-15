import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import {
  ScanSearch, AlertTriangle, ShieldCheck, ShieldX, RefreshCw, ChevronRight, ArrowUpDown,
  FileText, Loader2, Zap, CheckCircle, Link2, GitMerge
} from 'lucide-react';
import {
  getIntelligenceReviewQueue, getIntelligenceSummary, processDocumentIntelligence, createAutoDraft
} from '@/lib/api';

const DRAFT_TYPE_LABELS = {
  sales_order_draft: 'Create SO Draft',
  po_draft: 'Create PO Draft',
  ap_intake_draft: 'Create AP Draft',
};

const readinessBadge = (status) => {
  const map = {
    ready: { label: 'Ready', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
    needs_review: { label: 'Needs Review', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
    blocked: { label: 'Blocked', cls: 'bg-red-500/15 text-red-400 border-red-500/30' },
  };
  const m = map[status] || { label: status, cls: 'bg-muted text-muted-foreground' };
  return <Badge variant="outline" className={`text-[10px] font-semibold ${m.cls}`}>{m.label}</Badge>;
};

const readinessIcon = (status) => {
  if (status === 'ready') return <ShieldCheck className="w-4 h-4 text-emerald-500" />;
  if (status === 'needs_review') return <AlertTriangle className="w-4 h-4 text-amber-500" />;
  return <ShieldX className="w-4 h-4 text-red-500" />;
};

export default function DocumentReviewQueuePage() {
  const navigate = useNavigate();
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusCounts, setStatusCounts] = useState({});
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [processingId, setProcessingId] = useState(null);
  const [draftingId, setDraftingId] = useState(null);
  const [draftResults, setDraftResults] = useState({});

  // Filters
  const [statusFilter, setStatusFilter] = useState('all');
  const [docTypeFilter, setDocTypeFilter] = useState('all');
  const [sortOrder, setSortOrder] = useState(1);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100, sort_order: sortOrder };
      if (statusFilter !== 'all') params.status = statusFilter;
      if (docTypeFilter !== 'all') params.doc_type = docTypeFilter;
      const { data } = await getIntelligenceReviewQueue(params);
      setItems(data.items || []);
      setTotal(data.total || 0);
      setStatusCounts(data.status_counts || {});
    } catch (err) {
      toast.error('Failed to load review queue');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, docTypeFilter, sortOrder]);

  const fetchSummary = useCallback(async () => {
    try {
      const { data } = await getIntelligenceSummary();
      setSummary(data);
    } catch { /* non-critical */ }
  }, []);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);
  useEffect(() => { fetchSummary(); }, [fetchSummary]);

  const handleReprocess = async (docId) => {
    setProcessingId(docId);
    try {
      await processDocumentIntelligence(docId);
      toast.success('Document re-processed');
      fetchQueue();
    } catch (err) {
      toast.error('Re-processing failed');
    } finally {
      setProcessingId(null);
    }
  };

  const handleCreateDraft = async (e, docId) => {
    e.stopPropagation();
    setDraftingId(docId);
    try {
      const { data } = await createAutoDraft(docId);
      if (data.status === 'duplicate') {
        setDraftResults(prev => ({ ...prev, [docId]: { status: 'duplicate', id: data.existing_action?.target_entity_id } }));
        toast.info('Draft already exists');
      } else {
        setDraftResults(prev => ({ ...prev, [docId]: { status: 'created', id: data.target_entity_id, type: data.target_entity_type } }));
        toast.success('Draft created successfully');
      }
      fetchQueue();
      fetchSummary();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Auto-draft failed');
    } finally {
      setDraftingId(null);
    }
  };

  const uniqueDocTypes = [...new Set(items.map(i => i.document_type).filter(Boolean))];

  return (
    <div className="space-y-6" data-testid="document-review-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ScanSearch className="w-6 h-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Document Intelligence
          </h1>
        </div>
        <Button variant="outline" size="sm" onClick={() => { fetchQueue(); fetchSummary(); }} data-testid="refresh-queue-btn">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="border border-border" data-testid="summary-total">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">Total Processed</p>
            <p className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>{summary?.total_processed ?? '—'}</p>
          </CardContent>
        </Card>
        <Card className="border border-emerald-500/30" data-testid="summary-ready">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-emerald-400 uppercase tracking-wider mb-1">Ready</p>
            <p className="text-2xl font-bold text-emerald-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {summary?.by_readiness?.ready?.count ?? statusCounts.ready ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card className="border border-amber-500/30" data-testid="summary-needs-review">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-amber-400 uppercase tracking-wider mb-1">Needs Review</p>
            <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {summary?.by_readiness?.needs_review?.count ?? statusCounts.needs_review ?? 0}
            </p>
          </CardContent>
        </Card>
        <Card className="border border-red-500/30" data-testid="summary-blocked">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-red-400 uppercase tracking-wider mb-1">Blocked</p>
            <p className="text-2xl font-bold text-red-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {summary?.by_readiness?.blocked?.count ?? statusCounts.blocked ?? 0}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[160px] h-9 text-sm" data-testid="filter-status">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Review Items</SelectItem>
            <SelectItem value="needs_review">Needs Review</SelectItem>
            <SelectItem value="blocked">Blocked</SelectItem>
            <SelectItem value="ready">Ready</SelectItem>
          </SelectContent>
        </Select>

        <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
          <SelectTrigger className="w-[180px] h-9 text-sm" data-testid="filter-doc-type">
            <SelectValue placeholder="Doc Type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            {uniqueDocTypes.map(t => (
              <SelectItem key={t} value={t}>{t}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="ghost" size="sm" onClick={() => setSortOrder(o => o === 1 ? -1 : 1)} data-testid="toggle-sort">
          <ArrowUpDown className="w-3.5 h-3.5 mr-1" />
          Score {sortOrder === 1 ? 'Asc' : 'Desc'}
        </Button>

        <span className="ml-auto text-xs text-muted-foreground">{total} item{total !== 1 ? 's' : ''}</span>
      </div>

      {/* Queue Table */}
      <Card className="border border-border" data-testid="review-queue-table">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Review Queue
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
              <ShieldCheck className="w-10 h-10 mb-3 text-emerald-500/50" />
              <p className="text-sm font-medium">No items need review</p>
              <p className="text-xs mt-1">All processed documents are automation-ready</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-xs uppercase text-muted-foreground">
                    <th className="text-left px-4 py-2.5 font-medium">Status</th>
                    <th className="text-left px-4 py-2.5 font-medium">Document</th>
                    <th className="text-left px-4 py-2.5 font-medium">Type</th>
                    <th className="text-left px-4 py-2.5 font-medium">Confidence</th>
                    <th className="text-left px-4 py-2.5 font-medium">Score</th>
                    <th className="text-left px-4 py-2.5 font-medium">Reasons</th>
                    <th className="text-right px-4 py-2.5 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => {
                    const dr = draftResults[item.document_id];
                    const isReady = item.automation_readiness === 'ready';
                    const hasDraft = item.auto_draft_created || (dr && (dr.status === 'created' || dr.status === 'duplicate'));

                    return (
                      <tr
                        key={item.document_id}
                        className="border-b border-border/50 hover:bg-accent/50 cursor-pointer transition-colors"
                        onClick={() => navigate(`/documents/${item.document_id}`)}
                        data-testid={`review-row-${item.document_id}`}
                      >
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1.5">
                            {readinessIcon(item.automation_readiness)}
                            {readinessBadge(item.automation_readiness)}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <div>
                            <p className="font-medium text-sm truncate max-w-[200px]">{item.file_name || item.document_id}</p>
                            {item.email_sender && (
                              <p className="text-[11px] text-muted-foreground truncate max-w-[200px]">{item.email_sender}</p>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant="secondary" className="text-[10px] font-mono">{item.document_type}</Badge>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-2">
                            <div className="w-12 h-1.5 bg-muted rounded-full overflow-hidden">
                              <div
                                className={`h-full rounded-full ${
                                  item.classification_confidence >= 0.9 ? 'bg-emerald-500' :
                                  item.classification_confidence >= 0.75 ? 'bg-amber-500' : 'bg-red-500'
                                }`}
                                style={{ width: `${(item.classification_confidence || 0) * 100}%` }}
                              />
                            </div>
                            <span className="text-xs font-mono text-muted-foreground">
                              {((item.classification_confidence || 0) * 100).toFixed(0)}%
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-xs font-bold font-mono ${
                            item.automation_readiness_score >= 75 ? 'text-emerald-400' :
                            item.automation_readiness_score >= 40 ? 'text-amber-400' : 'text-red-400'
                          }`}>
                            {item.automation_readiness_score ?? '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex flex-wrap gap-1 max-w-[200px]">
                            {(item.automation_readiness_reasons || []).slice(0, 3).map((r, i) => (
                              <Badge key={i} variant="outline" className="text-[9px] font-mono border-muted-foreground/30">{r}</Badge>
                            ))}
                            {(item.automation_readiness_reasons || []).length > 3 && (
                              <Badge variant="outline" className="text-[9px]">+{item.automation_readiness_reasons.length - 3}</Badge>
                            )}
                            {item.entity_resolution_status === 'blocked' && (
                              <Badge variant="outline" className="text-[9px] font-mono border-red-500/30 text-red-400">entities unresolved</Badge>
                            )}
                            {item.entity_resolution_status === 'needs_review' && (
                              <Badge variant="outline" className="text-[9px] font-mono border-amber-500/30 text-amber-400">entities ambiguous</Badge>
                            )}
                            {item.unresolved_entity_count > 0 && (
                              <Badge variant="outline" className="text-[9px] border-red-500/30 text-red-400">{item.unresolved_entity_count} unresolved</Badge>
                            )}
                            {item.ambiguous_entity_count > 0 && (
                              <Badge variant="outline" className="text-[9px] border-amber-500/30 text-amber-400">{item.ambiguous_entity_count} ambiguous</Badge>
                            )}
                            {item.transaction_match_status === 'matched' && (
                              <Badge variant="outline" className="text-[9px] font-mono border-blue-500/30 text-blue-400"><GitMerge className="w-2.5 h-2.5 mr-0.5 inline" />tx match</Badge>
                            )}
                            {item.transaction_match_status === 'ambiguous' && (
                              <Badge variant="outline" className="text-[9px] font-mono border-amber-500/30 text-amber-400"><GitMerge className="w-2.5 h-2.5 mr-0.5 inline" />tx ambiguous</Badge>
                            )}
                            {item.transaction_match_status === 'confirmed' && (
                              <Badge variant="outline" className="text-[9px] font-mono border-emerald-500/30 text-emerald-400"><Link2 className="w-2.5 h-2.5 mr-0.5 inline" />linked</Badge>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex items-center justify-end gap-1">
                            {isReady && !hasDraft && !item.auto_link_created && !item.auto_draft_suppressed_due_to_match && (
                              <Button
                                variant="default"
                                size="sm"
                                className="h-7 text-[10px] bg-emerald-600 hover:bg-emerald-700 text-white"
                                onClick={(e) => handleCreateDraft(e, item.document_id)}
                                disabled={draftingId === item.document_id}
                                data-testid={`create-draft-btn-${item.document_id}`}
                              >
                                {draftingId === item.document_id ? (
                                  <Loader2 className="w-3 h-3 animate-spin mr-1" />
                                ) : (
                                  <Zap className="w-3 h-3 mr-1" />
                                )}
                                {DRAFT_TYPE_LABELS[item.target_entity_type] || 'Create Draft'}
                              </Button>
                            )}
                            {isReady && item.auto_link_available && !item.auto_link_created && (
                              <Badge className="text-[9px] bg-blue-500/15 text-blue-400 border border-blue-500/30">
                                <Link2 className="w-3 h-3 mr-1" />
                                Link Available
                              </Badge>
                            )}
                            {item.auto_link_created && (
                              <Badge className="text-[9px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                                <Link2 className="w-3 h-3 mr-1" />
                                Linked
                              </Badge>
                            )}
                            {hasDraft && (
                              <Badge className="text-[9px] bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                                <CheckCircle className="w-3 h-3 mr-1" />
                                {dr?.id || item.target_entity_id || 'Draft'}
                              </Badge>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-7 text-xs"
                              onClick={(e) => { e.stopPropagation(); handleReprocess(item.document_id); }}
                              disabled={processingId === item.document_id}
                              data-testid={`reprocess-btn-${item.document_id}`}
                            >
                              {processingId === item.document_id ? (
                                <Loader2 className="w-3 h-3 animate-spin" />
                              ) : (
                                <RefreshCw className="w-3 h-3" />
                              )}
                            </Button>
                            <ChevronRight className="w-4 h-4 text-muted-foreground" />
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Summary by Document Type */}
      {summary?.by_document_type?.length > 0 && (
        <Card className="border border-border" data-testid="summary-by-type">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              By Document Type
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {summary.by_document_type.map((t) => (
                <div key={t.type} className="flex items-center justify-between p-2 bg-accent/30 rounded-md">
                  <div className="flex items-center gap-2">
                    <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                    <span className="text-xs font-mono">{t.type}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-bold">{t.count}</span>
                    <span className="text-[10px] text-muted-foreground">{((t.avg_confidence || 0) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
