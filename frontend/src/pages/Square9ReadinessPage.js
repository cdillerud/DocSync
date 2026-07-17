import { useState, useEffect, useCallback, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Progress } from '../components/ui/progress';
import { RefreshCw, TrendingUp, CheckCircle2, XCircle, AlertTriangle, Play, Loader2 } from 'lucide-react';
import {
  ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ReferenceLine,
} from 'recharts';

const API = process.env.REACT_APP_BACKEND_URL;
const RUN_POLL_INTERVAL_MS = 3000;

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

function formatElapsed(iso) {
  if (!iso) return '';
  const startMs = new Date(iso).getTime();
  if (Number.isNaN(startMs)) return '';
  const seconds = Math.max(0, Math.round((Date.now() - startMs) / 1000));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
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

export default function Square9ReadinessPage() {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const [runState, setRunState] = useState({ status: 'idle' });
  // Never read directly - just forces a re-render once a second while a
  // run is in progress so the "running for Xs" display (computed fresh
  // from Date.now() on every render) actually advances visually, since
  // React has no reason to re-render on its own just because time passes.
  const [, setRunElapsedTick] = useState(0);
  const pollTimeoutRef = useRef(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [latestRes, historyRes] = await Promise.all([
        fetch(`${API}/api/square9/readiness/latest`),
        fetch(`${API}/api/square9/readiness/history`),
      ]);
      if (!latestRes.ok) {
        if (latestRes.status === 404) {
          setError('No readiness snapshots recorded yet.');
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
    } catch (e) {
      setError('Could not reach the server.');
    } finally {
      setLoading(false);
    }
  }, []);

  const pollRunStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/square9/readiness/run-status`);
      if (!res.ok) return;
      const data = await res.json();
      setRunState(data);

      if (data.status === 'running') {
        pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
      } else if (data.status === 'completed') {
        // Pull the fresh snapshot + trend into the main dashboard view.
        fetchAll();
      }
      // 'failed' and 'idle' just stop polling - the error/idle state
      // renders from runState directly, nothing else to refresh.
    } catch {
      // Transient fetch failure while polling - try again on the next
      // tick rather than giving up and leaving the button stuck.
      pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
    }
  }, [fetchAll]);

  const resumeIfAlreadyRunning = useCallback(async () => {
    // Mount-time check only: if a run is genuinely still in progress
    // (e.g. the page was navigated away from and back to), resume
    // polling it. Deliberately does NOT surface 'completed' or
    // 'failed' from this check - that would show a stale failure
    // banner from some past run every time the page loads, even
    // though the person viewing it hasn't triggered anything this
    // session. Failures/completions only render after a run this
    // session's triggerRun() actually started.
    try {
      const res = await fetch(`${API}/api/square9/readiness/run-status`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'running') {
        setRunState(data);
        pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
      }
    } catch {
      // Nothing to resume if we can't even check - stay idle, the
      // person can just click the button.
    }
  }, [pollRunStatus]);

  useEffect(() => {
    fetchAll();
    // Resume polling on mount only if a run is genuinely still in
    // progress - see resumeIfAlreadyRunning's own comment for why this
    // must not surface a stale completed/failed status from some past
    // run nobody triggered this session.
    resumeIfAlreadyRunning();
    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ticks the "running for Xs" display once a second while a run is in
  // progress, independent of the 3s poll interval, so the elapsed time
  // doesn't visibly stall between polls.
  useEffect(() => {
    if (runState.status !== 'running') return undefined;
    const tick = setInterval(() => setRunElapsedTick(t => t + 1), 1000);
    return () => clearInterval(tick);
  }, [runState.status]);

  const triggerRun = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/square9/readiness/run`, { method: 'POST' });
      if (res.status === 409) {
        // Someone else already started one (or a stray double-click) -
        // just start tracking it rather than erroring.
        const body = await res.json().catch(() => ({}));
        setRunState({ status: 'running', started_at: body?.detail?.started_at });
      } else if (res.ok) {
        const body = await res.json();
        setRunState({ status: 'running', started_at: body.started_at });
      } else {
        setRunState({ status: 'failed', error: `Failed to start (HTTP ${res.status}).` });
        return;
      }
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
      pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
    } catch {
      setRunState({ status: 'failed', error: 'Could not reach the server.' });
    }
  }, [pollRunStatus]);

  if (loading && !latest) {
    return (
      <div className="p-6 flex items-center gap-2 text-muted-foreground">
        <RefreshCw className="w-4 h-4 animate-spin" /> Loading readiness data…
      </div>
    );
  }

  if (error && !latest) {
    return (
      <div className="p-6 space-y-4 max-w-2xl">
        <Card className="border-l-4 border-l-amber-500 bg-amber-500/5">
          <CardContent className="p-5 flex items-center gap-2">
            <AlertTriangle className="w-4 h-4 text-amber-600" />
            <span>{error}</span>
          </CardContent>
        </Card>
        <button
          onClick={triggerRun}
          disabled={runState.status === 'running'}
          className={`flex items-center gap-2 text-sm rounded-md px-3 py-1.5 font-medium ${
            runState.status === 'running'
              ? 'bg-muted text-muted-foreground cursor-not-allowed'
              : 'bg-primary text-primary-foreground hover:opacity-90'
          }`}
        >
          {runState.status === 'running' ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              Running… {formatElapsed(runState.started_at) && `(${formatElapsed(runState.started_at)})`}
            </>
          ) : (
            <>
              <Play className="w-3.5 h-3.5" /> Run Readiness Check
            </>
          )}
        </button>
        {runState.status === 'failed' && (
          <p className="text-sm text-red-600 whitespace-pre-wrap">{runState.error}</p>
        )}
      </div>
    );
  }

  const matchRate = latest?.match_rate_pct ?? 0;
  const target = latest?.min_match_rate_pct ?? 85;
  const isGo = latest?.decision === 'GO';
  const bucketCounts = latest?.bucket_counts || {};
  const bucketC = latest?.bucket_C_intake_cohort_detail || [];

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Square9 Cutover Readiness</h1>
          <p className="text-sm text-muted-foreground">
            Last checked {formatTimestamp(latest?.recorded_utc)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={triggerRun}
            disabled={runState.status === 'running'}
            className={`flex items-center gap-2 text-sm rounded-md px-3 py-1.5 font-medium ${
              runState.status === 'running'
                ? 'bg-muted text-muted-foreground cursor-not-allowed'
                : 'bg-primary text-primary-foreground hover:opacity-90'
            }`}
          >
            {runState.status === 'running' ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Running… {formatElapsed(runState.started_at) && `(${formatElapsed(runState.started_at)})`}
              </>
            ) : (
              <>
                <Play className="w-3.5 h-3.5" /> Run Readiness Check
              </>
            )}
          </button>
          <button
            onClick={fetchAll}
            className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground border rounded-md px-3 py-1.5"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </button>
        </div>
      </div>

      {runState.status === 'running' && (
        <Card className="border-l-4 border-l-blue-500 bg-blue-500/5">
          <CardContent className="p-4 flex items-center gap-2 text-sm">
            <Loader2 className="w-4 h-4 animate-spin text-blue-600" />
            <span>
              Pulling the current Square9/Hub comparison — this typically takes 45–90 seconds.
              The dashboard below will refresh automatically when it's done.
            </span>
          </CardContent>
        </Card>
      )}

      {runState.status === 'failed' && (
        <Card className="border-l-4 border-l-red-500 bg-red-500/5">
          <CardContent className="p-4 flex items-start gap-2 text-sm">
            <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Readiness check failed to complete.</p>
              <p className="text-muted-foreground mt-1 whitespace-pre-wrap">{runState.error || 'Unknown error.'}</p>
            </div>
          </CardContent>
        </Card>
      )}

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
                  Match rate — need {target.toFixed(0)}% to cut over
                </p>
              </div>
            </div>
            <Badge className={isGo ? 'bg-emerald-600 text-white text-sm px-3 py-1' : 'bg-red-600 text-white text-sm px-3 py-1'}>
              {latest?.decision || 'UNKNOWN'}
            </Badge>
          </div>
          <Progress value={Math.min(matchRate, 100)} className="h-3" />
          {latest?.projected_match_rate_pct != null && (
            <p className="text-xs text-muted-foreground mt-2">
              Projected after applying all known-safe fixes: {latest.projected_match_rate_pct.toFixed(1)}%
              {latest.projected_match_rate_pct < target && ' — still short of target, real intake work required too'}
            </p>
          )}
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
                  <Tooltip
                    formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Match rate']}
                    labelFormatter={(label) => label}
                  />
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
        <Card><CardContent className="p-4"><StatBlock label="Square9 docs" value={latest?.square_count ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Matched" value={latest?.matched_count ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Strong evidence" value={bucketCounts.strong_evidence_match ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="No match" value={bucketCounts.no_match ?? '—'} /></CardContent></Card>
      </div>

      {/* Real remaining gaps */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            Real intake gaps — {bucketC.reduce((sum, c) => sum + (c.affected_doc_count || 0), 0)} documents across {bucketC.length} vendors
          </CardTitle>
        </CardHeader>
        <CardContent>
          {bucketC.length === 0 ? (
            <p className="text-sm text-muted-foreground">No real intake gaps recorded — nice.</p>
          ) : (
            <div className="space-y-2">
              {bucketC.map((c, i) => (
                <div key={i} className="flex items-center justify-between border-b last:border-b-0 py-2 text-sm">
                  <div>
                    <span className="font-medium">{c.likely_vendor === '<unknown>' ? 'Unidentified sender' : c.likely_vendor}</span>
                    <span className="text-muted-foreground ml-2">{c.recommended_intake_change?.replaceAll('_', ' ')}</span>
                  </div>
                  <Badge variant="outline">{c.affected_doc_count} doc{c.affected_doc_count === 1 ? '' : 's'}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
