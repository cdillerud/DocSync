/**
 * WeekOverWeekDeltaBanner — "Did we move the needle?" (v2.5.2)
 * ────────────────────────────────────────────────────────────
 *
 * Slim banner atop /learning/ops that pulls the latest TWO weekly
 * digests and shows deltas (events, active reviewers, new drift)
 * vs the prior week. Purely client-side — no new backend work.
 *
 * Collapses to a "baseline — no comparison yet" message when fewer
 * than 2 digests exist.
 */
import { useEffect, useState } from 'react';
import { TrendingUp, TrendingDown, Minus, Sparkles } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function fmtDelta(current, prior, invertGood = false) {
  const cur = Number(current) || 0;
  const pri = Number(prior) || 0;
  const diff = cur - pri;
  const pct = pri === 0 ? (cur > 0 ? 100 : 0) : Math.round((diff / pri) * 100);
  // For metrics where UP is good (events, reviewers): positive diff = green
  // For metrics where UP is bad (drift):              positive diff = amber/red
  const isPositive = diff > 0;
  const isNeutral = diff === 0;
  const good = invertGood ? !isPositive : isPositive;
  const tone = isNeutral
    ? 'text-muted-foreground'
    : good ? 'text-emerald-600' : 'text-amber-600';
  const Icon = isNeutral ? Minus : isPositive ? TrendingUp : TrendingDown;
  const sign = diff > 0 ? '+' : '';
  return { diff, pct, tone, Icon, sign, pri };
}

export default function WeekOverWeekDeltaBanner() {
  const [digests, setDigests] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/learning/digest?limit=2`);
        if (res.ok) {
          const d = await res.json();
          setDigests(d.digests || []);
        }
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return null;

  const [current, prior] = digests;
  if (!current) return null;

  if (!prior) {
    return (
      <div
        className="rounded-lg border border-sky-500/30 bg-sky-500/5 px-4 py-2.5 flex items-center gap-2 text-sm"
        data-testid="wow-delta-banner-baseline"
      >
        <Sparkles className="h-4 w-4 text-sky-500 shrink-0" />
        <span>
          <span className="font-medium">Baseline week.</span>{' '}
          <span className="text-muted-foreground">
            Week-over-week comparison will appear here after {current.week_key} rolls over.
          </span>
        </span>
      </div>
    );
  }

  const dEvents = fmtDelta(current.events?.total ?? 0, prior.events?.total ?? 0);
  const dReviewers = fmtDelta(
    current.leaderboard_unique_actors ?? 0,
    prior.leaderboard_unique_actors ?? 0,
  );
  const dDrift = fmtDelta(
    current.drift_summary?.total_new ?? 0,
    prior.drift_summary?.total_new ?? 0,
    /* invertGood */ true,
  );

  const cells = [
    { key: 'events',    label: 'Events',           delta: dEvents,    value: current.events?.total ?? 0 },
    { key: 'reviewers', label: 'Active reviewers', delta: dReviewers, value: current.leaderboard_unique_actors ?? 0 },
    { key: 'drift',     label: 'New drift',        delta: dDrift,     value: current.drift_summary?.total_new ?? 0 },
  ];

  return (
    <div
      className="rounded-lg border border-border bg-card px-4 py-3 flex items-center gap-4 flex-wrap"
      data-testid="wow-delta-banner"
    >
      <div className="text-xs text-muted-foreground shrink-0">
        <span className="font-semibold text-foreground">Did we move the needle?</span>
        <span className="ml-2 font-mono">{current.week_key}</span>
        <span className="mx-1 text-muted-foreground/60">vs</span>
        <span className="font-mono">{prior.week_key}</span>
      </div>
      <div className="flex items-center gap-5 flex-wrap ml-auto">
        {cells.map(({ key, label, delta, value }) => {
          const Icon = delta.Icon;
          return (
            <div
              key={key}
              className="flex items-center gap-2"
              data-testid={`wow-delta-${key}`}
              title={`${label}: ${value} this week vs ${delta.pri} prior`}
            >
              <span className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</span>
              <span className="text-sm font-bold tabular-nums mr-1">{value}</span>
              <span className={`flex items-center gap-0.5 text-xs font-semibold ${delta.tone}`}>
                <Icon className="h-3.5 w-3.5" />
                {delta.diff === 0
                  ? '0'
                  : `${delta.sign}${delta.diff} (${delta.sign}${Math.abs(delta.pct)}%)`}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
