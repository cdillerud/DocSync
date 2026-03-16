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
  Settings2, Zap, CheckCircle2, XCircle, TrendingUp, Gauge, Play,
} from 'lucide-react';
import {
  getStableVendors, getStableVendorDetail, applyVendorOverride,
  clearVendorOverride, getVendorOverrideHistory, reevaluateAllVendors,
  getStableVendorConfig, updateStableVendorConfig, diagnoseStableVendors,
  applySuggestedThresholds, diagnoseApprovalBacklog, dryRunAutoApprove, runAutoApprove,
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

// ─── Config Panel ─────────────────────────────────────────────
function ConfigPanel({ onConfigSaved }) {
  const [config, setConfig] = useState(null);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getStableVendorConfig().then(r => {
      setConfig(r.data);
      setDraft(r.data);
    }).catch(() => toast.error('Failed to load config'));
  }, []);

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates = {};
      const fields = [
        'min_documents_processed', 'min_automation_success_rate',
        'min_reference_resolution_rate', 'max_correction_rate',
        'min_validation_pass_rate', 'resolver_confidence_auto_ready',
        'resolver_confidence_low_priority',
      ];
      for (const f of fields) {
        if (draft[f] !== config[f]) {
          updates[f] = Number(draft[f]);
        }
      }
      if (Object.keys(updates).length === 0) {
        toast.info('No changes to save');
        setEditing(false);
        return;
      }
      const res = await updateStableVendorConfig(updates);
      setConfig(res.data);
      setDraft(res.data);
      setEditing(false);
      toast.success('Thresholds updated');
      onConfigSaved?.();
    } catch (e) {
      toast.error('Failed to save config');
    } finally { setSaving(false); }
  };

  if (!config) return null;

  const fields = [
    { key: 'min_documents_processed', label: 'Min Documents', desc: 'Minimum invoice count for stability', step: 1 },
    { key: 'min_automation_success_rate', label: 'Min Automation Rate', desc: 'Minimum automation success %', step: 0.05 },
    { key: 'min_reference_resolution_rate', label: 'Min Resolution Rate', desc: 'Minimum reference resolution %', step: 0.05 },
    { key: 'max_correction_rate', label: 'Max Correction Rate', desc: 'Maximum label correction %', step: 0.05 },
    { key: 'min_validation_pass_rate', label: 'Min Validation Rate', desc: 'Minimum validation pass %', step: 0.05 },
  ];

  return (
    <Card className="border border-border" data-testid="config-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <Settings2 className="w-4 h-4" /> Stability Thresholds
          </CardTitle>
          {!editing ? (
            <Button variant="outline" size="sm" className="text-xs h-7" onClick={() => setEditing(true)}
              data-testid="edit-config-btn">
              Edit
            </Button>
          ) : (
            <div className="flex gap-1.5">
              <Button variant="ghost" size="sm" className="text-xs h-7"
                onClick={() => { setDraft(config); setEditing(false); }}>Cancel</Button>
              <Button size="sm" className="text-xs h-7" onClick={handleSave} disabled={saving}
                data-testid="save-config-btn">
                {saving ? 'Saving...' : 'Save'}
              </Button>
            </div>
          )}
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          {fields.map(f => (
            <div key={f.key} className="space-y-1">
              <label className="text-[10px] uppercase tracking-wider text-muted-foreground">{f.label}</label>
              {editing ? (
                <Input type="number" step={f.step} value={draft[f.key] ?? ''}
                  onChange={e => setDraft(d => ({ ...d, [f.key]: e.target.value }))}
                  className="text-xs h-8 font-mono" data-testid={`config-${f.key}`} />
              ) : (
                <p className="text-sm font-mono font-bold">
                  {f.step < 1 ? `${((config[f.key] || 0) * 100).toFixed(0)}%` : config[f.key]}
                </p>
              )}
              <p className="text-[9px] text-muted-foreground leading-tight">{f.desc}</p>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

// ─── Diagnostics Panel ────────────────────────────────────────
function DiagnosticsPanel({ onThresholdsApplied }) {
  const [diag, setDiag] = useState(null);
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);

  const runDiagnose = async () => {
    setLoading(true);
    try {
      const res = await diagnoseStableVendors();
      setDiag(res.data);
    } catch {
      toast.error('Diagnose failed');
    } finally { setLoading(false); }
  };

  const handleApplySuggested = async () => {
    setApplying(true);
    try {
      const res = await applySuggestedThresholds();
      toast.success(`Thresholds applied. ${res.data.reevaluation?.stable || 0} vendors now stable`);
      setDiag(null);
      onThresholdsApplied?.();
    } catch {
      toast.error('Failed to apply thresholds');
    } finally { setApplying(false); }
  };

  return (
    <Card className="border border-border" data-testid="diagnostics-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <Gauge className="w-4 h-4" /> Vendor Diagnostics
          </CardTitle>
          <Button variant="outline" size="sm" className="text-xs h-7" onClick={runDiagnose}
            disabled={loading} data-testid="run-diagnose-btn">
            {loading ? 'Analyzing...' : 'Run Diagnosis'}
          </Button>
        </div>
      </CardHeader>
      {diag && (
        <CardContent className="pt-0 space-y-3">
          {/* Summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-muted/40 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono">{diag.currently_stable}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Currently Stable</p>
            </div>
            <div className="bg-muted/40 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono">{diag.total_vendors}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Total Vendors</p>
            </div>
            <div className="bg-muted/40 rounded-md p-2.5 text-center col-span-2">
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Check Pass Rates</p>
              <div className="flex flex-wrap gap-x-3 gap-y-0.5 justify-center">
                {Object.entries(diag.checks_pass_rate || {}).map(([k, v]) => (
                  <span key={k} className="text-[10px] text-muted-foreground">
                    {k.replace(/_/g, ' ')}: <strong className="text-foreground">{v}</strong>
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* Suggested thresholds */}
          {diag.suggested_thresholds && Object.keys(diag.suggested_thresholds).length > 0 && (
            <div className="bg-blue-500/10 border border-blue-700/30 rounded-md p-3">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-semibold text-blue-400 flex items-center gap-1.5">
                  <TrendingUp className="w-3.5 h-3.5" /> Suggested Thresholds
                </p>
                <Button size="sm" className="text-xs h-7 bg-blue-600 hover:bg-blue-700"
                  onClick={handleApplySuggested} disabled={applying}
                  data-testid="apply-suggested-btn">
                  <Zap className="w-3 h-3 mr-1" />
                  {applying ? 'Applying...' : 'Apply & Re-evaluate'}
                </Button>
              </div>
              <div className="flex gap-4 text-xs">
                {Object.entries(diag.suggested_thresholds).map(([k, v]) => (
                  <span key={k} className="text-muted-foreground">
                    {k.replace(/min_|max_/g, '').replace(/_/g, ' ')}:{' '}
                    <strong className="text-foreground font-mono">
                      {typeof v === 'number' && v < 1 ? `${(v * 100).toFixed(0)}%` : v}
                    </strong>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Vendor list */}
          <div className="max-h-[300px] overflow-y-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead className="text-[10px]">Vendor</TableHead>
                  <TableHead className="text-[10px]">Docs</TableHead>
                  <TableHead className="text-[10px]">Auto %</TableHead>
                  <TableHead className="text-[10px]">Valid %</TableHead>
                  <TableHead className="text-[10px]">Status</TableHead>
                  <TableHead className="text-[10px]">Failing</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(diag.vendors || []).map(v => (
                  <TableRow key={v.vendor_no} className="text-xs">
                    <TableCell className="py-1.5">
                      <p className="font-medium truncate max-w-[160px]">{v.vendor}</p>
                    </TableCell>
                    <TableCell className="py-1.5 font-mono">{v.invoice_count}</TableCell>
                    <TableCell className="py-1.5 font-mono">{(v.automation_rate * 100).toFixed(0)}%</TableCell>
                    <TableCell className="py-1.5 font-mono">{(v.validation_rate * 100).toFixed(0)}%</TableCell>
                    <TableCell className="py-1.5">
                      {v.is_stable
                        ? <Badge className="text-[9px] bg-emerald-500/20 text-emerald-400 border-emerald-700">Stable</Badge>
                        : <Badge className="text-[9px] bg-gray-500/20 text-gray-400 border-gray-600">{v.checks_passed}/{v.checks_total}</Badge>}
                    </TableCell>
                    <TableCell className="py-1.5">
                      <div className="flex flex-wrap gap-0.5">
                        {v.failing_checks?.map(f => (
                          <span key={f} className="text-[9px] px-1 py-0.5 rounded bg-red-500/10 text-red-400">
                            {f.replace(/_/g, ' ')}
                          </span>
                        ))}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// ─── Auto-Approve Panel ───────────────────────────────────────
function AutoApprovePanel() {
  const [backlogDiag, setBacklogDiag] = useState(null);
  const [dryRun, setDryRun] = useState(null);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [forceMode, setForceMode] = useState(false);
  const [requireStable, setRequireStable] = useState(true);

  const loadDiagnose = async () => {
    setLoading(true);
    try {
      const res = await diagnoseApprovalBacklog();
      setBacklogDiag(res.data);
    } catch {
      toast.error('Failed to diagnose backlog');
    } finally { setLoading(false); }
  };

  const handleDryRun = async () => {
    setLoading(true);
    try {
      const res = await dryRunAutoApprove({
        require_stable_vendor: requireStable && !forceMode,
        force: forceMode,
      });
      setDryRun(res.data);
    } catch {
      toast.error('Dry run failed');
    } finally { setLoading(false); }
  };

  const handleRun = async () => {
    setRunning(true);
    try {
      const res = await runAutoApprove({
        require_stable_vendor: requireStable && !forceMode,
        force: forceMode,
      });
      toast.success(`Auto-approved ${res.data.approved} documents`);
      setDryRun(null);
      setBacklogDiag(null);
    } catch {
      toast.error('Auto-approve failed');
    } finally { setRunning(false); }
  };

  return (
    <Card className="border border-border" data-testid="auto-approve-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4" /> Auto-Approve Engine
          </CardTitle>
          <div className="flex gap-1.5">
            <Button variant="outline" size="sm" className="text-xs h-7"
              onClick={loadDiagnose} disabled={loading} data-testid="diagnose-backlog-btn">
              Diagnose Backlog
            </Button>
            <Button variant="outline" size="sm" className="text-xs h-7"
              onClick={handleDryRun} disabled={loading} data-testid="dry-run-approve-btn">
              Dry Run
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        {/* Controls */}
        <div className="flex items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={requireStable} onChange={e => setRequireStable(e.target.checked)}
              className="rounded border-border" disabled={forceMode} />
            <span className="text-muted-foreground">Require stable vendor</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={forceMode} onChange={e => setForceMode(e.target.checked)}
              className="rounded border-border" data-testid="force-mode-checkbox" />
            <span className="text-amber-400 font-semibold">Force mode (approve ALL)</span>
          </label>
        </div>

        {/* Backlog diagnosis */}
        {backlogDiag && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <div className="bg-muted/40 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono">{backlogDiag.total_needs_approval}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Needs Approval</p>
            </div>
            <div className="bg-emerald-500/10 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono text-emerald-400">{backlogDiag.auto_approvable_now}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Auto-Approvable Now</p>
            </div>
            <div className="bg-amber-500/10 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono text-amber-400">{backlogDiag.needs_stable_vendor_first}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Needs Stable Vendor</p>
            </div>
            <div className="bg-muted/40 rounded-md p-2.5 text-center">
              <p className="text-2xl font-black font-mono">{backlogDiag.unique_vendors}</p>
              <p className="text-[10px] text-muted-foreground uppercase">Unique Vendors</p>
            </div>
          </div>
        )}

        {/* Dry run results */}
        {dryRun && (
          <div className="space-y-2">
            <div className="flex items-center gap-3">
              <div className="bg-emerald-500/10 border border-emerald-700/30 rounded-md px-3 py-2 text-center">
                <p className="text-xl font-black font-mono text-emerald-400">{dryRun.would_approve}</p>
                <p className="text-[10px] text-muted-foreground">Would Approve</p>
              </div>
              <div className="bg-gray-500/10 border border-gray-700/30 rounded-md px-3 py-2 text-center">
                <p className="text-xl font-black font-mono text-gray-400">{dryRun.would_skip}</p>
                <p className="text-[10px] text-muted-foreground">Would Skip</p>
              </div>
              {dryRun.would_approve > 0 && (
                <Button size="sm" className="h-9 bg-emerald-600 hover:bg-emerald-700 text-xs"
                  onClick={handleRun} disabled={running} data-testid="execute-approve-btn">
                  <Play className="w-3.5 h-3.5 mr-1.5" />
                  {running ? 'Approving...' : `Approve ${dryRun.would_approve} Documents`}
                </Button>
              )}
            </div>
            {Object.keys(dryRun.skip_reasons_summary || {}).length > 0 && (
              <div className="text-xs text-muted-foreground">
                <p className="font-semibold mb-0.5">Skip reasons:</p>
                {Object.entries(dryRun.skip_reasons_summary).map(([reason, count]) => (
                  <p key={reason} className="ml-2">{reason}: <strong>{count}</strong></p>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
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
              <SummaryItem label="Effective Status"><StatusBadge status={vendor.effective_status} /></SummaryItem>
              <SummaryItem label="System Status"><StatusBadge status={vendor.system_status} /></SummaryItem>
              <SummaryItem label="Score">
                <span className="font-mono font-bold text-sm">{(vendor.stable_vendor_score || 0).toFixed(3)}</span>
              </SummaryItem>
              <SummaryItem label="Documents"><span className="font-mono text-sm">{vendor.invoice_count || 0}</span></SummaryItem>
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

          {/* Stability Checks */}
          {vendor.stability_checks?.length > 0 && (
            <section data-testid="stability-checks">
              <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Check Details</h3>
              <div className="space-y-1.5">
                {vendor.stability_checks.map((c, i) => (
                  <div key={i} className="flex items-center justify-between text-xs px-2 py-1.5 bg-muted/30 rounded">
                    <span className="text-muted-foreground">{c.check?.replace(/_/g, ' ')}</span>
                    <div className="flex items-center gap-2">
                      <span className="font-mono">{typeof c.value === 'number' ? c.value.toFixed(3) : String(c.value)}</span>
                      <span className="font-mono text-[10px] text-muted-foreground">
                        (req: {typeof c.threshold === 'number' ? c.threshold : '-'})
                      </span>
                      {c.passed
                        ? <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
                        : <XCircle className="w-3.5 h-3.5 text-red-400" />}
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
          </section>

          {/* Override Actions */}
          <section data-testid="override-actions">
            <h3 className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Admin Actions</h3>
            {vendor.has_manual_override && (
              <div className="mb-3 p-2 bg-amber-500/10 border border-amber-700/40 rounded text-xs">
                <p className="text-amber-400 font-semibold">Active Override: {vendor.manual_override_status}</p>
                {vendor.manual_override_reason && <p className="text-muted-foreground mt-0.5">Reason: {vendor.manual_override_reason}</p>}
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
  const [configKey, setConfigKey] = useState(0);

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

  const handleConfigSaved = () => {
    setConfigKey(k => k + 1);
    fetchVendors();
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
    <div className="space-y-4" data-testid="stable-vendors-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Stable Vendor Admin
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {total} vendors &middot; Configure thresholds, diagnose stability, and auto-approve
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={handleReevaluate} disabled={reevalLoading}
          data-testid="reevaluate-all-btn">
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${reevalLoading ? 'animate-spin' : ''}`} />
          {reevalLoading ? 'Evaluating...' : 'Re-evaluate All'}
        </Button>
      </div>

      {/* Config Panel */}
      <ConfigPanel key={configKey} onConfigSaved={handleConfigSaved} />

      {/* Diagnostics + Auto-Approve */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <DiagnosticsPanel onThresholdsApplied={handleConfigSaved} />
        <AutoApprovePanel />
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
