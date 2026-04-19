/**
 * LearningOpsPage — Command center for the unified Learning Core (U5+, v2.5.2)
 * ────────────────────────────────────────────────────────────────────────────
 *
 * Single screen consolidating every learning-core surface:
 *   1. Cross-domain pattern health (trust/drift/retire + sparklines)
 *   2. Unified event feed (from learning_events_v2)
 *   3. Open drift alerts (with ack/resolve)
 *   4. Reviewer activity leaderboard (who's been giving the most feedback)
 *
 * Read-only. Never writes to BC. Admin/Ops surface — not part of the
 * day-to-day reviewer queue.
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Activity, Bell, Trophy, Users, CheckCircle2, AlertTriangle } from 'lucide-react';
import PatternHealthPanel from '../components/PatternHealthPanel';

const API = process.env.REACT_APP_BACKEND_URL;

function Stat({ label, value, tone = 'text-foreground', testId }) {
  return (
    <div className="bg-card border border-border rounded-lg p-3 min-w-[120px]">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${tone}`} data-testid={testId}>{value}</div>
    </div>
  );
}

function domainBadge(dom) {
  const tone = dom === 'ap_posting' ? 'bg-blue-500/15 text-blue-700'
    : dom === 'sales_intake' ? 'bg-amber-500/15 text-amber-700'
    : dom === 'inventory_xls' ? 'bg-emerald-500/15 text-emerald-700'
    : 'bg-muted text-muted-foreground';
  return <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${tone}`}>{dom}</span>;
}

export default function LearningOpsPage() {
  const [eventsSummary, setEventsSummary] = useState(null);
  const [recentEvents, setRecentEvents] = useState([]);
  const [driftAlerts, setDriftAlerts] = useState([]);
  const [driftSummary, setDriftSummary] = useState(null);
  const [leaderboard, setLeaderboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [phRefreshKey, setPhRefreshKey] = useState(0);
  const [leaderDays, setLeaderDays] = useState(7);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, evtRes, driftRes, driftSumRes, lbRes] = await Promise.all([
        fetch(`${API}/api/learning/events/summary`),
        fetch(`${API}/api/learning/events?limit=25`),
        fetch(`${API}/api/learning/drift/alerts?status=open&limit=25`),
        fetch(`${API}/api/learning/drift/summary`),
        fetch(`${API}/api/learning/reviewers/leaderboard?days=${leaderDays}&limit=10`),
      ]);
      if (sumRes.ok) setEventsSummary(await sumRes.json());
      if (evtRes.ok) {
        const d = await evtRes.json();
        setRecentEvents(d.events || []);
      }
      if (driftRes.ok) {
        const d = await driftRes.json();
        setDriftAlerts(d.alerts || []);
      }
      if (driftSumRes.ok) setDriftSummary(await driftSumRes.json());
      if (lbRes.ok) setLeaderboard(await lbRes.json());
      setPhRefreshKey((k) => k + 1);
    } finally {
      setLoading(false);
    }
  }, [leaderDays]);

  useEffect(() => { load(); }, [load]);

  const acknowledgeDrift = async (id) => {
    try {
      await fetch(`${API}/api/learning/drift/alerts/${id}/acknowledge`, { method: 'POST' });
      setDriftAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) { /* noop */ }
  };
  const resolveDrift = async (id) => {
    try {
      await fetch(`${API}/api/learning/drift/alerts/${id}/resolve`, { method: 'POST' });
      setDriftAlerts((prev) => prev.filter((a) => a.id !== id));
    } catch (e) { /* noop */ }
  };

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto" data-testid="learning-ops-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Activity className="h-5 w-5 text-sky-500" /> Learning Ops
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Unified command center for the Learning Core. Cross-domain pattern
            health, the raw event feed, open drift alerts, and reviewer activity
            — all in one place. Read-only.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted disabled:opacity-50"
          data-testid="learning-ops-reload"
        >
          <RefreshCw className={`h-4 w-4 inline mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </button>
      </div>

      {/* Top-line stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="learning-ops-kpis">
        <Stat
          label="Total Events"
          value={eventsSummary?.total_events ?? 0}
          tone="text-sky-600"
          testId="ops-kpi-total-events"
        />
        <Stat
          label="Open Drift Alerts"
          value={driftSummary?.total_open ?? driftAlerts.length}
          tone={(driftSummary?.total_open || driftAlerts.length) > 0 ? 'text-amber-600' : 'text-emerald-600'}
          testId="ops-kpi-drift-open"
        />
        <Stat
          label={`Active Reviewers (${leaderDays}d)`}
          value={leaderboard?.unique_actors ?? 0}
          tone="text-violet-600"
          testId="ops-kpi-active-reviewers"
        />
        <Stat
          label={`Feedback Events (${leaderDays}d)`}
          value={leaderboard?.total_events ?? 0}
          tone="text-emerald-600"
          testId="ops-kpi-feedback-events"
        />
      </div>

      {/* Cross-domain pattern health (reuses U5 component) */}
      <PatternHealthPanel refreshKey={phRefreshKey} title="Cross-domain Pattern Health" />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Reviewer leaderboard */}
        <div className="rounded-lg border border-border bg-card" data-testid="reviewer-leaderboard">
          <div className="flex items-center justify-between p-3 border-b border-border">
            <div className="text-sm font-semibold flex items-center gap-2">
              <Trophy className="h-4 w-4 text-amber-500" /> Reviewer Activity Leaderboard
            </div>
            <div className="flex items-center gap-2 text-xs">
              <span className="text-muted-foreground">Window:</span>
              <select
                value={leaderDays}
                onChange={(e) => setLeaderDays(Number(e.target.value))}
                className="bg-background border border-border rounded px-1 py-0.5"
                data-testid="leaderboard-window-select"
              >
                <option value={7}>7 days</option>
                <option value={14}>14 days</option>
                <option value={30}>30 days</option>
              </select>
            </div>
          </div>
          {!leaderboard || leaderboard.reviewers?.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground flex items-center justify-center gap-2" data-testid="leaderboard-empty">
              <Users className="h-4 w-4" /> No reviewer activity in the last {leaderDays} days.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                    <th className="p-2 w-10">#</th>
                    <th className="p-2">Actor</th>
                    <th className="p-2 text-right">Events</th>
                    <th className="p-2">Domains</th>
                    <th className="p-2">Top event type</th>
                  </tr>
                </thead>
                <tbody>
                  {leaderboard.reviewers.map((r, i) => (
                    <tr
                      key={r.actor}
                      className="border-b border-border/50 hover:bg-muted/30"
                      data-testid={`leaderboard-row-${i}`}
                    >
                      <td className="p-2 font-mono text-muted-foreground">
                        {i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : i + 1}
                      </td>
                      <td className="p-2 font-medium">{r.actor}</td>
                      <td className="p-2 text-right tabular-nums font-bold text-emerald-600">{r.events}</td>
                      <td className="p-2">
                        <span className="flex flex-wrap gap-1">
                          {Object.entries(r.domains || {}).map(([d, c]) => (
                            <span key={d} className="inline-flex items-center gap-1">
                              {domainBadge(d)}<span className="text-[10px] tabular-nums">{c}</span>
                            </span>
                          ))}
                        </span>
                      </td>
                      <td className="p-2 text-[11px] font-mono text-muted-foreground">
                        {r.top_event_type || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Drift alerts */}
        <div className="rounded-lg border border-border bg-card" data-testid="ops-drift-alerts">
          <div className="flex items-center justify-between p-3 border-b border-border">
            <div className="text-sm font-semibold flex items-center gap-2">
              <Bell className="h-4 w-4 text-amber-500" /> Open Drift Alerts
              {driftAlerts.length > 0 && (
                <span className="text-xs bg-amber-500/20 text-amber-700 px-2 py-0.5 rounded-full">
                  {driftAlerts.length}
                </span>
              )}
            </div>
          </div>
          {driftAlerts.length === 0 ? (
            <div className="p-6 text-sm text-muted-foreground flex items-center justify-center gap-2" data-testid="ops-drift-empty">
              <CheckCircle2 className="h-4 w-4 text-emerald-500" /> No open drift alerts.
            </div>
          ) : (
            <div className="divide-y divide-border max-h-96 overflow-y-auto">
              {driftAlerts.map((a) => {
                const sevClass =
                  a.severity === 'critical' ? 'border-l-red-500 bg-red-500/5' :
                  a.severity === 'warn' ? 'border-l-amber-500 bg-amber-500/5' :
                  'border-l-sky-500 bg-sky-500/5';
                return (
                  <div key={a.id} className={`p-3 border-l-4 ${sevClass}`} data-testid={`ops-drift-${a.alert_type}`}>
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-[10px] uppercase font-mono">{a.severity}</span>
                          {domainBadge(a.domain)}
                          <span className="text-sm font-medium">{a.title}</span>
                        </div>
                        <div className="text-xs text-muted-foreground mt-1">{a.description}</div>
                      </div>
                      <div className="flex flex-col gap-1 shrink-0">
                        <button
                          onClick={() => acknowledgeDrift(a.id)}
                          className="text-[10px] px-2 py-0.5 rounded border border-border hover:bg-muted"
                          data-testid={`ops-drift-ack-${a.id.slice(0,8)}`}
                        >Ack</button>
                        <button
                          onClick={() => resolveDrift(a.id)}
                          className="text-[10px] px-2 py-0.5 rounded border border-emerald-500/30 text-emerald-700 hover:bg-emerald-500/10"
                          data-testid={`ops-drift-resolve-${a.id.slice(0,8)}`}
                        >Resolve</button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {/* Recent events feed */}
      <div className="rounded-lg border border-border bg-card" data-testid="ops-events-feed">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="text-sm font-semibold flex items-center gap-2">
            <Activity className="h-4 w-4 text-sky-500" /> Recent Learning Events
          </div>
          <div className="text-xs text-muted-foreground">{recentEvents.length}</div>
        </div>
        {recentEvents.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground flex items-center justify-center gap-2" data-testid="ops-events-empty">
            <AlertTriangle className="h-4 w-4" /> No events yet. Activity will appear here as reviewers give feedback.
          </div>
        ) : (
          <div className="divide-y divide-border max-h-[480px] overflow-y-auto">
            {recentEvents.map((e) => (
              <div key={e.id} className="p-2.5 flex items-center gap-3 text-xs" data-testid={`ops-event-${e.id.slice(0,8)}`}>
                {domainBadge(e.domain)}
                <span className="font-mono text-[11px] uppercase text-muted-foreground shrink-0">
                  {e.event_type}
                </span>
                {e.scope_value && <span className="font-mono shrink-0">{e.scope_value}</span>}
                {e.target?.item_no && <span className="font-mono text-muted-foreground shrink-0">{e.target.item_no}</span>}
                <span className="ml-auto text-[10px] text-muted-foreground shrink-0">
                  <span className="mr-2">{e.actor}</span>
                  {new Date(e.created_at).toLocaleString()}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
