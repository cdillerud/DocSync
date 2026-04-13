import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { ScrollArea } from './ui/scroll-area';
import {
  CheckCircle2, XCircle, Play, Loader2, ChevronDown, ChevronUp,
  Filter, RefreshCw, AlertTriangle, Sparkles, Package, MapPin,
  Gauge, FileText, Hash
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const TYPE_CONFIG = {
  add_alternate_ship_to:       { icon: MapPin,     label: 'Ship-To',     color: 'text-blue-600' },
  add_occasional_valid_item:   { icon: Package,    label: 'Item',        color: 'text-violet-600' },
  add_alternate_uom_for_item:  { icon: Hash,       label: 'UOM',         color: 'text-cyan-600' },
  widen_order_value_tolerance:  { icon: Gauge,      label: 'Amount',      color: 'text-amber-600' },
  revise_po_pattern:           { icon: FileText,   label: 'PO Pattern',  color: 'text-orange-600' },
  increase_variability_tolerance: { icon: Sparkles, label: 'Variability', color: 'text-emerald-600' },
};

const STATUS_STYLE = {
  pending:               'bg-amber-500/10 text-amber-600 border-amber-300',
  approved:              'bg-blue-500/10 text-blue-600 border-blue-300',
  rejected:              'bg-red-500/10 text-red-600 border-red-300',
  applied:               'bg-emerald-500/10 text-emerald-600 border-emerald-300',
  insufficient_evidence: 'bg-muted text-muted-foreground border-border',
};

export default function LearningSuggestionsPanel() {
  const [suggestions, setSuggestions] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [expanded, setExpanded] = useState(null);
  const [actionLoading, setActionLoading] = useState(null);
  const [statusFilter, setStatusFilter] = useState('pending');
  const [typeFilter, setTypeFilter] = useState('');

  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchSuggestions = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '100' });
      if (statusFilter) params.set('status', statusFilter);
      if (typeFilter) params.set('suggestion_type', typeFilter);
      const res = await fetch(`${API}/api/admin/sales-learning/learning-suggestions?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setSuggestions(data.suggestions || []);
        setTotal(data.total || 0);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [statusFilter, typeFilter]);

  useEffect(() => { fetchSuggestions(); }, [fetchSuggestions]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      await fetch(`${API}/api/admin/sales-learning/generate-learning-suggestions?sync=true`, { method: 'POST', headers });
      await fetchSuggestions();
    } catch { /* ignore */ }
    setGenerating(false);
  };

  const handleAction = async (id, action) => {
    setActionLoading(`${id}-${action}`);
    try {
      const res = await fetch(`${API}/api/admin/sales-learning/learning-suggestions/${id}/${action}`, { method: 'POST', headers });
      if (res.ok) await fetchSuggestions();
    } catch { /* ignore */ }
    setActionLoading(null);
  };

  const statusOptions = ['', 'pending', 'approved', 'rejected', 'applied', 'insufficient_evidence'];
  const typeOptions = ['', ...Object.keys(TYPE_CONFIG)];

  return (
    <Card data-testid="learning-suggestions-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-muted-foreground" />
            Learning Suggestions
            <Badge variant="outline" className="text-[10px] ml-1">{total}</Badge>
          </CardTitle>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleGenerate} disabled={generating} data-testid="generate-suggestions-btn">
              {generating ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <RefreshCw className="w-3 h-3 mr-1" />}
              Generate
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* Filters */}
        <div className="flex items-center gap-2 mb-3 flex-wrap" data-testid="suggestions-filters">
          <Filter className="w-3.5 h-3.5 text-muted-foreground" />
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="text-xs border rounded px-2 py-1 bg-background"
            data-testid="status-filter"
          >
            {statusOptions.map(s => <option key={s} value={s}>{s || 'All statuses'}</option>)}
          </select>
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="text-xs border rounded px-2 py-1 bg-background"
            data-testid="type-filter"
          >
            {typeOptions.map(t => <option key={t} value={t}>{t ? (TYPE_CONFIG[t]?.label || t) : 'All types'}</option>)}
          </select>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!loading && suggestions.length === 0 && (
          <div className="text-center py-8 text-sm text-muted-foreground">
            <p>No learning suggestions {statusFilter ? `with status "${statusFilter}"` : 'found'}.</p>
            <p className="text-xs mt-1">Click <strong>Generate</strong> to analyze reviewer feedback.</p>
          </div>
        )}

        {!loading && suggestions.length > 0 && (
          <ScrollArea className="max-h-[500px]">
            <div className="space-y-1" data-testid="suggestions-list">
              {suggestions.map(s => {
                const tc = TYPE_CONFIG[s.suggestion_type] || { icon: Sparkles, label: s.suggestion_type, color: 'text-muted-foreground' };
                const TypeIcon = tc.icon;
                const isExpanded = expanded === s.suggestion_id;
                const change = s.proposed_profile_change || {};

                return (
                  <div key={s.suggestion_id} className="border border-border/40 rounded-md" data-testid={`suggestion-${s.suggestion_id}`}>
                    {/* Row header */}
                    <div
                      className="flex items-center gap-2 py-2 px-3 cursor-pointer hover:bg-muted/30 transition-colors"
                      onClick={() => setExpanded(isExpanded ? null : s.suggestion_id)}
                    >
                      <TypeIcon className={`w-3.5 h-3.5 ${tc.color} shrink-0`} />
                      <span className="text-xs font-semibold w-16 shrink-0">{tc.label}</span>
                      <span className="text-xs font-mono text-blue-600 w-16 shrink-0">{s.customer_no}</span>
                      <span className="text-xs text-muted-foreground flex-1 truncate">{s.evidence_summary?.slice(0, 80)}</span>
                      <span className="text-[10px] font-mono font-bold w-10 text-right shrink-0">{Math.round((s.confidence || 0) * 100)}%</span>
                      <Badge variant="outline" className={`text-[9px] w-16 justify-center ${STATUS_STYLE[s.status] || ''}`}>
                        {s.status}
                      </Badge>
                      {isExpanded ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                    </div>

                    {/* Expanded detail */}
                    {isExpanded && (
                      <div className="px-3 pb-3 pt-1 border-t border-border/30 space-y-2 bg-muted/10">
                        <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-[11px]">
                          <div><span className="text-muted-foreground">Customer:</span> <strong>{s.customer_name || s.customer_no}</strong></div>
                          <div><span className="text-muted-foreground">Confidence:</span> <strong>{Math.round((s.confidence || 0) * 100)}%</strong></div>
                          <div><span className="text-muted-foreground">Evidence:</span> {s.supporting_feedback_count || 0} feedback record(s)</div>
                          <div><span className="text-muted-foreground">Docs:</span> {(s.supporting_documents || []).length} supporting</div>
                        </div>

                        <div className="text-[11px]">
                          <span className="text-muted-foreground">Evidence: </span>
                          <span>{s.evidence_summary}</span>
                        </div>

                        <div className="text-[11px] bg-muted/30 rounded px-2 py-1.5">
                          <span className="text-muted-foreground font-semibold">Proposed change: </span>
                          <span className="font-mono">
                            {change.action === 'add' && `Add "${change.value}" to ${change.key?.split('.')[0]}`}
                            {change.action === 'add_uom' && `Add UOM "${change.uom}" for item "${change.item}"`}
                            {change.action === 'widen' && 'Widen order-value tolerance by ~15-20%'}
                            {change.action === 'revise' && 'Relax PO pattern to accept any format'}
                            {change.action === 'increase' && `Increase variability index from ${change.current}`}
                          </span>
                        </div>

                        {s.current_profile_snapshot && (
                          <div className="text-[10px] text-muted-foreground">
                            Profile: {s.current_profile_snapshot.template_confidence} confidence, {s.current_profile_snapshot.invoices_analyzed} orders
                          </div>
                        )}

                        {s.applied_by && <div className="text-[10px] text-emerald-600">Applied by {s.applied_by} at {s.applied_at}</div>}
                        {s.approved_by && !s.applied_by && <div className="text-[10px] text-blue-600">Approved by {s.approved_by} at {s.approved_at}</div>}
                        {s.rejected_by && <div className="text-[10px] text-red-600">Rejected by {s.rejected_by} at {s.rejected_at}</div>}

                        {/* Action buttons */}
                        <div className="flex items-center gap-2 pt-1">
                          {(s.status === 'pending' || s.status === 'insufficient_evidence') && (
                            <>
                              <Button size="sm" className="h-6 text-[10px] bg-blue-600 hover:bg-blue-700" onClick={() => handleAction(s.suggestion_id, 'approve')}
                                disabled={actionLoading === `${s.suggestion_id}-approve`} data-testid={`approve-${s.suggestion_id}`}>
                                {actionLoading === `${s.suggestion_id}-approve` ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3 mr-1" />}
                                Approve
                              </Button>
                              <Button size="sm" variant="outline" className="h-6 text-[10px] text-red-600 border-red-300 hover:bg-red-500/10" onClick={() => handleAction(s.suggestion_id, 'reject')}
                                disabled={actionLoading === `${s.suggestion_id}-reject`} data-testid={`reject-${s.suggestion_id}`}>
                                <XCircle className="w-3 h-3 mr-1" />Reject
                              </Button>
                            </>
                          )}
                          {s.status === 'approved' && (
                            <>
                              <Button size="sm" className="h-6 text-[10px] bg-emerald-600 hover:bg-emerald-700" onClick={() => handleAction(s.suggestion_id, 'apply')}
                                disabled={actionLoading === `${s.suggestion_id}-apply`} data-testid={`apply-${s.suggestion_id}`}>
                                {actionLoading === `${s.suggestion_id}-apply` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3 mr-1" />}
                                Apply to Profile
                              </Button>
                              <Button size="sm" variant="outline" className="h-6 text-[10px] text-red-600 border-red-300 hover:bg-red-500/10" onClick={() => handleAction(s.suggestion_id, 'reject')}
                                disabled={actionLoading === `${s.suggestion_id}-reject`}>
                                <XCircle className="w-3 h-3 mr-1" />Reject
                              </Button>
                            </>
                          )}
                          {s.status === 'applied' && (
                            <div className="flex items-center gap-1.5 text-[10px] text-emerald-600">
                              <CheckCircle2 className="w-3 h-3" />
                              Applied{s.apply_result?.no_op ? ' (no-op — already present)' : ''}
                            </div>
                          )}
                          {s.status === 'rejected' && (
                            <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground">
                              <AlertTriangle className="w-3 h-3" />Rejected
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
