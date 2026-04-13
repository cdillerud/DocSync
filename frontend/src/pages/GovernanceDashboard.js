import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import {
  Shield, Activity, TrendingUp, AlertTriangle, Users, Package,
  RefreshCw, FileCheck, Clock, CheckCircle2, XCircle, ArrowUpRight,
  ChevronDown, ChevronRight, BarChart3
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ icon: Icon, label, value, sub, accent, testId }) {
  const accents = {
    emerald: 'border-l-emerald-500 bg-emerald-500/5',
    amber: 'border-l-amber-500 bg-amber-500/5',
    red: 'border-l-red-500 bg-red-500/5',
    blue: 'border-l-blue-500 bg-blue-500/5',
    slate: 'border-l-slate-500 bg-slate-500/5',
    violet: 'border-l-violet-500 bg-violet-500/5',
  };
  return (
    <Card className={`border-l-4 ${accents[accent] || accents.slate}`} data-testid={testId}>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 mb-2">
          <Icon className="w-4 h-4 text-muted-foreground" />
          <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
        </div>
        <p className="text-2xl font-bold tracking-tight" data-testid={`${testId}-value`}>{value}</p>
        {sub && <p className="text-xs text-muted-foreground mt-1">{sub}</p>}
      </CardContent>
    </Card>
  );
}

function DriftBar({ low, medium, high, testId }) {
  const total = low + medium + high;
  if (total === 0) {
    return (
      <div className="text-xs text-muted-foreground text-center py-6" data-testid={testId}>
        No profile changes yet — drift tracking starts after suggestions are applied
      </div>
    );
  }
  const pLow = (low / total * 100).toFixed(0);
  const pMed = (medium / total * 100).toFixed(0);
  const pHigh = (high / total * 100).toFixed(0);

  return (
    <div data-testid={testId}>
      <div className="flex h-6 rounded-md overflow-hidden border border-border mb-3">
        {low > 0 && <div className="bg-emerald-500/80 flex items-center justify-center" style={{ width: `${pLow}%` }}>
          <span className="text-[10px] font-bold text-white">{low}</span>
        </div>}
        {medium > 0 && <div className="bg-amber-500/80 flex items-center justify-center" style={{ width: `${pMed}%` }}>
          <span className="text-[10px] font-bold text-white">{medium}</span>
        </div>}
        {high > 0 && <div className="bg-red-500/80 flex items-center justify-center" style={{ width: `${pHigh}%` }}>
          <span className="text-[10px] font-bold text-white">{high}</span>
        </div>}
      </div>
      <div className="flex justify-between text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-emerald-500 inline-block" /> Low ({low})</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-amber-500 inline-block" /> Medium ({medium})</span>
        <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> High ({high})</span>
      </div>
    </div>
  );
}

function PipelineCard({ title, icon: Icon, data, entityLabel, testId }) {
  const [expanded, setExpanded] = useState(false);
  const s = data?.suggestions || {};
  const fb = data?.feedback || {};
  const drift = data?.drift_30d || {};
  const hotspots = data?.hotspots || [];

  return (
    <Card className="border border-border" data-testid={testId}>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between text-base">
          <div className="flex items-center gap-2">
            <Icon className="w-4 h-4" />
            {title}
          </div>
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-muted-foreground hover:text-foreground transition-colors"
            data-testid={`${testId}-toggle`}
          >
            {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
          </button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Suggestion counts */}
        <div className="grid grid-cols-4 gap-2">
          <div className="text-center p-2 rounded-md bg-amber-500/10 border border-amber-500/20" data-testid={`${testId}-pending`}>
            <p className="text-lg font-bold text-amber-500">{s.pending || 0}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Pending</p>
          </div>
          <div className="text-center p-2 rounded-md bg-blue-500/10 border border-blue-500/20" data-testid={`${testId}-approved`}>
            <p className="text-lg font-bold text-blue-500">{s.approved || 0}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Approved</p>
          </div>
          <div className="text-center p-2 rounded-md bg-emerald-500/10 border border-emerald-500/20" data-testid={`${testId}-applied`}>
            <p className="text-lg font-bold text-emerald-500">{s.applied || 0}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Applied</p>
          </div>
          <div className="text-center p-2 rounded-md bg-slate-500/10 border border-slate-500/20" data-testid={`${testId}-rejected`}>
            <p className="text-lg font-bold text-slate-400">{s.rejected || 0}</p>
            <p className="text-[10px] text-muted-foreground uppercase">Rejected</p>
          </div>
        </div>

        {/* Agreement + Drift summary line */}
        <div className="flex items-center justify-between text-sm">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
            <span className="text-muted-foreground">Agreement</span>
            <span className="font-semibold" data-testid={`${testId}-agreement`}>
              {fb.total > 0 ? `${fb.agreement_pct}%` : 'N/A'}
            </span>
            {fb.total > 0 && <span className="text-xs text-muted-foreground">({fb.total} reviews)</span>}
          </div>
          <div className="flex items-center gap-2">
            <Activity className="w-3.5 h-3.5 text-blue-500" />
            <span className="text-muted-foreground">30d changes</span>
            <span className="font-semibold" data-testid={`${testId}-drift-count`}>{drift.changes || 0}</span>
          </div>
        </div>

        {/* Drift mini bar */}
        <div>
          <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">Drift Risk</p>
          <DriftBar
            low={drift.risk_distribution?.low || 0}
            medium={drift.risk_distribution?.medium || 0}
            high={drift.risk_distribution?.high || 0}
            testId={`${testId}-drift`}
          />
        </div>

        {/* Expanded: Hotspots */}
        {expanded && (
          <div className="pt-2 border-t border-border" data-testid={`${testId}-hotspots`}>
            <p className="text-xs font-medium text-muted-foreground mb-2 uppercase tracking-wider">
              Top Friction {entityLabel}s
            </p>
            {hotspots.length === 0 ? (
              <p className="text-xs text-muted-foreground py-2">No friction hotspots detected yet</p>
            ) : (
              <div className="space-y-2">
                {hotspots.map((h, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded-md bg-accent/30">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-xs font-mono text-muted-foreground w-4">{i + 1}.</span>
                      <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{h.entity_name || h.entity_id}</p>
                        <p className="text-[10px] text-muted-foreground">{h.feedback_count} reviews, {h.incorrect_count} disagreements</p>
                      </div>
                    </div>
                    <Badge variant={h.disagree_rate > 50 ? "destructive" : h.disagree_rate > 25 ? "secondary" : "outline"} className="text-[10px] shrink-0">
                      {h.disagree_rate}%
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function GovernanceDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/governance/dashboard`);
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error('[Governance] Fetch failed:', err);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRefresh = () => {
    setRefreshing(true);
    fetchData();
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="governance-loading">
        <RefreshCw className="w-5 h-5 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">Loading governance data...</span>
      </div>
    );
  }

  const sys = data?.system_health || {};
  const cd = data?.combined_drift || {};

  return (
    <div className="space-y-6 max-w-7xl mx-auto" data-testid="governance-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Satoshi, sans-serif' }} data-testid="governance-title">
            Governance Dashboard
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Cross-pipeline learning, drift controls, and system health
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium border border-border hover:bg-accent transition-colors disabled:opacity-50"
          data-testid="governance-refresh-btn"
        >
          <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* System Health Strip */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" data-testid="system-health-strip">
        <StatCard icon={FileCheck} label="Total Docs" value={sys.total_documents} accent="slate" testId="stat-total-docs" />
        <StatCard icon={Clock} label="Pending" value={sys.pending_review} accent={sys.pending_review > 20 ? "red" : sys.pending_review > 5 ? "amber" : "emerald"} testId="stat-pending" />
        <StatCard icon={CheckCircle2} label="Completed" value={sys.completed} accent="emerald" testId="stat-completed" />
        <StatCard icon={ArrowUpRight} label="Posted 7d" value={sys.posted_to_bc_7d} accent="blue" testId="stat-posted-7d" />
        <StatCard icon={Package} label="Ready" value={sys.ready_to_post} accent="violet" testId="stat-ready" />
        <StatCard icon={Users} label="Vendor Profiles" value={sys.vendor_profiles} accent="blue" testId="stat-vendor-profiles" />
        <StatCard icon={TrendingUp} label="Auto Rate" value={`${sys.automation_rate}%`} accent={sys.automation_rate >= 50 ? "emerald" : sys.automation_rate >= 25 ? "amber" : "red"} testId="stat-auto-rate" />
      </div>

      {/* Combined Drift — Front and Center */}
      <Card className="border border-border" data-testid="combined-drift-card">
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <BarChart3 className="w-4 h-4" />
            Combined Drift Risk Distribution
            <Badge variant="outline" className="ml-2 text-[10px]">SO + AP</Badge>
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Tracks how aggressively profiles are being modified across both pipelines
          </p>
        </CardHeader>
        <CardContent>
          <DriftBar low={cd.low || 0} medium={cd.medium || 0} high={cd.high || 0} testId="combined-drift-bar" />
        </CardContent>
      </Card>

      {/* Pipeline Cards — Side by Side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4" data-testid="pipeline-cards">
        <PipelineCard
          title="Sales Orders"
          icon={Shield}
          data={data?.sales_orders}
          entityLabel="Customer"
          testId="so-pipeline"
        />
        <PipelineCard
          title="AP Invoices"
          icon={Package}
          data={data?.ap_invoices}
          entityLabel="Vendor"
          testId="ap-pipeline"
        />
      </div>

      {/* Actionable Summary */}
      {(data?.sales_orders?.suggestions?.total_actionable > 0 || data?.ap_invoices?.suggestions?.total_actionable > 0) && (
        <Card className="border-l-4 border-l-amber-500 bg-amber-500/5" data-testid="action-needed-card">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-amber-500 shrink-0" />
            <div>
              <p className="text-sm font-medium">
                {(data.sales_orders.suggestions.total_actionable || 0) + (data.ap_invoices.suggestions.total_actionable || 0)} suggestion(s) need attention
              </p>
              <p className="text-xs text-muted-foreground">
                {data.sales_orders.suggestions.total_actionable > 0 && `${data.sales_orders.suggestions.total_actionable} SO`}
                {data.sales_orders.suggestions.total_actionable > 0 && data.ap_invoices.suggestions.total_actionable > 0 && ' + '}
                {data.ap_invoices.suggestions.total_actionable > 0 && `${data.ap_invoices.suggestions.total_actionable} AP`}
                {' '}— review in AI Learning page
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Timestamp */}
      {data?.generated_at && (
        <p className="text-[10px] text-muted-foreground text-right font-mono" data-testid="governance-timestamp">
          Last updated: {new Date(data.generated_at).toLocaleString()}
        </p>
      )}
    </div>
  );
}
