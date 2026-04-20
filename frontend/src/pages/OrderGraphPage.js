/**
 * Order Graph — v2.5.18 Phase 2
 * ─────────────────────────────────────────────────────
 * Timeline visualization of every doc related by PO (or SO).
 *
 * Swimlanes by role (Shipping / AP_Invoice / AR_Invoice / Compliance /
 * Other); x-axis is `created_utc`. Doc chips are colored by vendor
 * (deterministic hash → hue) so mis-linked cross-vendor docs pop out
 * visually.
 *
 * Entry points:
 *   • Standalone page — search PO# or SO# at the top.
 *   • Deep-link: `/order-graph?po=112753` (added to DocumentDetailPage
 *     as a "Show related docs" action).
 */
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams, Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '../components/ui/tooltip';
import {
  Network, Search, Loader2, FileText, AlertTriangle, CheckCircle2,
  Truck, Receipt, Package, Shield, HelpCircle, Flame, BarChart3,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

// Visual grammar: swimlane order + icon per role
const ROLES_ORDER = ['PO', 'SO', 'Shipping', 'AP_Invoice', 'AR_Invoice', 'Compliance', 'Other', 'Unknown'];
const ROLE_ICONS = {
  PO: FileText, SO: FileText,
  Shipping: Truck, AP_Invoice: Receipt, AR_Invoice: Receipt,
  Compliance: Shield, Other: Package, Unknown: HelpCircle,
};
const ROLE_LANE_COLORS = {
  PO: 'border-blue-500/40 bg-blue-500/5',
  SO: 'border-cyan-500/40 bg-cyan-500/5',
  Shipping: 'border-amber-500/40 bg-amber-500/5',
  AP_Invoice: 'border-emerald-500/40 bg-emerald-500/5',
  AR_Invoice: 'border-violet-500/40 bg-violet-500/5',
  Compliance: 'border-rose-500/40 bg-rose-500/5',
  Other: 'border-slate-500/30 bg-slate-500/5',
  Unknown: 'border-slate-400/30 bg-slate-400/5',
};

// Deterministic vendor → hue mapping so the SAME vendor gets the SAME
// chip color across reloads without a central palette.
function vendorColor(vendor) {
  if (!vendor) return { bg: 'hsl(210 10% 85%)', fg: 'hsl(210 10% 25%)' };
  let hash = 0;
  for (let i = 0; i < vendor.length; i++) hash = (hash * 31 + vendor.charCodeAt(i)) & 0xffffffff;
  const hue = Math.abs(hash) % 360;
  return {
    bg: `hsl(${hue} 70% 90%)`,
    fg: `hsl(${hue} 60% 25%)`,
    ring: `hsl(${hue} 60% 55%)`,
  };
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: '2-digit' });
}

function fmtTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function DocChip({ node }) {
  const Icon = ROLE_ICONS[node.role] || FileText;
  const vc = vendorColor(node.vendor);
  const hasFuzzy = (node.edges || []).some(e => e.match_type === 'fuzzy');
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <Link
            to={`/documents/${encodeURIComponent(node.id)}`}
            className="block transition-transform hover:scale-[1.02] hover:-translate-y-0.5"
            data-testid={`doc-chip-${node.id}`}
          >
            <div
              className="rounded-lg border-2 px-3 py-2 min-w-[200px] max-w-[260px] shadow-sm"
              style={{
                backgroundColor: vc.bg,
                color: vc.fg,
                borderColor: vc.ring,
              }}
            >
              <div className="flex items-center gap-1.5 mb-1">
                <Icon className="w-3.5 h-3.5 shrink-0" />
                <span className="text-[10px] uppercase tracking-wider font-bold opacity-80">
                  {node.doc_type || 'Unknown'}
                </span>
                {hasFuzzy && (
                  <Flame className="w-3 h-3 ml-auto opacity-60" aria-label="fuzzy match" />
                )}
                {node.is_duplicate && (
                  <Badge variant="outline" className="text-[9px] h-4 px-1 ml-auto">DUP</Badge>
                )}
              </div>
              <div className="text-xs font-semibold leading-tight truncate" title={node.file_name}>
                {node.file_name || '(unnamed)'}
              </div>
              <div className="text-[10px] opacity-75 mt-0.5 truncate" title={node.vendor}>
                {node.vendor || '—'}
              </div>
              <div className="text-[10px] opacity-60 mt-0.5 font-mono">
                {fmtDate(node.created_utc)}
              </div>
            </div>
          </Link>
        </TooltipTrigger>
        <TooltipContent side="bottom" className="max-w-sm">
          <div className="space-y-1 text-xs">
            <div><strong>{node.doc_type}</strong> · {node.role}</div>
            <div>Created: {fmtTime(node.created_utc)}</div>
            <div>Status: {node.status || '—'}</div>
            {node.workflow_status && <div>Workflow: {node.workflow_status}</div>}
            {node.edges?.length > 0 && (
              <div className="pt-1 border-t border-border/50">
                <div className="font-semibold text-[10px] uppercase opacity-60 mb-0.5">Linked via</div>
                {node.edges.slice(0, 4).map((e, i) => (
                  <div key={i} className="text-[10px]">
                    <span className={e.match_type === 'fuzzy' ? 'text-amber-500' : ''}>
                      {e.match_type === 'fuzzy' ? '~ ' : '✓ '}
                    </span>
                    <code>{e.matched_field}</code> → {e.matched_value || e.ref_value}
                  </div>
                ))}
              </div>
            )}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function Swimlane({ role, nodes }) {
  const Icon = ROLE_ICONS[role] || FileText;
  return (
    <div
      className={`border-l-4 rounded-r-md px-4 py-3 ${ROLE_LANE_COLORS[role]}`}
      data-testid={`swimlane-${role}`}
    >
      <div className="flex items-center gap-2 mb-2 text-sm font-bold uppercase tracking-widest opacity-70">
        <Icon className="w-4 h-4" />
        <span>{role}</span>
        <Badge variant="secondary" className="ml-auto text-[10px] font-mono">{nodes.length}</Badge>
      </div>
      <div className="flex flex-wrap gap-2">
        {nodes.map(n => <DocChip key={n.id} node={n} />)}
      </div>
    </div>
  );
}

function StatRow({ label, value, tone = 'default' }) {
  const toneClass = {
    default: 'text-foreground',
    good: 'text-emerald-600',
    warn: 'text-amber-600',
    bad: 'text-red-600',
  }[tone];
  return (
    <div className="flex items-center justify-between py-1.5 border-b border-border/40 last:border-0">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className={`text-sm font-mono font-semibold ${toneClass}`}>{value}</span>
    </div>
  );
}

export default function OrderGraphPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const initialPo = searchParams.get('po') || '';
  const initialSo = searchParams.get('so') || '';
  const [poInput, setPoInput] = useState(initialPo);
  const [soInput, setSoInput] = useState(initialSo);
  const [loading, setLoading] = useState(false);
  const [graph, setGraph] = useState(null);
  const [error, setError] = useState(null);

  const runBuild = useCallback(async (po, so) => {
    if (!po && !so) { setGraph(null); return; }
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (po) params.set('po_number', po);
      if (so) params.set('so_number', so);
      params.set('include_fuzzy', 'true');
      const res = await fetch(`${API}/api/admin/sales-order-graph/build?${params}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      if (data.error) throw new Error(data.error);
      setGraph(data);
    } catch (e) {
      setError(e.message || 'Failed to build graph');
      setGraph(null);
    } finally {
      setLoading(false);
    }
  }, []);

  // Auto-run on mount if params were deep-linked
  useEffect(() => {
    if (initialPo || initialSo) runBuild(initialPo, initialSo);
  }, [initialPo, initialSo, runBuild]);

  const handleSearch = (e) => {
    e.preventDefault();
    const po = poInput.trim();
    const so = soInput.trim();
    const next = {};
    if (po) next.po = po;
    if (so) next.so = so;
    setSearchParams(next);
    runBuild(po, so);
  };

  // Group nodes by role for the swimlane layout
  const lanes = {};
  (graph?.nodes || []).forEach(n => {
    const r = n.role || 'Unknown';
    if (!lanes[r]) lanes[r] = [];
    lanes[r].push(n);
  });
  const activeRoles = ROLES_ORDER.filter(r => lanes[r]?.length > 0);
  const uniqueVendors = Array.from(
    new Set((graph?.nodes || []).map(n => n.vendor).filter(Boolean))
  );

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-6" data-testid="order-graph-page">
      {/* Header + search */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-3">
            <Network className="w-5 h-5 text-primary" />
            <CardTitle>Order Graph</CardTitle>
            <Badge variant="outline" className="ml-2 text-[10px]">Phase 2 · PO-centric</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSearch} className="flex flex-wrap items-end gap-3" data-testid="order-graph-search">
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-muted-foreground mb-1 block">PO Number</label>
              <Input
                value={poInput}
                onChange={(e) => setPoInput(e.target.value)}
                placeholder="e.g. PO019363, 112753, P0024333"
                data-testid="po-input"
              />
            </div>
            <div className="flex-1 min-w-[200px]">
              <label className="text-xs text-muted-foreground mb-1 block">SO Number <span className="opacity-50">(rare in PO-centric schema)</span></label>
              <Input
                value={soInput}
                onChange={(e) => setSoInput(e.target.value)}
                placeholder="Sales Order #"
                data-testid="so-input"
              />
            </div>
            <Button type="submit" disabled={loading} data-testid="build-btn">
              {loading ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Search className="w-4 h-4 mr-2" />}
              Build Graph
            </Button>
          </form>
          {error && (
            <div className="mt-3 text-sm text-red-600 flex items-center gap-2" data-testid="error-banner">
              <AlertTriangle className="w-4 h-4" />{error}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Results */}
      {graph && (
        <div className="grid grid-cols-1 lg:grid-cols-[1fr_280px] gap-6">
          {/* Timeline swimlanes */}
          <div className="space-y-3">
            {graph.nodes_total === 0 ? (
              <Card>
                <CardContent className="py-12 text-center text-muted-foreground">
                  <Network className="w-12 h-12 mx-auto opacity-40 mb-3" />
                  <div className="text-sm">No related documents found for this reference.</div>
                  <div className="text-xs mt-1 opacity-70">Try variants — the extracted value may be stored differently (e.g. without the PO prefix).</div>
                </CardContent>
              </Card>
            ) : (
              activeRoles.map(role => (
                <Swimlane key={role} role={role} nodes={lanes[role]} />
              ))
            )}
          </div>

          {/* Summary sidebar */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm flex items-center gap-2">
                  <BarChart3 className="w-4 h-4" /> Summary
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <StatRow label="Seed PO" value={graph.seed?.po_number || '—'} />
                <StatRow label="Seed SO" value={graph.seed?.so_number || '—'} />
                <StatRow label="Docs found" value={graph.nodes_total}
                  tone={graph.nodes_total > 0 ? 'good' : 'warn'} />
                <StatRow label="Edges total" value={graph.edges_total} />
                <StatRow label="Vendors" value={uniqueVendors.length} />
              </CardContent>
            </Card>

            {Object.keys(graph.role_counts || {}).length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Role Breakdown</CardTitle>
                </CardHeader>
                <CardContent>
                  {Object.entries(graph.role_counts).map(([role, n]) => {
                    const Icon = ROLE_ICONS[role] || FileText;
                    return (
                      <div key={role} className="flex items-center gap-2 text-xs py-1" data-testid={`role-count-${role}`}>
                        <Icon className="w-3.5 h-3.5 opacity-60" />
                        <span>{role}</span>
                        <Badge variant="secondary" className="ml-auto font-mono text-[10px]">{n}</Badge>
                      </div>
                    );
                  })}
                </CardContent>
              </Card>
            )}

            {graph.edge_counts_by_type && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Match Quality</CardTitle>
                </CardHeader>
                <CardContent className="text-xs space-y-1">
                  {Object.entries(graph.edge_counts_by_type).map(([t, n]) => (
                    <div key={t} className="flex items-center gap-2" data-testid={`edge-count-${t}`}>
                      {t === 'exact'
                        ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                        : <Flame className="w-3.5 h-3.5 text-amber-500" />}
                      <span>{t}</span>
                      <Badge variant="secondary" className="ml-auto font-mono text-[10px]">{n}</Badge>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}

            {uniqueVendors.length > 1 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-sm">Vendors</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-wrap gap-1.5">
                    {uniqueVendors.map(v => {
                      const vc = vendorColor(v);
                      return (
                        <Badge
                          key={v}
                          variant="outline"
                          className="text-[10px]"
                          style={{
                            backgroundColor: vc.bg, color: vc.fg, borderColor: vc.ring,
                          }}
                          data-testid={`vendor-legend-${v}`}
                        >{v}</Badge>
                      );
                    })}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}

      {/* First-run hint */}
      {!graph && !loading && !error && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            <Network className="w-12 h-12 mx-auto opacity-40 mb-3" />
            <div className="text-sm font-medium">Search a PO or SO to see related docs.</div>
            <div className="text-xs mt-2 opacity-70">Try <code className="text-primary">112753</code> or <code className="text-primary">PO019363</code> on prod.</div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
