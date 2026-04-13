import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { ScrollArea } from '../components/ui/scroll-area';
import {
  ArrowLeftRight, ChevronLeft, ChevronRight, Loader2,
  CheckCircle2, XCircle, AlertTriangle, FileText, Search,
  Layers, Target, Play, Clock, TrendingUp, BarChart3
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const VERDICT_STYLE = {
  MATCH: 'bg-emerald-500/10 text-emerald-600 border-emerald-300',
  MISMATCH: 'bg-red-500/10 text-red-600 border-red-300',
  CLOSE: 'bg-amber-500/10 text-amber-600 border-amber-300',
  GAP: 'bg-orange-500/10 text-orange-600 border-orange-300',
};

const VERDICT_ICON = {
  MATCH: CheckCircle2,
  MISMATCH: XCircle,
  CLOSE: AlertTriangle,
  GAP: AlertTriangle,
};

function VerdictBadge({ verdict }) {
  const Icon = VERDICT_ICON[verdict] || AlertTriangle;
  return (
    <Badge variant="outline" className={`text-xs font-mono ${VERDICT_STYLE[verdict] || ''}`} data-testid={`verdict-${verdict}`}>
      <Icon className="w-3 h-3 mr-1" />{verdict}
    </Badge>
  );
}

function LineRow({ line, side }) {
  const bg = side === 'human' ? 'bg-blue-500/5' : 'bg-violet-500/5';
  return (
    <div className={`flex items-start gap-2 py-2 px-3 rounded-md ${bg} text-sm`} data-testid={`line-${side}`}>
      <Badge variant="outline" className="text-[10px] shrink-0 mt-0.5 font-mono">
        {line.line_type || '—'}
      </Badge>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          {line.item_or_account && (
            <span className="font-mono text-xs font-semibold">{line.item_or_account}</span>
          )}
          {line.description && (
            <span className="text-muted-foreground truncate text-xs">{line.description}</span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
          <span>Qty: {line.quantity}</span>
          <span>Unit: ${Number(line.unit_cost || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
          <span className="font-semibold text-foreground">
            Net: ${Number(line.net_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}
          </span>
          {line.tax_code && <span>Tax: {line.tax_code}</span>}
          {line.uom && <span>UOM: {line.uom}</span>}
        </div>
      </div>
    </div>
  );
}

function DimensionScoreBar({ name, score, weight }) {
  const color = score >= 80 ? 'bg-emerald-500' : score >= 50 ? 'bg-amber-500' : 'bg-red-500';
  const label = name.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
  return (
    <div className="flex items-center gap-3 py-1" data-testid={`dim-score-${name}`}>
      <span className="text-xs w-28 shrink-0 text-muted-foreground">{label}</span>
      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="text-xs font-mono w-12 text-right font-semibold">{score}%</span>
      <span className="text-[10px] text-muted-foreground w-10 text-right">w:{weight}%</span>
    </div>
  );
}

function LineAlignmentRow({ pair }) {
  const score = pair.score || 0;
  const color = score >= 80 ? 'text-emerald-500' : score >= 50 ? 'text-amber-500' : 'text-red-500';
  const bg = score >= 80 ? 'bg-emerald-500/5' : score >= 50 ? 'bg-amber-500/5' : 'bg-red-500/5';
  return (
    <div className={`flex items-center gap-3 py-2 px-3 rounded-md ${bg} text-xs`} data-testid={`alignment-pair-${pair.human_idx}`}>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-mono font-semibold text-blue-600">{pair.human_item || '—'}</span>
          <span className="text-muted-foreground truncate">{pair.human_desc}</span>
        </div>
        <span className="text-muted-foreground">${Number(pair.human_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
      </div>
      <div className="shrink-0 text-center w-14">
        <span className={`font-bold text-sm ${color}`}>{score}%</span>
      </div>
      <div className="flex-1 min-w-0 text-right">
        <div className="flex items-center gap-1.5 justify-end">
          <span className="text-muted-foreground truncate">{pair.ai_desc}</span>
          <span className="font-mono font-semibold text-violet-600">{pair.ai_item || '—'}</span>
        </div>
        <span className="text-muted-foreground">${Number(pair.ai_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
      </div>
    </div>
  );
}

function ComparisonRow({ item }) {
  return (
    <div className="flex items-center gap-3 py-2 px-3 border-b border-border/40" data-testid={`comparison-${item.dimension}`}>
      <VerdictBadge verdict={item.verdict} />
      <span className="text-sm font-medium w-40 shrink-0">{item.dimension}</span>
      {item.value ? (
        <span className="text-sm text-muted-foreground flex-1">{item.value}</span>
      ) : (
        <div className="flex-1 flex items-center gap-4 text-sm">
          <div className="flex-1">
            <span className="text-blue-600 font-mono text-xs">Human: </span>
            <span className="text-muted-foreground">{item.human || '—'}</span>
          </div>
          <ArrowLeftRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          <div className="flex-1">
            <span className="text-violet-600 font-mono text-xs">AI: </span>
            <span className="text-muted-foreground">{item.ai || '—'}</span>
          </div>
        </div>
      )}
      {item.note && <span className="text-[10px] text-muted-foreground italic shrink-0 max-w-48 text-right">{item.note}</span>}
    </div>
  );
}

/* ─── Match-rate pill ─── */
function MatchPill({ rate }) {
  if (rate == null) return <span className="text-xs text-muted-foreground">—</span>;
  const color = rate >= 80 ? 'bg-emerald-500/15 text-emerald-600' : rate >= 50 ? 'bg-amber-500/15 text-amber-600' : 'bg-red-500/15 text-red-600';
  return <span className={`text-xs font-mono font-bold px-2 py-0.5 rounded-full ${color}`}>{rate}%</span>;
}

/* ─── SVG Sparkline ─── */
function Sparkline({ points, width = 260, height = 48 }) {
  if (!points || points.length < 2) return null;
  const rates = points.map(p => p.avg_match_rate);
  const max = Math.max(...rates, 100);
  const min = Math.min(...rates, 0);
  const range = max - min || 1;
  const step = width / (rates.length - 1);
  const coords = rates.map((v, i) => ({
    x: i * step,
    y: height - ((v - min) / range) * (height - 4) - 2,
  }));
  const pathD = coords.map((c, i) => `${i === 0 ? 'M' : 'L'}${c.x.toFixed(1)},${c.y.toFixed(1)}`).join(' ');
  const areaD = `${pathD} L${width},${height} L0,${height} Z`;
  const last = coords[coords.length - 1];
  const lastRate = rates[rates.length - 1];
  const dotColor = lastRate >= 80 ? '#10b981' : lastRate >= 50 ? '#f59e0b' : '#ef4444';

  return (
    <svg width={width} height={height} className="overflow-visible" data-testid="trend-sparkline">
      <defs>
        <linearGradient id="sparkFill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={dotColor} stopOpacity="0.15" />
          <stop offset="100%" stopColor={dotColor} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaD} fill="url(#sparkFill)" />
      <path d={pathD} fill="none" stroke={dotColor} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      <circle cx={last.x} cy={last.y} r="3" fill={dotColor} />
    </svg>
  );
}

/* ─── Vendor Leaderboard Row ─── */
function LeaderRow({ v, rank, onClick }) {
  const color = v.avg_match_rate >= 80 ? 'text-emerald-500' : v.avg_match_rate >= 50 ? 'text-amber-500' : 'text-red-500';
  return (
    <div
      className="flex items-center gap-3 py-1.5 px-2 rounded hover:bg-muted/50 cursor-pointer transition-colors text-xs"
      onClick={() => onClick(v.vendor_no)}
      data-testid={`leader-${v.vendor_no}`}
    >
      <span className="text-muted-foreground w-5 text-right font-mono">{rank}</span>
      <span className="font-mono font-semibold text-blue-600 w-16 shrink-0">{v.vendor_no}</span>
      <span className="flex-1 truncate text-muted-foreground">{v.vendor_name}</span>
      <span className={`font-mono font-bold w-10 text-right ${color}`}>{v.avg_match_rate}%</span>
      <span className="text-muted-foreground w-8 text-right">{v.traces_count}x</span>
    </div>
  );
}

/* ─── ELT Summary Banner — the one number for the executive pitch ─── */
function ELTSummaryBanner() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/posting-patterns/daily-trace/trend?days=90`);
        const d = await res.json();
        setData(d);
      } catch { /* ignore */ }
      setLoading(false);
    })();
  }, []);

  if (loading) return null;
  if (!data || !data.points || data.points.length === 0) return null;

  const overallAvg = data.overall_avg || 0;
  const leaders = data.vendor_leaderboard || [];
  const above80 = leaders.filter(v => v.avg_match_rate >= 80).length;
  const above95 = leaders.filter(v => v.avg_match_rate >= 95).length;
  const totalVendors = leaders.length;
  const dataPoints = data.data_points || 0;
  const totalTraced = data.points.reduce((s, p) => s + (p.traced || 0), 0);

  const avgColor = overallAvg >= 80 ? 'text-emerald-500' : overallAvg >= 50 ? 'text-amber-500' : 'text-red-500';
  const avgBg = overallAvg >= 80 ? 'from-emerald-500/5 to-emerald-500/0' : overallAvg >= 50 ? 'from-amber-500/5 to-amber-500/0' : 'from-red-500/5 to-red-500/0';

  return (
    <div className={`rounded-xl border border-border/40 bg-gradient-to-r ${avgBg} p-6`} data-testid="elt-summary-banner">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-8">
          <div className="text-center">
            <p className={`text-5xl font-bold tracking-tight ${avgColor}`}>{overallAvg}%</p>
            <p className="text-xs text-muted-foreground mt-1 font-medium">AI Match Rate</p>
          </div>
          <div className="border-l border-border/40 pl-8 space-y-1">
            <p className="text-sm font-medium">AI replicates human posting at <span className={`font-bold ${avgColor}`}>{overallAvg}%</span> accuracy</p>
            <p className="text-xs text-muted-foreground">
              Across <strong>{totalVendors}</strong> vendors, <strong>{totalTraced}</strong> invoices traced over <strong>{dataPoints}</strong> daily runs
            </p>
            {above95 > 0 && (
              <p className="text-xs text-emerald-600 font-medium">
                {above95} vendor{above95 > 1 ? 's' : ''} at 95%+ match — production-ready for automation
              </p>
            )}
            {above80 > above95 && (
              <p className="text-xs text-blue-600 font-medium">
                {above80} vendor{above80 > 1 ? 's' : ''} at 80%+ match — ready to replace manual posting
              </p>
            )}
          </div>
        </div>
        <div className="text-right text-xs text-muted-foreground">
          <p>PROD BC vs AI Template</p>
          <p>Last 90 days</p>
        </div>
      </div>
    </div>
  );
}


/* ─── Daily Trace Feed ─── */
function DailyTraceFeed({ onSelectVendor }) {
  const [latestRun, setLatestRun] = useState(null);
  const [trend, setTrend] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [showLeaderboard, setShowLeaderboard] = useState(false);

  const fetchData = async () => {
    try {
      const [latestRes, trendRes] = await Promise.all([
        fetch(`${API}/api/posting-patterns/daily-trace/latest`),
        fetch(`${API}/api/posting-patterns/daily-trace/trend?days=30`),
      ]);
      const latestData = await latestRes.json();
      const trendData = await trendRes.json();
      if (!latestData.error) setLatestRun(latestData);
      if (trendData.points) setTrend(trendData);
    } catch { /* ignore */ }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  const handleRunNow = async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/daily-trace/run?sync=true&count=15`, { method: 'POST' });
      const data = await res.json();
      if (!data.error) setLatestRun(data);
      // Refresh trend after new run
      const trendRes = await fetch(`${API}/api/posting-patterns/daily-trace/trend?days=30`);
      const trendData = await trendRes.json();
      if (trendData.points) setTrend(trendData);
    } catch { /* ignore */ }
    setRunning(false);
  };

  const results = latestRun?.results || [];
  const successResults = results.filter(r => r.match_rate != null);
  const avgMatch = latestRun?.avg_match_rate || 0;
  const matchColor = avgMatch >= 80 ? 'text-emerald-500' : avgMatch >= 50 ? 'text-amber-500' : 'text-red-500';

  return (
    <Card data-testid="daily-trace-feed">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <BarChart3 className="w-4 h-4 text-muted-foreground" />
            Daily Trace Feed
            <span className="text-[10px] font-normal text-muted-foreground">PROD vs AI Template (last 3 months)</span>
            {latestRun && (
              <Badge variant="outline" className="text-[10px] ml-1">
                <Clock className="w-3 h-3 mr-1" />
                {new Date(latestRun.run_date).toLocaleDateString()} {new Date(latestRun.run_date).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Badge>
            )}
          </CardTitle>
          <Button size="sm" variant="outline" onClick={handleRunNow} disabled={running} className="h-8" data-testid="run-daily-trace-btn">
            {running ? <Loader2 className="w-4 h-4 animate-spin mr-1" /> : <Play className="w-4 h-4 mr-1" />}
            {running ? 'Running...' : 'Run Now'}
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        {loading && (
          <div className="flex items-center justify-center py-8">
            <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
          </div>
        )}

        {!loading && !latestRun && (
          <div className="text-center py-8 text-sm text-muted-foreground">
            <p>No daily traces yet. Click <strong>Run Now</strong> to generate your first batch.</p>
            <p className="text-xs mt-1">Traces also run automatically every 24 hours.</p>
          </div>
        )}

        {!loading && latestRun && (
          <>
            {/* Summary strip + Trend */}
            <div className="flex items-center gap-6 mb-4 pb-3 border-b border-border/40">
              <div className="text-center">
                <p className={`text-2xl font-bold ${matchColor}`}>{avgMatch}%</p>
                <p className="text-[10px] text-muted-foreground">Avg Match</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold">{successResults.length}</p>
                <p className="text-[10px] text-muted-foreground">Traced</p>
              </div>
              <div className="text-center">
                <p className="text-lg font-bold text-red-500">{results.filter(r => r.error).length}</p>
                <p className="text-[10px] text-muted-foreground">Errors</p>
              </div>
              {/* Sparkline trend */}
              {trend && trend.points && trend.points.length >= 2 && (
                <div className="flex-1 flex flex-col items-center gap-0.5">
                  <Sparkline points={trend.points} width={220} height={36} />
                  <span className="text-[9px] text-muted-foreground">{trend.data_points}-day trend (overall avg: {trend.overall_avg}%)</span>
                </div>
              )}
              {!trend || !trend.points || trend.points.length < 2 ? (
                <div className="flex-1 text-right">
                  <div className="flex items-center gap-1.5 justify-end text-xs text-muted-foreground">
                    <TrendingUp className="w-3.5 h-3.5" />
                    <span>{latestRun.prod_invoices_scanned || latestRun.traces_requested} PROD PIs scanned{latestRun.cutoff_date ? ` (since ${latestRun.cutoff_date})` : ''}</span>
                  </div>
                  <p className="text-[10px] text-muted-foreground mt-0.5">Trend chart appears after 2+ daily runs</p>
                </div>
              ) : null}
              {/* Leaderboard toggle */}
              {trend && trend.vendor_leaderboard && trend.vendor_leaderboard.length > 0 && (
                <Button
                  size="sm" variant="ghost" className="h-7 text-xs"
                  onClick={() => setShowLeaderboard(!showLeaderboard)}
                  data-testid="toggle-leaderboard-btn"
                >
                  <TrendingUp className="w-3.5 h-3.5 mr-1" />
                  {showLeaderboard ? 'Hide' : 'Top Vendors'}
                </Button>
              )}
            </div>

            {/* Vendor Leaderboard (collapsible) */}
            {showLeaderboard && trend?.vendor_leaderboard && (
              <div className="mb-4 pb-3 border-b border-border/40" data-testid="vendor-leaderboard">
                <p className="text-xs font-semibold text-muted-foreground mb-2 px-2">Vendor Performance (30-day window)</p>
                <ScrollArea className="max-h-[200px]">
                  {trend.vendor_leaderboard.map((v, i) => (
                    <LeaderRow key={v.vendor_no} v={v} rank={i + 1} onClick={onSelectVendor} />
                  ))}
                </ScrollArea>
              </div>
            )}

            {/* Results table */}
            <ScrollArea className="max-h-[350px]">
              <div className="space-y-1" data-testid="daily-trace-results">
                {results.map((r, i) => (
                  <div
                    key={i}
                    className="flex items-center gap-3 py-2 px-3 rounded-md hover:bg-muted/50 cursor-pointer transition-colors text-sm"
                    onClick={() => r.vendor_no && onSelectVendor(r.vendor_no)}
                    data-testid={`daily-trace-row-${i}`}
                  >
                    <span className="font-mono text-xs font-semibold w-20 shrink-0 text-blue-600">{r.vendor_no}</span>
                    <span className="flex-1 min-w-0 truncate text-muted-foreground text-xs">{r.vendor_name || r.vendor_no}</span>
                    <span className="text-xs text-muted-foreground w-24 shrink-0 truncate">{r.invoice_number || '—'}</span>
                    <span className="text-xs text-muted-foreground w-20 shrink-0">{r.invoice_date ? new Date(r.invoice_date).toLocaleDateString() : '—'}</span>
                    <span className="text-xs font-mono w-20 shrink-0 text-right">
                      {r.total_amount != null ? `$${Number(r.total_amount).toLocaleString(undefined, { minimumFractionDigits: 0 })}` : '—'}
                    </span>
                    {r.has_template ? (
                      <Badge variant="outline" className="text-[9px] border-emerald-300 text-emerald-600 w-8 justify-center shrink-0">T</Badge>
                    ) : (
                      <span className="w-8 shrink-0" />
                    )}
                    <div className="w-14 shrink-0 text-center">
                      {r.error ? (
                        <Badge variant="outline" className="text-[9px] text-red-500 border-red-200">ERR</Badge>
                      ) : (
                        <MatchPill rate={r.match_rate} />
                      )}
                    </div>
                    <span className="text-xs w-8 shrink-0 text-muted-foreground text-right">{r.human_line_count || 0}L</span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </>
        )}
      </CardContent>
    </Card>
  );
}


export default function InvoiceTracePage() {
  const [vendorNo, setVendorNo] = useState('TUMALOC');
  const [invoiceIndex, setInvoiceIndex] = useState(0);
  const [trace, setTrace] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const fetchTrace = useCallback(async (vendor, idx) => {
    setLoading(true);
    setError('');
    try {
      const res = await fetch(`${API}/api/posting-patterns/trace/${vendor}?invoice_index=${idx}`);
      const data = await res.json();
      if (data.error) {
        setError(data.error);
        setTrace(null);
      } else {
        setTrace(data);
      }
    } catch (e) {
      setError(e.message);
      setTrace(null);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchTrace(vendorNo, invoiceIndex);
  }, []);

  const handleSearch = () => {
    setInvoiceIndex(0);
    fetchTrace(vendorNo, 0);
  };

  const handleSelectVendor = (vno) => {
    setVendorNo(vno);
    setInvoiceIndex(0);
    fetchTrace(vno, 0);
  };

  const handlePrev = () => {
    const newIdx = Math.max(0, invoiceIndex - 1);
    setInvoiceIndex(newIdx);
    fetchTrace(vendorNo, newIdx);
  };

  const handleNext = () => {
    const max = (trace?.total_invoices_available || 1) - 1;
    const newIdx = Math.min(max, invoiceIndex + 1);
    setInvoiceIndex(newIdx);
    fetchTrace(vendorNo, newIdx);
  };

  const comp = trace?.comparison || {};
  const matchRate = comp.match_rate || 0;
  const matchColor = matchRate >= 80 ? 'text-emerald-500' : matchRate >= 60 ? 'text-amber-500' : 'text-red-500';

  return (
    <div className="space-y-6 max-w-7xl mx-auto" data-testid="invoice-trace-page">
      {/* Header & Search */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Invoice Trace</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Side-by-side: how humans posted vs how the AI would post
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Input
            value={vendorNo}
            onChange={e => setVendorNo(e.target.value.toUpperCase())}
            placeholder="Vendor No..."
            className="w-40 h-9 font-mono text-sm"
            onKeyDown={e => e.key === 'Enter' && handleSearch()}
            data-testid="vendor-search-input"
          />
          <Button size="sm" onClick={handleSearch} disabled={loading} data-testid="trace-search-btn">
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
          </Button>
        </div>
      </div>

      {/* Executive Summary — The one number that matters */}
      <ELTSummaryBanner />

      {/* Daily Trace Feed */}
      <DailyTraceFeed onSelectVendor={handleSelectVendor} />

      {error && (
        <Card className="border-red-200 bg-red-500/5">
          <CardContent className="py-4 text-sm text-red-600" data-testid="trace-error">
            {error}
          </CardContent>
        </Card>
      )}

      {trace && !error && (
        <>
          {/* Invoice Navigator */}
          <Card>
            <CardContent className="py-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <FileText className="w-5 h-5 text-muted-foreground" />
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="font-semibold text-sm">{trace.vendor_name}</span>
                      <span className="font-mono text-xs text-muted-foreground">{trace.vendor_no}</span>
                    </div>
                    <div className="flex items-center gap-3 text-xs text-muted-foreground mt-0.5">
                      <span>Invoice #{trace.invoice?.vendor_invoice_number || trace.invoice?.number}</span>
                      <span>{trace.invoice?.invoice_date}</span>
                      <span className="font-semibold">${Number(trace.invoice?.total_excl_tax || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                      <Badge variant="outline" className="text-[10px]">{trace.invoice?.status}</Badge>
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <Button size="sm" variant="outline" className="h-8" onClick={handlePrev} disabled={invoiceIndex <= 0 || loading} data-testid="trace-prev-btn">
                    <ChevronLeft className="w-4 h-4" />
                  </Button>
                  <span className="text-xs font-mono text-muted-foreground" data-testid="trace-index">
                    {invoiceIndex + 1} / {trace.total_invoices_available}
                  </span>
                  <Button size="sm" variant="outline" className="h-8" onClick={handleNext} disabled={invoiceIndex >= (trace.total_invoices_available || 1) - 1 || loading} data-testid="trace-next-btn">
                    <ChevronRight className="w-4 h-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Match Rate */}
          <Card>
            <CardContent className="py-5">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-4">
                  <div className={`text-4xl font-bold tracking-tight ${matchColor}`} data-testid="match-rate">
                    {matchRate}%
                  </div>
                  <div>
                    <p className="text-sm font-medium">Match Rate</p>
                    <p className="text-xs text-muted-foreground">{comp.verdict}</p>
                  </div>
                </div>
                <div className="flex items-center gap-6 text-sm">
                  <div className="text-center">
                    <p className="text-lg font-bold text-emerald-500" data-testid="match-count">{(comp.matches || []).length}</p>
                    <p className="text-[10px] text-muted-foreground">Matches</p>
                  </div>
                  <div className="text-center">
                    <p className="text-lg font-bold text-red-500" data-testid="mismatch-count">{(comp.mismatches || []).length}</p>
                    <p className="text-[10px] text-muted-foreground">Mismatches</p>
                  </div>
                  <div className="text-center">
                    <p className="text-lg font-bold text-orange-500" data-testid="gap-count">{(comp.gaps || []).length}</p>
                    <p className="text-[10px] text-muted-foreground">Gaps</p>
                  </div>
                </div>
                <div className="text-right text-xs text-muted-foreground">
                  <p>Template: <span className="font-semibold">{trace.ai_would_post?.template_confidence?.toUpperCase()}</span></p>
                  <p>Based on {trace.profile_invoices_studied} invoices studied</p>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Dimension Scores Breakdown */}
          {comp.dimension_scores && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <Target className="w-4 h-4 text-muted-foreground" />
                  Weighted Dimension Scores
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1" data-testid="dimension-scores">
                  {Object.entries(comp.dimension_scores).map(([name, data]) => (
                    <DimensionScoreBar key={name} name={name} score={data.score} weight={data.weight} />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Dimension-by-Dimension Comparison */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Dimension-by-Dimension Comparison</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="max-h-[400px]">
                {(comp.matches || []).map((m, i) => <ComparisonRow key={`m-${i}`} item={m} />)}
                {(comp.mismatches || []).map((m, i) => <ComparisonRow key={`mm-${i}`} item={m} />)}
                {(comp.gaps || []).map((g, i) => (
                  <div key={`g-${i}`} className="flex items-center gap-3 py-2 px-3 border-b border-border/40" data-testid={`gap-${g.dimension}`}>
                    <VerdictBadge verdict="GAP" />
                    <span className="text-sm font-medium w-40 shrink-0">{g.dimension}</span>
                    <span className="text-xs text-muted-foreground italic">{g.note}</span>
                  </div>
                ))}
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Line-by-Line Alignment */}
          {comp.line_alignment && comp.line_alignment.pairs && comp.line_alignment.pairs.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <Layers className="w-4 h-4 text-muted-foreground" />
                  Line-by-Line Alignment
                  <Badge variant="outline" className="ml-2 text-[10px]">
                    Avg: {comp.line_alignment.avg_score}%
                  </Badge>
                  {comp.line_alignment.unmatched_human > 0 && (
                    <Badge variant="outline" className="text-[10px] text-orange-600 border-orange-300">
                      +{comp.line_alignment.unmatched_human} unmatched human
                    </Badge>
                  )}
                  {comp.line_alignment.unmatched_ai > 0 && (
                    <Badge variant="outline" className="text-[10px] text-orange-600 border-orange-300">
                      +{comp.line_alignment.unmatched_ai} unmatched AI
                    </Badge>
                  )}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-1.5 text-xs mb-2 text-muted-foreground">
                  <div className="flex items-center gap-6 px-3 font-semibold">
                    <span className="flex-1 text-blue-600">Human Line</span>
                    <span className="w-14 text-center">Score</span>
                    <span className="flex-1 text-right text-violet-600">AI Line</span>
                  </div>
                </div>
                <ScrollArea className="max-h-[400px]">
                  <div className="space-y-1" data-testid="line-alignment">
                    {comp.line_alignment.pairs.map((pair, i) => (
                      <LineAlignmentRow key={i} pair={pair} />
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          )}

          {/* Side-by-Side Lines */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {/* Human Lines */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-blue-500" />
                  Human Posted ({trace.human_posted?.line_count || 0} lines)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="max-h-[500px]">
                  <div className="space-y-1.5" data-testid="human-lines">
                    {(trace.human_posted?.lines || []).length === 0 && (
                      <p className="text-xs text-muted-foreground py-4 text-center">No line data available</p>
                    )}
                    {(trace.human_posted?.lines || []).map((l, i) => (
                      <LineRow key={i} line={l} side="human" />
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>

            {/* AI Lines */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base flex items-center gap-2">
                  <div className="w-2.5 h-2.5 rounded-full bg-violet-500" />
                  AI Would Post ({trace.ai_would_post?.line_count || 0} lines)
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ScrollArea className="max-h-[500px]">
                  <div className="space-y-1.5" data-testid="ai-lines">
                    {(trace.ai_would_post?.lines || []).length === 0 && (
                      <p className="text-xs text-muted-foreground py-4 text-center">No template data — run analyzer first</p>
                    )}
                    {(trace.ai_would_post?.lines || []).map((l, i) => (
                      <LineRow key={i} line={l} side="ai" />
                    ))}
                  </div>
                </ScrollArea>
              </CardContent>
            </Card>
          </div>
        </>
      )}

      {loading && !trace && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
          <span className="ml-2 text-sm text-muted-foreground">Fetching invoice from BC Production...</span>
        </div>
      )}
    </div>
  );
}
