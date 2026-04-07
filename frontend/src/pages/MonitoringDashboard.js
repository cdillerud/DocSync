import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import { RefreshCw, Activity, Shield, Users, AlertTriangle, TrendingUp } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function MetricCard({ icon: Icon, title, value, subtitle, status, detail, testId }) {
  const statusColors = {
    good: 'border-l-emerald-500 bg-emerald-500/5',
    warning: 'border-l-amber-500 bg-amber-500/5',
    critical: 'border-l-red-500 bg-red-500/5',
    neutral: 'border-l-slate-500 bg-slate-500/5',
  };
  const badgeColors = {
    good: 'bg-emerald-600 text-white',
    warning: 'bg-amber-600 text-white',
    critical: 'bg-red-600 text-white',
    neutral: 'bg-slate-600 text-white',
  };
  const labels = { good: 'Healthy', warning: 'Watch', critical: 'Action Needed', neutral: 'Building' };

  return (
    <Card className={`border-l-4 ${statusColors[status]}`} data-testid={testId}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between mb-3">
          <div className="flex items-center gap-2">
            <Icon className="w-4 h-4 text-muted-foreground" />
            <span className="text-sm font-medium text-muted-foreground">{title}</span>
          </div>
          <Badge className={`text-[10px] ${badgeColors[status]}`}>{labels[status]}</Badge>
        </div>
        <p className="text-3xl font-bold tracking-tight mb-1" data-testid={`${testId}-value`}>{value}</p>
        <p className="text-sm text-muted-foreground mb-2">{subtitle}</p>
        {detail && <p className="text-xs text-muted-foreground/70 leading-relaxed">{detail}</p>}
      </CardContent>
    </Card>
  );
}

export default function MonitoringDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);
  const [backfillRunning, setBackfillRunning] = useState(false);
  const [backfillResult, setBackfillResult] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [pulseRes, gapRes, deepRes, escRes, dupRes] = await Promise.all([
        fetch(`${API}/api/posting-patterns/learning-pulse`).then(r => r.ok ? r.json() : {}),
        fetch(`${API}/api/posting-patterns/gap-closer/status`).then(r => r.ok ? r.json() : {}),
        fetch(`${API}/api/posting-patterns/deep-learning/summary`).then(r => r.ok ? r.json() : {}),
        fetch(`${API}/api/posting-patterns/escalation-intelligence`).then(r => r.ok ? r.json() : {}),
        fetch(`${API}/api/posting-patterns/duplicate-intelligence`).then(r => r.ok ? r.json() : {}),
      ]);
      const poGapRes = await fetch(`${API}/api/posting-patterns/po-gap-breakdown`).then(r => r.ok ? r.json() : {});
      setData({ pulse: pulseRes, gap: gapRes, deep: deepRes, escalation: escRes, duplicate: dupRes, poGaps: poGapRes });
      setLastRefresh(new Date());
    } catch (e) {
      console.error('[Monitor] fetch failed', e);
    }
    setLoading(false);
  }, []);

  const runBackfill = async () => {
    setBackfillRunning(true);
    setBackfillResult(null);
    try {
      const res = await fetch(`${API}/api/posting-patterns/intelligence/backfill`, { method: 'POST' });
      if (res.ok) {
        const result = await res.json();
        setBackfillResult(result);
        // Refresh data after backfill
        await fetchAll();
      }
    } catch (e) {
      console.error('[Monitor] backfill failed', e);
    }
    setBackfillRunning(false);
  };

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // Compute the 5 metrics
  const metrics = computeMetrics(data);

  return (
    <div className="max-w-4xl mx-auto space-y-6" data-testid="monitoring-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">System Monitor</h1>
          <p className="text-sm text-muted-foreground mt-1">
            The 5 numbers that matter. Everything else is noise.
          </p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="text-xs text-muted-foreground">
              {lastRefresh.toLocaleTimeString()}
            </span>
          )}
          <button
            onClick={runBackfill}
            disabled={backfillRunning}
            className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors disabled:opacity-50"
            data-testid="backfill-btn"
          >
            {backfillRunning ? 'Running...' : 'Run Intelligence Backfill'}
          </button>
          <button
            onClick={fetchAll}
            disabled={loading}
            className="p-2 rounded-md hover:bg-accent transition-colors"
            data-testid="refresh-monitor-btn"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Overall Health Bar */}
      <Card data-testid="health-summary">
        <CardContent className="p-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium">Automation Health</span>
            <span className="text-2xl font-bold" data-testid="health-score">
              {metrics.healthScore}%
            </span>
          </div>
          <Progress value={metrics.healthScore} className="h-2" />
          <p className="text-xs text-muted-foreground mt-2">{metrics.healthSummary}</p>
        </CardContent>
      </Card>

      {/* Backfill Result */}
      {backfillResult && (
        <Card className="border-emerald-500/30 bg-emerald-500/5" data-testid="backfill-result">
          <CardContent className="p-4">
            <p className="text-sm font-medium mb-2">Intelligence Backfill Complete</p>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-xs">
              <div>
                <p className="text-muted-foreground">Escalation Tracked</p>
                <p className="font-bold">{backfillResult.escalation_backfill?.tracked || 0} docs</p>
              </div>
              <div>
                <p className="text-muted-foreground">Dup False Positives</p>
                <p className="font-bold">{backfillResult.duplicate_backfill?.tracked || 0} docs</p>
              </div>
              <div>
                <p className="text-muted-foreground">Vendor Maturity</p>
                <p className="font-bold">{backfillResult.vendor_maturity?.computed || 0} vendors</p>
                {backfillResult.vendor_maturity?.levels && (
                  <p className="text-muted-foreground">{Object.entries(backfillResult.vendor_maturity.levels).map(([k,v]) => `${v} ${k}`).join(', ')}</p>
                )}
              </div>
              <div>
                <p className="text-muted-foreground">Dups Cleared</p>
                <p className="font-bold">{backfillResult.duplicate_clear?.cleared || 0} docs</p>
              </div>
              <div>
                <p className="text-muted-foreground">PO Gaps Resolved</p>
                <p className="font-bold text-emerald-400">{backfillResult.po_revalidation?.resolved || 0} / {backfillResult.po_revalidation?.found || 0}</p>
                {(backfillResult.po_revalidation?.skipped_by_profile > 0 || backfillResult.po_revalidation?.bc_matched > 0) && (
                  <p className="text-muted-foreground">
                    {backfillResult.po_revalidation?.skipped_by_profile || 0} via profile, {backfillResult.po_revalidation?.bc_matched || 0} via BC
                  </p>
                )}
              </div>
            </div>
            {/* Vendor Profile Refresh Results */}
            {backfillResult.vendor_profile_refresh?.profiles && Array.isArray(backfillResult.vendor_profile_refresh.profiles) && backfillResult.vendor_profile_refresh.profiles.length > 0 && (
              <div className="mt-3 pt-3 border-t border-border/50">
                <p className="text-xs font-medium mb-2">Vendor PO Learning Status ({backfillResult.vendor_profile_refresh.refreshed || 0} profiles refreshed)</p>
                <div className="space-y-1">
                  {backfillResult.vendor_profile_refresh.profiles.map((v, i) => (
                    <div key={i} className="flex items-center justify-between text-[10px] p-1.5 rounded bg-accent/30">
                      <span className="font-mono">{v.vendor_no}</span>
                      <div className="flex items-center gap-3">
                        <span>{v.gaps} gaps</span>
                        <span>BC cache: {v.bc_cache_invoices ?? '?'} PIs</span>
                        <span>w/ PO: {v.bc_cache_with_po ?? '?'}</span>
                        <span className={v.po_expected === false ? 'text-emerald-400 font-bold' : 'text-muted-foreground'}>
                          {v.po_expected === false ? 'PO SKIP (learned)' : v.bc_cache_invoices === 0 ? 'No BC data yet' : 'PO required'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* The 5 Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <MetricCard
          icon={Shield}
          title="1. AI Confidence Accuracy"
          value={metrics.confidenceAccuracy}
          subtitle={metrics.confidenceSubtitle}
          status={metrics.confidenceStatus}
          detail={metrics.confidenceDetail}
          testId="metric-confidence"
        />
        <MetricCard
          icon={Users}
          title="2. Vendor Maturity"
          value={metrics.vendorMaturity}
          subtitle={metrics.vendorMaturitySubtitle}
          status={metrics.vendorMaturityStatus}
          detail={metrics.vendorMaturityDetail}
          testId="metric-vendor-maturity"
        />
        <MetricCard
          icon={Activity}
          title="3. Auto-File Rate"
          value={metrics.autoFileRate}
          subtitle={metrics.autoFileSubtitle}
          status={metrics.autoFileStatus}
          detail={metrics.autoFileDetail}
          testId="metric-auto-file"
        />
        <MetricCard
          icon={AlertTriangle}
          title="4. Validation Gaps"
          value={metrics.gapCount}
          subtitle={metrics.gapSubtitle}
          status={metrics.gapStatus}
          detail={metrics.gapDetail}
          testId="metric-gaps"
        />
        <MetricCard
          icon={TrendingUp}
          title="5. Escalation Patterns"
          value={metrics.escalationCount}
          subtitle={metrics.escalationSubtitle}
          status={metrics.escalationStatus}
          detail={metrics.escalationDetail}
          testId="metric-escalation"
        />
      </div>

      {/* Escalation Detail — show which combos always fail */}
      {data?.escalation?.top_escalated?.length > 0 && (
        <Card className="border-red-500/20" data-testid="escalation-detail">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-red-400">Vendor+Type Combos That Always Fail Automation</CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="space-y-2">
              {data.escalation.top_escalated.map((e, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded bg-red-500/5 border border-red-500/10 text-xs">
                  <div>
                    <span className="font-mono font-medium">{e.vendor_no || '?'}</span>
                    <span className="text-muted-foreground mx-2">+</span>
                    <span className="font-medium">{e.doc_type || '?'}</span>
                  </div>
                  <div className="flex items-center gap-4 text-muted-foreground">
                    <span>Success: <strong className="text-red-400">{e.success_rate != null ? `${Math.round(e.success_rate * 100)}%` : '?'}</strong></span>
                    <span>{e.total_attempts || 0} attempts</span>
                    <span>{e.failure_count || 0} failures</span>
                    <span>{e.review_count || 0} reviews</span>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground mt-2">These combos are pre-routed to manual review. They may need process-level fixes (non-standard formats, missing data from vendor, etc.)</p>
          </CardContent>
        </Card>
      )}

      {/* PO Validation Gap Breakdown */}
      {data?.gap?.total_validation_gaps && Object.keys(data.gap.total_validation_gaps).length > 0 && (
        <Card className="border-amber-500/20" data-testid="gap-breakdown">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-amber-400">Validation Gap Breakdown</CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(data.gap.total_validation_gaps)
                .sort(([,a], [,b]) => b - a)
                .map(([gap, count]) => (
                  <div key={gap} className="p-2 rounded bg-accent/50 text-xs">
                    <p className="font-medium">{gap.replace(/_/g, ' ')}</p>
                    <p className="text-lg font-bold">{count}</p>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* PO Gap by Vendor — which vendors are responsible */}
      {data?.poGaps?.by_vendor?.length > 0 && (
        <Card className="border-orange-500/20" data-testid="po-gap-vendors">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-orange-400">PO Validation Gaps by Vendor ({data.poGaps.total_po_gaps} total)</CardTitle>
          </CardHeader>
          <CardContent className="pb-4">
            <div className="space-y-1.5">
              {data.poGaps.by_vendor.map((v, i) => (
                <div key={i} className="flex items-center justify-between p-2 rounded bg-accent/30 text-xs">
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="font-mono font-medium shrink-0">{v.vendor_no}</span>
                    {v.vendor_name && <span className="text-muted-foreground truncate">{v.vendor_name}</span>}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="font-bold text-orange-400">{v.gap_count} gaps</span>
                    {v.sample_po_numbers?.length > 0 && (
                      <span className="text-muted-foreground text-[10px]">
                        POs: {v.sample_po_numbers.slice(0, 3).join(', ')}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[10px] text-muted-foreground mt-2">
              If a vendor consistently has PO gaps, check: (1) Are POs created in BC before invoices arrive? (2) Does this vendor use non-PO purchases? (3) Is the PO number format different than BC's?
            </p>
          </CardContent>
        </Card>
      )}

      {/* Quick context */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium text-muted-foreground">What moves these numbers?</CardTitle>
        </CardHeader>
        <CardContent className="text-xs text-muted-foreground space-y-2 pb-4">
          <p><strong>Volume is the #1 lever.</strong> Every document that flows through the system trains 20 learning dimensions. The jump from 50 to 500 documents is transformational.</p>
          <p><strong>Confidence accuracy</strong> self-corrects as the AI sees more vendor-specific patterns. If stuck below 50% after 200+ docs, check extraction prompt quality.</p>
          <p><strong>Vendor maturity</strong> progresses automatically: Learning → Developing → Stable → Autonomous. Each vendor needs ~50 documents to mature.</p>
          <p><strong>Validation gaps</strong> marked "bc_connection" mean BC API is unreachable — that's infrastructure, not AI. Everything else the AI handles.</p>
        </CardContent>
      </Card>
    </div>
  );
}

function computeMetrics(data) {
  const empty = {
    healthScore: 0, healthSummary: 'Loading...',
    confidenceAccuracy: '--', confidenceSubtitle: '', confidenceStatus: 'neutral', confidenceDetail: '',
    vendorMaturity: '--', vendorMaturitySubtitle: '', vendorMaturityStatus: 'neutral', vendorMaturityDetail: '',
    autoFileRate: '--', autoFileSubtitle: '', autoFileStatus: 'neutral', autoFileDetail: '',
    gapCount: '--', gapSubtitle: '', gapStatus: 'neutral', gapDetail: '',
    escalationCount: '--', escalationSubtitle: '', escalationStatus: 'neutral', escalationDetail: '',
  };
  if (!data) return empty;

  const { pulse, gap, deep, escalation, duplicate } = data;
  const m = { ...empty };

  // 1. Confidence Accuracy (95-100% band)
  const cal = pulse?.confidence_calibration || {};
  const topBand = cal['95_100'] || {};
  const confTotal = topBand.total || 0;
  const confAcc = topBand.accuracy;
  if (confTotal > 0 && confAcc != null) {
    const pct = Math.round(confAcc * 100);
    m.confidenceAccuracy = `${pct}%`;
    m.confidenceSubtitle = `Based on ${confTotal} high-confidence documents`;
    m.confidenceStatus = pct >= 80 ? 'good' : pct >= 50 ? 'warning' : 'critical';
    m.confidenceDetail = pct < 50
      ? `The AI says it's 95%+ confident but is only right ${pct}% of the time. Gap Closer 1 is protecting you by routing these to review. Needs more training data.`
      : pct < 80
        ? `Improving — accuracy will climb as more documents train the model.`
        : `Strong accuracy. The AI's confidence matches reality.`;
  } else {
    m.confidenceAccuracy = 'No data';
    m.confidenceSubtitle = 'Feed documents to start calibrating';
    m.confidenceStatus = 'neutral';
  }

  // 2. Vendor Maturity
  const levels = deep?.vendor_maturity?.levels || {};
  const autonomous = levels.autonomous || 0;
  const stable = levels.stable || 0;
  const developing = levels.developing || 0;
  const learning = levels.learning || 0;
  const totalVendors = autonomous + stable + developing + learning;
  const matureCount = autonomous + stable;
  if (totalVendors > 0) {
    m.vendorMaturity = `${matureCount}/${totalVendors}`;
    m.vendorMaturitySubtitle = `${matureCount} mature vendor${matureCount !== 1 ? 's' : ''} (Stable or Autonomous)`;
    m.vendorMaturityStatus = matureCount >= totalVendors * 0.5 ? 'good' : matureCount > 0 ? 'warning' : 'critical';
    const parts = [];
    if (autonomous) parts.push(`${autonomous} Autonomous`);
    if (stable) parts.push(`${stable} Stable`);
    if (developing) parts.push(`${developing} Developing`);
    if (learning) parts.push(`${learning} Learning`);
    m.vendorMaturityDetail = parts.join(' · ') + '. Each vendor needs ~50 docs to mature.';
  } else {
    m.vendorMaturity = '0 vendors';
    m.vendorMaturitySubtitle = 'No vendor data yet';
    m.vendorMaturityStatus = 'neutral';
    m.vendorMaturityDetail = 'Vendors are tracked automatically as documents flow in.';
  }

  // 3. Auto-File Rate
  const outcomes = pulse?.outcomes || {};
  const autoFiled = outcomes.auto_filed || 0;
  const totalLearned = pulse?.total_documents_learned_from || 0;
  if (totalLearned > 0) {
    const rate = Math.round((autoFiled / totalLearned) * 100);
    m.autoFileRate = `${rate}%`;
    m.autoFileSubtitle = `${autoFiled} auto-filed out of ${totalLearned} documents`;
    m.autoFileStatus = rate >= 60 ? 'good' : rate >= 30 ? 'warning' : 'critical';
    m.autoFileDetail = rate < 30
      ? `Most documents still need human review. This will improve dramatically as vendor maturity and confidence accuracy climb.`
      : rate < 60
        ? `Good progress. As vendors mature, expect this to climb to 60-80%.`
        : `Strong automation. The system is handling most documents without human intervention.`;
  } else {
    m.autoFileRate = 'No data';
    m.autoFileSubtitle = 'Waiting for documents to process';
    m.autoFileStatus = 'neutral';
  }

  // 4. Validation Gaps
  const gaps = gap?.total_validation_gaps || {};
  const totalGaps = Object.values(gaps).reduce((a, b) => a + b, 0);
  const topGap = Object.entries(gaps).sort((a, b) => b[1] - a[1])[0];
  m.gapCount = `${totalGaps}`;
  m.gapSubtitle = totalGaps === 0 ? 'No open validation gaps' : `${totalGaps} gap${totalGaps !== 1 ? 's' : ''} detected`;
  m.gapStatus = totalGaps === 0 ? 'good' : totalGaps <= 5 ? 'warning' : 'critical';
  if (topGap) {
    const label = topGap[0].replace(/_/g, ' ');
    m.gapDetail = `Biggest gap: "${label}" (${topGap[1]}). ${topGap[0] === 'bc_connection' ? 'This is a BC API connectivity issue — check your BC credentials and token.' : 'The AI gap closers are working to resolve this automatically.'}`;
  }

  // Also add duplicate intel context
  const dupBlocked = duplicate?.currently_blocked_by_duplicate || 0;
  if (dupBlocked > 0) {
    m.gapDetail += ` Also: ${dupBlocked} document${dupBlocked !== 1 ? 's' : ''} blocked by duplicate flag.`;
  }

  // 5. Escalation Patterns
  const escTotal = escalation?.total_combinations_tracked || 0;
  const escAlways = escalation?.always_escalate || 0;
  const escAuto = escalation?.fully_automated || 0;
  if (escTotal > 0) {
    m.escalationCount = `${escAlways} escalated`;
    m.escalationSubtitle = `${escTotal} vendor+type combos tracked, ${escAuto} fully automated`;
    m.escalationStatus = escAlways === 0 ? 'good' : escAlways <= 3 ? 'warning' : 'critical';
    m.escalationDetail = escAlways > 0
      ? `${escAlways} vendor+document type combination${escAlways !== 1 ? 's' : ''} consistently fail automation and are pre-routed to review. These may need process-level fixes (e.g., vendor sends non-standard formats).`
      : 'No patterns requiring permanent escalation detected yet.';
  } else {
    m.escalationCount = 'No data';
    m.escalationSubtitle = 'Tracking starts as documents are processed';
    m.escalationStatus = 'neutral';
    m.escalationDetail = 'The system will automatically identify vendor+type combos that consistently fail.';
  }

  // Health Score — weighted average
  let score = 0;
  let weights = 0;
  if (confTotal > 0) { score += (confAcc || 0) * 30; weights += 30; }
  if (totalVendors > 0) { score += (matureCount / totalVendors) * 20; weights += 20; }
  if (totalLearned > 0) { score += (autoFiled / totalLearned) * 30; weights += 30; }
  if (totalGaps >= 0) { score += Math.max(0, 1 - totalGaps / 20) * 10; weights += 10; }
  if (escTotal > 0) { score += Math.max(0, 1 - escAlways / Math.max(escTotal, 1)) * 10; weights += 10; }

  m.healthScore = weights > 0 ? Math.round((score / weights) * 100) : 0;

  if (weights === 0) {
    m.healthSummary = 'No production data yet. Feed documents to start building intelligence.';
  } else if (m.healthScore >= 70) {
    m.healthSummary = 'System is performing well. Monitor vendor maturity for continued improvement.';
  } else if (m.healthScore >= 40) {
    m.healthSummary = 'System is learning. More document volume will improve all metrics.';
  } else {
    m.healthSummary = 'Early stage — confidence accuracy and vendor maturity need more training data.';
  }

  return m;
}
