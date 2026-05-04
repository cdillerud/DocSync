import { useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Search as SearchIcon, ExternalLink, FileText, Loader2, X, Filter } from 'lucide-react';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '../components/ui/select';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow
} from '../components/ui/table';

const API = process.env.REACT_APP_BACKEND_URL;

// Square9-style "drawer" presets — one click into a named bucket.
// Each preset maps to a doc-type group (passed as `document_types` to the
// list endpoint) and optionally a status. These mirror the categories
// users opened in Square9 most often.
const QUICK_FILTERS = {
  ap: {
    label: 'AP Invoices',
    types: ['AP_INVOICE', 'CREDIT_MEMO'],
  },
  po: {
    label: 'Purchase Orders',
    types: ['PurchaseOrder', 'Purchase_Order', 'PURCHASE_ORDER'],
  },
  sales: {
    label: 'Sales',
    types: ['SALES_INVOICE', 'Sales_Order', 'SALES_ORDER', 'Order_Confirmation'],
  },
  warehouse: {
    label: 'Warehouse / Shipping',
    types: ['Shipping_Document', 'SHIPMENT', 'RECEIPT', 'Receipt'],
  },
  unclassified: {
    label: 'Unclassified',
    types: ['OTHER', 'Unknown', 'unknown'],
  },
  needs_review: {
    label: 'Needs Review',
    types: [],
    status: 'NeedsReview',
  },
  exceptions: {
    label: 'Exceptions',
    types: [],
    status: 'Exception',
  },
};

function fmtDate(s) {
  if (!s) return '—';
  try {
    const d = new Date(s);
    if (isNaN(d.getTime())) return s;
    return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  } catch {
    return s;
  }
}

function fmtMoney(v) {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (Number.isNaN(n)) return String(v);
  return n.toLocaleString(undefined, { style: 'currency', currency: 'USD' });
}

// Normalize a hub_document row from either the search endpoint (compact)
// or the list endpoint (full document) into a single shape the table renders.
function normalizeRow(d) {
  const id = d.doc_id || d.id;
  const ef = d.extracted_fields || {};
  return {
    id,
    file_name: d.file_name || ef.file_name || '(unnamed)',
    document_type: d.document_type || d.doc_type || d.suggested_job_type || '—',
    vendor_canonical: d.vendor_canonical || d.vendor_raw || ef.vendor || '',
    customer: ef.customer || d.customer || '',
    invoice_number_clean: d.invoice_number_clean || ef.invoice_number || '',
    po_number_clean: d.po_number_clean || ef.po_number || '',
    amount_float: (d.amount_float ?? null),
    workflow_status: d.workflow_status || d.status || '',
    created_utc: d.created_utc || d.created_at || '',
    sharepoint_web_url: d.sharepoint_web_url || d.sharepoint_share_link_url || '',
    bc_document_no: d.bc_document_no || '',
    sender_email: ef.sender_email || d.sender_email || '',
    match_fields: d.match_fields || [],
  };
}

function MatchPills({ fields }) {
  if (!fields || fields.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {fields.map((f) => (
        <Badge key={f} variant="outline" className="text-[10px] px-1.5 py-0 font-mono" data-testid={`match-pill-${f}`}>
          {f.replace('extracted_fields.', '')}
        </Badge>
      ))}
    </div>
  );
}

export default function SearchPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();

  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [docType, setDocType] = useState(searchParams.get('doc_type') || 'all');
  const [statusFilter, setStatusFilter] = useState(searchParams.get('status') || 'all');
  const [vendor, setVendor] = useState(searchParams.get('vendor') || '');
  const [customer, setCustomer] = useState(searchParams.get('customer') || '');
  const [dateFrom, setDateFrom] = useState(searchParams.get('from') || '');
  const [dateTo, setDateTo] = useState(searchParams.get('to') || '');
  const [bcNo, setBcNo] = useState(searchParams.get('bc_no') || '');

  const [docTypeGroup, setDocTypeGroup] = useState(searchParams.get('group') || '');
  const [results, setResults] = useState([]);
  const [totalAvailable, setTotalAvailable] = useState(0);
  const [searchMethod, setSearchMethod] = useState('');
  const [docTypeOpts, setDocTypeOpts] = useState([]);
  const [statusOpts, setStatusOpts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const initialLoadDone = useRef(false);

  const filtersActive =
    (docType !== 'all') || (statusFilter !== 'all') ||
    !!vendor || !!customer || !!dateFrom || !!dateTo || !!bcNo;

  const updateUrl = useCallback(() => {
    const params = {};
    if (query.trim()) params.q = query.trim();
    if (docType !== 'all') params.doc_type = docType;
    if (statusFilter !== 'all') params.status = statusFilter;
    if (vendor) params.vendor = vendor;
    if (customer) params.customer = customer;
    if (dateFrom) params.from = dateFrom;
    if (dateTo) params.to = dateTo;
    if (bcNo) params.bc_no = bcNo;
    setSearchParams(params, { replace: true });
  }, [query, docType, statusFilter, vendor, customer, dateFrom, dateTo, bcNo, setSearchParams]);

  // Mode selection:
  //  - text query present  → /api/documents/search (relevance-ranked)
  //  - filters only        → /api/documents (browse + filter)
  //  - nothing             → /api/documents (recent 50, default browse)
  const runQuery = useCallback(async () => {
    setError('');
    setLoading(true);
    try {
      updateUrl();
      const trimmedQuery = query.trim();
      const useTextSearch = !!trimmedQuery;

      let url;
      if (useTextSearch) {
        url = `${API}/api/documents/search?q=${encodeURIComponent(trimmedQuery)}&limit=200`;
      } else {
        const params = new URLSearchParams();
        params.set('limit', '100');
        params.set('queue_view', 'false');
        params.set('include_cleared', 'true');
        if (docType !== 'all') {
          params.set('document_type', docType);
        } else if (docTypeGroup && QUICK_FILTERS[docTypeGroup]?.types) {
          params.set('document_types', QUICK_FILTERS[docTypeGroup].types.join(','));
        }
        if (statusFilter !== 'all') {
          params.set('status', statusFilter);
        } else if (docTypeGroup && QUICK_FILTERS[docTypeGroup]?.status) {
          params.set('status', QUICK_FILTERS[docTypeGroup].status);
        }
        if (dateFrom) params.set('date_from', dateFrom);
        if (dateTo) params.set('date_to', dateTo);
        // The list endpoint's `search` term covers the same fields as
        // the search endpoint; reuse it for vendor/customer/bcNo single-field
        // shorthand when the user has typed only one of those.
        const inlineSearch = vendor || customer || bcNo;
        if (inlineSearch) params.set('search', inlineSearch);
        url = `${API}/api/documents?${params.toString()}`;
      }

      const res = await fetch(url);
      if (!res.ok) throw new Error(`Request failed (${res.status})`);
      const data = await res.json();

      let rawRows;
      let total;
      let method;
      if (useTextSearch) {
        rawRows = data.results || [];
        total = data.total || rawRows.length;
        method = data.search_method || 'text';
      } else {
        rawRows = data.documents || data.items || [];
        total = data.total || rawRows.length;
        method = 'browse';
      }

      let rows = rawRows.map(normalizeRow);

      // Client-side narrowing — applies in BOTH modes for the fields
      // the chosen endpoint did not narrow on.
      if (useTextSearch) {
        if (docType !== 'all') {
          const dt = docType.toLowerCase();
          rows = rows.filter((r) => (r.document_type || '').toLowerCase().includes(dt));
        }
        if (statusFilter !== 'all') {
          const st = statusFilter.toLowerCase();
          rows = rows.filter((r) => (r.workflow_status || '').toLowerCase() === st);
        }
        if (dateFrom) {
          const fromTs = new Date(dateFrom).getTime();
          rows = rows.filter((r) => {
            const t = new Date(r.created_utc || 0).getTime();
            return Number.isFinite(t) && t >= fromTs;
          });
        }
        if (dateTo) {
          const toTs = new Date(dateTo).getTime() + 24 * 60 * 60 * 1000 - 1;
          rows = rows.filter((r) => {
            const t = new Date(r.created_utc || 0).getTime();
            return Number.isFinite(t) && t <= toTs;
          });
        }
      }

      // Vendor / customer / bcNo overlay narrowing — works in either mode
      if (vendor.trim()) {
        const v = vendor.trim().toLowerCase();
        rows = rows.filter((r) => (r.vendor_canonical || '').toLowerCase().includes(v));
      }
      if (customer.trim()) {
        const c = customer.trim().toLowerCase();
        rows = rows.filter((r) =>
          (r.customer || '').toLowerCase().includes(c) ||
          (r.file_name || '').toLowerCase().includes(c)
        );
      }
      if (bcNo.trim()) {
        const b = bcNo.trim().toLowerCase();
        rows = rows.filter((r) => (r.bc_document_no || '').toLowerCase().includes(b));
      }

      setResults(rows);
      setTotalAvailable(total);
      setSearchMethod(method);

      // Capture filter options from list endpoint when available
      if (!useTextSearch && data.filter_options) {
        if (Array.isArray(data.filter_options.types)) {
          setDocTypeOpts(data.filter_options.types);
        }
        if (Array.isArray(data.filter_options.statuses)) {
          setStatusOpts(data.filter_options.statuses);
        }
      }
    } catch (e) {
      setError(e.message || 'Request failed');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, docType, statusFilter, vendor, customer, dateFrom, dateTo, bcNo, docTypeGroup, updateUrl]);

  // Initial load — populate filter options + show recent docs by default.
  useEffect(() => {
    if (initialLoadDone.current) return;
    initialLoadDone.current = true;
    runQuery();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clearFilters = () => {
    setQuery('');
    setDocType('all');
    setStatusFilter('all');
    setVendor('');
    setCustomer('');
    setDateFrom('');
    setDateTo('');
    setBcNo('');
    setDocTypeGroup('');
    setSearchParams({}, { replace: true });
    // Re-run with cleared state
    setTimeout(runQuery, 0);
  };

  const applyQuickFilter = (key) => {
    // Toggle off if same key clicked
    const next = docTypeGroup === key ? '' : key;
    setDocTypeGroup(next);
    setDocType('all');
    if (next && QUICK_FILTERS[next]?.status) {
      setStatusFilter('all'); // group's status takes effect via URL params build above
    }
    setTimeout(runQuery, 0);
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      runQuery();
    }
  };

  return (
    <div data-testid="search-page" className="space-y-4 max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center gap-2">
        <SearchIcon className="w-6 h-6 text-primary" />
        <h1 className="text-2xl font-semibold">Documents</h1>
        <Badge variant="secondary" className="ml-2 text-[10px]">Search · Browse · Filter</Badge>
      </div>

      <div className="flex flex-wrap gap-2" data-testid="quick-filter-chips">
        {Object.entries(QUICK_FILTERS).map(([key, cfg]) => (
          <Button
            key={key}
            variant={docTypeGroup === key ? 'default' : 'outline'}
            size="sm"
            onClick={() => applyQuickFilter(key)}
            data-testid={`quick-filter-${key}`}
            className="text-xs"
          >
            {cfg.label}
          </Button>
        ))}
        {docTypeGroup && (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => { setDocTypeGroup(''); setTimeout(runQuery, 0); }}
            data-testid="quick-filter-clear"
            className="text-xs"
          >
            <X className="w-3 h-3 mr-1" /> Clear preset
          </Button>
        )}
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <Filter className="w-4 h-4" />
            Filters
            {filtersActive && (
              <Badge variant="outline" className="ml-1 text-[10px]" data-testid="filters-active-badge">active</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-2">
            <div className="md:col-span-6">
              <Input
                placeholder="Search vendor, invoice #, PO, customer, BC #, file name, or amount..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={onKeyDown}
                data-testid="search-input"
              />
            </div>
            <div className="md:col-span-2">
              <Select value={docType} onValueChange={setDocType}>
                <SelectTrigger data-testid="search-doc-type-filter">
                  <SelectValue placeholder="All types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all" data-testid="search-doc-type-all">All types</SelectItem>
                  {docTypeOpts.map((o) => (
                    <SelectItem key={o.value} value={o.value} data-testid={`search-doc-type-${o.value}`}>
                      {o.value} {o.count !== undefined && <span className="text-muted-foreground ml-1">({o.count})</span>}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2">
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger data-testid="search-status-filter">
                  <SelectValue placeholder="All statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all" data-testid="search-status-all">All statuses</SelectItem>
                  {statusOpts.map((o) => (
                    <SelectItem key={o.value} value={o.value} data-testid={`search-status-${o.value}`}>
                      {o.value} {o.count !== undefined && <span className="text-muted-foreground ml-1">({o.count})</span>}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-2 flex gap-2">
              <Button onClick={runQuery} disabled={loading} className="flex-1" data-testid="search-submit-btn">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <SearchIcon className="w-4 h-4 mr-1" />}
                Apply
              </Button>
              <Button onClick={clearFilters} variant="outline" data-testid="search-clear-btn" title="Clear filters">
                <X className="w-4 h-4" />
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 pt-1">
            <div className="md:col-span-3">
              <Input
                placeholder="Vendor"
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                onKeyDown={onKeyDown}
                data-testid="search-vendor-filter"
              />
            </div>
            <div className="md:col-span-3">
              <Input
                placeholder="Customer"
                value={customer}
                onChange={(e) => setCustomer(e.target.value)}
                onKeyDown={onKeyDown}
                data-testid="search-customer-filter"
              />
            </div>
            <div className="md:col-span-2">
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                placeholder="From"
                data-testid="search-date-from"
              />
            </div>
            <div className="md:col-span-2">
              <Input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                placeholder="To"
                data-testid="search-date-to"
              />
            </div>
            <div className="md:col-span-2">
              <Input
                placeholder="BC document #"
                value={bcNo}
                onChange={(e) => setBcNo(e.target.value)}
                onKeyDown={onKeyDown}
                data-testid="search-bc-no-filter"
              />
            </div>
          </div>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-destructive">
          <CardContent className="py-3 text-sm text-destructive" data-testid="search-error">{error}</CardContent>
        </Card>
      )}

      <Card>
        <CardHeader className="pb-3 flex flex-row items-center justify-between">
          <CardTitle className="text-base">
            Results
            {results.length > 0 && (
              <span className="ml-2 text-sm font-normal text-muted-foreground" data-testid="results-count">
                {results.length} of {totalAvailable}
                {searchMethod && <span className="ml-1">· {searchMethod}</span>}
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading && (
            <div className="flex items-center justify-center py-10 text-sm text-muted-foreground" data-testid="search-loading">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading...
            </div>
          )}
          {!loading && results.length === 0 && (
            <div className="py-10 text-center text-sm text-muted-foreground" data-testid="search-empty">
              No documents match these filters. Try clearing filters or a broader query.
            </div>
          )}
          {!loading && results.length > 0 && (
            <Table data-testid="search-results-table">
              <TableHeader>
                <TableRow>
                  <TableHead>Document</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Vendor / Customer</TableHead>
                  <TableHead>Invoice / PO</TableHead>
                  <TableHead className="text-right">Amount</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Open</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {results.map((r) => (
                  <TableRow
                    key={r.id}
                    className="cursor-pointer hover:bg-muted/40"
                    data-testid={`search-result-row-${r.id}`}
                    onClick={() => navigate(`/documents/${r.id}`)}
                  >
                    <TableCell className="max-w-[260px]">
                      <div className="flex items-start gap-2">
                        <FileText className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
                        <div className="min-w-0">
                          <div className="font-medium truncate" title={r.file_name}>
                            {r.file_name}
                          </div>
                          <MatchPills fields={r.match_fields} />
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {r.document_type}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate" title={r.vendor_canonical || r.customer || ''}>
                      {r.vendor_canonical || r.customer || '—'}
                    </TableCell>
                    <TableCell className="max-w-[160px] truncate font-mono text-xs">
                      {r.invoice_number_clean || r.po_number_clean || '—'}
                    </TableCell>
                    <TableCell className="text-right font-mono text-xs">
                      {fmtMoney(r.amount_float)}
                    </TableCell>
                    <TableCell className="text-xs">
                      {fmtDate(r.created_utc)}
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-[10px]">
                        {r.workflow_status || '—'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={(e) => {
                            e.stopPropagation();
                            navigate(`/documents/${r.id}`);
                          }}
                          data-testid={`search-open-detail-${r.id}`}
                        >
                          Detail
                        </Button>
                        {r.sharepoint_web_url && (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={(e) => {
                              e.stopPropagation();
                              window.open(r.sharepoint_web_url, '_blank', 'noopener');
                            }}
                            data-testid={`search-open-sharepoint-${r.id}`}
                            title="Open in SharePoint"
                          >
                            <ExternalLink className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
