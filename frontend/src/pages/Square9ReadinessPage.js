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
  const [trend, setTrend] = useState(null);
  const [daily, setDaily] = useState(null);
  const [learningSummary, setLearningSummary] = useState(null);
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
      const [latestRes, historyRes, trendRes, dailyRes, learnRes] = await Promise.all([
        fetch(`${API}/api/square9/readiness/latest`),
        fetch(`${API}/api/square9/readiness/history`),
        fetch(`${API}/api/square9/readiness/trend`).catch(() => null),
        fetch(`${API}/api/square9/readiness/daily`).catch(() => null),
        fetch(`${API}/api/square9/learning/summary`).catch(() => null),
      ]);
      setTrend(trendRes && trendRes.ok ? await trendRes.json() : null);
      setDaily(dailyRes && dailyRes.ok ? await dailyRes.json() : null);
      setLearningSummary(learnRes && learnRes.ok ? await learnRes.json() : null);
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

      {/* Cutover stability: daily decisions since the 2026-10-01 measurement fix */}
      {trend && trend.days && trend.days.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Cutover stability</CardTitle>
            <p className="text-xs text-muted-foreground">
              One check per day since {trend.measurement_fixed_date} (earlier snapshots used a truncated
              comparison window and are not comparable). Safety-net backfills are excluded from the rate.
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">GO days (last 7)</p>
                <p className="text-2xl font-bold">{trend.last7.go_days} / {trend.last7.days_measured}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Consecutive GO days</p>
                <p className="text-2xl font-bold">{trend.consecutive_go_days}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Lowest rate (last 7)</p>
                <p className="text-2xl font-bold">{trend.last7.min_rate_pct != null ? `${trend.last7.min_rate_pct}%` : '—'}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground uppercase tracking-wide">Caught by safety net</p>
                <p className="text-2xl font-bold">
                  {trend.days.slice(-7).reduce((n, d) => n + d.square9_backfilled + d.drop_folder_ingested, 0)}
                </p>
                <p className="text-xs text-muted-foreground">docs that never arrived by email</p>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {trend.days.map(d => (
                <div key={d.date}
                     className={`rounded border px-2 py-1 text-xs ${d.decision === 'GO'
                       ? 'border-emerald-500/50 bg-emerald-500/10' : 'border-red-500/50 bg-red-500/10'}`}>
                  <div className="font-medium">{d.date.slice(5)} · {d.decision}</div>
                  <div className="text-muted-foreground">
                    {d.match_rate_pct}%{(d.square9_backfilled + d.drop_folder_ingested) > 0
                      ? ` · ${d.square9_backfilled + d.drop_folder_ingested} backfilled` : ''}
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Learning from BC: hourly cycle */}
      {learningSummary && learningSummary.bc_reconciliation && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Learning from Business Central</CardTitle>
            <p className="text-xs text-muted-foreground">
              Every hour the Hub links recent AP documents to the BC purchase invoice they became and learns from
              it: vendor and document type corrected from BC, amount mismatches flagged, BC order numbers used for
              routing, repeated copies and split supporting pages marked. Last cycle:{' '}
              {learningSummary.last_cycle?.finished_at
                ? new Date(learningSummary.last_cycle.finished_at).toLocaleString()
                : 'not yet run'}.
            </p>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Linked to BC (45 days)</div>
                <div className="text-lg font-semibold">
                  {learningSummary.bc_reconciliation.linked} / {learningSummary.bc_reconciliation.documents}
                  <span className="ml-1 text-xs text-muted-foreground">({learningSummary.bc_reconciliation.link_rate_pct}%)</span>
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Exact (number + amount)</div>
                <div className="text-lg font-semibold">{learningSummary.bc_reconciliation['linked:number+amount'] || 0}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Corrected from BC (7 days)</div>
                <div className="text-lg font-semibold">
                  {Object.values(learningSummary.corrections_7d || {}).reduce((a, b) => a + b, 0)}
                </div>
                <div className="text-xs text-muted-foreground">
                  {Object.entries(learningSummary.corrections_7d || {}).map(([k, v]) => `${k.replace('_', ' ')} ${v}`).join(' · ') || '—'}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Amount mismatches / suspected fraud</div>
                <div className="text-lg font-semibold">
                  {learningSummary.bc_reconciliation.amount_mismatch || 0} / {learningSummary.fraud_flagged_7d || 0}
                </div>
                <div className="text-xs text-muted-foreground">
                  duplicates marked (7d): {Object.values(learningSummary.duplicates_marked_7d || {}).reduce((a, b) => a + b, 0)}
                </div>
              </div>
            </div>
            {(learningSummary.first_pass_by_day || []).length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <div className="text-xs text-muted-foreground mb-1">
                  First-pass accuracy by intake day: how often extraction already matched BC before any correction
                  (measured when the invoice reaches BC). This is the trend the learning should push up.
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground text-left border-b">
                      <th className="py-1 pr-3">Intake day</th>
                      <th className="py-1 pr-3 text-right">Invoices in BC</th>
                      <th className="py-1 pr-3 text-right">Invoice # right</th>
                      <th className="py-1 pr-3 text-right">Vendor right</th>
                      <th className="py-1 pr-3 text-right">PO right</th>
                    </tr>
                  </thead>
                  <tbody>
                    {learningSummary.first_pass_by_day.slice(-10).reverse().map(r => (
                      <tr key={r.date} className="border-b last:border-0">
                        <td className="py-1 pr-3">{r.date}</td>
                        <td className="py-1 pr-3 text-right">{r.documents}</td>
                        <td className="py-1 pr-3 text-right">{r.invoice_number_pct}%</td>
                        <td className="py-1 pr-3 text-right">{r.vendor_pct}%</td>
                        <td className="py-1 pr-3 text-right">{r.po_pct == null ? '—' : `${r.po_pct}%`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {(learningSummary.bc_number_typo_suspects || []).length > 0 && (
              <div className="mt-4 overflow-x-auto">
                <div className="text-xs text-muted-foreground mb-1">
                  Possible invoice number typos in BC: same vendor and amount, number off by one digit or a swap,
                  and the vendor&apos;s document shows the Hub&apos;s number. Worth a look by AP (duplicate-payment checks use this number).
                </div>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-xs text-muted-foreground text-left border-b">
                      <th className="py-1 pr-3">Vendor</th>
                      <th className="py-1 pr-3">On the invoice</th>
                      <th className="py-1 pr-3">In BC</th>
                      <th className="py-1 pr-3">BC document</th>
                      <th className="py-1 pr-3 text-right">Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {learningSummary.bc_number_typo_suspects.map(t => (
                      <tr key={t.document_id} className="border-b last:border-0">
                        <td className="py-1 pr-3">{t.vendor}</td>
                        <td className="py-1 pr-3 font-mono">{t.invoice_number}{t.file_supports_hub ? '' : ' ?'}</td>
                        <td className="py-1 pr-3 font-mono">{t.bc_number}</td>
                        <td className="py-1 pr-3 font-mono">{t.bc_document_no}</td>
                        <td className="py-1 pr-3 text-right">{t.amount == null ? '—' : Number(t.amount).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2})}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Daily efficacy: each business day scored on its own */}
      {daily && daily.days && daily.days.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Daily efficacy</CardTitle>
            <p className="text-xs text-muted-foreground">
              Each business day on its own, separate from the 7-day cutover rate: of the Square9 AP documents
              filed that day, how many the Hub caught through its own intake. Recycle-bin recoveries are shown
              separately (documents staff already processed and removed from Square9; the cutover gate counts
              them, so the adjusted rate is the comparable one). Safety net = documents that never arrived by
              email. The day is when the file was filed or last touched in Square9 (Central time). Partial = day
              cut by the 7-day window, or still in progress.
            </p>
            <p className="text-xs text-muted-foreground">
              BC entered = purchase invoices AP entered in Business Central (drafts and posted, by posting date)
              and how many of them the Hub received. Staff remove a Square9 item once it is entered in BC, so this
              measures intake against what AP actually processed, independent of folder housekeeping. Hover a
              rate to see the vendors not received.
            </p>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs text-muted-foreground text-left border-b">
                  <th className="py-2 pr-3">Date</th>
                  <th className="py-2 pr-3 text-right">Square9 docs</th>
                  <th className="py-2 pr-3 text-right">Caught</th>
                  <th className="py-2 pr-3 text-right">Missed</th>
                  <th className="py-2 pr-3 text-right">Raw rate</th>
                  <th className="py-2 pr-3 text-right">Recycle bin</th>
                  <th className="py-2 pr-3 text-right">Adjusted rate</th>
                  <th className="py-2 pr-3 text-right">Safety net</th>
                  <th className="py-2 pr-3 text-right">BC entered → Hub</th>
                  <th className="py-2 pr-3 text-right">BC rate</th>
                </tr>
              </thead>
              <tbody>
                {daily.days.map(d => {
                  const net = Object.values(d.safety_net || {}).reduce((a, b) => a + b, 0);
                  const rate = d.raw_rate_pct;
                  const adj = d.adjusted_rate_pct;
                  return (
                    <tr key={d.date} className="border-b last:border-0">
                      <td className="py-2 pr-3 whitespace-nowrap">
                        {d.date}{d.partial && <span className="ml-1 text-xs text-muted-foreground">(partial)</span>}
                      </td>
                      <td className="py-2 pr-3 text-right">{d.square9_docs}</td>
                      <td className="py-2 pr-3 text-right">{d.caught}</td>
                      <td className="py-2 pr-3 text-right">{d.missed}</td>
                      <td className="py-2 pr-3 text-right">{rate == null ? '—' : `${rate}%`}</td>
                      <td className="py-2 pr-3 text-right">{d.recycle_bin_recovered || 0}</td>
                      <td className={`py-2 pr-3 text-right font-medium ${adj == null ? '' : adj >= 85 ? 'text-emerald-500' : 'text-red-500'}`}>
                        {adj == null ? '—' : `${adj}%`}
                      </td>
                      <td className="py-2 pr-3 text-right">{net}</td>
                      <td className="py-2 pr-3 text-right">
                        {d.bc_entered == null ? '—' : `${d.bc_caught}/${d.bc_entered}`}
                      </td>
                      <td
                        className={`py-2 pr-3 text-right font-medium ${d.bc_rate_pct == null ? '' : d.bc_rate_pct >= 85 ? 'text-emerald-500' : 'text-red-500'}`}
                        title={(d.bc_missing_top || []).map(m => `${m.vendor}: ${m.count}`).join(', ')}
                      >
                        {d.bc_rate_pct == null ? '—' : `${d.bc_rate_pct}%`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

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
