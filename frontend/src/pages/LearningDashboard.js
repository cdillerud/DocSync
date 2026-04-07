import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  Brain, RefreshCw, TrendingUp, CheckCircle2, AlertTriangle,
  Zap, BookOpen, ArrowRight, Activity, Database, Loader2,
  RotateCcw, Sparkles, Shield, Fingerprint, Target, Gauge,
  Eye, Search, BarChart3, GitBranch, Copy, FileText, Users
} from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ title, value, icon: Icon, subtitle, color = "text-emerald-500" }) {
  return (
    <Card data-testid={`stat-${title.toLowerCase().replace(/\s/g, '-')}`}>
      <CardContent className="pt-4 pb-3 px-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">{title}</p>
            <p className="text-2xl font-bold mt-1">{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
          </div>
          <Icon className={`w-8 h-8 ${color} opacity-70`} />
        </div>
      </CardContent>
    </Card>
  );
}

function LearningEnginesSection({ onComplete }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning/run-all`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
        toast.success('All learning engines completed');
        if (onComplete) onComplete();
      } else {
        toast.error('Learning engines failed');
      }
    } catch {
      toast.error('Network error');
    }
    setRunning(false);
  };

  const posted = result?.posted_draft_detection || {};
  const cross = result?.cross_vendor_learning || {};
  const promo = result?.confidence_auto_promotion || {};

  return (
    <Card data-testid="learning-engines-section">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-500" />
          Continuous Learning Engines
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-3">
          Runs automatically every 2h. Detects posted drafts in BC, propagates corrections across similar vendors,
          and auto-promotes vendor confidence based on approval ratio.
        </p>
        <Button onClick={handleRun} disabled={running} data-testid="run-engines-btn">
          {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Zap className="w-4 h-4 mr-2" />}
          {running ? 'Running Engines...' : 'Run All Learning Engines'}
        </Button>

        {result && (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3" data-testid="engines-results">
            {/* A: Posted Draft Detection */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-emerald-400 mb-2">A. Posted Draft Detection</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Checked</span><span>{posted.checked || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Posted Found</span><span className="text-emerald-400">{posted.posted_found || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Changes Learned</span><span className="text-violet-400">{posted.changes_learned || 0}</span></div>
              </div>
            </div>

            {/* B: Cross-Vendor Learning */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-blue-400 mb-2">B. Cross-Vendor Propagation</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Corrections Checked</span><span>{cross.corrections_checked || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Vendors Propagated To</span><span className="text-blue-400">{cross.propagated_to_vendors || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Adjustments Applied</span><span className="text-violet-400">{cross.propagations_applied || 0}</span></div>
              </div>
            </div>

            {/* C: Confidence Auto-Promotion */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-amber-400 mb-2">C. Confidence Promotion</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Promoted</span><span className="text-emerald-400">{promo.promoted?.length || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Demoted</span><span className="text-rose-400">{promo.demoted?.length || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Unchanged</span><span>{promo.unchanged || 0}</span></div>
              </div>
              {promo.promoted?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {promo.promoted.map((p, i) => (
                    <div key={i} className="flex items-center gap-1 text-xs">
                      <span className="font-mono">{p.vendor}</span>
                      <Badge variant="outline" className="text-xs text-rose-400">{p.from}</Badge>
                      <ArrowRight className="w-3 h-3" />
                      <Badge variant="outline" className="text-xs text-emerald-400">{p.to}</Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ReEvaluateSection({ onComplete }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/api/readiness/reevaluate-all`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
        toast.success(
          `Re-evaluated ${data.total_processed} docs — ${data.total_corrections} corrections applied`
        );
        if (onComplete) onComplete();
      } else {
        toast.error('Re-evaluation failed');
      }
    } catch {
      toast.error('Network error');
    }
    setRunning(false);
  };

  return (
    <Card data-testid="reevaluate-section">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-500" />
          Batch Re-evaluate & Learn
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-3">
          Re-run readiness evaluation across all documents. Detects and corrects signal contradictions
          (stale duplicate flags, premature PO resolved, etc.) — every correction feeds into the learning pipeline.
        </p>
        <Button onClick={handleRun} disabled={running} data-testid="reevaluate-all-btn">
          {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <RotateCcw className="w-4 h-4 mr-2" />}
          {running ? 'Re-evaluating...' : 'Re-evaluate All Documents'}
        </Button>

        {result && (
          <div className="mt-4 space-y-3" data-testid="reevaluate-results">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold">{result.total_processed}</p>
                <p className="text-xs text-muted-foreground">Processed</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-violet-400">{result.total_corrections}</p>
                <p className="text-xs text-muted-foreground">Corrections Learned</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-amber-400">{result.status_transitions?.length || 0}</p>
                <p className="text-xs text-muted-foreground">Status Changes</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-rose-400">{result.errors}</p>
                <p className="text-xs text-muted-foreground">Errors</p>
              </div>
            </div>

            {/* Status Distribution */}
            {result.by_status && Object.keys(result.by_status).length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">Status Distribution</p>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(result.by_status).map(([status, count]) => (
                    <Badge key={status} variant="outline" className="text-xs">
                      {status}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Status Transitions */}
            {result.status_transitions?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  Status Transitions ({result.status_transitions.length})
                </p>
                <div className="max-h-[200px] overflow-y-auto space-y-1">
                  {result.status_transitions.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs bg-muted/50 rounded px-2 py-1">
                      <span className="font-mono">{t.doc_id}</span>
                      {t.vendor_no && <span className="text-muted-foreground">{t.vendor_no}</span>}
                      <Badge variant="outline" className="text-rose-400 border-rose-500/30">{t.from}</Badge>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">{t.to}</Badge>
                      <span className="text-muted-foreground ml-auto">
                        {(t.old_confidence * 100).toFixed(0)}% → {(t.new_confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Vendor Corrections */}
            {result.vendor_corrections?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  Vendors with Corrections ({result.vendor_corrections.length})
                </p>
                <div className="max-h-[150px] overflow-y-auto space-y-1">
                  {result.vendor_corrections.map((v, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs bg-muted/50 rounded px-2 py-1">
                      <span className="font-mono font-medium">{v.vendor_no}</span>
                      <Badge variant="secondary">{v.correction_count} corrections</Badge>
                      {v.signals.map((s, j) => (
                        <Badge key={j} variant="outline" className="text-xs text-violet-400 border-violet-500/30">{s}</Badge>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function GapCloserSection() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchStatus = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/gap-closer/status`);
      if (res.ok) setStatus(await res.json());
    } catch (err) { console.error(err); }
    setLoading(false);
  };

  useEffect(() => { fetchStatus(); }, []);

  const gapColors = (triggers) => triggers ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-muted';

  return (
    <Card data-testid="gap-closer-section">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Target className="w-4 h-4 text-emerald-500" />
            Validation Gap Closers
          </CardTitle>
          <Button variant="outline" size="sm" onClick={fetchStatus} disabled={loading} data-testid="refresh-gaps-btn">
            <RefreshCw className={`w-3 h-3 mr-1 ${loading ? 'animate-spin' : ''}`} />Refresh
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          Using learned intelligence to close the 10 biggest validation gaps. Active on every document.
        </p>
      </CardHeader>
      <CardContent>
        {loading && !status ? (
          <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : !status ? (
          <p className="text-sm text-muted-foreground text-center py-4">No gap data yet.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {/* GAP 1: Confidence Calibration */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-1-confidence">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Shield className="w-3 h-3 text-emerald-500" /> Gap 1: Confidence Miscalibration
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Routes unreliable confidence bands to human review automatically.
              </p>
              {status.gap_1_confidence_calibration?.bands && (
                <div className="space-y-1">
                  {Object.entries(status.gap_1_confidence_calibration.bands).map(([band, info]) => (
                    <div key={band} className="flex items-center justify-between text-[10px]">
                      <span className="font-mono">{band}</span>
                      <span>{info.samples} samples</span>
                      <span className={info.accuracy !== null ?
                        (info.accuracy >= 0.8 ? 'text-emerald-400' : info.accuracy >= 0.65 ? 'text-amber-400' : 'text-red-400 font-bold')
                        : 'text-muted-foreground'}>
                        {info.accuracy !== null ? `${(info.accuracy * 100).toFixed(0)}%` : '--'}
                      </span>
                      {info.triggers_review && (
                        <Badge variant="destructive" className="text-[8px]">→ REVIEW</Badge>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* GAP 2: PO Matching */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-2-po">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Zap className="w-3 h-3 text-cyan-500" /> Gap 2: PO Validation
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Fuzzy PO matching + vendor patterns + document flow cross-reference.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_2_po_matching?.vendors_with_po_patterns || 0}</p>
                  <p className="text-muted-foreground">PO Patterns</p>
                </div>
                <div>
                  <p className="font-bold">{status.gap_2_po_matching?.po_flow_events || 0}</p>
                  <p className="text-muted-foreground">Flow Events</p>
                </div>
                <div>
                  <p className="font-bold text-red-400">{status.gap_2_po_matching?.gap_count || 0}</p>
                  <p className="text-muted-foreground">Open Gap</p>
                </div>
              </div>
            </div>

            {/* GAP 3: Customer Match */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-3-customer">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Activity className="w-3 h-3 text-amber-500" /> Gap 3: Customer Match
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Suggests customers from vendor history when direct match fails.
              </p>
              <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_3_customer_matching?.historical_matches || 0}</p>
                  <p className="text-muted-foreground">Historical Matches</p>
                </div>
                <div>
                  <p className="font-bold text-red-400">{status.gap_3_customer_matching?.gap_count || 0}</p>
                  <p className="text-muted-foreground">Open Gap</p>
                </div>
              </div>
            </div>

            {/* GAP 4: Sales Order Match */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-4-sales-order">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <GitBranch className="w-3 h-3 text-violet-500" /> Gap 4: Sales Order Match
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Cross-references document flow + fuzzy matching to find orders.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_4_sales_order_matching?.flow_events || 0}</p>
                  <p className="text-muted-foreground">Flow Events</p>
                </div>
                <div>
                  <p className="font-bold">{status.gap_4_sales_order_matching?.historical_so_matches || 0}</p>
                  <p className="text-muted-foreground">SO Matches</p>
                </div>
                <div>
                  <p className="font-bold text-red-400">{status.gap_4_sales_order_matching?.gap_count || 0}</p>
                  <p className="text-muted-foreground">Open Gap</p>
                </div>
              </div>
            </div>

            {/* GAP 5: Duplicate Intelligence */}
            <div className={`p-3 rounded border ${gapColors(!!status.gap_5_duplicate_intelligence?.vendors_with_intel)}`} data-testid="gap-5-duplicate">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Copy className="w-3 h-3 text-rose-500" /> Gap 5: Duplicate Intelligence
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Learns from false-positive duplicate flags. Auto-clears unreliable vendor duplicates.
              </p>
              <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_5_duplicate_intelligence?.vendors_with_intel || 0}</p>
                  <p className="text-muted-foreground">Vendors Tracked</p>
                </div>
                <div>
                  <p className="font-bold">
                    {status.gap_5_duplicate_intelligence?.global_false_positive_rate != null
                      ? `${(status.gap_5_duplicate_intelligence.global_false_positive_rate * 100).toFixed(0)}%`
                      : '--'}
                  </p>
                  <p className="text-muted-foreground">Global FP Rate</p>
                </div>
                <div>
                  <p className="font-bold text-emerald-400">{status.gap_5_duplicate_intelligence?.safe_to_clear_vendors || 0}</p>
                  <p className="text-muted-foreground">Safe to Clear</p>
                </div>
                <div>
                  <p className="font-bold text-red-400">{status.gap_5_duplicate_intelligence?.currently_blocked || 0}</p>
                  <p className="text-muted-foreground">Blocked</p>
                </div>
              </div>
            </div>

            {/* GAP 6: Amount Anomaly */}
            <div className={`p-3 rounded border ${gapColors(!!status.gap_6_amount_anomaly?.vendors_with_patterns)}`} data-testid="gap-6-amount">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <TrendingUp className="w-3 h-3 text-orange-500" /> Gap 6: Amount Anomaly
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Detects unusual amounts per vendor. High-severity anomalies forced to review.
              </p>
              <div className="grid grid-cols-2 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_6_amount_anomaly?.vendors_with_patterns || 0}</p>
                  <p className="text-muted-foreground">Vendors Tracked</p>
                </div>
                <div>
                  <p className="font-bold text-amber-400">{status.gap_6_amount_anomaly?.active_anomalies || 0}</p>
                  <p className="text-muted-foreground">Active Anomalies</p>
                </div>
              </div>
            </div>

            {/* GAP 7: Escalation Intelligence */}
            <div className={`p-3 rounded border ${gapColors(!!status.gap_7_escalation_intelligence?.combinations_tracked)}`} data-testid="gap-7-escalation">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <AlertTriangle className="w-3 h-3 text-yellow-500" /> Gap 7: Auto-Escalation
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Pre-routes vendor+doc_type combos with consistent failures to manual review.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold">{status.gap_7_escalation_intelligence?.combinations_tracked || 0}</p>
                  <p className="text-muted-foreground">Tracked</p>
                </div>
                <div>
                  <p className="font-bold text-red-400">{status.gap_7_escalation_intelligence?.always_escalate || 0}</p>
                  <p className="text-muted-foreground">Escalated</p>
                </div>
                <div>
                  <p className="font-bold text-emerald-400">{status.gap_7_escalation_intelligence?.fully_automated || 0}</p>
                  <p className="text-muted-foreground">Automated</p>
                </div>
              </div>
            </div>

            {/* GAP 8: Extraction Quality Gate */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-8-extraction">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <FileText className="w-3 h-3 text-sky-500" /> Gap 8: Extraction Quality
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Filename parsing + batch context inheritance. Downgrades empty docs to advisory.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold text-red-400">{status.gap_8_extraction_quality?.blocking_count || 0}</p>
                  <p className="text-muted-foreground">Blocking</p>
                </div>
                <div>
                  <p className="font-bold text-emerald-400">{status.gap_8_extraction_quality?.resolved_by_filename || 0}</p>
                  <p className="text-muted-foreground">Resolved</p>
                </div>
                <div>
                  <p className="font-bold text-amber-400">{status.gap_8_extraction_quality?.downgraded_to_advisory || 0}</p>
                  <p className="text-muted-foreground">Advisory</p>
                </div>
              </div>
            </div>

            {/* GAP 9: Enhanced Vendor Match */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-9-vendor-enhanced">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Users className="w-3 h-3 text-indigo-500" /> Gap 9: Enhanced Vendor Match
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Cross-doc inference, email domain mapping, aggressive first-word matching.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold text-red-400">{status.gap_9_enhanced_vendor_match?.blocking_count || 0}</p>
                  <p className="text-muted-foreground">Open Gap</p>
                </div>
                <div>
                  <p className="font-bold text-emerald-400">{status.gap_9_enhanced_vendor_match?.enhanced_resolved || 0}</p>
                  <p className="text-muted-foreground">AI Resolved</p>
                </div>
                <div>
                  <p className="font-bold">{status.gap_9_enhanced_vendor_match?.total_aliases || 0}</p>
                  <p className="text-muted-foreground">Aliases</p>
                </div>
              </div>
            </div>

            {/* GAP 10: Enhanced PO Revalidation */}
            <div className={`p-3 rounded border ${gapColors(true)}`} data-testid="gap-10-po-enhanced">
              <div className="flex items-center justify-between mb-2">
                <p className="text-xs font-medium flex items-center gap-1">
                  <Zap className="w-3 h-3 text-teal-500" /> Gap 10: Enhanced PO
                </p>
                <Badge className="bg-emerald-600 text-white text-[10px]">ACTIVE</Badge>
              </div>
              <p className="text-[10px] text-muted-foreground mb-2">
                Profile relaxation (&lt;30% PO rate), broader ref matching, doc-type downgrade.
              </p>
              <div className="grid grid-cols-3 gap-2 text-center text-[10px]">
                <div>
                  <p className="font-bold text-red-400">{status.gap_10_enhanced_po?.blocking_count || 0}</p>
                  <p className="text-muted-foreground">Open Gap</p>
                </div>
                <div>
                  <p className="font-bold text-emerald-400">{status.gap_10_enhanced_po?.enhanced_resolved || 0}</p>
                  <p className="text-muted-foreground">AI Resolved</p>
                </div>
                <div>
                  <p className="font-bold text-amber-400">{status.gap_10_enhanced_po?.downgraded_to_advisory || 0}</p>
                  <p className="text-muted-foreground">Advisory</p>
                </div>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function AdvancedLearningSection() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [backfilling, setBackfilling] = useState(false);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/advanced-learning/summary`);
      if (res.ok) setSummary(await res.json());
    } catch (err) { console.error(err); }
    setLoading(false);
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/advanced-learning/backfill?limit=1000`, { method: 'POST' });
      if (res.ok) {
        toast.success('Advanced learning backfill started');
        setTimeout(fetchSummary, 5000);
      }
    } catch { toast.error('Backfill failed'); }
    setBackfilling(false);
  };

  useEffect(() => { fetchSummary(); }, []);

  const li = summary?.line_item_intelligence;
  const df = summary?.document_flow;
  const ap = summary?.amount_patterns;
  const cr = summary?.correction_replay;
  const fc = summary?.field_correlations;
  const ti = summary?.temporal_intelligence;
  const ep = summary?.error_patterns;
  const vp = ti?.volume_prediction;
  const dow = ti?.by_day_of_week || {};
  const maxDow = Math.max(...Object.values(dow), 1);

  return (
    <Card data-testid="advanced-learning-section">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-rose-500" />
            Advanced Intelligence — 7 Engines
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={fetchSummary} disabled={loading} data-testid="refresh-advanced-btn">
              <RefreshCw className={`w-3 h-3 mr-1 ${loading ? 'animate-spin' : ''}`} />Refresh
            </Button>
            <Button variant="secondary" size="sm" onClick={handleBackfill} disabled={backfilling} data-testid="backfill-advanced-btn">
              {backfilling ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Database className="w-3 h-3 mr-1" />}
              Backfill All 7
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Line items, document flow, amount anomalies, correction replay, field correlations, temporal patterns, error recognition.
        </p>
      </CardHeader>
      <CardContent>
        {loading && !summary ? (
          <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : !summary ? (
          <p className="text-sm text-muted-foreground text-center py-4">No data yet. Click "Backfill All 7" to process existing documents.</p>
        ) : (
          <div className="space-y-5">
            {/* 7 Engine KPIs */}
            <div className="grid grid-cols-7 gap-2">
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-lines">
                <p className="text-lg font-bold text-cyan-500">{li?.unique_patterns || 0}</p>
                <p className="text-[10px] text-muted-foreground">Line Patterns</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-flow">
                <p className="text-lg font-bold text-blue-500">{df?.total_flow_events || 0}</p>
                <p className="text-[10px] text-muted-foreground">Flow Events</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-amounts">
                <p className="text-lg font-bold text-emerald-500">{ap?.vendors_tracked || 0}</p>
                <p className="text-[10px] text-muted-foreground">Amount Profiles</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-replays">
                <p className="text-lg font-bold text-amber-500">{cr?.total_replayed_docs || 0}</p>
                <p className="text-[10px] text-muted-foreground">Corrections Replayed</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-correlations">
                <p className="text-lg font-bold text-violet-500">{fc?.total_correlations || 0}</p>
                <p className="text-[10px] text-muted-foreground">Field Rules</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-temporal">
                <p className="text-lg font-bold text-rose-500">{vp?.predicted_volume || '--'}</p>
                <p className="text-[10px] text-muted-foreground">Tomorrow's Vol</p>
              </div>
              <div className="text-center p-2 rounded bg-muted/50" data-testid="adv-kpi-errors">
                <p className="text-lg font-bold text-red-500">{ep?.total_errors || 0}</p>
                <p className="text-[10px] text-muted-foreground">Errors Learned</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {/* Line Item Intelligence */}
              {li?.top_vendors?.length > 0 && (
                <div data-testid="adv-line-items">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Line Item Patterns</p>
                  <div className="space-y-1">
                    {li.top_vendors.map((v, i) => (
                      <div key={i} className="flex items-center justify-between p-1.5 rounded bg-muted/50 text-xs">
                        <span className="font-mono">{v.vendor_no}</span>
                        <span>{v.unique_line_types} types</span>
                        <span className="text-muted-foreground">{v.total_invoices_with_lines} inv</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Amount Patterns */}
              {ap?.top_vendors?.length > 0 && (
                <div data-testid="adv-amounts">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Amount Intelligence</p>
                  <div className="space-y-1">
                    {ap.top_vendors.map((v, i) => (
                      <div key={i} className="flex items-center gap-2 p-1.5 rounded bg-muted/50 text-xs">
                        <span className="font-mono w-16 truncate">{v.vendor_no}</span>
                        <span className="flex-1 text-right">
                          ${(v.avg_amount || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </span>
                        <span className="text-muted-foreground">
                          ${(v.min_amount || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}-${(v.max_amount || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                        </span>
                        {v.latest_is_anomaly && (
                          <Badge variant="destructive" className="text-[10px]">ANOMALY</Badge>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Field Correlation Rules */}
              {fc?.strong_rules?.length > 0 && (
                <div data-testid="adv-correlations">
                  <p className="text-xs font-medium text-muted-foreground mb-2">Learned Rules</p>
                  <div className="space-y-1">
                    {fc.strong_rules.map((r, i) => (
                      <div key={i} className="p-1.5 rounded bg-muted/50 text-xs">
                        <div className="flex items-center gap-1">
                          <span className="font-mono text-violet-400">{r.rule}</span>
                          <ArrowRight className="w-3 h-3 text-muted-foreground" />
                          <span className="font-medium">{r.predicts}</span>
                        </div>
                        <div className="flex items-center gap-2 mt-0.5">
                          <Badge variant="outline" className="text-[10px]">{(r.confidence * 100).toFixed(0)}%</Badge>
                          <span className="text-muted-foreground text-[10px]">{r.samples} samples</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Temporal Intelligence — Day of Week Pattern */}
            {Object.keys(dow).length > 0 && (
              <div data-testid="adv-temporal">
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                  <BarChart3 className="w-3 h-3" /> Weekly Volume Pattern
                  {vp?.peak_day && (
                    <span className="text-[10px] ml-2">Peak: <strong>{vp.peak_day}</strong> | Quiet: <strong>{vp.quiet_day}</strong></span>
                  )}
                </p>
                <div className="flex items-end gap-1.5 h-20">
                  {['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'].map(day => {
                    const val = dow[day] || 0;
                    const height = Math.max(val / maxDow * 100, 4);
                    const isPeak = day === vp?.peak_day;
                    return (
                      <div key={day} className="flex-1 flex flex-col items-center gap-0.5">
                        <span className="text-[10px] font-medium">{val}</span>
                        <div className={`w-full rounded-t ${isPeak ? 'bg-rose-500' : 'bg-blue-500/60'}`}
                             style={{ height: `${height}%` }} />
                        <span className="text-[9px] text-muted-foreground">{day.slice(0, 3)}</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Error Patterns */}
            {ep?.total_errors > 0 && (
              <div data-testid="adv-errors">
                <p className="text-xs font-medium text-muted-foreground mb-2">Error Pattern Recognition</p>
                <div className="flex gap-2 flex-wrap">
                  {Object.entries(ep.categories || {}).map(([cat, count]) => (
                    <div key={cat} className="text-center px-3 py-1.5 rounded bg-muted/50">
                      <p className="text-sm font-bold">{count}</p>
                      <p className="text-[10px] text-muted-foreground">{cat.replace(/_/g, ' ')}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

const maturityColors = {
  mastered: 'bg-emerald-500 text-white',
  proficient: 'bg-blue-500 text-white',
  developing: 'bg-amber-500 text-white',
  learning: 'bg-orange-500 text-white',
  novice: 'bg-red-500/80 text-white',
  unknown: 'bg-muted text-muted-foreground',
};

const maturityIcons = {
  mastered: '5',
  proficient: '4',
  developing: '3',
  learning: '2',
  novice: '1',
};

function DeepLearningSection() {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selfCorrecting, setSelfCorrecting] = useState(false);
  const [computingMaturity, setComputingMaturity] = useState(false);
  const [auditResult, setAuditResult] = useState(null);

  const fetchSummary = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/deep-learning/summary`);
      if (res.ok) setSummary(await res.json());
    } catch (err) { console.error(err); }
    setLoading(false);
  };

  const runSelfCorrection = async () => {
    setSelfCorrecting(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/deep-learning/self-correction/run?sample_size=100`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setAuditResult(data);
        toast.success(`Self-correction: ${data.audited} audited, ${data.drifts} drifts found (${(data.drift_rate * 100).toFixed(1)}%)`);
        fetchSummary();
      }
    } catch { toast.error('Self-correction failed'); }
    setSelfCorrecting(false);
  };

  const computeMaturity = async () => {
    setComputingMaturity(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/deep-learning/vendor-maturity/compute-all`, { method: 'POST' });
      if (res.ok) {
        toast.success('Vendor maturity computation started');
        setTimeout(fetchSummary, 3000);
      }
    } catch { toast.error('Maturity computation failed'); }
    setComputingMaturity(false);
  };

  useEffect(() => { fetchSummary(); }, []);

  const ep = summary?.extraction_patterns;
  const sc = summary?.self_correction;
  const vm = summary?.vendor_maturity;
  const pr = summary?.predictive_readiness;
  const ds = summary?.document_similarity;

  return (
    <Card data-testid="deep-learning-section">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Brain className="w-4 h-4 text-violet-500" />
            Deep Learning Engine
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={fetchSummary} disabled={loading} data-testid="refresh-deep-btn">
              <RefreshCw className={`w-3 h-3 mr-1 ${loading ? 'animate-spin' : ''}`} />Refresh
            </Button>
            <Button variant="secondary" size="sm" onClick={runSelfCorrection} disabled={selfCorrecting} data-testid="self-correction-btn">
              {selfCorrecting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Shield className="w-3 h-3 mr-1" />}
              Self-Correct
            </Button>
            <Button variant="secondary" size="sm" onClick={computeMaturity} disabled={computingMaturity} data-testid="compute-maturity-btn">
              {computingMaturity ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Gauge className="w-3 h-3 mr-1" />}
              Score Vendors
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          5 advanced intelligence layers: extraction patterns, document similarity, self-correction, vendor maturity, predictive readiness.
        </p>
      </CardHeader>
      <CardContent>
        {loading && !summary ? (
          <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : !summary ? (
          <p className="text-sm text-muted-foreground text-center py-4">No deep learning data yet. Process documents to start learning.</p>
        ) : (
          <div className="space-y-5">
            {/* 5 Engine KPIs */}
            <div className="grid grid-cols-5 gap-3">
              <div className="text-center p-3 rounded bg-muted/50" data-testid="deep-kpi-patterns">
                <Fingerprint className="w-4 h-4 mx-auto mb-1 text-cyan-500" />
                <p className="text-xl font-bold">{ep?.vendors_tracked || 0}</p>
                <p className="text-[10px] text-muted-foreground">Extraction Patterns</p>
              </div>
              <div className="text-center p-3 rounded bg-muted/50" data-testid="deep-kpi-fingerprints">
                <Search className="w-4 h-4 mx-auto mb-1 text-amber-500" />
                <p className="text-xl font-bold">{ds?.fingerprints_stored || 0}</p>
                <p className="text-[10px] text-muted-foreground">Doc Fingerprints</p>
              </div>
              <div className="text-center p-3 rounded bg-muted/50" data-testid="deep-kpi-audits">
                <Shield className="w-4 h-4 mx-auto mb-1 text-emerald-500" />
                <p className="text-xl font-bold">{sc?.latest_audit ? `${((1 - sc.latest_audit.drift_rate) * 100).toFixed(0)}%` : '--'}</p>
                <p className="text-[10px] text-muted-foreground">Decision Accuracy</p>
              </div>
              <div className="text-center p-3 rounded bg-muted/50" data-testid="deep-kpi-maturity">
                <Gauge className="w-4 h-4 mx-auto mb-1 text-violet-500" />
                <p className="text-xl font-bold">{Object.values(vm?.levels || {}).reduce((a, b) => a + b, 0)}</p>
                <p className="text-[10px] text-muted-foreground">Vendors Scored</p>
              </div>
              <div className="text-center p-3 rounded bg-muted/50" data-testid="deep-kpi-predictions">
                <Eye className="w-4 h-4 mx-auto mb-1 text-rose-500" />
                <p className="text-xl font-bold">{pr?.predictions_made || 0}</p>
                <p className="text-[10px] text-muted-foreground">Predictions Made</p>
              </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Extraction Patterns — Top Vendors */}
              {ep?.top_vendors?.length > 0 && (
                <div data-testid="deep-extraction-patterns">
                  <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                    <Fingerprint className="w-3 h-3" /> Extraction Pattern Mastery
                  </p>
                  <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                    {ep.top_vendors.map((v, i) => (
                      <div key={i} className="flex items-center gap-2 p-2 rounded bg-muted/50 text-xs">
                        <span className="font-mono font-medium w-20 truncate">{v.vendor_no}</span>
                        <span className="text-muted-foreground truncate flex-1">{v.vendor_name}</span>
                        <span className="font-medium">{v.documents} docs</span>
                        <div className="flex items-center gap-1">
                          <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                            <div className="h-full bg-cyan-500 rounded-full"
                                 style={{ width: `${v.total_fields > 0 ? (v.reliable_fields / v.total_fields) * 100 : 0}%` }} />
                          </div>
                          <span className="text-[10px] text-muted-foreground">{v.reliable_fields}/{v.total_fields}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Vendor Maturity Levels */}
              {vm?.levels && Object.keys(vm.levels).length > 0 && (
                <div data-testid="deep-vendor-maturity">
                  <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                    <Gauge className="w-3 h-3" /> Vendor Maturity Distribution
                  </p>
                  <div className="flex gap-2 mb-3">
                    {['mastered', 'proficient', 'developing', 'learning', 'novice'].map(level => (
                      <div key={level} className="text-center flex-1">
                        <div className={`rounded px-2 py-1.5 ${maturityColors[level]}`}>
                          <p className="text-lg font-bold">{vm.levels[level] || 0}</p>
                        </div>
                        <p className="text-[10px] text-muted-foreground mt-1 capitalize">{level}</p>
                      </div>
                    ))}
                  </div>
                  {vm.top_vendors?.length > 0 && (
                    <div className="space-y-1 max-h-[120px] overflow-y-auto">
                      {vm.top_vendors.slice(0, 6).map((v, i) => (
                        <div key={i} className="flex items-center gap-2 text-xs px-2 py-1 rounded bg-muted/30">
                          <Badge className={`text-[10px] ${maturityColors[v.level]}`}>{v.level}</Badge>
                          <span className="font-mono">{v.vendor_no}</span>
                          <span className="text-muted-foreground truncate flex-1">{v.vendor_name}</span>
                          <span className="font-medium">{v.score}/100</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Self-Correction Results */}
            {(auditResult || sc?.latest_audit) && (
              <div data-testid="deep-self-correction">
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                  <Shield className="w-3 h-3" /> Self-Correction Audit
                </p>
                {(() => {
                  const a = auditResult || sc?.latest_audit || {};
                  const driftRate = a.drift_rate || 0;
                  return (
                    <div className="p-3 rounded bg-muted/50">
                      <div className="flex items-center gap-4 mb-2">
                        <div>
                          <p className="text-2xl font-bold text-emerald-500">{a.audited || a.confirmations || 0}</p>
                          <p className="text-[10px] text-muted-foreground">Docs Audited</p>
                        </div>
                        <div>
                          <p className={`text-2xl font-bold ${driftRate > 0.1 ? 'text-amber-500' : 'text-emerald-500'}`}>
                            {(a.drifts || a.drift_count || 0)}
                          </p>
                          <p className="text-[10px] text-muted-foreground">Drifts Found</p>
                        </div>
                        <div>
                          <p className={`text-2xl font-bold ${driftRate > 0.1 ? 'text-amber-500' : 'text-emerald-500'}`}>
                            {((1 - driftRate) * 100).toFixed(1)}%
                          </p>
                          <p className="text-[10px] text-muted-foreground">Decision Accuracy</p>
                        </div>
                        <p className="text-xs text-muted-foreground ml-auto">
                          {a.run_at ? `Last run: ${new Date(a.run_at).toLocaleString()}` : ''}
                        </p>
                      </div>
                      {a.drift_details?.length > 0 && (
                        <div className="space-y-1 max-h-[100px] overflow-y-auto">
                          {a.drift_details.slice(0, 5).map((d, i) => (
                            <div key={i} className="flex items-center gap-2 text-xs px-2 py-1 rounded bg-background/50">
                              <Badge variant="destructive" className="text-[10px]">drift</Badge>
                              <span className="font-mono">{(d.doc_id || '').substring(0, 12)}</span>
                              <span className="text-muted-foreground truncate">{d.drift_reason}</span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            )}

            {/* Predictive Readiness */}
            {pr && pr.predictions_made > 0 && (
              <div data-testid="deep-predictions">
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                  <Eye className="w-3 h-3" /> Predictive Readiness Breakdown
                </p>
                <div className="flex gap-3">
                  {Object.entries(pr.breakdown || {}).map(([rec, count]) => (
                    <div key={rec} className="text-center px-4 py-2 rounded bg-muted/50">
                      <p className="text-lg font-bold">{count}</p>
                      <p className="text-[10px] text-muted-foreground">{rec.replace(/_/g, ' ')}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function LearningPulseSection() {
  const [pulse, setPulse] = useState(null);
  const [loading, setLoading] = useState(true);
  const [backfilling, setBackfilling] = useState(false);

  const fetchPulse = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning-pulse`);
      if (res.ok) setPulse(await res.json());
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning-pulse/backfill?limit=1000`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Backfill: ${data.processed || 0} documents learned from`);
        fetchPulse();
      } else {
        toast.error('Backfill failed');
      }
    } catch {
      toast.error('Backfill error');
    }
    setBackfilling(false);
  };

  useEffect(() => { fetchPulse(); }, []);

  const bandLabels = { '0_50': '0-50%', '50_70': '50-70%', '70_85': '70-85%', '85_95': '85-95%', '95_100': '95-100%' };
  const bandColors = { '0_50': 'bg-red-500', '50_70': 'bg-orange-500', '70_85': 'bg-yellow-500', '85_95': 'bg-blue-500', '95_100': 'bg-emerald-500' };

  return (
    <Card data-testid="learning-pulse-section">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-amber-500" />
            Per-Document Intelligence Pulse
          </CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={fetchPulse} disabled={loading} data-testid="refresh-pulse-btn">
              <RefreshCw className={`w-3 h-3 mr-1 ${loading ? 'animate-spin' : ''}`} />Refresh
            </Button>
            <Button variant="secondary" size="sm" onClick={handleBackfill} disabled={backfilling} data-testid="backfill-btn">
              {backfilling ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Database className="w-3 h-3 mr-1" />}
              Backfill History
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted-foreground">
          Every document makes the AI smarter. This shows real-time learning across all 8 dimensions (6 core + 2 intelligence layers).
        </p>
      </CardHeader>
      <CardContent>
        {loading && !pulse ? (
          <div className="flex justify-center py-6"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
        ) : !pulse ? (
          <p className="text-sm text-muted-foreground text-center py-4">No learning pulse data yet. Click "Backfill History" to process existing documents.</p>
        ) : (
          <div className="space-y-5">
            {/* Total learned + outcome breakdown */}
            <div className="flex items-center gap-4 flex-wrap">
              <div className="text-center">
                <p className="text-3xl font-bold text-violet-500">{(pulse.total_documents_learned_from || 0).toLocaleString()}</p>
                <p className="text-xs text-muted-foreground">Documents Learned From</p>
              </div>
              {pulse.outcomes && Object.entries(pulse.outcomes).map(([outcome, count]) => (
                <div key={outcome} className="text-center px-3 py-1.5 rounded bg-muted/50">
                  <p className="text-lg font-semibold">{count.toLocaleString()}</p>
                  <p className="text-[10px] text-muted-foreground">{outcome.replace(/_/g, ' ')}</p>
                </div>
              ))}
            </div>

            {/* Confidence Calibration */}
            {pulse.confidence_calibration && Object.keys(pulse.confidence_calibration).length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                  <TrendingUp className="w-3 h-3" /> Confidence Calibration — Is the AI's confidence justified?
                </p>
                <div className="grid grid-cols-5 gap-2">
                  {Object.entries(bandLabels).map(([band, label]) => {
                    const d = pulse.confidence_calibration[band] || {};
                    const accuracy = d.accuracy || 0;
                    return (
                      <div key={band} className="text-center p-2 rounded bg-muted/50" data-testid={`calibration-band-${band}`}>
                        <div className={`h-1.5 rounded-full mb-1.5 ${bandColors[band]}`} style={{ opacity: accuracy || 0.2 }} />
                        <p className="text-xs font-medium">{label}</p>
                        <p className="text-lg font-bold">{(accuracy * 100).toFixed(0)}%</p>
                        <p className="text-[10px] text-muted-foreground">{d.total || 0} docs</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Top Vendors + Validation Gap Hotspots */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {/* Top Vendors by Learning Volume */}
              {pulse.top_vendors?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                    <Activity className="w-3 h-3" /> Top Vendors by Learning
                  </p>
                  <div className="space-y-1.5 max-h-[200px] overflow-y-auto">
                    {pulse.top_vendors.map((v, i) => (
                      <div key={i} className="flex items-center gap-2 p-2 rounded bg-muted/50 text-xs">
                        <span className="font-mono font-medium w-20 truncate">{v.vendor_no}</span>
                        <span className="text-muted-foreground truncate flex-1">{v.vendor_name}</span>
                        <span className="font-medium">{v.total_documents} docs</span>
                        <Badge variant={v.auto_validation_rate >= 0.8 ? 'default' : v.auto_validation_rate >= 0.5 ? 'secondary' : 'destructive'}
                               className={v.auto_validation_rate >= 0.8 ? 'bg-emerald-600 text-[10px]' : 'text-[10px]'}>
                          {((v.auto_validation_rate || 0) * 100).toFixed(0)}% auto
                        </Badge>
                        {v.confidence_to_validation_gap > 0.15 && (
                          <Badge variant="outline" className="text-[10px] text-amber-500 border-amber-500/30">
                            gap {(v.confidence_to_validation_gap * 100).toFixed(0)}%
                          </Badge>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Validation Gap Hotspots */}
              {pulse.validation_gap_hotspots?.length > 0 && (
                <div>
                  <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                    <AlertTriangle className="w-3 h-3" /> Validation Gap Hotspots
                  </p>
                  <div className="space-y-1.5">
                    {pulse.validation_gap_hotspots.map((g, i) => (
                      <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50 text-xs">
                        <span className="font-medium">{g.check.replace(/_/g, ' ')}</span>
                        <Badge variant="destructive" className="text-[10px]">{g.count} failures</Badge>
                      </div>
                    ))}
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-1">
                    Why high-confidence docs fail validation — the AI uses this to improve
                  </p>
                </div>
              )}
            </div>

            {/* Recent Learning Feed */}
            {pulse.recent_learning?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-2 flex items-center gap-1">
                  <Brain className="w-3 h-3" /> Live Learning Feed
                </p>
                <div className="max-h-[150px] overflow-y-auto space-y-1">
                  {pulse.recent_learning.map((r, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs px-2 py-1 rounded bg-muted/30">
                      <Badge variant="outline" className="text-[10px] shrink-0">
                        {r.trigger}
                      </Badge>
                      <span className="font-mono text-muted-foreground truncate">{(r.doc_id || '').substring(0, 12)}</span>
                      <Badge variant={
                        r.outcome === 'auto_validated' || r.outcome === 'auto_filed' || r.outcome === 'approved' || r.outcome === 'posted_to_bc'
                          ? 'default' : r.outcome === 'needs_review' ? 'secondary' : 'destructive'
                      } className={
                        r.outcome === 'auto_validated' || r.outcome === 'auto_filed' || r.outcome === 'approved' || r.outcome === 'posted_to_bc'
                          ? 'bg-emerald-600 text-[10px]' : 'text-[10px]'
                      }>
                        {r.outcome?.replace(/_/g, ' ')}
                      </Badge>
                      {r.vendor_no && <span className="font-mono text-muted-foreground">{r.vendor_no}</span>}
                      <span className="text-muted-foreground ml-auto">
                        {r.ai_confidence ? `${(r.ai_confidence * 100).toFixed(0)}%` : ''}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function LearningDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning-dashboard`);
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64" data-testid="learning-loading">
      <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
    </div>
  );

  if (!data) return (
    <div className="p-6 text-center text-muted-foreground" data-testid="learning-error">
      Failed to load learning data
    </div>
  );

  const s = data.summary;

  return (
    <div className="p-4 space-y-6 max-w-[1400px] mx-auto" data-testid="learning-dashboard">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Brain className="w-6 h-6 text-violet-500" />
            AI Learning Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Proof of what the system has learned and continues to learn
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} data-testid="refresh-learning-btn">
          <RefreshCw className="w-4 h-4 mr-1" />Refresh
        </Button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="learning-stats">
        <StatCard title="Learning Events" value={s.total_learning_events} icon={Activity}
                  subtitle="From BC postings" color="text-violet-500" />
        <StatCard title="Vendor Templates" value={s.total_posting_profiles} icon={Database}
                  subtitle={`${s.continuously_learning_vendors} continuously learning`} color="text-blue-500" />
        <StatCard title="Corrections Learned" value={s.total_corrections} icon={BookOpen}
                  subtitle="Classification fixes" color="text-amber-500" />
        <StatCard title="Label Corrections" value={s.total_label_corrections} icon={ArrowRight}
                  subtitle="Reference relabeling" color="text-rose-500" />
        <StatCard title="Auto-Drafted PIs" value={s.total_auto_drafted} icon={Zap}
                  subtitle="Template-driven" color="text-emerald-500" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Template Confidence Breakdown */}
        <Card data-testid="confidence-breakdown">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-500" />
              Posting Template Confidence
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.posting_template_confidence.length === 0 ? (
              <p className="text-sm text-muted-foreground">No templates analyzed yet</p>
            ) : (
              <div className="space-y-3">
                {data.posting_template_confidence.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50">
                    <div className="flex items-center gap-2">
                      <Badge variant={p.confidence === 'high' ? 'default' : p.confidence === 'medium' ? 'secondary' : 'outline'}
                             className={p.confidence === 'high' ? 'bg-emerald-600' : ''}>
                        {p.confidence}
                      </Badge>
                      <span className="text-sm font-medium">{p.vendor_count} vendors</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      avg {p.avg_invoices_analyzed} invoices analyzed
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Label Correction Patterns */}
        <Card data-testid="label-corrections">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <ArrowRight className="w-4 h-4 text-rose-500" />
              Learned Label Corrections
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.label_correction_patterns.length === 0 ? (
              <p className="text-sm text-muted-foreground">No label corrections recorded yet</p>
            ) : (
              <div className="space-y-2">
                {data.label_correction_patterns.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-rose-600 border-rose-300">{p.from_label}</Badge>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <Badge variant="outline" className="text-emerald-600 border-emerald-300">{p.to_label}</Badge>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-medium">{p.corrections}x</span>
                      <span className="text-xs text-muted-foreground ml-2">{p.vendors_affected} vendors</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Vendor Learning Activity */}
        <Card data-testid="vendor-learning">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="w-4 h-4 text-violet-500" />
              Vendor Learning Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.vendor_learning_activity.length === 0 ? (
              <p className="text-sm text-muted-foreground">No learning events yet</p>
            ) : (
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                {data.vendor_learning_activity.map((v, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50 text-sm">
                    <div>
                      <span className="font-mono font-medium">{v.vendor_no}</span>
                      <span className="text-muted-foreground ml-2">{v.learning_events} events</span>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <div>${v.total_amount_learned.toLocaleString()}</div>
                      <div>{v.avg_lines_per_invoice} lines/inv</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Auto-Draft Results by Vendor */}
        <Card data-testid="auto-draft-results">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="w-4 h-4 text-emerald-500" />
              Auto-Drafted PIs by Vendor
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.auto_draft_by_vendor.length === 0 ? (
              <p className="text-sm text-muted-foreground">No auto-drafts yet</p>
            ) : (
              <div className="space-y-1.5">
                {data.auto_draft_by_vendor.map((d, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50 text-sm">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      <span className="font-mono font-medium">{d.vendor_no}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-medium">{d.drafts_created} drafts</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {d.last_draft ? new Date(d.last_draft).toLocaleDateString() : ''}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Learning Events */}
      <Card data-testid="recent-events">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Brain className="w-4 h-4 text-violet-500" />
            Recent Learning Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_learning_events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No learning events recorded yet. Learning starts when PIs are created in BC.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Vendor</th>
                    <th className="pb-2 font-medium">When</th>
                    <th className="pb-2 font-medium">Lines</th>
                    <th className="pb-2 font-medium">Items Learned</th>
                    <th className="pb-2 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_learning_events.map((e, i) => (
                    <tr key={i} className="border-b border-muted/50">
                      <td className="py-1.5 font-mono">{e.vendor_no}</td>
                      <td className="py-1.5 text-muted-foreground">
                        {e.posted_at ? new Date(e.posted_at).toLocaleString() : 'N/A'}
                      </td>
                      <td className="py-1.5">{e.line_count}</td>
                      <td className="py-1.5">
                        {(e.items_used || []).map((item, j) => (
                          <Badge key={j} variant="outline" className="mr-1 text-xs">{item}</Badge>
                        ))}
                      </td>
                      <td className="py-1.5">${(e.amount || 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Corrections */}
      {data.recent_corrections.length > 0 && (
        <Card data-testid="recent-corrections">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-amber-500" />
              Recent Classification Corrections
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {data.recent_corrections.map((c, i) => (
                <div key={i} className="flex items-center gap-3 p-2 rounded bg-muted/50 text-sm">
                  <Badge variant="outline" className="text-xs">{c.correction_type || 'correction'}</Badge>
                  {c.vendor_id && <span className="font-mono text-xs">{c.vendor_id}</span>}
                  {c.original_type && c.corrected_type && (
                    <span className="text-muted-foreground">
                      {c.original_type} <ArrowRight className="w-3 h-3 inline" /> {c.corrected_type}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">
                    {c.source || ''} {c.confirmed_at ? new Date(c.confirmed_at).toLocaleDateString() : ''}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Learning Engines Section */}
      <LearningEnginesSection onComplete={fetchData} />

      {/* Per-Document Intelligence Pulse */}
      <LearningPulseSection />

      {/* Deep Learning Engine */}
      <DeepLearningSection />

      {/* Advanced Intelligence — 7 Engines */}
      <AdvancedLearningSection />

      {/* Gap Closer Status */}
      <GapCloserSection />

      {/* Batch Re-evaluate Section */}
      <ReEvaluateSection onComplete={fetchData} />
    </div>
  );
}
