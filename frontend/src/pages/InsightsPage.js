import { useState, useEffect } from 'react';
import { Badge } from '@/components/ui/badge';
import {
  LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend, Area, AreaChart,
} from 'recharts';
import {
  TrendingUp, ShieldCheck, Brain, Zap, BarChart3,
  RefreshCw, Calendar,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import api from '@/lib/api';

const CHART_COLORS = {
  ingested: '#38bdf8',       // sky-400
  autoRate: '#22c55e',       // green-500
  confidence: '#a78bfa',     // violet-400
  vendorResolve: '#fb923c',  // orange-400
  validation: '#facc15',     // yellow-400
  exception: '#ef4444',      // red-500
};

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr + 'T00:00:00');
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function StatCard({ icon: Icon, label, value, sub, color }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg border border-border/60 bg-muted/10" data-testid={`insight-stat-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <Icon className={`w-4 h-4 ${color}`} />
      <div>
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide">{label}</div>
        <div className="text-lg font-semibold text-foreground">{value}</div>
        {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
      </div>
    </div>
  );
}

function ChartTooltipContent({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-zinc-900 border border-border/60 rounded-lg px-3 py-2 text-xs shadow-xl">
      <div className="font-medium text-foreground mb-1">{formatDate(label)}</div>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 text-muted-foreground">
          <div className="w-2 h-2 rounded-full" style={{ backgroundColor: entry.color }} />
          <span>{entry.name}:</span>
          <span className="font-medium text-foreground">
            {entry.name.includes('%') || entry.name.includes('Rate') || entry.name.includes('Confidence')
              ? `${entry.value}%`
              : entry.value}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function InsightsPage() {
  const [trends, setTrends] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState(30);

  useEffect(() => {
    const fetchTrends = async () => {
      setLoading(true);
      try {
        const res = await api.get(`/dashboard/insights-trends?days=${days}`);
        setTrends(res.data);
      } catch (err) {
        console.error('Failed to load insights:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchTrends();
  }, [days]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64 text-muted-foreground text-sm" data-testid="insights-loading">
        <RefreshCw className="w-4 h-4 animate-spin mr-2" /> Loading insights...
      </div>
    );
  }

  const daily = trends?.daily || [];
  const bakeoff = trends?.bakeoff_runs || [];

  // Compute summary from latest data
  const latest = daily[daily.length - 1] || {};
  const totalIngested = daily.reduce((sum, d) => sum + d.ingested, 0);
  const avgAutoRate = daily.length > 0
    ? (daily.reduce((sum, d) => sum + d.auto_rate, 0) / daily.length).toFixed(1)
    : '0';
  const avgConfidence = daily.length > 0
    ? (daily.reduce((sum, d) => sum + d.ai_confidence, 0) / daily.length).toFixed(1)
    : '0';
  const avgVendorRate = daily.length > 0
    ? (daily.reduce((sum, d) => sum + d.vendor_resolve_rate, 0) / daily.length).toFixed(1)
    : '0';

  return (
    <div className="space-y-6" data-testid="insights-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Processing Insights</h2>
          <p className="text-sm text-muted-foreground mt-0.5">AI learning trends and automation performance</p>
        </div>
        <div className="flex items-center gap-2">
          {[7, 14, 30].map(d => (
            <Button
              key={d}
              variant={days === d ? 'default' : 'outline'}
              size="sm"
              className="h-7 text-xs"
              onClick={() => setDays(d)}
              data-testid={`period-${d}d`}
            >
              {d}d
            </Button>
          ))}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard icon={BarChart3} label="Total Ingested" value={totalIngested} sub={`${days}-day period`} color="text-sky-400" />
        <StatCard icon={ShieldCheck} label="Avg Auto Rate" value={`${avgAutoRate}%`} sub="auto-validated" color="text-emerald-400" />
        <StatCard icon={Brain} label="Avg AI Confidence" value={`${avgConfidence}%`} sub="classification" color="text-violet-400" />
        <StatCard icon={Zap} label="Vendor Resolve" value={`${avgVendorRate}%`} sub="auto-resolved" color="text-orange-400" />
      </div>

      {daily.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground text-sm border border-border/60 rounded-lg">
          <Calendar className="w-8 h-8 mx-auto mb-2 opacity-30" />
          No processing data yet for this period.
          <br />
          <span className="text-xs">Documents will appear here as they're ingested and processed.</span>
        </div>
      ) : (
        <>
          {/* Ingestion Volume Chart */}
          <div className="border border-border/60 rounded-lg p-4" data-testid="chart-ingestion">
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-sky-400" />
              Daily Ingestion Volume
            </h3>
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={daily} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11, fill: '#71717a' }} axisLine={false} tickLine={false} />
                <YAxis tick={{ fontSize: 11, fill: '#71717a' }} axisLine={false} tickLine={false} />
                <Tooltip content={<ChartTooltipContent />} />
                <Bar dataKey="ingested" name="Documents" fill={CHART_COLORS.ingested} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Automation & AI Learning Trends */}
          <div className="border border-border/60 rounded-lg p-4" data-testid="chart-automation">
            <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
              <ShieldCheck className="w-4 h-4 text-emerald-400" />
              Automation & AI Learning Trends
            </h3>
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={daily} margin={{ top: 5, right: 10, left: 0, bottom: 5 }}>
                <defs>
                  <linearGradient id="gradAuto" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART_COLORS.autoRate} stopOpacity={0.2} />
                    <stop offset="100%" stopColor={CHART_COLORS.autoRate} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradConf" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART_COLORS.confidence} stopOpacity={0.2} />
                    <stop offset="100%" stopColor={CHART_COLORS.confidence} stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="gradVendor" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={CHART_COLORS.vendorResolve} stopOpacity={0.2} />
                    <stop offset="100%" stopColor={CHART_COLORS.vendorResolve} stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="date" tickFormatter={formatDate} tick={{ fontSize: 11, fill: '#71717a' }} axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} tick={{ fontSize: 11, fill: '#71717a' }} axisLine={false} tickLine={false} tickFormatter={v => `${v}%`} />
                <Tooltip content={<ChartTooltipContent />} />
                <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }} />
                <Area type="monotone" dataKey="auto_rate" name="Auto-Validation Rate" stroke={CHART_COLORS.autoRate} fill="url(#gradAuto)" strokeWidth={2} dot={{ r: 3 }} />
                <Area type="monotone" dataKey="ai_confidence" name="AI Confidence" stroke={CHART_COLORS.confidence} fill="url(#gradConf)" strokeWidth={2} dot={{ r: 3 }} />
                <Area type="monotone" dataKey="vendor_resolve_rate" name="Vendor Resolve Rate" stroke={CHART_COLORS.vendorResolve} fill="url(#gradVendor)" strokeWidth={2} dot={{ r: 3 }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </>
      )}

      {/* Bakeoff / S9 Comparison */}
      {bakeoff.length > 0 && (
        <div className="border border-border/60 rounded-lg p-4" data-testid="chart-bakeoff">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Zap className="w-4 h-4 text-yellow-400" />
            S9 vs GPI Routing Accuracy (Benchmark Runs)
          </h3>
          <div className="space-y-2">
            {bakeoff.map((run) => {
              const pct = run.summary?.folder_accuracy_pct ?? 0;
              const docs = run.summary?.total_docs ?? 0;
              return (
                <div key={run.id} className="flex items-center gap-3 text-sm" data-testid={`bakeoff-run-${run.id}`}>
                  <span className="text-xs text-muted-foreground w-20 shrink-0 truncate">{run.name}</span>
                  <div className="flex-1 h-2 bg-muted/30 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all"
                      style={{
                        width: `${pct}%`,
                        backgroundColor: pct >= 95 ? CHART_COLORS.autoRate : pct >= 80 ? CHART_COLORS.vendorResolve : CHART_COLORS.exception,
                      }}
                    />
                  </div>
                  <Badge className={`text-[10px] px-1.5 py-0 ${pct >= 95 ? 'bg-emerald-500/15 text-emerald-400' : pct >= 80 ? 'bg-amber-500/15 text-amber-400' : 'bg-red-500/15 text-red-400'}`}>
                    {pct}%
                  </Badge>
                  <span className="text-[10px] text-muted-foreground">{docs} docs</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
