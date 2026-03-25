import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  DialogDescription,
} from '../components/ui/dialog';
import { Textarea } from '../components/ui/textarea';
import { toast } from 'sonner';
import {
  Loader2, CheckCircle2, AlertTriangle, Flag, Search, RefreshCw,
  ChevronRight, FileText, Clock, User, Inbox, ArrowUpDown,
  XCircle, CircleDot, UserCheck,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const REVIEW_STATUS_CONFIG = {
  pending_rep_review: { label: 'Pending Review', color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-700', icon: Clock },
  approved:           { label: 'Approved',       color: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-700', icon: CheckCircle2 },
  flagged:            { label: 'Flagged',        color: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 border-red-200 dark:border-red-700', icon: Flag },
};

export default function MyQueuePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(false);
  const [reps, setReps] = useState([]);
  const [selectedRep, setSelectedRep] = useState('');
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState({ pending_rep_review: 0, approved: 0, flagged: 0, total: 0 });
  const [statusFilter, setStatusFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState('created_desc');

  // Flag modal
  const [flagModal, setFlagModal] = useState({ open: false, docId: '', fileName: '' });
  const [flagNotes, setFlagNotes] = useState('');
  const [actionLoading, setActionLoading] = useState('');

  // Load reps on mount
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/sales-dashboard/reps`);
        const data = await res.json();
        setReps(data.reps || []);
        if (data.reps?.length > 0) {
          setSelectedRep(data.reps[0].rep_email);
        }
      } catch {
        toast.error('Failed to load sales reps');
      }
    })();
  }, []);

  // Debounce search
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Fetch queue when rep / filters change
  const fetchQueue = useCallback(async () => {
    if (!selectedRep) return;
    setLoading(true);
    try {
      const params = new URLSearchParams({ rep_email: selectedRep, sort: sortBy, limit: '200' });
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (search) params.set('search', search);
      const res = await fetch(`${API}/api/sales-dashboard/my-queue?${params}`);
      const data = await res.json();
      setItems(data.items || []);
      setSummary(data.summary || { pending_rep_review: 0, approved: 0, flagged: 0, total: 0 });
    } catch {
      toast.error('Failed to load queue');
    } finally {
      setLoading(false);
    }
  }, [selectedRep, statusFilter, search, sortBy]);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  // Actions
  const handleApprove = async (docId) => {
    setActionLoading(docId);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/queue/${docId}/approve`, { method: 'POST' });
      if (!res.ok) throw new Error('Approve failed');
      toast.success('Document approved');
      fetchQueue();
    } catch {
      toast.error('Failed to approve document');
    } finally {
      setActionLoading('');
    }
  };

  const handleFlag = async () => {
    if (!flagModal.docId) return;
    setActionLoading(flagModal.docId);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/queue/${flagModal.docId}/flag`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ notes: flagNotes }),
      });
      if (!res.ok) throw new Error('Flag failed');
      toast.success('Document flagged');
      setFlagModal({ open: false, docId: '', fileName: '' });
      setFlagNotes('');
      fetchQueue();
    } catch {
      toast.error('Failed to flag document');
    } finally {
      setActionLoading('');
    }
  };

  const selectedRepName = reps.find(r => r.rep_email === selectedRep)?.rep_name || selectedRep;

  return (
    <div className="max-w-[1400px] mx-auto space-y-6" data-testid="my-queue-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Inbox className="w-5 h-5 text-primary" />
            My Queue
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Documents assigned to you for review
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Rep dropdown */}
          <div className="flex items-center gap-2">
            <User className="w-4 h-4 text-muted-foreground" />
            <Select value={selectedRep} onValueChange={setSelectedRep}>
              <SelectTrigger className="w-64 h-9 text-sm" data-testid="rep-selector">
                <UserCheck className="w-3.5 h-3.5 mr-1.5 text-muted-foreground" />
                <SelectValue placeholder="Select Rep" />
              </SelectTrigger>
              <SelectContent>
                {reps.map(r => (
                  <SelectItem key={r.rep_email} value={r.rep_email}>
                    {r.rep_name || r.rep_email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <Button variant="outline" size="sm" onClick={fetchQueue} disabled={loading} data-testid="my-queue-refresh-btn">
            <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      {selectedRep && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="my-queue-summary">
          <SummaryCard label="Pending Review" count={summary.pending_rep_review} color="amber" icon={Clock} active={statusFilter === 'pending_rep_review'} onClick={() => setStatusFilter(statusFilter === 'pending_rep_review' ? 'all' : 'pending_rep_review')} />
          <SummaryCard label="Approved" count={summary.approved} color="emerald" icon={CheckCircle2} active={statusFilter === 'approved'} onClick={() => setStatusFilter(statusFilter === 'approved' ? 'all' : 'approved')} />
          <SummaryCard label="Flagged" count={summary.flagged} color="red" icon={Flag} active={statusFilter === 'flagged'} onClick={() => setStatusFilter(statusFilter === 'flagged' ? 'all' : 'flagged')} />
          <SummaryCard label="Total Assigned" count={summary.total} color="blue" icon={Inbox} active={false} onClick={() => setStatusFilter('all')} />
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3" data-testid="my-queue-filters">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="Search PO, customer, filename..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} className="pl-9 h-9 text-sm" data-testid="my-queue-search" />
        </div>
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-40 h-9 text-sm" data-testid="my-queue-sort">
            <ArrowUpDown className="w-3.5 h-3.5 mr-1.5 text-muted-foreground" />
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="created_desc">Newest First</SelectItem>
            <SelectItem value="created_asc">Oldest First</SelectItem>
            <SelectItem value="amount_desc">Highest Amount</SelectItem>
            <SelectItem value="amount_asc">Lowest Amount</SelectItem>
          </SelectContent>
        </Select>
        {(statusFilter !== 'all' || search) && (
          <Button variant="ghost" size="sm" className="h-9 text-xs" onClick={() => { setStatusFilter('all'); setSearchInput(''); setSearch(''); }} data-testid="my-queue-clear-filters">
            <XCircle className="w-3.5 h-3.5 mr-1" /> Clear
          </Button>
        )}
      </div>

      {/* No rep selected */}
      {!selectedRep && (
        <Card className="border border-border">
          <CardContent className="py-16 text-center text-muted-foreground">
            <User className="w-10 h-10 mx-auto mb-3 opacity-20" />
            <p className="text-sm">Select a sales rep to view their queue</p>
          </CardContent>
        </Card>
      )}

      {/* Queue Table */}
      {selectedRep && (
        <Card className="border border-border" data-testid="my-queue-table">
          <CardContent className="p-0">
            {loading && items.length === 0 ? (
              <div className="flex items-center justify-center py-16">
                <Loader2 className="w-6 h-6 animate-spin text-primary" />
              </div>
            ) : items.length === 0 ? (
              <div className="py-16 text-center text-muted-foreground">
                <Inbox className="w-10 h-10 mx-auto mb-3 opacity-20" />
                <p className="text-sm">No documents in {selectedRepName}'s queue{statusFilter !== 'all' ? ` with status "${statusFilter}"` : ''}</p>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase tracking-wider">
                      <th className="text-left py-3 px-4 font-medium">Review Status</th>
                      <th className="text-left py-3 px-3 font-medium">Customer</th>
                      <th className="text-left py-3 px-3 font-medium">PO / Ext Doc</th>
                      <th className="text-left py-3 px-3 font-medium">File</th>
                      <th className="text-right py-3 px-3 font-medium">Amount</th>
                      <th className="text-center py-3 px-3 font-medium">Lines</th>
                      <th className="text-left py-3 px-3 font-medium">Date</th>
                      <th className="text-left py-3 px-3 font-medium">Info</th>
                      <th className="text-right py-3 px-4 font-medium">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((item) => (
                      <QueueRow
                        key={item.id}
                        item={item}
                        navigate={navigate}
                        onApprove={handleApprove}
                        onFlag={(id, fn) => { setFlagModal({ open: true, docId: id, fileName: fn }); setFlagNotes(''); }}
                        actionLoading={actionLoading}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {!loading && items.length > 0 && (
              <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
                Showing {items.length} documents for {selectedRepName}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Flag Modal */}
      <Dialog open={flagModal.open} onOpenChange={(open) => { if (!open) setFlagModal({ open: false, docId: '', fileName: '' }); }}>
        <DialogContent className="sm:max-w-md" data-testid="flag-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Flag className="w-4 h-4 text-red-500" />
              Flag Document
            </DialogTitle>
            <DialogDescription>
              Flag <span className="font-mono font-medium">{flagModal.fileName}</span> for attention
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Textarea
              placeholder="Add notes about the issue (e.g., 'Customer requested different ship date', 'PO number mismatch')..."
              value={flagNotes}
              onChange={(e) => setFlagNotes(e.target.value)}
              className="min-h-[100px] text-sm"
              data-testid="flag-notes-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setFlagModal({ open: false, docId: '', fileName: '' })}>
              Cancel
            </Button>
            <Button variant="destructive" size="sm" onClick={handleFlag} disabled={actionLoading === flagModal.docId} data-testid="flag-confirm-btn">
              {actionLoading === flagModal.docId ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Flag className="w-4 h-4 mr-1.5" />}
              Flag Document
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* SUMMARY CARD                                                    */
/* ════════════════════════════════════════════════════════════════ */

function SummaryCard({ label, count, color, icon: Icon, active, onClick }) {
  const colorMap = {
    amber:   { bg: 'bg-amber-50 dark:bg-amber-950/20', border: 'border-amber-200 dark:border-amber-800', text: 'text-amber-700 dark:text-amber-300', icon: 'text-amber-500' },
    emerald: { bg: 'bg-emerald-50 dark:bg-emerald-950/20', border: 'border-emerald-200 dark:border-emerald-800', text: 'text-emerald-700 dark:text-emerald-300', icon: 'text-emerald-500' },
    red:     { bg: 'bg-red-50 dark:bg-red-950/20', border: 'border-red-200 dark:border-red-800', text: 'text-red-700 dark:text-red-300', icon: 'text-red-500' },
    blue:    { bg: 'bg-blue-50 dark:bg-blue-950/20', border: 'border-blue-200 dark:border-blue-800', text: 'text-blue-700 dark:text-blue-300', icon: 'text-blue-500' },
  };
  const c = colorMap[color];
  return (
    <Card
      className={`cursor-pointer transition-all border ${c.border} ${c.bg} ${active ? 'ring-2 ring-primary shadow-sm' : 'hover:shadow-sm'}`}
      onClick={onClick}
      data-testid={`my-queue-card-${label.toLowerCase().replace(/\s/g, '-')}`}
    >
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className={`text-2xl font-bold ${c.text}`}>{count}</p>
            <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
          </div>
          <Icon className={`w-5 h-5 ${c.icon} opacity-70`} />
        </div>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* QUEUE ROW                                                       */
/* ════════════════════════════════════════════════════════════════ */

function QueueRow({ item, navigate, onApprove, onFlag, actionLoading }) {
  const reviewStatus = item.sales_review_status || 'pending_rep_review';
  const cfg = REVIEW_STATUS_CONFIG[reviewStatus] || REVIEW_STATUS_CONFIG.pending_rep_review;
  const StatusIcon = cfg.icon;

  const formatDate = (d) => {
    if (!d) return '-';
    try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' }); } catch { return d; }
  };

  const formatAmount = (a) => {
    if (a == null) return '-';
    const num = typeof a === 'string' ? parseFloat(a.replace(/,/g, '')) : Number(a);
    if (isNaN(num)) return '-';
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const isLoading = actionLoading === item.id;
  const isPending = reviewStatus === 'pending_rep_review';

  return (
    <tr className="border-b border-border/50 hover:bg-muted/30 transition-colors group" data-testid={`my-queue-row-${item.id}`}>
      <td className="py-3 px-4">
        <Badge variant="outline" className={`text-[10px] font-medium ${cfg.color}`} data-testid={`my-queue-row-${item.id}-status`}>
          <StatusIcon className="w-3 h-3 mr-1" />
          {cfg.label}
        </Badge>
      </td>
      <td className="py-3 px-3">
        <div className="min-w-0">
          {item.customer_name ? (
            <span className="text-xs font-medium truncate block max-w-[160px]" title={item.customer_name}>{item.customer_name}</span>
          ) : (
            <span className="text-xs text-muted-foreground italic">Not resolved</span>
          )}
          {item.customer_no && <span className="text-[10px] text-muted-foreground font-mono block">{item.customer_no}</span>}
        </div>
      </td>
      <td className="py-3 px-3">
        {item.external_doc_no ? (
          <span className="text-xs font-mono">{item.external_doc_no}</span>
        ) : (
          <span className="text-xs text-muted-foreground italic">None</span>
        )}
      </td>
      <td className="py-3 px-3">
        <div className="flex items-center gap-1.5 min-w-0">
          <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs truncate max-w-[180px]" title={item.file_name}>{item.file_name || '-'}</span>
        </div>
      </td>
      <td className="py-3 px-3 text-right">
        <span className="text-xs font-mono font-medium">{formatAmount(item.amount)}</span>
      </td>
      <td className="py-3 px-3 text-center">
        <span className="text-xs text-muted-foreground">{item.line_count || 0}</span>
      </td>
      <td className="py-3 px-3">
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">{formatDate(item.created_utc)}</span>
        </div>
      </td>
      <td className="py-3 px-3">
        {reviewStatus === 'flagged' && item.flag_notes ? (
          <span className="text-[10px] text-red-600 dark:text-red-400 truncate block max-w-[180px]" title={item.flag_notes}>
            {item.flag_notes}
          </span>
        ) : item.warnings?.length > 0 ? (
          <span className="text-[10px] text-amber-600 dark:text-amber-400 truncate block max-w-[180px]" title={item.warnings.join('; ')}>
            {item.warnings[0]}{item.warnings.length > 1 && ` (+${item.warnings.length - 1})`}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </td>
      <td className="py-3 px-4 text-right">
        <div className="flex items-center justify-end gap-1.5">
          {(isPending || reviewStatus === 'flagged') && (
            <Button
              variant="default"
              size="sm"
              className="h-7 text-xs"
              onClick={() => onApprove(item.id)}
              disabled={isLoading}
              data-testid={`my-queue-approve-${item.id}`}
            >
              {isLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3 mr-1" />}
              Approve
            </Button>
          )}
          {isPending && (
            <Button
              variant="outline"
              size="sm"
              className="h-7 text-xs text-red-600 border-red-200 hover:bg-red-50 dark:text-red-400 dark:border-red-800 dark:hover:bg-red-950"
              onClick={() => onFlag(item.id, item.file_name)}
              disabled={isLoading}
              data-testid={`my-queue-flag-${item.id}`}
            >
              <Flag className="w-3 h-3 mr-1" />
              Flag
            </Button>
          )}
          <Button
            variant="ghost"
            size="sm"
            className="h-7 text-xs"
            onClick={() => navigate(`/review/${encodeURIComponent(item.id)}`)}
            data-testid={`my-queue-view-${item.id}`}
          >
            <ChevronRight className="w-3 h-3" />
          </Button>
        </div>
      </td>
    </tr>
  );
}
