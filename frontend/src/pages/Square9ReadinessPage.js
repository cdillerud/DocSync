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

// Latest clean, measured V117 held-out result. Update this only after a
// complete V117 run proves the immutable routing gate on a real holdout.
const AP_ROUTING_MEASURED_BASELINE = {
  featureCommit: '6c455f1a027361115eba3ea9ecde989009bda76e',
  measuredOn: 'Sep 3, 2026',
  holdoutCount: 62,
  autoRouted: 26,
  reviewed: 36,
  coveragePct: 41.94,
  targetCoveragePct: 90,
  accuracyPct: 100,
  targetAccuracyPct: 100,
  wrongAutoRoutes: 0,
  maxWrongAutoRoutes: 0,
  gate: 'FAIL_COVERAGE',
};

// Newer code exists, but it must not influence cutover status until a full
// held-out run measures it. This keeps the page honest while work continues.
const AP_ROUTING_PENDING_CANDIDATE = {
  featureCommit: '609ad242af95877a9f663e4cf0bcfb17198674f8',
  focusedTestsExpected: 52,
  status: 'PENDING RERUN',
};

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

function GateRow({ label, detail, passed, blockedLabel = 'BLOCKED' }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2 border-b last:border-b-0">
      <div>
        <p className="text-sm font-medium">{label}</p>
        <p className="text-xs text-muted-foreground">{detail}</p>
      </div>
      <Badge className={passed ? 'bg-emerald-600 text-white' : 'bg-amber-600 text-white'}>
        {passed ? 'PASS' : blockedLabel}
      </Badge>
    </div>
  );
}

export default function Square9ReadinessPage() {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [runState, setRunState] = useState({ status: 'idle' });
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
          setError('No historical readiness snapshots recorded yet.');
        } else {
          setError(`Failed to load latest historical snapshot (HTTP ${latestRes.status}).`);
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

  const pollRunStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/square9/readiness/run-status`);
      if (!res.ok) return;
      const data = await res.json();
      setRunState(data);

      if (data.status === 'running') {
        pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
      } else if (data.status === 'completed') {
        fetchAll();
      }
    } catch {
      pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
    }
  }, [fetchAll]);

  const resumeIfAlreadyRunning = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/square9/readiness/run-status`);
      if (!res.ok) return;
      const data = await res.json();
      if (data.status === 'running') {
        setRunState(data);
        pollTimeoutRef.current = setTimeout(pollRunStatus, RUN_POLL_INTERVAL_MS);
      }
    } catch {
      // Stay idle if status cannot be checked.
    }
  }, [pollRunStatus]);

  useEffect(() => {
    fetchAll();
    resumeIfAlreadyRunning();
    return () => {
      if (pollTimeoutRef.current) clearTimeout(pollTimeoutRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (runState.status !== 'running') return undefined;
    const tick = setInterval(() => setRunElapsedTick(t => t + 1), 1000);
    return () => clearInterval(tick);
  }, [runState.status]);

  const triggerRun = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/square9/readiness/run`, { method: 'POST' });
      if (res.status === 409) {
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
              <Play className="w-3.5 h-3.5" /> Run Historical Check
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
  const historicalTarget = latest?.min_match_rate_pct ?? 85;
  const bucketCounts = latest?.bucket_counts || {};
  const bucketC = latest?.bucket_C_intake_cohort_detail || [];

  const historicalMatchPass = matchRate >= historicalTarget;
  const routingSafetyPass =
    AP_ROUTING_MEASURED_BASELINE.accuracyPct >= AP_ROUTING_MEASURED_BASELINE.targetAccuracyPct
    && AP_ROUTING_MEASURED_BASELINE.wrongAutoRoutes <= AP_ROUTING_MEASURED_BASELINE.maxWrongAutoRoutes;
  const routingCoveragePass =
    AP_ROUTING_MEASURED_BASELINE.coveragePct >= AP_ROUTING_MEASURED_BASELINE.targetCoveragePct;
  const overallReady = historicalMatchPass && routingSafetyPass && routingCoveragePass;

  return (
    <div className="p-6 space-y-6 max-w-6xl mx-auto">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Square9 Cutover Readiness</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Overall cutover requires historical document parity plus the V117 AP routing promotion gates.
          </p>
          <p className="text-xs text-muted-foreground mt-1">
            Historical check last run {formatTimestamp(latest?.recorded_utc)}
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
                <Play className="w-3.5 h-3.5" /> Run Historical Check
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
              Pulling the current Square9/Hub historical comparison. This does not rerun the V117 AP routing gate.
            </span>
          </CardContent>
        </Card>
      )}

      {runState.status === 'failed' && (
        <Card className="border-l-4 border-l-red-500 bg-red-500/5">
          <CardContent className="p-4 flex items-start gap-2 text-sm">
            <AlertTriangle className="w-4 h-4 text-red-600 shrink-0 mt-0.5" />
            <div>
              <p className="font-medium">Historical readiness check failed to complete.</p>
              <p className="text-muted-foreground mt-1 whitespace-pre-wrap">{runState.error || 'Unknown error.'}</p>
            </div>
          </CardContent>
        </Card>
      )}

      <Card className={`border-l-4 ${overallReady ? 'border-l-emerald-500 bg-emerald-500/5' : 'border-l-red-500 bg-red-500/5'}`}>
        <CardContent className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="flex items-start gap-3">
              {overallReady
                ? <CheckCircle2 className="w-9 h-9 text-emerald-600 mt-1" />
                : <XCircle className="w-9 h-9 text-red-600 mt-1" />}
              <div>
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Overall cutover status</p>
                <p className="text-4xl font-bold tracking-tight mt-1">{overallReady ? 'READY' : 'NOT READY'}</p>
                <p className="text-sm text-muted-foreground mt-2 max-w-3xl">
                  Historical document parity {historicalMatchPass ? 'has passed' : 'has not passed'}.
                  {' '}AP routing safety {routingSafetyPass ? 'has passed' : 'has not passed'}.
                  {' '}Automatic routing coverage is {AP_ROUTING_MEASURED_BASELINE.coveragePct.toFixed(1)}%
                  {' '}and must reach {AP_ROUTING_MEASURED_BASELINE.targetCoveragePct}%.
                </p>
              </div>
            </div>
            <Badge className={overallReady ? 'bg-emerald-600 text-white text-sm px-3 py-1' : 'bg-red-600 text-white text-sm px-3 py-1'}>
              {overallReady ? 'GO' : 'HOLD'}
            </Badge>
          </div>

          <div className="mt-5 border rounded-lg px-4">
            <GateRow
              label="Historical document parity"
              detail={`${matchRate.toFixed(1)}% match rate; threshold ${historicalTarget.toFixed(0)}%`}
              passed={historicalMatchPass}
            />
            <GateRow
              label="AP routing safety"
              detail={`${AP_ROUTING_MEASURED_BASELINE.accuracyPct.toFixed(0)}% auto-route accuracy; ${AP_ROUTING_MEASURED_BASELINE.wrongAutoRoutes} wrong automatic routes`}
              passed={routingSafetyPass}
            />
            <GateRow
              label="AP routing coverage"
              detail={`${AP_ROUTING_MEASURED_BASELINE.coveragePct.toFixed(2)}% measured coverage; target ${AP_ROUTING_MEASURED_BASELINE.targetCoveragePct}%`}
              passed={routingCoveragePass}
            />
          </div>
        </CardContent>
      </Card>

      <div className="grid md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center justify-between gap-3">
              <span>Historical Document Parity</span>
              <Badge className={historicalMatchPass ? 'bg-emerald-600 text-white' : 'bg-amber-600 text-white'}>
                {historicalMatchPass ? 'PASS' : 'BLOCKED'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex items-end gap-2">
              <p className="text-4xl font-bold tracking-tight">{matchRate.toFixed(1)}%</p>
              <p className="text-sm text-muted-foreground mb-1">target {historicalTarget.toFixed(0)}%</p>
            </div>
            <Progress value={Math.min(matchRate, 100)} className="h-3 mt-4" />
            {latest?.projected_match_rate_pct != null && (
              <p className="text-xs text-muted-foreground mt-3">
                Projected historical match after known-safe fixes: {latest.projected_match_rate_pct.toFixed(1)}%
              </p>
            )}
            <p className="text-xs text-muted-foreground mt-2">
              Live from the Square9/Hub historical comparison API. This is not the AP routing promotion gate.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center justify-between gap-3">
              <span>AP Routing Promotion</span>
              <Badge className={routingCoveragePass && routingSafetyPass ? 'bg-emerald-600 text-white' : 'bg-amber-600 text-white'}>
                {routingCoveragePass && routingSafetyPass ? 'PASS' : 'BLOCKED'}
              </Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div>
              <div className="flex items-end gap-2">
                <p className="text-4xl font-bold tracking-tight">{AP_ROUTING_MEASURED_BASELINE.coveragePct.toFixed(1)}%</p>
                <p className="text-sm text-muted-foreground mb-1">coverage; target {AP_ROUTING_MEASURED_BASELINE.targetCoveragePct}%</p>
              </div>
              <Progress value={AP_ROUTING_MEASURED_BASELINE.coveragePct} className="h-3 mt-4" />
            </div>

            <div className="grid grid-cols-2 gap-3 text-sm">
              <div className="border rounded-md p-3">
                <p className="text-xs text-muted-foreground uppercase">Accuracy</p>
                <p className="text-xl font-bold">{AP_ROUTING_MEASURED_BASELINE.accuracyPct.toFixed(0)}%</p>
              </div>
              <div className="border rounded-md p-3">
                <p className="text-xs text-muted-foreground uppercase">Wrong autos</p>
                <p className="text-xl font-bold">{AP_ROUTING_MEASURED_BASELINE.wrongAutoRoutes}</p>
              </div>
              <div className="border rounded-md p-3">
                <p className="text-xs text-muted-foreground uppercase">Auto-routed</p>
                <p className="text-xl font-bold">{AP_ROUTING_MEASURED_BASELINE.autoRouted}/{AP_ROUTING_MEASURED_BASELINE.holdoutCount}</p>
              </div>
              <div className="border rounded-md p-3">
                <p className="text-xs text-muted-foreground uppercase">Review</p>
                <p className="text-xl font-bold">{AP_ROUTING_MEASURED_BASELINE.reviewed}</p>
              </div>
            </div>

            <div className="text-xs text-muted-foreground space-y-1">
              <p>
                Measured V117 baseline: {AP_ROUTING_MEASURED_BASELINE.measuredOn} · feature {AP_ROUTING_MEASURED_BASELINE.featureCommit.slice(0, 10)} · {AP_ROUTING_MEASURED_BASELINE.gate}
              </p>
              <p>
                New candidate {AP_ROUTING_PENDING_CANDIDATE.featureCommit.slice(0, 10)} is {AP_ROUTING_PENDING_CANDIDATE.status.toLowerCase()} and is not counted in readiness.
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {history.length > 1 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4" /> Historical document match progress
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
                    formatter={(value) => [`${Number(value).toFixed(1)}%`, 'Historical match']}
                    labelFormatter={(label) => label}
                  />
                  <ReferenceLine
                    y={historicalTarget}
                    stroke="#dc2626"
                    strokeDasharray="4 4"
                    label={{ value: `${historicalTarget}% historical target`, position: 'insideTopRight', fontSize: 11, fill: '#dc2626' }}
                  />
                  <Line type="monotone" dataKey="match_rate_pct" stroke="#2563eb" strokeWidth={2} dot={{ r: 3 }} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><CardContent className="p-4"><StatBlock label="Square9 docs" value={latest?.square_count ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Matched" value={latest?.matched_count ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="Strong evidence" value={bucketCounts.strong_evidence_match ?? '—'} /></CardContent></Card>
        <Card><CardContent className="p-4"><StatBlock label="No match" value={latest?.no_match_count ?? bucketCounts.no_match ?? '—'} /></CardContent></Card>
      </div>

      {bucketC.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Real intake gaps</CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground mb-4">
              Historical Square9 items without a verified Hub match. These are document-parity gaps, separate from AP routing coverage.
            </p>
            <div className="space-y-2 max-h-80 overflow-auto">
              {bucketC.slice(0, 50).map((row, index) => (
                <div key={`${row?.name || row?.file_name || 'gap'}-${index}`} className="border rounded-md p-3 text-sm">
                  <p className="font-medium break-all">{row?.name || row?.file_name || row?.document_name || 'Unmatched document'}</p>
                  {(row?.reason || row?.detail) && (
                    <p className="text-xs text-muted-foreground mt-1">{row.reason || row.detail}</p>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
