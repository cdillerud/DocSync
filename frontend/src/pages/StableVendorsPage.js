import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Textarea } from '@/components/ui/textarea';
import {
  ShieldCheck, ShieldAlert, Eye, Search, ArrowUpDown, X,
  ChevronUp, ChevronDown, UserCog, RefreshCw, Clock, AlertTriangle,
} from 'lucide-react';
import {
  getStableVendors, getStableVendorDetail, applyVendorOverride,
  clearVendorOverride, getVendorOverrideHistory, reevaluateAllVendors,
} from '../lib/api';

// ─── Status styling ───────────────────────────────────────────
const STATUS_STYLES = {
  stable:   { label: 'Stable',   cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-700' },
  watch:    { label: 'Watch',    cls: 'bg-amber-500/20 text-amber-400 border-amber-700' },
  unstable: { label: 'Unstable', cls: 'bg-gray-500/20 text-gray-400 border-gray-600' },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.unstable;
  return <Badge data-testid={`status-${status}`} className={`text-[10px] font-semibold border ${s.cls}`}>{s.label}</Badge>;
}

function Pct({ value }) {
  if (value == null) return <span className="text-muted-foreground">-</span>;
  return <span className="font-mono text-xs">{(value * 100).toFixed(0)}%</span>;
}

// ─── Detail Drawer ────────────────────────────────────────────
function VendorDetailDrawer({ vendor, onClose, onRefresh }) {
  const [history, setHistory] = useState([]);
  const [overrideStatus, setOverrideStatus] = useState('');
  const [overrideReason, setOverrideReason] = useState('');
  const [overrideNote, setOverrideNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (vendor?.vendor_no || vendor?.vendor_name) {
      const vId = vendor.vendor_no || vendor.vendor_name;
      getVendorOverrideHistory(vId)
        .then(r => setHistory(r.data || []))
        .catch(() => {});
    }
  }, [vendor]);

  if (!vendor) return null;

  const vId = vendor.vendor_no || vendor.vendor_name;

  const handleOverride = async () => {
    if (!overrideStatus) { toast.error('Select an override status'); return; }
    setSubmitting(true);
    try {
      await applyVendorOverride(vId, {
        status: overrideStatus, reason: overrideReason, note: overrideNote, actor: 'admin',
      });
      toast.success(`Override applied: ${overrideStatus}`);
      setOverrideStatus(''); setOverrideReason(''); setOverrideNote('');
      onRefresh();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Override failed');
    } finally { setSubmitting(false); }
  };

  const handleClearOverride = async () => {
    setSubmitting(true);
    try {
      await clearVendorOverride(vId, { reason: 'Manual clear', actor: 'admin' });
      toast.success('Override cleared');
      onRefresh();
    } catch (e) {
      toast.error('Failed to clear override');
    } finally { setSubmitting(false); }
  };

  const ri = vendor.routing_impact || {};
  const qs = vendor.quality_signals || {};

  return (
    <div className="fixed inset-0 z-50 flex justify-end" data-testid="vendor-detail-drawer">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <div className="relative w-full max-w-xl bg-background border-l border-border overflow-y-auto shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 z-10 bg-background border-b border-border px-5 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {vendor.vendor_name || vId}
            </h2>
            {vendor.vendor_no && vendor.vendor_name !== vendor.vendor_no && (
              <p className="text-xs text-muted-foreground mt-0.5">{vendor.vendor_no}</p>
            )}
          </div>
          <Button variant="ghost" size="icon" onClick={onClose} data-testid="close-drawer-btn">
            <X className="w-4 h-4" />
          </Button>
        </div>

        <div className="px-5 py-4 space-y-5">
          {/* Summary */}
          <section data-testid="vendor-summary">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Summary</h3>
            <div className="grid grid-cols-3 gap-3">
              <SummaryItem label="Effective Status">
                <StatusBadge status={vendor.effective_status} />
              </SummaryItem>
              <SummaryItem label="System Status">
                <StatusBadge status={vendor.system_status} />
              </SummaryItem>
              <SummaryItem label="Score">
                <span className="font-mono font-bold text-sm">{(vendor.stable_vendor_score || 0).toFixed(3)}</span>
              </SummaryItem>
              <SummaryItem label="Documents">
                <span className="font-mono text-sm">{vendor.invoice_count || 0}</span>
              </SummaryItem>
              <SummaryItem label="Stable Flag">
                {vendor.stable_vendor_flag
                  ? <ShieldCheck className="w-4 h-4 text-emerald-500" />
                  : <ShieldAlert className="w-4 h-4 text-muted-foreground" />}
              </SummaryItem>
              <SummaryItem label="Last Evaluated">
                <span className="text-[10px] text-muted-foreground">
                  {vendor.stable_vendor_last_evaluated
                    ? new Date(vendor.stable_vendor_last_evaluated).toLocaleDateString()
                    : 'Never'}
                </span>
              </SummaryItem>
            </div>
          </section>

          {/* Stability Reasons */}
          {vendor.stability_reasons?.length > 0 && (
            <section data-testid="stability-reasons">
              <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Stability Reasoning</h3>
              <div className="bg-muted/50 rounded-md p-3 space-y-0.5">
                {vendor.stability_reasons.map((r, i) => (
                  <p key={i} className="text-xs text-muted-foreground">{`\u2022 ${r}`}</p>
                ))}
              </div>
            </section>
          )}

          {/* Stability Checks */}
          {vendor.stability_checks?.length > 0 && (
            <section data-testid="stability-checks">
              <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Check Details</h3>
              <div className="space-y-1.5">
                {vendor.stability_checks.map((c, i) => (
                  <div key={i} className="flex items-center justify-between text-xs px-2 py-1 bg-muted/30 rounded">
                    <span className="text-muted-foreground">{c.check?.replace(/_/g, ' ')}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono">{typeof c.value === 'number' ? c.value.toFixed(3) : String(c.value)}</span>
                      {c.passed
                        ? <ShieldCheck className="w-3 h-3 text-emerald-500" />
                        : <AlertTriangle className="w-3 h-3 text-red-400" />}
                    </div>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* Routing Impact */}
          <section data-testid="routing-impact">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Routing Impact</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-muted/30 rounded p-2">
                <span className="text-muted-foreground">Auto-Ready Eligible</span>
                <p className="font-semibold mt-0.5">{ri.auto_ready_eligible ? 'Yes' : 'No'}</p>
              </div>
              <div className="bg-muted/30 rounded p-2">
                <span className="text-muted-foreground">Low-Priority Eligible</span>
                <p className="font-semibold mt-0.5">{ri.low_priority_eligible ? 'Yes' : 'No'}</p>
              </div>
            </div>
            {ri.blocked_by?.length > 0 && (
              <div className="mt-2 text-xs text-red-400 space-y-0.5">
                {ri.blocked_by.map((b, i) => <p key={i}>{`\u26D4 ${b}`}</p>)}
              </div>
            )}
          </section>

          {/* Quality Signals */}
          <section data-testid="quality-signals">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Quality Signals</h3>
            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-muted/30 rounded p-2">
                <span className="text-muted-foreground">Layout Families</span>
                <p className="font-mono font-semibold mt-0.5">{qs.layout_families_count ?? 0}</p>
              </div>
              <div className="bg-muted/30 rounded p-2">
                <span className="text-muted-foreground">Active Alerts</span>
                <p className="font-mono font-semibold mt-0.5">{qs.active_alerts ?? 0}</p>
              </div>
            </div>
            {qs.top_correction_patterns?.length > 0 && (
              <div className="mt-2">
                <p className="text-[10px] text-muted-foreground mb-1">Top Correction Patterns</p>
                {qs.top_correction_patterns.slice(0, 3).map(([key, val], i) => (
                  <p key={i} className="text-xs text-muted-foreground">{`\u2022 ${key}: ${val?.count || val}`}</p>
                ))}
              </div>
            )}
          </section>

          {/* Override Actions */}
          <section data-testid="override-actions">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Admin Actions</h3>
            {vendor.has_manual_override && (
              <div className="mb-3 p-2 bg-amber-500/10 border border-amber-700/40 rounded text-xs">
                <p className="text-amber-400 font-semibold">Active Override: {vendor.manual_override_status}</p>
                {vendor.manual_override_reason && <p className="text-muted-foreground mt-0.5">Reason: {vendor.manual_override_reason}</p>}
                {vendor.manual_override_by && <p className="text-muted-foreground">By: {vendor.manual_override_by} at {vendor.manual_override_at ? new Date(vendor.manual_override_at).toLocaleString() : '-'}</p>}
                <Button variant="outline" size="sm" className="mt-2" onClick={handleClearOverride}
                  disabled={submitting} data-testid="clear-override-btn">
                  Clear Override
                </Button>
              </div>
            )}
            <div className="space-y-2">
              <div className="flex gap-2">
                {[
                  { val: 'force_stable', label: 'Promote Stable', cls: 'border-emerald-700 text-emerald-400 hover:bg-emerald-900/30' },
                  { val: 'force_watch', label: 'Set Watch', cls: 'border-amber-700 text-amber-400 hover:bg-amber-900/30' },
                  { val: 'force_unstable', label: 'Demote', cls: 'border-red-700 text-red-400 hover:bg-red-900/30' },
                ].map(o => (
                  <Button key={o.val} variant="outline" size="sm"
                    className={`text-xs flex-1 ${overrideStatus === o.val ? 'ring-1 ring-offset-1 ring-offset-background' : ''} ${o.cls}`}
                    onClick={() => setOverrideStatus(overrideStatus === o.val ? '' : o.val)}
                    data-testid={`override-btn-${o.val}`}>
                    {o.label}
                  </Button>
                ))}
              </div>
              {overrideStatus && (
                <div className="space-y-2 pt-1">
                  <Input placeholder="Reason (required)" value={overrideReason}
                    onChange={e => setOverrideReason(e.target.value)} className="text-xs"
                    data-testid="override-reason-input" />
                  <Textarea placeholder="Note (optional)" value={overrideNote}
                    onChange={e => setOverrideNote(e.target.value)} className="text-xs min-h-[60px]"
                    data-testid="override-note-input" />
                  <Button size="sm" onClick={handleOverride} disabled={submitting || !overrideReason}
                    className="w-full" data-testid="apply-override-btn">
                    {submitting ? 'Applying...' : `Apply ${overrideStatus.replace('force_', '').replace('_', ' ')}`}
                  </Button>
                </div>
              )}
            </div>
          </section>

          {/* Override History */}
          {history.length > 0 && (
            <section data-testid="override-history">
              <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Override History</h3>
              <div className="space-y-2">
                {history.map((h, i) => (
                  <div key={i} className="bg-muted/30 rounded p-2 text-xs space-y-0.5">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold">{h.action?.replace(/_/g, ' ')}</span>
                      <span className="text-[10px] text-muted-foreground">
                        {h.timestamp ? new Date(h.timestamp).toLocaleString() : ''}
                      </span>
                    </div>
                    <p className="text-muted-foreground">{h.old_status} → {h.new_status}</p>
                    {h.reason && <p className="text-muted-foreground">Reason: {h.reason}</p>}
                    {h.actor && <p className="text-muted-foreground">By: {h.actor}</p>}
                  </div>
                ))}
              </div>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryItem({ label, children }) {
  return (
    <div className="text-center">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">{label}</p>
      <div>{children}</div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────
export default function StableVendorsPage() {
  const [vendors, setVendors] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [sortBy, setSortBy] = useState('stable_vendor_score');
  const [sortDir, setSortDir] = useState(-1);
  const [selectedVendor, setSelectedVendor] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [reevalLoading, setReevalLoading] = useState(false);

  const fetchVendors = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getStableVendors({ search, status: statusFilter, sort_by: sortBy, sort_dir: sortDir });
      setVendors(res.data.vendors || []);
      setTotal(res.data.total || 0);
    } catch {
      toast.error('Failed to load vendors');
    } finally { setLoading(false); }
  }, [search, statusFilter, sortBy, sortDir]);

  useEffect(() => { fetchVendors(); }, [fetchVendors]);

  const openDetail = async (v) => {
    setSelectedVendor(v);
    try {
      const vId = v.vendor_no || v.vendor_name;
      const res = await getStableVendorDetail(vId);
      setDetailData(res.data);
    } catch {
      toast.error('Failed to load vendor detail');
    }
  };

  const refreshDetail = async () => {
    fetchVendors();
    if (selectedVendor) {
      try {
        const vId = selectedVendor.vendor_no || selectedVendor.vendor_name;
        const res = await getStableVendorDetail(vId);
        setDetailData(res.data);
      } catch {}
    }
  };

  const handleSort = (col) => {
    if (sortBy === col) setSortDir(d => d * -1);
    else { setSortBy(col); setSortDir(-1); }
  };

  const handleReevaluate = async () => {
    setReevalLoading(true);
    try {
      await reevaluateAllVendors();
      toast.success('Vendor reevaluation started');
      setTimeout(() => fetchVendors(), 3000);
    } catch {
      toast.error('Reevaluation failed');
    } finally { setReevalLoading(false); }
  };

  const SortIcon = ({ col }) => {
    if (sortBy !== col) return <ArrowUpDown className="w-3 h-3 text-muted-foreground/40" />;
    return sortDir === -1 ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />;
  };

  const filters = [
    { val: '', label: 'All' },
    { val: 'stable', label: 'Stable' },
    { val: 'watch', label: 'Watch' },
    { val: 'unstable', label: 'Unstable' },
    { val: 'overridden', label: 'Overridden' },
  ];

  return (
    <div className="space-y-6" data-testid="stable-vendors-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Stable Vendor Admin
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {total} vendors &middot; Oversight and manual controls for stable vendor routing
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleReevaluate} disabled={reevalLoading}
          data-testid="reevaluate-all-btn">
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${reevalLoading ? 'animate-spin' : ''}`} />
          {reevalLoading ? 'Evaluating...' : 'Reevaluate All'}
        </Button>
      </div>

      {/* Filters */}
      <Card className="border border-border">
        <CardContent className="py-3 px-4">
          <div className="flex items-center gap-3 flex-wrap">
            <div className="relative flex-1 min-w-[200px] max-w-sm">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
              <Input placeholder="Search vendor name or no..." value={search}
                onChange={e => setSearch(e.target.value)} className="pl-8 text-xs h-8"
                data-testid="vendor-search-input" />
            </div>
            <div className="flex gap-1">
              {filters.map(f => (
                <Button key={f.val} variant={statusFilter === f.val ? 'default' : 'ghost'}
                  size="sm" className="text-xs h-7 px-2.5"
                  onClick={() => setStatusFilter(f.val)}
                  data-testid={`filter-${f.val || 'all'}`}>
                  {f.label}
                </Button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card className="border border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-[220px]">Vendor</TableHead>
                <TableHead className="w-[100px]">Status</TableHead>
                <TableHead className="w-[90px] cursor-pointer" onClick={() => handleSort('stable_vendor_score')}>
                  <span className="flex items-center gap-1">Score <SortIcon col="stable_vendor_score" /></span>
                </TableHead>
                <TableHead className="w-[90px] cursor-pointer" onClick={() => handleSort('automation_success_rate')}>
                  <span className="flex items-center gap-1">Auto Rate <SortIcon col="automation_success_rate" /></span>
                </TableHead>
                <TableHead className="w-[90px] cursor-pointer" onClick={() => handleSort('reference_resolution_success_rate')}>
                  <span className="flex items-center gap-1">Resolution <SortIcon col="reference_resolution_success_rate" /></span>
                </TableHead>
                <TableHead className="w-[90px] cursor-pointer" onClick={() => handleSort('correction_rate')}>
                  <span className="flex items-center gap-1">Corrections <SortIcon col="correction_rate" /></span>
                </TableHead>
                <TableHead className="w-[70px]">Docs</TableHead>
                <TableHead className="w-[90px]">Override</TableHead>
                <TableHead className="w-[50px]" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground">Loading...</TableCell></TableRow>
              ) : vendors.length === 0 ? (
                <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground">No vendors found</TableCell></TableRow>
              ) : vendors.map(v => {
                const vId = v.vendor_no || v.vendor_name;
                return (
                  <TableRow key={vId} className="cursor-pointer hover:bg-muted/40" onClick={() => openDetail(v)}
                    data-testid={`vendor-row-${vId}`}>
                    <TableCell>
                      <p className="text-sm font-medium truncate max-w-[200px]">{v.vendor_name || vId}</p>
                      {v.vendor_no && v.vendor_name !== v.vendor_no && (
                        <p className="text-[10px] text-muted-foreground">{v.vendor_no}</p>
                      )}
                    </TableCell>
                    <TableCell><StatusBadge status={v.effective_status} /></TableCell>
                    <TableCell><span className="font-mono text-xs">{(v.stable_vendor_score || 0).toFixed(3)}</span></TableCell>
                    <TableCell><Pct value={v.automation_success_rate} /></TableCell>
                    <TableCell><Pct value={v.reference_resolution_success_rate} /></TableCell>
                    <TableCell><Pct value={v.correction_rate} /></TableCell>
                    <TableCell><span className="font-mono text-xs">{v.invoice_count || 0}</span></TableCell>
                    <TableCell>
                      {v.has_manual_override
                        ? <Badge className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-700">
                            <UserCog className="w-2.5 h-2.5 mr-1" />Manual
                          </Badge>
                        : <span className="text-[10px] text-muted-foreground">-</span>}
                    </TableCell>
                    <TableCell>
                      <Button variant="ghost" size="icon" className="h-6 w-6" data-testid={`view-detail-${vId}`}>
                        <Eye className="w-3 h-3" />
                      </Button>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Detail Drawer */}
      {selectedVendor && (
        <VendorDetailDrawer
          vendor={detailData}
          onClose={() => { setSelectedVendor(null); setDetailData(null); }}
          onRefresh={refreshDetail}
        />
      )}
    </div>
  );
}
