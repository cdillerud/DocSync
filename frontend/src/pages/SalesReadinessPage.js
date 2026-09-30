import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import { RefreshCw, TrendingUp, CheckCircle2, XCircle, Play, FlaskConical } from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts';

const API = process.env.REACT_APP_BACKEND_URL;

function formatTimestamp(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

function StatBlock({ label, value, sublabel }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold tracking-tight">{value}</p>
      {sublabel && <p className="text-xs text-muted-foreground">{sublabel}</p>}
    </div>
  );
}

export default function SalesReadinessPage() {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [running, setRunning] = useState(false);

  const [dryRun, setDryRun] = useState(null);
  const [dryRunLoading, setDryRunLoading] = useState(false);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [latestRes, historyRes] = await Promise.all([
        fetch(`${API}/api/sales/readiness/latest`),
        fetch(`${API}/api/sales/readiness/history`),
      ]);
      if (!latestRes.ok) {
        if (latestRes.status === 404) {
          setError('No sales readiness snapshots recorded yet.');
        } else {
          setError(`Failed to load latest snapshot (HTTP ${latestRes.status}).`);
        }
        setLatest(null);
      } else {
        setLatest(await latestRes.json());
      }
      if (historyRes.ok) {
        const h = await historyRes.json();
        setHistory((h.history || []).map(row => ({
          ...row,
          label: formatTimestamp(row.recorded_utc),
        })));
      }
    } catch {
      setError('Could not reach the server.');
    } finally {
      setLoading(false);
    }
  }, []);

  const triggerRun = useCallback(async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API}/api/sales/readiness/run`, { method: 'POST' });
      if (res.ok) {
        await fetchAll();
      }
    } catch {
      /* fetchAll's own error state covers this on next load */
    } finally {
      setRunning(false);
    }
  }, [fetchAll]);

  const runDryRun = useCallback(async () => {
    setDryRunLoading(true);
    try {
      const res = await fetch(`${API}/api/sales/readiness/dry-run?limit=2000`);
      if (res.ok) setDryRun(await res.json());
    } catch {
      /* leave prior state, button remains clickable to retry */
    } finally {
      setDryRunLoading(false);
    }
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  if (loading && !latest) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <RefreshCw className="w-4 h-4 animate-spin" /> Loading sales readiness data…
      </div>
    );
  }

  if (error && !latest) {
    return (
      <div className="p-6 space-y-4 max-w-2xl">
        <Card className="border-l-4 border-l-amber-500 bg-amber-500/5">
          <CardContent className="p-5 flex items-center gap-2">
            <span>{error}</span>
          </CardContent>
        </Card>
        <button
          onClick={triggerRun}
          disabled={running}
          className="flex items-center gap-2 text-sm rounded-md px-3 py-1.5 font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          <Play className="w-3.5 h-3.5" /> {running ? 'Running…' : 'Compute First Snapshot'}
        </button>
      </div>
    );
  }

  const matchRate = latest?.match_rate_pct ?? 0;
  const target = latest?.min_match_rate_pct ?? 85;
  const isGo = latest?.decision === 'GO';
  const buckets = latest?.tier_buckets || {};

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Sales Order Readiness</h1>
          <p className="text-sm text-muted-foreground">
            Last checked {formatTimestamp(latest?.recorded_utc)} — tracks the real gates on Sales Order auto-creation
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={triggerRun}
            disabled={running}
            className="flex items-center gap-2 text-sm rounded-md px-3 py-1.5 font-medium bg-primary text-primary-foreground hover:opacity-90 disabled:opacity-50"
          >
            {running ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {running ? 'Running…' : 'Run Readiness Check'}
          </button>
        </div>
      </div>

      <Card className="border-l-4 border-l-amber-500 bg-amber-500/5">
        <CardContent className="p-3 text-xs text-muted-foreground">
          The {target.toFixed(0)}% target below is a <strong className="text-foreground">proposed</strong> threshold (mirrors the AP/Square9 cutover bar), not an established one — there's no prior track record yet for what sales order match rate is safe to automate on. Revisit as real data accumulates.
        </CardContent>
      </Card>

      {/* Headline */}
      <Card className={`border-l-4 ${isGo ? 'border-l-emerald-500 bg-emerald-500/5' : 'border-l-red-500 bg-red-500/5'}`}>
        <CardContent className="p-6">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-3">
              {isGo
                ? <CheckCircle2 className="w-8 h-8 text-emerald-600" />
                : <XCircle className="w-8 h-8 text-red-600" />}
              <div>
                <p className="text-5xl font-bold tracking-tight">{matchRate.toFixed(1)}%</p>
                <p className="text-sm text-muted-foreground">
                  Order match rate — need {target.toFixed(0)}% before auto-creation should be considered
                </p>
              </div>
            </div>
            <Badge className={isGo ? 'bg-emerald-600 text-white text-sm px-3 py-1' : 'bg-red-600 text-white text-sm px-3 py-1'}>
              {latest?.decision || 'UNKNOWN'}
            </Badge>
          </div>
          <Progress value={Math.min(matchRate, 100)} className="h-3" />
        </CardContent>
      </Card>

      {/* Trend chart */}
      {history.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4" /> Progress over time
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div style={{ width: '100%', height: 260 }}>
              <ResponsiveContainer>
                <LineChart data={history} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                  <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
                  <Tooltip formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Order match rate']} />
                  <ReferenceLine y={target} stroke="#dc2626" strokeDasharray="4 4"
                    label={{ value: `${target}% target`, position: 'insideTopRight', fontSize: 11, fill: '#dc2626' }} />
                  <Line type="monotone" dataKey="match_rate_pct" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Breakdown */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardContent className="p-4"><StatBlock label="Pilot docs" value={latest?.total_pilot_docs ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Customer match" value={`${latest?.customer_match_pct ?? 0}%`} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Rep assigned" value={`${latest?.rep_assignment_rate_pct ?? 0}%`} sublabel={`${latest?.rep_assigned_count ?? 0} docs`} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="SOs auto-created" value={latest?.so_created_count ?? 0} sublabel="ground truth, not estimated" /></CardContent></Card>
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">Order match tier distribution</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-3 text-sm">
            <div><p className="text-muted-foreground text-xs">Exact</p><p className="font-bold text-lg">{buckets.exact ?? 0}</p></div>
            <div><p className="text-muted-foreground text-xs">Cust-scoped</p><p className="font-bold text-lg">{buckets.scoped ?? 0}</p></div>
            <div><p className="text-muted-foreground text-xs">Fuzzy</p><p className="font-bold text-lg">{buckets.fuzzy ?? 0}</p></div>
            <div><p className="text-muted-foreground text-xs">Live BC</p><p className="font-bold text-lg">{buckets.live ?? 0}</p></div>
            <div><p className="text-red-600 text-xs">No match</p><p className="font-bold text-lg text-red-600">{buckets.no_match ?? 0}</p></div>
            <div><p className="text-muted-foreground text-xs">No ref</p><p className="font-bold text-lg">{buckets.no_ref ?? 0}</p></div>
          </div>
        </CardContent>
      </Card>

      {/* Dry-run simulation */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <FlaskConical className="w-4 h-4" /> What if auto-creation were on right now?
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-muted-foreground">
            Read-only simulation against the real eligibility logic. Makes no BC calls, modifies nothing, and never touches the actual safety gate.
          </p>
          <button
            onClick={runDryRun}
            disabled={dryRunLoading}
            className="flex items-center gap-2 text-sm rounded-md px-3 py-1.5 font-medium border hover:bg-muted disabled:opacity-50"
          >
            {dryRunLoading ? <RefreshCw className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            {dryRunLoading ? 'Simulating…' : 'Run Simulation'}
          </button>
          {dryRun && (
            <div className="grid grid-cols-2 md:grid-cols-3 gap-4 pt-2 text-sm">
              <div><p className="text-muted-foreground text-xs">Checked</p><p className="font-bold text-lg">{dryRun.total_checked}</p></div>
              <div><p className="text-emerald-600 text-xs">Would create an SO</p><p className="font-bold text-lg text-emerald-600">{dryRun.would_be_eligible_if_gate_removed}</p></div>
              <div><p className="text-muted-foreground text-xs">Still blocked (other reasons)</p><p className="font-bold text-lg">{dryRun.would_still_be_blocked_other_reasons}</p></div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
