/**
 * PatternHealthPanel — reusable cross-domain learning health panel (U5, v2.5.2)
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Single component that renders pattern-trust/drift/retire state for
 * either a specific domain (`sales_intake` or `ap_posting`) or a
 * combined cross-domain view.
 *
 *   <PatternHealthPanel domain="sales_intake" />     → intake-focused
 *   <PatternHealthPanel domain="ap_posting" />       → AP-focused
 *   <PatternHealthPanel />                            → cross-domain roll-up
 *
 * Optional props:
 *   - title          override the card title (default depends on mode)
 *   - limit          passed as ?limit=N to the backend (default 15)
 *   - showEvents     render the Recent reviewer feedback list (default true for domain mode)
 *   - showPerScope   render the per-customer/per-vendor table (default true for domain mode)
 *   - className      extra wrapper classes
 *   - refreshKey     parent-controlled int — bumping forces a re-fetch
 *
 * Fetches: GET /api/learning/pattern-health/unified?domain=&limit=
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { ShieldCheck, Sparkles, Archive, RefreshCw } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const DOMAIN_LABELS = {
  sales_intake: 'Intake (Customers)',
  ap_posting:   'AP (Vendors)',
};

const SCOPE_HEADERS = {
  sales_intake: 'Customer',
  ap_posting:   'Vendor',
};

function Metric({ label, value, hint, tone = 'text-foreground', testId }) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${tone}`} data-testid={testId}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}

/** Tiny inline SVG polyline for a 7-day trend series. */
function Sparkline({ points = [], width = 64, height = 18, className = 'text-sky-500', testId }) {
  if (!Array.isArray(points) || points.length === 0) return null;
  const counts = points.map((p) => Number(p.count) || 0);
  const max = Math.max(1, ...counts);
  const stepX = points.length > 1 ? width / (points.length - 1) : 0;
  const coords = counts.map((c, i) => {
    const x = i * stepX;
    const y = height - (c / max) * (height - 2) - 1;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const total = counts.reduce((a, b) => a + b, 0);
  return (
    <svg
      width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      className={`inline-block align-middle ${className}`}
      data-testid={testId}
      aria-label={`7-day trend, ${total} events`}
    >
      <polyline
        fill="none" stroke="currentColor" strokeWidth="1.25"
        strokeLinejoin="round" strokeLinecap="round"
        points={coords.join(' ')}
      />
    </svg>
  );
}

export function PatternHealthPanel({
  domain = null,
  title,
  limit = 15,
  showEvents = true,
  showPerScope = true,
  className = '',
  refreshKey = 0,
}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const qs = new URLSearchParams();
      if (domain) qs.set('domain', domain);
      qs.set('limit', String(limit));
      const res = await fetch(`${API}/api/learning/pattern-health/unified?${qs}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setData(await res.json());
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [domain, limit]);

  useEffect(() => { load(); }, [load, refreshKey]);

  const isCombined = !domain;

  const resolvedTitle = title
    || (isCombined ? 'Cross-Domain Pattern Health' : `Pattern Health — ${DOMAIN_LABELS[domain] || domain}`);

  const summary = useMemo(() => {
    if (!data) return null;
    return isCombined ? data.combined_summary : data.summary;
  }, [data, isCombined]);

  const perDomain = Array.isArray(data?.domains) ? data.domains : [];
  const perScope  = Array.isArray(data?.per_scope) ? data.per_scope : [];
  const recentEvents = Array.isArray(data?.recent_events) ? data.recent_events : [];
  const trend = Array.isArray(data?.trend_7d) ? data.trend_7d : [];
  const trendTotal = trend.reduce((a, p) => a + (Number(p.count) || 0), 0);

  const scopeHeader = SCOPE_HEADERS[domain] || 'Scope';
  const testIdPrefix = `pattern-health-${domain || 'unified'}`;

  return (
    <div
      className={`rounded-lg border border-border bg-card ${className}`}
      data-testid={testIdPrefix}
    >
      <div className="flex items-center justify-between p-3 border-b border-border">
        <div className="text-sm font-semibold flex items-center gap-2">
          {isCombined
            ? <Sparkles className="h-4 w-4 text-sky-500" />
            : <ShieldCheck className="h-4 w-4 text-emerald-500" />}
          {resolvedTitle}
        </div>
        <div className="flex items-center gap-2">
          {!isCombined && trend.length > 0 && (
            <span
              className="flex items-center gap-1 text-[11px] text-muted-foreground"
              title={`Last 7d — ${trendTotal} events`}
            >
              <Sparkline
                points={trend}
                className={trendTotal > 0 ? 'text-sky-500' : 'text-muted-foreground/60'}
                testId={`${testIdPrefix}-sparkline`}
              />
              <span className="tabular-nums">{trendTotal}</span>
            </span>
          )}
          {data?.generated_at && (
            <div className="text-[10px] text-muted-foreground">
              {new Date(data.generated_at).toLocaleString()}
            </div>
          )}
          <button
            onClick={load}
            className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted"
            data-testid={`${testIdPrefix}-reload`}
            title="Reload"
          >
            <RefreshCw className={`h-3 w-3 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {loading && !data && (
        <div className="p-6 text-xs text-muted-foreground text-center">Loading…</div>
      )}
      {error && (
        <div className="p-4 text-xs text-red-600" data-testid={`${testIdPrefix}-error`}>
          Failed to load pattern health: {error}
        </div>
      )}

      {summary && (
        <div className="p-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Metric
            label="Trusted" value={summary.trusted ?? 0}
            tone="text-emerald-600" hint="Acceptance ≥ 90%"
            testId={`${testIdPrefix}-trusted`}
          />
          <Metric
            label="Drifting" value={summary.drifting ?? 0}
            tone="text-amber-600" hint="Needs feedback"
            testId={`${testIdPrefix}-drifting`}
          />
          <Metric
            label="Retired" value={summary.retired ?? 0}
            tone="text-red-600" hint="Acceptance < 40%"
            testId={`${testIdPrefix}-retired`}
          />
          <Metric
            label="Unscored" value={summary.unscored ?? 0}
            hint="No feedback yet"
            testId={`${testIdPrefix}-unscored`}
          />
        </div>
      )}

      {/* Combined mode — per-domain pills with sparklines */}
      {isCombined && perDomain.length > 0 && (
        <div className="border-t border-border p-3 flex flex-wrap gap-4 text-[11px] text-muted-foreground">
          {perDomain.map((r) => {
            const t7 = Array.isArray(r.trend_7d)
              ? r.trend_7d.reduce((a, p) => a + (Number(p.count) || 0), 0)
              : 0;
            return (
              <span
                key={r.domain}
                className="flex items-center gap-2"
                data-testid={`unified-domain-${r.domain}`}
              >
                <span className="font-mono">{r.domain}</span>:{' '}
                <span className="text-emerald-600">{r.summary?.trusted ?? 0}✓</span>{' / '}
                <span className="text-amber-600">{r.summary?.drifting ?? 0}⚠</span>{' / '}
                <span className="text-red-600">{r.summary?.retired ?? 0}✗</span>
                {Array.isArray(r.trend_7d) && r.trend_7d.length > 0 && (
                  <span
                    className="flex items-center gap-1 pl-2 border-l border-border"
                    title={`Last 7d — ${t7} events`}
                  >
                    <Sparkline
                      points={r.trend_7d}
                      className={t7 > 0 ? 'text-sky-500' : 'text-muted-foreground/60'}
                      testId={`sparkline-${r.domain}`}
                    />
                    <span className="text-[10px] tabular-nums">{t7}</span>
                  </span>
                )}
              </span>
            );
          })}
        </div>
      )}

      {/* Domain mode — per-scope table */}
      {!isCombined && showPerScope && perScope.length > 0 && (
        <div className="overflow-x-auto border-t border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                <th className="p-2">{scopeHeader}</th>
                <th className="p-2 text-right">Patterns</th>
                <th className="p-2 text-right">Trusted</th>
                <th className="p-2 text-right">Drifting</th>
                <th className="p-2 text-right">Retired</th>
                <th className="p-2">Last feedback</th>
              </tr>
            </thead>
            <tbody>
              {perScope.slice(0, limit).map((r) => (
                <tr
                  key={r.scope_value || r.customer_no || r.vendor_no}
                  className="border-b border-border/50 hover:bg-muted/30"
                  data-testid={`${testIdPrefix}-row-${r.scope_value || r.customer_no || r.vendor_no}`}
                >
                  <td className="p-2 font-mono">{r.scope_value || r.customer_no || r.vendor_no}</td>
                  <td className="p-2 text-right">{r.patterns_total ?? 0}</td>
                  <td className="p-2 text-right text-emerald-600">{r.trusted || '—'}</td>
                  <td className="p-2 text-right text-amber-600">{r.drifting || '—'}</td>
                  <td className="p-2 text-right text-red-600">{r.retired || '—'}</td>
                  <td className="p-2 text-xs text-muted-foreground">
                    {r.last_feedback_at ? new Date(r.last_feedback_at).toLocaleDateString() : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Domain mode — recent reviewer feedback */}
      {!isCombined && showEvents && recentEvents.length > 0 && (
        <div className="border-t border-border p-3">
          <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1">
            <Archive className="h-3 w-3" /> Recent reviewer feedback
          </div>
          <div className="space-y-1 text-xs max-h-48 overflow-y-auto">
            {recentEvents.slice(0, 10).map((e) => (
              <div key={e.id} className="flex items-center justify-between gap-2 py-0.5">
                <div className="truncate">
                  <span className="font-mono text-[10px] uppercase text-muted-foreground">{e.event_type}</span>
                  {e.scope_value && <span className="ml-2 font-mono">{e.scope_value}</span>}
                  {e.target?.item_no && <span className="ml-2 font-mono">{e.target.item_no}</span>}
                </div>
                <div className="text-[10px] text-muted-foreground shrink-0">
                  {new Date(e.created_at).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default PatternHealthPanel;
