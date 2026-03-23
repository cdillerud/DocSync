import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import { toast } from 'sonner';
import {
  ShoppingCart, Loader2, CheckCircle2, AlertCircle,
  AlertTriangle, Search, RefreshCw, ChevronRight,
  FileText, ExternalLink, CircleDot, XCircle, Clock,
  ArrowUpDown, Filter,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_CONFIG = {
  ready:            { label: 'Ready',              color: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-700', icon: CheckCircle2, iconColor: 'text-emerald-500' },
  ready_warnings:   { label: 'Ready w/ Warnings',  color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200 dark:border-amber-700', icon: AlertTriangle, iconColor: 'text-amber-500' },
  needs_review:     { label: 'Needs Review',        color: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300 border-red-200 dark:border-red-700', icon: AlertCircle, iconColor: 'text-red-500' },
  already_created:  { label: 'Already Created',     color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300 border-blue-200 dark:border-blue-700', icon: CircleDot, iconColor: 'text-blue-500' },
};

export default function SalesDashboardPage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [summary, setSummary] = useState({ ready: 0, ready_warnings: 0, needs_review: 0, already_created: 0, total: 0 });
  const [total, setTotal] = useState(0);

  // Filters
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [createdFilter, setCreatedFilter] = useState('all');
  const [sortBy, setSortBy] = useState('created_desc');

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (search) params.set('search', search);
      if (statusFilter !== 'all') params.set('status', statusFilter);
      if (createdFilter === 'yes') params.set('has_bc_order', 'yes');
      else if (createdFilter === 'no') params.set('has_bc_order', 'no');
      params.set('sort', sortBy);
      params.set('limit', '100');

      const res = await fetch(`${API}/api/sales-dashboard/queue?${params}`);
      const data = await res.json();
      setItems(data.items || []);
      setTotal(data.total || 0);
      if (data.summary) setSummary(data.summary);
    } catch (err) {
      toast.error('Failed to load sales queue');
    } finally {
      setLoading(false);
    }
  }, [search, statusFilter, createdFilter, sortBy]);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  // Debounced search
  const [searchInput, setSearchInput] = useState('');
  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  const activeFilter = statusFilter !== 'all' || createdFilter !== 'all' || search;

  return (
    <div className="max-w-[1400px] mx-auto space-y-6" data-testid="sales-dashboard-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <ShoppingCart className="w-5 h-5 text-primary" />
            Sales Orders
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Orders awaiting review, correction, or creation in Business Central
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchQueue} disabled={loading} data-testid="sales-refresh-btn">
            <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            className="text-red-500 border-red-200 hover:bg-red-50 dark:border-red-800 dark:hover:bg-red-950"
            data-testid="sales-clear-queue-btn"
            onClick={async () => {
              if (!window.confirm(`Clear all ${total} sales documents from the queue? This cannot be undone.`)) return;
              try {
                const resp = await fetch(`${API}/api/sales-dashboard/queue/clear`, { method: 'DELETE' });
                const data = await resp.json();
                toast.success(`Cleared ${data.deleted} documents`);
                fetchQueue();
              } catch (err) {
                toast.error('Failed to clear queue');
              }
            }}
          >
            <XCircle className="w-4 h-4 mr-1.5" />
            Clear Queue
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <SummaryCards summary={summary} activeStatus={statusFilter} onStatusClick={(s) => setStatusFilter(s === statusFilter ? 'all' : s)} />

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3" data-testid="sales-filters">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            placeholder="Search PO, customer, filename..."
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="pl-9 h-9 text-sm"
            data-testid="sales-search-input"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-44 h-9 text-sm" data-testid="sales-status-filter">
            <Filter className="w-3.5 h-3.5 mr-1.5 text-muted-foreground" />
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="ready">Ready</SelectItem>
            <SelectItem value="ready_warnings">Ready w/ Warnings</SelectItem>
            <SelectItem value="needs_review">Needs Review</SelectItem>
            <SelectItem value="already_created">Already Created</SelectItem>
          </SelectContent>
        </Select>
        <Select value={createdFilter} onValueChange={setCreatedFilter}>
          <SelectTrigger className="w-40 h-9 text-sm" data-testid="sales-created-filter">
            <SelectValue placeholder="BC Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="no">Not Created</SelectItem>
            <SelectItem value="yes">Already Created</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sortBy} onValueChange={setSortBy}>
          <SelectTrigger className="w-40 h-9 text-sm" data-testid="sales-sort-select">
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
        {activeFilter && (
          <Button variant="ghost" size="sm" className="h-9 text-xs" onClick={() => { setStatusFilter('all'); setCreatedFilter('all'); setSearchInput(''); setSearch(''); }} data-testid="sales-clear-filters-btn">
            <XCircle className="w-3.5 h-3.5 mr-1" /> Clear
          </Button>
        )}
      </div>

      {/* Queue Table */}
      <Card className="border border-border" data-testid="sales-queue-table">
        <CardContent className="p-0">
          {loading && items.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center text-muted-foreground">
              <ShoppingCart className="w-10 h-10 mx-auto mb-3 opacity-20" />
              <p className="text-sm">No sales orders found{activeFilter ? ' matching filters' : ''}</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase tracking-wider">
                    <th className="text-left py-3 px-4 font-medium">Status</th>
                    <th className="text-left py-3 px-3 font-medium">Customer</th>
                    <th className="text-left py-3 px-3 font-medium">PO / Ext Doc</th>
                    <th className="text-left py-3 px-3 font-medium">File</th>
                    <th className="text-right py-3 px-3 font-medium">Amount</th>
                    <th className="text-center py-3 px-3 font-medium">Lines</th>
                    <th className="text-left py-3 px-3 font-medium">Date</th>
                    <th className="text-left py-3 px-3 font-medium">Info</th>
                    <th className="text-right py-3 px-4 font-medium">Action</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <QueueRow key={item.id} item={item} navigate={navigate} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!loading && items.length > 0 && (
            <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground flex items-center justify-between">
              <span>Showing {items.length} of {total} documents</span>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* SUMMARY CARDS                                                   */
/* ════════════════════════════════════════════════════════════════ */

function SummaryCards({ summary, activeStatus, onStatusClick }) {
  const cards = [
    { key: 'ready', label: 'Ready', count: summary.ready, bg: 'bg-emerald-50 dark:bg-emerald-950/20', border: 'border-emerald-200 dark:border-emerald-800', text: 'text-emerald-700 dark:text-emerald-300', icon: CheckCircle2, iconColor: 'text-emerald-500' },
    { key: 'ready_warnings', label: 'With Warnings', count: summary.ready_warnings, bg: 'bg-amber-50 dark:bg-amber-950/20', border: 'border-amber-200 dark:border-amber-800', text: 'text-amber-700 dark:text-amber-300', icon: AlertTriangle, iconColor: 'text-amber-500' },
    { key: 'needs_review', label: 'Needs Review', count: summary.needs_review, bg: 'bg-red-50 dark:bg-red-950/20', border: 'border-red-200 dark:border-red-800', text: 'text-red-700 dark:text-red-300', icon: AlertCircle, iconColor: 'text-red-500' },
    { key: 'already_created', label: 'Already Created', count: summary.already_created, bg: 'bg-blue-50 dark:bg-blue-950/20', border: 'border-blue-200 dark:border-blue-800', text: 'text-blue-700 dark:text-blue-300', icon: CircleDot, iconColor: 'text-blue-500' },
  ];

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="sales-summary-cards">
      {cards.map(c => {
        const Icon = c.icon;
        const active = activeStatus === c.key;
        return (
          <Card
            key={c.key}
            className={`cursor-pointer transition-all border ${c.border} ${c.bg} ${active ? 'ring-2 ring-primary shadow-sm' : 'hover:shadow-sm'}`}
            onClick={() => onStatusClick(c.key)}
            data-testid={`sales-card-${c.key}`}
          >
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className={`text-2xl font-bold ${c.text}`}>{c.count}</p>
                  <p className="text-xs text-muted-foreground mt-0.5">{c.label}</p>
                </div>
                <Icon className={`w-5 h-5 ${c.iconColor} opacity-70`} />
              </div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* QUEUE ROW                                                       */
/* ════════════════════════════════════════════════════════════════ */

function QueueRow({ item, navigate }) {
  const cfg = STATUS_CONFIG[item.status] || STATUS_CONFIG.needs_review;
  const Icon = cfg.icon;
  const hasWarnings = (item.warnings?.length || 0) + (item.blocking_issues?.length || 0) > 0;
  const allIssues = [...(item.blocking_issues || []), ...(item.warnings || [])];

  const formatDate = (d) => {
    if (!d) return '-';
    try {
      return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' });
    } catch { return d; }
  };

  const formatAmount = (a) => {
    if (a == null) return '-';
    const num = typeof a === 'string' ? parseFloat(a.replace(/,/g, '')) : Number(a);
    if (isNaN(num)) return '-';
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const handleAction = () => {
    navigate(`/documents/${encodeURIComponent(item.id)}`);
  };

  const actionLabel = item.status === 'already_created' ? 'View' : item.status === 'ready' || item.status === 'ready_warnings' ? 'Review' : 'Review';

  return (
    <tr className="border-b border-border/50 hover:bg-muted/30 transition-colors group" data-testid={`sales-row-${item.id}`}>
      {/* Status */}
      <td className="py-3 px-4">
        <Badge variant="outline" className={`text-[10px] font-medium ${cfg.color}`} data-testid={`sales-row-${item.id}-status`}>
          <Icon className={`w-3 h-3 mr-1 ${cfg.iconColor}`} />
          {cfg.label}
        </Badge>
      </td>

      {/* Customer */}
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

      {/* PO / External Doc */}
      <td className="py-3 px-3">
        {item.external_doc_no ? (
          <span className="text-xs font-mono" data-testid={`sales-row-${item.id}-po`}>{item.external_doc_no}</span>
        ) : (
          <span className="text-xs text-muted-foreground italic">None</span>
        )}
      </td>

      {/* Filename */}
      <td className="py-3 px-3">
        <div className="flex items-center gap-1.5 min-w-0">
          <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <span className="text-xs truncate max-w-[180px]" title={item.file_name}>{item.file_name || '-'}</span>
        </div>
      </td>

      {/* Amount */}
      <td className="py-3 px-3 text-right">
        <span className="text-xs font-mono font-medium">{formatAmount(item.amount)}</span>
      </td>

      {/* Lines */}
      <td className="py-3 px-3 text-center">
        <span className="text-xs text-muted-foreground">{item.line_count || (item.status === 'already_created' ? `${item.bc_lines_added}/${item.bc_lines_total}` : '0')}</span>
      </td>

      {/* Date */}
      <td className="py-3 px-3">
        <div className="flex items-center gap-1">
          <Clock className="w-3 h-3 text-muted-foreground" />
          <span className="text-xs text-muted-foreground">{formatDate(item.created_utc)}</span>
        </div>
      </td>

      {/* Info (warnings / BC record) */}
      <td className="py-3 px-3">
        {item.status === 'already_created' && item.bc_record_no ? (
          <div className="flex items-center gap-1">
            <Badge variant="secondary" className="text-[10px] font-mono" data-testid={`sales-row-${item.id}-bc-no`}>
              SO {item.bc_record_no}
            </Badge>
          </div>
        ) : hasWarnings ? (
          <span className="text-[10px] text-amber-600 dark:text-amber-400 truncate block max-w-[180px]" title={allIssues.join('; ')}>
            {allIssues[0]}
            {allIssues.length > 1 && ` (+${allIssues.length - 1})`}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground">-</span>
        )}
      </td>

      {/* Action */}
      <td className="py-3 px-4 text-right">
        <Button
          variant={item.status === 'ready' ? 'default' : 'outline'}
          size="sm"
          className="h-7 text-xs"
          onClick={handleAction}
          data-testid={`sales-row-${item.id}-action`}
        >
          {item.status === 'already_created' ? (
            <><ExternalLink className="w-3 h-3 mr-1" /> View</>
          ) : (
            <><ChevronRight className="w-3 h-3 mr-1" /> {actionLabel}</>
          )}
        </Button>
      </td>
    </tr>
  );
}
