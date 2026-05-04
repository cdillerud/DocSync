import { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Search as SearchIcon, ExternalLink, FileText, Loader2, X } from 'lucide-react';
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

const DOC_TYPE_OPTIONS = [
  { value: 'all', label: 'All types' },
  { value: 'AP_INVOICE', label: 'AP Invoice' },
  { value: 'SALES_INVOICE', label: 'Sales Invoice' },
  { value: 'PURCHASE_ORDER', label: 'Purchase Order' },
  { value: 'SALES_ORDER', label: 'Sales Order' },
  { value: 'RECEIPT', label: 'Receipt' },
  { value: 'SHIPMENT', label: 'Shipment / Packing Slip' },
  { value: 'CREDIT_MEMO', label: 'Credit Memo' },
  { value: 'OTHER', label: 'Other' },
];

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
  const [vendor, setVendor] = useState(searchParams.get('vendor') || '');
  const [customer, setCustomer] = useState(searchParams.get('customer') || '');
  const [dateFrom, setDateFrom] = useState(searchParams.get('from') || '');
  const [dateTo, setDateTo] = useState(searchParams.get('to') || '');
  const [bcNo, setBcNo] = useState(searchParams.get('bc_no') || '');

  const [results, setResults] = useState([]);
  const [searchMethod, setSearchMethod] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [touched, setTouched] = useState(false);

  const filtersActive = (docType !== 'all') || vendor || customer || dateFrom || dateTo || bcNo;

  const runSearch = useCallback(async () => {
    setError('');
    if (!query.trim() && !filtersActive) {
      setResults([]);
      setTouched(true);
      return;
    }
    setLoading(true);
    try {
      // Update URL state for shareable deep links
      const params = {};
      if (query.trim()) params.q = query.trim();
      if (docType !== 'all') params.doc_type = docType;
      if (vendor) params.vendor = vendor;
      if (customer) params.customer = customer;
      if (dateFrom) params.from = dateFrom;
      if (dateTo) params.to = dateTo;
      if (bcNo) params.bc_no = bcNo;
      setSearchParams(params, { replace: true });

      // Backend search endpoint requires q (min_length 1). If only filters, derive a permissive q.
      const effectiveQ = (query.trim() || vendor || customer || bcNo || '*').toString();
      const url = `${API}/api/documents/search?q=${encodeURIComponent(effectiveQ)}&limit=100`;
      const res = await fetch(url);
      if (!res.ok) throw new Error(`Search failed (${res.status})`);
      const data = await res.json();
      let rows = data.results || [];

      // Client-side filter overlay (the backend search endpoint is broad-text;
      // these filters narrow without requiring a backend change).
      if (docType !== 'all') {
        rows = rows.filter((r) => (r.document_type || '').toUpperCase().includes(docType));
      }
      if (vendor.trim()) {
        const v = vendor.trim().toLowerCase();
        rows = rows.filter((r) => (r.vendor_canonical || '').toLowerCase().includes(v));
      }
      if (customer.trim()) {
        const c = customer.trim().toLowerCase();
        rows = rows.filter((r) =>
          (r.match_fields || []).some((f) => f.includes('customer')) ||
          (r.file_name || '').toLowerCase().includes(c)
        );
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
      if (bcNo.trim()) {
        const b = bcNo.trim().toLowerCase();
        rows = rows.filter((r) => {
          const inMatch = (r.match_fields || []).some((f) => f.includes('bc_document_no'));
          const inFile = (r.file_name || '').toLowerCase().includes(b);
          return inMatch || inFile;
        });
      }

      setResults(rows);
      setSearchMethod(data.search_method || '');
      setTouched(true);
    } catch (e) {
      setError(e.message || 'Search failed');
      setResults([]);
    } finally {
      setLoading(false);
    }
  }, [query, docType, vendor, customer, dateFrom, dateTo, bcNo, filtersActive, setSearchParams]);

  // Auto-run when arriving with URL params populated
  useEffect(() => {
    const hasUrlParams = searchParams.get('q') || searchParams.get('vendor') ||
      searchParams.get('customer') || searchParams.get('bc_no') ||
      searchParams.get('from') || searchParams.get('to') ||
      (searchParams.get('doc_type') && searchParams.get('doc_type') !== 'all');
    if (hasUrlParams && !touched) {
      runSearch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clearFilters = () => {
    setQuery('');
    setDocType('all');
    setVendor('');
    setCustomer('');
    setDateFrom('');
    setDateTo('');
    setBcNo('');
    setResults([]);
    setSearchMethod('');
    setTouched(false);
    setSearchParams({}, { replace: true });
  };

  const onKeyDown = (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      runSearch();
    }
  };

  return (
    <div data-testid="search-page" className="space-y-4 max-w-7xl mx-auto px-4 py-6">
      <div className="flex items-center gap-2">
        <SearchIcon className="w-6 h-6 text-primary" />
        <h1 className="text-2xl font-semibold">Document Search</h1>
        <Badge variant="secondary" className="ml-2 text-[10px]">Square9 retrieval replacement</Badge>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filters</CardTitle>
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
            <div className="md:col-span-3">
              <Select value={docType} onValueChange={setDocType}>
                <SelectTrigger data-testid="search-doc-type-filter">
                  <SelectValue placeholder="Document type" />
                </SelectTrigger>
                <SelectContent>
                  {DOC_TYPE_OPTIONS.map((o) => (
                    <SelectItem key={o.value} value={o.value} data-testid={`search-doc-type-${o.value}`}>
                      {o.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="md:col-span-3 flex gap-2">
              <Button onClick={runSearch} disabled={loading} className="flex-1" data-testid="search-submit-btn">
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <SearchIcon className="w-4 h-4 mr-1" />}
                Search
              </Button>
              <Button onClick={clearFilters} variant="outline" data-testid="search-clear-btn">
                <X className="w-4 h-4" />
              </Button>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-12 gap-2 pt-1">
            <div className="md:col-span-3">
              <Input
                placeholder="Vendor name"
                value={vendor}
                onChange={(e) => setVendor(e.target.value)}
                onKeyDown={onKeyDown}
                data-testid="search-vendor-filter"
              />
            </div>
            <div className="md:col-span-3">
              <Input
                placeholder="Customer name"
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
              <span className="ml-2 text-sm font-normal text-muted-foreground">
                ({results.length}{searchMethod && ` · ${searchMethod}`})
              </span>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {loading && (
            <div className="flex items-center justify-center py-10 text-sm text-muted-foreground" data-testid="search-loading">
              <Loader2 className="w-4 h-4 animate-spin mr-2" /> Searching...
            </div>
          )}
          {!loading && touched && results.length === 0 && (
            <div className="py-10 text-center text-sm text-muted-foreground" data-testid="search-empty">
              No documents match these filters.
            </div>
          )}
          {!loading && !touched && (
            <div className="py-10 text-center text-sm text-muted-foreground" data-testid="search-initial">
              Enter a query above and press Search. Try a vendor name, invoice number, PO, customer, BC document number, or amount.
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
                    key={r.doc_id}
                    className="cursor-pointer hover:bg-muted/40"
                    data-testid={`search-result-row-${r.doc_id}`}
                    onClick={() => navigate(`/documents/${r.doc_id}`)}
                  >
                    <TableCell className="max-w-[260px]">
                      <div className="flex items-start gap-2">
                        <FileText className="w-4 h-4 mt-0.5 text-muted-foreground shrink-0" />
                        <div className="min-w-0">
                          <div className="font-medium truncate" title={r.file_name}>
                            {r.file_name || '(unnamed)'}
                          </div>
                          <MatchPills fields={r.match_fields} />
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-xs">
                        {r.document_type || '—'}
                      </Badge>
                    </TableCell>
                    <TableCell className="max-w-[180px] truncate">
                      {r.vendor_canonical || '—'}
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
                            navigate(`/documents/${r.doc_id}`);
                          }}
                          data-testid={`search-open-detail-${r.doc_id}`}
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
                            data-testid={`search-open-sharepoint-${r.doc_id}`}
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
