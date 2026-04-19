/**
 * WeeklyDigestCard — "This Week" snapshot card (U5+, v2.5.2)
 * ──────────────────────────────────────────────────────────
 *
 * Renders the latest weekly digest from `/api/learning/digest/latest`.
 * Headline + KPI row + top-3 reviewer pills + new drift count.
 * Rebuild button (admin) forces a fresh build of the current week.
 */
import { useCallback, useEffect, useState } from 'react';
import { CalendarDays, Trophy, Activity, Bell, RefreshCw, Download } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function medal(i) {
  return i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `#${i + 1}`;
}

export default function WeeklyDigestCard({ onRebuilt }) {
  const [digest, setDigest] = useState(null);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [selectedWeek, setSelectedWeek] = useState(null);

  const load = useCallback(async (weekKey = null) => {
    setLoading(true);
    try {
      const [latestRes, histRes] = await Promise.all([
        fetch(`${API}/api/learning/digest/${weekKey || 'latest'}`),
        fetch(`${API}/api/learning/digest?limit=8`),
      ]);
      if (latestRes.ok) {
        const d = await latestRes.json();
        // `/latest` returns {digest: null, hint} when none exists
        setDigest(d.digest === null ? null : d);
      } else {
        setDigest(null);
      }
      if (histRes.ok) {
        const h = await histRes.json();
        setHistory(h.digests || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const rebuild = async () => {
    setRebuilding(true);
    try {
      const res = await fetch(`${API}/api/learning/digest/rebuild`, { method: 'POST' });
      if (res.ok) {
        setSelectedWeek(null);
        await load();
        if (onRebuilt) onRebuilt();
      }
    } finally {
      setRebuilding(false);
    }
  };

  const downloadJson = () => {
    if (!digest) return;
    const blob = new Blob([JSON.stringify(digest, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `learning-digest-${digest.week_key}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  if (loading && !digest) {
    return (
      <div className="rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground text-center" data-testid="digest-card-loading">
        Loading weekly digest…
      </div>
    );
  }

  if (!digest) {
    return (
      <div className="rounded-lg border border-border bg-card p-6" data-testid="digest-card-empty">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-sm font-semibold flex items-center gap-2">
              <CalendarDays className="h-4 w-4 text-sky-500" /> Weekly Digest
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              No digest generated yet. Rebuild to generate one for the current week.
            </p>
          </div>
          <button
            onClick={rebuild}
            disabled={rebuilding}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            data-testid="digest-rebuild-btn"
          >
            {rebuilding ? 'Rebuilding…' : 'Rebuild'}
          </button>
        </div>
      </div>
    );
  }

  const ev = digest.events || {};
  const ds = digest.drift_summary || {};
  const top = digest.top_reviewers || [];

  return (
    <div className="rounded-lg border border-border bg-card" data-testid="weekly-digest-card">
      <div className="flex items-start justify-between gap-3 p-4 border-b border-border flex-wrap">
        <div className="min-w-0">
          <div className="text-sm font-semibold flex items-center gap-2">
            <CalendarDays className="h-4 w-4 text-sky-500" /> Weekly Digest
            <span className="text-[11px] font-mono text-muted-foreground" data-testid="digest-week-key">
              {digest.week_key}
            </span>
            <span className="text-[11px] text-muted-foreground">
              ({digest.week_start} → {digest.week_end})
            </span>
          </div>
          <p className="text-sm mt-2 text-foreground" data-testid="digest-headline">
            {digest.headline}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {history.length > 1 && (
            <select
              value={selectedWeek || digest.week_key}
              onChange={(e) => {
                const w = e.target.value;
                setSelectedWeek(w);
                load(w);
              }}
              className="text-xs bg-background border border-border rounded px-2 py-1"
              data-testid="digest-week-select"
            >
              {history.map((h) => (
                <option key={h.week_key} value={h.week_key}>{h.week_key}</option>
              ))}
            </select>
          )}
          <button
            onClick={downloadJson}
            className="text-[11px] px-2 py-1 rounded border border-border hover:bg-muted flex items-center gap-1"
            title="Download this digest as JSON"
            data-testid="digest-download-btn"
          >
            <Download className="h-3 w-3" /> JSON
          </button>
          <button
            onClick={rebuild}
            disabled={rebuilding}
            className="text-[11px] px-2 py-1 rounded border border-border hover:bg-muted flex items-center gap-1 disabled:opacity-50"
            data-testid="digest-rebuild-btn"
          >
            <RefreshCw className={`h-3 w-3 ${rebuilding ? 'animate-spin' : ''}`} />
            {rebuilding ? 'Rebuilding…' : 'Rebuild'}
          </button>
        </div>
      </div>

      <div className="p-4 grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="bg-muted/30 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
            <Activity className="h-3 w-3" /> Events
          </div>
          <div className="text-2xl font-bold text-sky-600 mt-1" data-testid="digest-events-total">{ev.total ?? 0}</div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {Object.entries(ev.by_domain || {}).map(([d, c], i) => (
              <span key={d} className="inline-block">
                {i > 0 && <span className="mx-1">·</span>}
                <span className="font-mono">{d}</span>: {c}
              </span>
            ))}
          </div>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
            <Trophy className="h-3 w-3" /> Top Reviewer
          </div>
          <div className="text-sm font-bold text-emerald-600 mt-1 truncate" data-testid="digest-top-reviewer">
            {top[0]?.actor || '—'}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {top[0] ? `${top[0].events} events · ${digest.leaderboard_unique_actors ?? 0} active` : 'No activity'}
          </div>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground flex items-center gap-1">
            <Bell className="h-3 w-3" /> New Drift
          </div>
          <div className={`text-2xl font-bold mt-1 ${(ds.total_new || 0) > 0 ? 'text-amber-600' : 'text-emerald-600'}`} data-testid="digest-drift-new">
            {ds.total_new ?? 0}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            {ds.critical || 0} critical · {ds.warn || 0} warn · {ds.info || 0} info
          </div>
        </div>
        <div className="bg-muted/30 rounded-lg p-3">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">Generated</div>
          <div className="text-sm font-medium mt-1" data-testid="digest-generated-at">
            {new Date(digest.generated_at).toLocaleDateString()}
          </div>
          <div className="text-[10px] text-muted-foreground mt-0.5">
            by {digest.generated_by || 'scheduler'}
          </div>
        </div>
      </div>

      {top.length > 0 && (
        <div className="border-t border-border p-3">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2">Top Reviewers</div>
          <div className="flex flex-wrap gap-2">
            {top.map((r, i) => (
              <span
                key={r.actor}
                className="inline-flex items-center gap-1.5 text-xs bg-muted/50 rounded-full px-2.5 py-1"
                data-testid={`digest-top-reviewer-${i}`}
              >
                <span>{medal(i)}</span>
                <span className="font-medium">{r.actor}</span>
                <span className="text-muted-foreground tabular-nums">{r.events}</span>
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
