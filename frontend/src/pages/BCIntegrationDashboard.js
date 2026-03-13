import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import {
  ShoppingCart, FileInput, AlertTriangle, Copy, RefreshCw,
  Loader2, ExternalLink, Search, ChevronLeft, ChevronRight,
  CheckCircle2, XCircle, ArrowUpDown
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

export default function BCIntegrationDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFilters] = useState({ record_type: '', status: '', search: '' });
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 25;

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (filters.record_type) params.set('record_type', filters.record_type);
      if (filters.status) params.set('status', filters.status);
      params.set('limit', String(PAGE_SIZE));
      params.set('skip', String(page * PAGE_SIZE));

      const res = await fetch(`${API}/api/gpi-integration/dashboard?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [filters.record_type, filters.status, page]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const filteredTransactions = (data?.transactions || []).filter(t => {
    if (!filters.search) return true;
    const s = filters.search.toLowerCase();
    return (
      (t.bc_record_no || '').toLowerCase().includes(s) ||
      (t.source_document_id || '').toLowerCase().includes(s) ||
      (t.idempotency_key || '').toLowerCase().includes(s) ||
      (t.customer_name || '').toLowerCase().includes(s) ||
      (t.vendor_name || '').toLowerCase().includes(s) ||
      (t.external_ref || '').toLowerCase().includes(s) ||
      (t.transaction_id || '').toLowerCase().includes(s)
    );
  });

  const counts = data?.counts || {};
  const totalPages = Math.ceil((data?.total || 0) / PAGE_SIZE);

  return (
    <div className="space-y-6" data-testid="bc-integration-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            BC Integration
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Business Central record creation audit log
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} data-testid="dashboard-refresh-btn">
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4" data-testid="dashboard-summary-cards">
        <SummaryCard
          title="Sales Orders"
          count={counts.sales_order_created || 0}
          icon={<ShoppingCart className="w-5 h-5" />}
          color="blue"
          testId="card-sales-orders"
        />
        <SummaryCard
          title="Purchase Invoices"
          count={counts.purchase_invoice_created || 0}
          icon={<FileInput className="w-5 h-5" />}
          color="violet"
          testId="card-purchase-invoices"
        />
        <SummaryCard
          title="Already Exists"
          count={counts.already_exists || 0}
          icon={<Copy className="w-5 h-5" />}
          color="amber"
          testId="card-already-exists"
        />
        <SummaryCard
          title="Failed"
          count={counts.failed || 0}
          icon={<XCircle className="w-5 h-5" />}
          color="red"
          testId="card-failed"
        />
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center" data-testid="dashboard-filters">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            className="pl-9 h-9 text-sm"
            placeholder="Search by record no, document, key..."
            value={filters.search}
            onChange={e => setFilters(f => ({ ...f, search: e.target.value }))}
            data-testid="dashboard-search-input"
          />
        </div>
        <Select
          value={filters.record_type}
          onValueChange={v => { setFilters(f => ({ ...f, record_type: v === 'all' ? '' : v })); setPage(0); }}
        >
          <SelectTrigger className="w-[180px] h-9 text-sm" data-testid="filter-record-type">
            <SelectValue placeholder="All Record Types" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Record Types</SelectItem>
            <SelectItem value="sales_order">Sales Orders</SelectItem>
            <SelectItem value="purchase_invoice">Purchase Invoices</SelectItem>
          </SelectContent>
        </Select>
        <Select
          value={filters.status}
          onValueChange={v => { setFilters(f => ({ ...f, status: v === 'all' ? '' : v })); setPage(0); }}
        >
          <SelectTrigger className="w-[160px] h-9 text-sm" data-testid="filter-status">
            <SelectValue placeholder="All Statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="created">Created</SelectItem>
            <SelectItem value="already_exists">Already Exists</SelectItem>
            <SelectItem value="failed">Failed</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-3 text-sm text-red-600 dark:text-red-400">
          Failed to load dashboard: {error}
        </div>
      )}

      {/* Transaction Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-xs" data-testid="dashboard-transactions-table">
              <thead>
                <tr className="border-b bg-muted/40">
                  <th className="text-left p-3 font-medium text-muted-foreground">Timestamp</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Type</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">BC Record No</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Counterparty</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">External Ref</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Status</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Idempotency Key</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Transaction ID</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Source Doc</th>
                  <th className="text-left p-3 font-medium text-muted-foreground">Error</th>
                </tr>
              </thead>
              <tbody>
                {loading && !data && (
                  <tr>
                    <td colSpan={10} className="p-8 text-center text-muted-foreground">
                      <Loader2 className="w-5 h-5 animate-spin inline mr-2" />Loading...
                    </td>
                  </tr>
                )}
                {!loading && filteredTransactions.length === 0 && (
                  <tr>
                    <td colSpan={10} className="p-8 text-center text-muted-foreground">
                      No integration transactions found.
                    </td>
                  </tr>
                )}
                {filteredTransactions.map((txn, i) => (
                  <TransactionRow key={`${txn.source_document_id}-${txn.record_type}-${i}`} txn={txn} />
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t p-3">
              <span className="text-xs text-muted-foreground">
                Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, data?.total || 0)} of {data?.total || 0}
              </span>
              <div className="flex gap-1">
                <Button
                  variant="outline" size="sm" className="h-7 text-xs"
                  disabled={page === 0}
                  onClick={() => setPage(p => p - 1)}
                  data-testid="pagination-prev"
                >
                  <ChevronLeft className="w-3 h-3" />
                </Button>
                <span className="flex items-center px-2 text-xs text-muted-foreground">
                  {page + 1} / {totalPages}
                </span>
                <Button
                  variant="outline" size="sm" className="h-7 text-xs"
                  disabled={page >= totalPages - 1}
                  onClick={() => setPage(p => p + 1)}
                  data-testid="pagination-next"
                >
                  <ChevronRight className="w-3 h-3" />
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SummaryCard({ title, count, icon, color, testId }) {
  const colors = {
    blue: 'text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/30',
    violet: 'text-violet-600 dark:text-violet-400 bg-violet-50 dark:bg-violet-950/30',
    amber: 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30',
    red: 'text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30',
  };

  return (
    <Card data-testid={testId}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">{title}</p>
            <p className="text-2xl font-bold mt-1">{count}</p>
          </div>
          <div className={`p-2.5 rounded-lg ${colors[color]}`}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function TransactionRow({ txn }) {
  const counterparty = txn.record_type === 'Sales Order'
    ? `${txn.customer_no}${txn.customer_name ? ' — ' + txn.customer_name : ''}`
    : `${txn.vendor_no}${txn.vendor_name ? ' — ' + txn.vendor_name : ''}`;

  return (
    <tr className="border-b last:border-0 hover:bg-muted/30 transition-colors" data-testid="transaction-row">
      <td className="p-3 whitespace-nowrap">
        {txn.created_at ? new Date(txn.created_at).toLocaleString(undefined, {
          month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        }) : '-'}
      </td>
      <td className="p-3">
        <Badge variant="outline" className={`text-[10px] ${txn.record_type === 'Sales Order' ? 'border-blue-300 text-blue-700 dark:text-blue-400' : 'border-violet-300 text-violet-700 dark:text-violet-400'}`}>
          {txn.record_type === 'Sales Order' ? <ShoppingCart className="w-2.5 h-2.5 mr-1 inline" /> : <FileInput className="w-2.5 h-2.5 mr-1 inline" />}
          {txn.record_type}
        </Badge>
      </td>
      <td className="p-3 font-mono font-medium">
        {txn.bc_record_no || '-'}
      </td>
      <td className="p-3 max-w-[180px] truncate" title={counterparty}>
        {counterparty || '-'}
      </td>
      <td className="p-3 font-mono text-[10px]">
        {txn.external_ref || '-'}
      </td>
      <td className="p-3">
        <StatusBadge status={txn.status} success={txn.success} />
      </td>
      <td className="p-3 font-mono text-[10px] max-w-[140px] truncate" title={txn.idempotency_key}>
        {txn.idempotency_key || '-'}
      </td>
      <td className="p-3 font-mono text-[10px] max-w-[120px] truncate" title={txn.transaction_id}>
        {txn.transaction_id || '-'}
      </td>
      <td className="p-3">
        {txn.source_document_id ? (
          <Link
            to={`/documents/${txn.source_document_id}`}
            className="inline-flex items-center gap-1 text-blue-600 dark:text-blue-400 hover:underline"
            data-testid="source-doc-link"
          >
            <ExternalLink className="w-3 h-3" />
            <span className="truncate max-w-[80px]">{txn.source_document_id.slice(0, 8)}...</span>
          </Link>
        ) : '-'}
      </td>
      <td className="p-3 max-w-[200px]">
        {txn.error_message ? (
          <span className="text-red-500 truncate block" title={txn.error_message}>
            {txn.error_message.slice(0, 60)}{txn.error_message.length > 60 ? '...' : ''}
          </span>
        ) : '-'}
      </td>
    </tr>
  );
}

function StatusBadge({ status, success }) {
  if (status === 'already_exists') {
    return (
      <Badge variant="outline" className="text-[10px] border-amber-300 text-amber-700 dark:text-amber-400 bg-amber-50/50 dark:bg-amber-950/20">
        <Copy className="w-2.5 h-2.5 mr-1 inline" />Duplicate
      </Badge>
    );
  }
  if (success) {
    return (
      <Badge variant="outline" className="text-[10px] border-emerald-300 text-emerald-700 dark:text-emerald-400 bg-emerald-50/50 dark:bg-emerald-950/20">
        <CheckCircle2 className="w-2.5 h-2.5 mr-1 inline" />Created
      </Badge>
    );
  }
  return (
    <Badge variant="outline" className="text-[10px] border-red-300 text-red-700 dark:text-red-400 bg-red-50/50 dark:bg-red-950/20">
      <XCircle className="w-2.5 h-2.5 mr-1 inline" />Failed
    </Badge>
  );
}
