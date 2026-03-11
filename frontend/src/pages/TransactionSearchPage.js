import { useState, useCallback, useRef, useEffect } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Slider } from '@/components/ui/slider';
import {
  Search, ArrowRight, GitBranch, FileText, Link2, ExternalLink, ChevronDown, ChevronRight,
  Filter, X, Package, Truck, FileSpreadsheet, Receipt, Globe, Database,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const NODE_ICONS = {
  document: FileText,
  purchase_order: Package,
  sales_order: Receipt,
  invoice: FileSpreadsheet,
  bill_of_lading: Truck,
  shipment: Truck,
  customs_entry: Globe,
  bc_record: Database,
};

const NODE_COLORS = {
  document:       { bg: 'bg-blue-500/15',    text: 'text-blue-400',    border: 'border-blue-500/30' },
  purchase_order: { bg: 'bg-emerald-500/15',  text: 'text-emerald-400',  border: 'border-emerald-500/30' },
  sales_order:    { bg: 'bg-purple-500/15',   text: 'text-purple-400',   border: 'border-purple-500/30' },
  invoice:        { bg: 'bg-amber-500/15',    text: 'text-amber-400',    border: 'border-amber-500/30' },
  bill_of_lading: { bg: 'bg-cyan-500/15',     text: 'text-cyan-400',     border: 'border-cyan-500/30' },
  shipment:       { bg: 'bg-teal-500/15',     text: 'text-teal-400',     border: 'border-teal-500/30' },
  customs_entry:  { bg: 'bg-orange-500/15',   text: 'text-orange-400',   border: 'border-orange-500/30' },
  bc_record:      { bg: 'bg-indigo-500/15',   text: 'text-indigo-400',   border: 'border-indigo-500/30' },
};

const TIER_STYLES = {
  exact:      { label: 'Exact',      cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-600' },
  normalized: { label: 'Normalized', cls: 'bg-blue-500/20 text-blue-400 border-blue-600' },
  likely:     { label: 'Likely',     cls: 'bg-amber-500/20 text-amber-400 border-amber-600' },
  fuzzy:      { label: 'Fuzzy',      cls: 'bg-red-500/20 text-red-400 border-red-600' },
};

const PROV_LABELS = {
  linked_by_extraction: 'extraction',
  linked_by_resolver: 'resolver',
  linked_by_processor: 'processor',
  linked_by_shared_reference: 'shared ref',
  linked_by_bc_linkage: 'BC linkage',
  manual: 'manual',
};

const NODE_TYPES = [
  { value: 'all', label: 'All Types' },
  { value: 'purchase_order', label: 'Purchase Order' },
  { value: 'sales_order', label: 'Sales Order' },
  { value: 'invoice', label: 'Invoice' },
  { value: 'bill_of_lading', label: 'Bill of Lading' },
  { value: 'shipment', label: 'Shipment' },
  { value: 'customs_entry', label: 'Customs Entry' },
  { value: 'bc_record', label: 'BC Record' },
  { value: 'document', label: 'Document' },
];

function ConfidenceBar({ value, size = 'sm' }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  const h = size === 'sm' ? 'h-1.5' : 'h-2';
  return (
    <div className="flex items-center gap-2">
      <div className={`flex-1 ${h} bg-muted rounded-full overflow-hidden min-w-[60px]`}>
        <div className={`h-full rounded-full ${color} transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground w-8 text-right">{pct}%</span>
    </div>
  );
}

function NodeTypeBadge({ type }) {
  const c = NODE_COLORS[type] || NODE_COLORS.document;
  const Icon = NODE_ICONS[type] || FileText;
  return (
    <Badge className={`text-[10px] font-semibold border ${c.bg} ${c.text} ${c.border} gap-1`}>
      <Icon className="w-2.5 h-2.5" />
      {type.replace(/_/g, ' ')}
    </Badge>
  );
}

function TierBadge({ tier }) {
  const s = TIER_STYLES[tier] || TIER_STYLES.fuzzy;
  return <Badge className={`text-[9px] font-semibold border ${s.cls}`}>{s.label}</Badge>;
}

// ─── Chain Step ─────────────────────────────────────────────────
function ChainStep({ step, isLast, onOpenDocument }) {
  const c = NODE_COLORS[step.node_type] || NODE_COLORS.document;
  const Icon = NODE_ICONS[step.node_type] || FileText;
  const isDoc = step.node_type === 'document';

  return (
    <div className="relative" data-testid={`chain-step-${step.node_id}`}>
      {/* Connector line */}
      {!isLast && (
        <div className="absolute left-[15px] top-[32px] bottom-0 w-px bg-border" />
      )}
      <div className={`flex items-start gap-3 p-3 rounded-lg border transition-colors ${c.border} ${c.bg} hover:border-primary/40`}>
        {/* Icon */}
        <div className={`mt-0.5 p-1.5 rounded ${c.bg} ${c.text}`}>
          <Icon className="w-4 h-4" />
        </div>

        {/* Content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-semibold truncate">{step.reference_value}</span>
            <NodeTypeBadge type={step.node_type} />
            {step.depth > 0 && <span className="text-[10px] text-muted-foreground">depth {step.depth}</span>}
          </div>
          {step.vendor_name && <p className="text-xs text-muted-foreground mt-0.5">{step.vendor_name}</p>}
          {step.bc_document_no && (
            <p className="text-xs text-muted-foreground mt-0.5">BC: {step.bc_document_no} ({step.bc_entity_type})</p>
          )}
          {isDoc && step.metadata?.file_name && (
            <p className="text-xs text-muted-foreground mt-0.5">{step.metadata.file_name}</p>
          )}

          {/* Edges */}
          {step.edges?.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {step.edges.map(e => (
                <div key={e.edge_id} className="flex items-center gap-1 text-[10px] text-muted-foreground bg-muted/40 px-1.5 py-0.5 rounded">
                  <span className={e.direction === 'outgoing' ? 'text-blue-400' : 'text-emerald-400'}>
                    {e.direction === 'outgoing' ? '\u2192' : '\u2190'}
                  </span>
                  <span>{PROV_LABELS[e.provenance] || e.provenance}</span>
                  <span className="font-mono">({Math.round(e.confidence * 100)}%)</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Action */}
        {isDoc && (
          <Button
            variant="ghost"
            size="sm"
            className="shrink-0"
            onClick={() => onOpenDocument(step.reference_value)}
            data-testid={`open-doc-${step.reference_value}`}
          >
            <ExternalLink className="w-3 h-3 mr-1" />Open
          </Button>
        )}
      </div>
    </div>
  );
}

// ─── Chain Panel ────────────────────────────────────────────────
function ChainPanel({ nodeId, onOpenDocument }) {
  const [chain, setChain] = useState(null);
  const [loading, setLoading] = useState(false);
  const [maxDepth, setMaxDepth] = useState(3);

  const loadChain = useCallback(async () => {
    if (!nodeId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/transaction-search/node/${nodeId}/chain?max_depth=${maxDepth}`);
      if (!res.ok) throw new Error(await res.text());
      setChain(await res.json());
    } catch (e) {
      toast.error(`Chain load failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [nodeId, maxDepth]);

  // Auto-load on nodeId change
  useEffect(() => { if (nodeId) loadChain(); }, [nodeId, loadChain]);

  if (!nodeId) return <p className="text-sm text-muted-foreground py-8 text-center">Select a search result to view its transaction chain</p>;
  if (loading) return <p className="text-sm text-muted-foreground py-8 text-center">Loading chain...</p>;
  if (!chain) return (
    <div className="text-center py-8">
      <Button onClick={loadChain} data-testid="load-chain-btn">
        <GitBranch className="w-4 h-4 mr-2" />Load Transaction Chain
      </Button>
    </div>
  );

  return (
    <div className="space-y-3" data-testid="chain-panel">
      {/* Chain header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <GitBranch className="w-3 h-3" />
          <span data-testid="chain-node-count">{chain.total_nodes} nodes</span>
          <span>\u00b7</span>
          <span data-testid="chain-edge-count">{chain.total_edges} edges</span>
          {chain.connected_documents?.length > 0 && (
            <>
              <span>\u00b7</span>
              <span data-testid="chain-doc-count">{chain.connected_documents.length} documents</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-[10px] text-muted-foreground">Depth: {maxDepth}</span>
          <div className="w-20">
            <Slider
              value={[maxDepth]}
              onValueChange={([v]) => setMaxDepth(v)}
              min={1}
              max={5}
              step={1}
              data-testid="depth-slider"
            />
          </div>
          <Button variant="outline" size="sm" onClick={loadChain} data-testid="refresh-chain-btn">Refresh</Button>
        </div>
      </div>

      {/* Chain steps */}
      <div className="space-y-2">
        {chain.chain_steps.map((step, i) => (
          <ChainStep
            key={step.node_id}
            step={step}
            isLast={i === chain.chain_steps.length - 1}
            onOpenDocument={onOpenDocument}
          />
        ))}
      </div>

      {/* Connected documents summary */}
      {chain.connected_documents?.length > 0 && (
        <Card className="border-dashed" data-testid="connected-docs-summary">
          <CardHeader className="pb-2 pt-3">
            <CardTitle className="text-xs font-semibold text-muted-foreground">Connected Documents ({chain.connected_documents.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1 pb-3">
            {chain.connected_documents.map(cd => (
              <div
                key={cd.doc_id}
                className="flex items-center gap-2 text-xs py-1.5 px-2 rounded hover:bg-muted/30 cursor-pointer transition-colors"
                onClick={() => onOpenDocument(cd.doc_id)}
                data-testid={`chain-doc-${cd.doc_id}`}
              >
                <Badge variant="outline" className="text-[9px] shrink-0">{cd.doc_type || 'DOC'}</Badge>
                <span className="truncate flex-1">{cd.file_name || cd.doc_id.slice(0, 16)}</span>
                {cd.vendor_name && <span className="text-muted-foreground truncate max-w-[120px]">{cd.vendor_name}</span>}
                <ArrowRight className="w-3 h-3 text-muted-foreground shrink-0" />
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// ─── Main Page ──────────────────────────────────────────────────
export default function TransactionSearchPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const inputRef = useRef(null);

  const [query, setQuery] = useState(searchParams.get('q') || '');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [selectedNodeId, setSelectedNodeId] = useState(null);

  // Filters
  const [showFilters, setShowFilters] = useState(false);
  const [nodeTypeFilter, setNodeTypeFilter] = useState('all');
  const [vendorFilter, setVendorFilter] = useState('');
  const [minConfidence, setMinConfidence] = useState(0);

  const doSearch = useCallback(async (q) => {
    if (!q || q.length < 1) return;
    setLoading(true);
    setSelectedNodeId(null);
    try {
      const params = new URLSearchParams({ q });
      if (nodeTypeFilter && nodeTypeFilter !== 'all') params.set('node_type', nodeTypeFilter);
      if (vendorFilter) params.set('vendor', vendorFilter);
      if (minConfidence > 0) params.set('min_confidence', (minConfidence / 100).toString());
      params.set('limit', '50');

      const res = await fetch(`${API}/api/transaction-search?${params}`);
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setResults(data);
      setSearchParams({ q }, { replace: true });
    } catch (e) {
      toast.error(`Search failed: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [nodeTypeFilter, vendorFilter, minConfidence, setSearchParams]);

  const handleSubmit = (e) => {
    e.preventDefault();
    doSearch(query);
  };

  const openDocument = (docId) => {
    navigate(`/documents/${docId}`);
  };

  // Auto-search from URL param on mount
  useEffect(() => {
    const q = searchParams.get('q');
    if (q) {
      setQuery(q);
      doSearch(q);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="space-y-5" data-testid="transaction-search-page">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight" data-testid="page-title">Transaction Search</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Search by any reference to retrieve the full connected transaction chain
        </p>
      </div>

      {/* Search bar */}
      <form onSubmit={handleSubmit} className="flex gap-2">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search by PO, invoice, BOL, shipment, customs entry, or any reference..."
            className="pl-9 h-11 text-base"
            data-testid="search-input"
          />
        </div>
        <Button type="submit" disabled={loading || !query} className="h-11 px-6" data-testid="search-btn">
          {loading ? 'Searching...' : 'Search'}
        </Button>
        <Button
          type="button"
          variant="outline"
          className="h-11"
          onClick={() => setShowFilters(!showFilters)}
          data-testid="toggle-filters-btn"
        >
          <Filter className="w-4 h-4" />
          {showFilters ? <X className="w-3 h-3 ml-1" /> : <ChevronDown className="w-3 h-3 ml-1" />}
        </Button>
      </form>

      {/* Filters */}
      {showFilters && (
        <Card data-testid="filters-panel">
          <CardContent className="pt-4 pb-3">
            <div className="flex flex-wrap gap-4 items-end">
              <div>
                <label className="text-[10px] text-muted-foreground mb-1 block">Node Type</label>
                <Select value={nodeTypeFilter} onValueChange={setNodeTypeFilter}>
                  <SelectTrigger className="w-[160px] h-8 text-xs" data-testid="filter-node-type">
                    <SelectValue placeholder="All Types" />
                  </SelectTrigger>
                  <SelectContent>
                    {NODE_TYPES.map(t => (
                      <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div>
                <label className="text-[10px] text-muted-foreground mb-1 block">Vendor</label>
                <Input
                  value={vendorFilter}
                  onChange={e => setVendorFilter(e.target.value)}
                  placeholder="Filter by vendor..."
                  className="w-[180px] h-8 text-xs"
                  data-testid="filter-vendor"
                />
              </div>
              <div className="w-[180px]">
                <label className="text-[10px] text-muted-foreground mb-1 block">Min Confidence: {minConfidence}%</label>
                <Slider
                  value={[minConfidence]}
                  onValueChange={([v]) => setMinConfidence(v)}
                  min={0}
                  max={100}
                  step={5}
                  data-testid="filter-confidence"
                />
              </div>
              <Button variant="ghost" size="sm" onClick={() => { setNodeTypeFilter('all'); setVendorFilter(''); setMinConfidence(0); }} data-testid="clear-filters-btn">
                Clear
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Results + Chain layout */}
      {results && (
        <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
          {/* Results list */}
          <div className="lg:col-span-2 space-y-2">
            <div className="flex items-center justify-between">
              <p className="text-xs text-muted-foreground" data-testid="result-count">
                {results.total_results} result{results.total_results !== 1 ? 's' : ''} for "<span className="font-mono">{results.query}</span>"
                {results.normalized !== results.query && (
                  <span className="ml-1">(normalized: <span className="font-mono">{results.normalized}</span>)</span>
                )}
              </p>
            </div>

            {results.total_results === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground">
                  <Search className="w-8 h-8 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">No results found</p>
                  <p className="text-xs mt-1">Try a different reference or adjust filters</p>
                </CardContent>
              </Card>
            ) : (
              <div className="space-y-1.5 max-h-[calc(100vh-280px)] overflow-y-auto pr-1">
                {results.results.map(r => {
                  const c = NODE_COLORS[r.node_type] || NODE_COLORS.document;
                  const Icon = NODE_ICONS[r.node_type] || FileText;
                  const isSelected = selectedNodeId === r.node_id;

                  return (
                    <div
                      key={r.node_id}
                      className={`relative p-3 rounded-lg border cursor-pointer transition-all ${
                        isSelected
                          ? `${c.border} ${c.bg} ring-1 ring-primary/40`
                          : 'border-border hover:border-primary/30 hover:bg-muted/20'
                      }`}
                      onClick={() => setSelectedNodeId(r.node_id)}
                      data-testid={`result-${r.node_id}`}
                    >
                      <div className="flex items-center gap-2">
                        <div className={`p-1 rounded ${c.bg} ${c.text}`}><Icon className="w-3.5 h-3.5" /></div>
                        <span className="font-mono text-sm font-semibold truncate flex-1">{r.reference_value}</span>
                        <TierBadge tier={r.match_tier} />
                      </div>
                      <div className="flex items-center gap-2 mt-1.5 text-[10px] text-muted-foreground">
                        <NodeTypeBadge type={r.node_type} />
                        {r.vendor_name && <span className="truncate">{r.vendor_name}</span>}
                        <span className="ml-auto flex items-center gap-1">
                          <Link2 className="w-2.5 h-2.5" />{r.connected_count}
                        </span>
                      </div>
                      {isSelected && <ChevronRight className="w-3 h-3 text-primary absolute right-3 top-1/2 -translate-y-1/2" />}
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Chain panel */}
          <div className="lg:col-span-3">
            <Card className="sticky top-4">
              <CardHeader className="pb-2">
                <CardTitle className="text-sm font-semibold flex items-center gap-2">
                  <GitBranch className="w-4 h-4" />Transaction Chain
                </CardTitle>
              </CardHeader>
              <CardContent className="max-h-[calc(100vh-280px)] overflow-y-auto">
                <ChainPanel nodeId={selectedNodeId} onOpenDocument={openDocument} />
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* Empty state */}
      {!results && !loading && (
        <Card>
          <CardContent className="py-16 text-center">
            <GitBranch className="w-12 h-12 mx-auto mb-4 text-muted-foreground/30" />
            <h3 className="text-lg font-semibold mb-2">Transaction-Aware Document Retrieval</h3>
            <p className="text-sm text-muted-foreground max-w-md mx-auto mb-6">
              Search by any business reference (PO, invoice, BOL, shipment, customs entry) to find the full chain of connected documents and Business Central records.
            </p>
            <div className="flex flex-wrap gap-2 justify-center">
              {['PO12345', '111428', 'SI-02-26-31449', 'SELGA4925700'].map(ex => (
                <Button
                  key={ex}
                  variant="outline"
                  size="sm"
                  className="font-mono text-xs"
                  onClick={() => { setQuery(ex); doSearch(ex); }}
                  data-testid={`example-${ex}`}
                >
                  {ex}
                </Button>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
