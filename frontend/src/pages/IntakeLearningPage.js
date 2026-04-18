/**
 * IntakeLearningPage — hub-wide dashboard for BC + Spiro intake
 * learning coverage.  Replaces the Giovanni-only view with a
 * whole-hub picture:
 *   • Coverage KPIs (eligible docs, with insights, cold-start %)
 *   • Top customers by doc volume + learned patterns
 *   • XLS staging coverage
 *   • Actionable findings + backfill button
 */
import { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Sparkles, AlertTriangle, Info, Database, TrendingUp, ShieldCheck, Archive, Activity } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function Metric({ label, value, hint, tone = 'text-foreground' }) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={`text-2xl font-bold mt-1 ${tone}`} data-testid={`metric-${label.replace(/\s+/g, '-').toLowerCase()}`}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}

export default function IntakeLearningPage() {
  const [summary, setSummary] = useState(null);
  const [flagged, setFlagged] = useState([]);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, flaggedRes, healthRes] = await Promise.all([
        fetch(`${API}/api/intake/learning/summary`),
        fetch(`${API}/api/intake/flagged?limit=25`),
        fetch(`${API}/api/intake/learning/pattern-health?limit=25`),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (flaggedRes.ok) {
        const data = await flaggedRes.json();
        setFlagged(data.documents || []);
      }
      if (healthRes.ok) setHealth(await healthRes.json());
    } finally {
      setLoading(false);
    }
  }, []);

  const runBackfill = async (forceAll = false) => {
    setRunning(true);
    try {
      const res = await fetch(
        `${API}/api/intake/learning/backfill?limit=500&only_missing=${forceAll ? 'false' : 'true'}`,
        { method: 'POST' },
      );
      const data = await res.json();
      alert(
        `Backfill complete — ` +
        `hub: ${data.hub_documents.processed} processed, ` +
        `${data.hub_documents.actionable} actionable; ` +
        `XLS: ${data.xls_staging.processed} processed, ` +
        `${data.xls_staging.actionable} actionable.`,
      );
      await load();
    } catch (e) {
      alert(`Backfill failed: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  const runHygiene = async () => {
    setRunning(true);
    try {
      const res = await fetch(`${API}/api/intake/learning/hygiene`, { method: 'POST' });
      const data = await res.json();
      alert(`Pattern hygiene — scanned ${data.patterns_scanned}, retired ${data.retired}, promoted ${data.promoted}.`);
      await load();
    } catch (e) {
      alert(`Hygiene failed: ${e.message}`);
    } finally {
      setRunning(false);
    }
  };

  useEffect(() => { load(); }, [load]);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24 text-muted-foreground">
        <RefreshCw className="h-5 w-5 animate-spin mr-2" /> Loading intake-learning summary…
      </div>
    );
  }

  const hub = summary?.hub || {};
  const xls = summary?.xls_staging || {};
  const tops = summary?.top_customers || [];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto" data-testid="intake-learning-page">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Sparkles className="h-5 w-5 text-amber-500" /> Intake Learning
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-2xl">
            Hub-wide Giovanni-style BC + Spiro learning. Every ingested PO,
            sales order, invoice and inventory spreadsheet is cross-referenced
            against Business Central posted history + Spiro opportunities to
            surface anomalies, suggested lines, and cold-start gaps. Read-only —
            never writes to BC.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => load()}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted"
            data-testid="intake-learning-reload"
          >
            <RefreshCw className="h-4 w-4 inline mr-1" /> Refresh
          </button>
          <button
            disabled={running}
            onClick={() => runBackfill(false)}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            data-testid="intake-learning-backfill"
          >
            {running ? 'Running…' : 'Backfill new docs'}
          </button>
          <button
            disabled={running}
            onClick={() => runBackfill(true)}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted disabled:opacity-50"
            title="Re-run learning on every doc, ignoring existing insights"
            data-testid="intake-learning-force-backfill"
          >
            Force re-run all
          </button>
          <button
            disabled={running}
            onClick={runHygiene}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted disabled:opacity-50"
            title="Retire low-confidence patterns, promote trusted ones"
            data-testid="intake-learning-hygiene"
          >
            <Activity className="h-4 w-4 inline mr-1" /> Pattern hygiene
          </button>
        </div>
      </div>

      {/* Hub KPIs */}
      <div>
        <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-2">
          <Database className="h-3.5 w-3.5" /> Hub Documents
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-3">
          <Metric label="Eligible Docs" value={hub.eligible_docs ?? 0} />
          <Metric label="With Insights" value={hub.with_insights ?? 0} hint={`${hub.coverage_pct ?? 0}% coverage`} tone="text-sky-600" />
          <Metric label="Cold Start" value={hub.cold_start ?? 0} tone="text-amber-600" hint="No BC history yet" />
          <Metric label="Actionable" value={hub.actionable_findings ?? 0} tone="text-amber-600" />
          <Metric label="Bounds Violations" value={hub.bounds_violations ?? 0} tone="text-red-600" />
          <Metric label="XLS Staging" value={xls.with_insights ?? 0} hint={`/${xls.total ?? 0} total`} />
        </div>
      </div>

      {/* Top customers */}
      <div className="rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="text-sm font-semibold flex items-center gap-2">
            <TrendingUp className="h-4 w-4" /> Top Customers by Learning Coverage
          </div>
          <div className="text-xs text-muted-foreground">{tops.length} customers</div>
        </div>
        {tops.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground text-center">
            No learned customers yet. Run the backfill or ingest more POs to seed patterns.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="p-2">BC Customer</th>
                  <th className="p-2">Name</th>
                  <th className="p-2 text-right">Docs</th>
                  <th className="p-2 text-right">Patterns</th>
                  <th className="p-2 text-right">Cold-start</th>
                  <th className="p-2 text-right">Actionable</th>
                </tr>
              </thead>
              <tbody>
                {tops.map((c) => (
                  <tr key={c.customer_no} className="border-b border-border/50 hover:bg-muted/30" data-testid={`top-customer-${c.customer_no}`}>
                    <td className="p-2 font-mono">{c.customer_no}</td>
                    <td className="p-2">{c.customer_name || '—'}</td>
                    <td className="p-2 text-right">{c.doc_count}</td>
                    <td className="p-2 text-right">
                      {c.patterns_available > 0 ? (
                        <span className="text-emerald-600 font-medium">{c.patterns_available}</span>
                      ) : (
                        <span className="text-muted-foreground">0</span>
                      )}
                    </td>
                    <td className="p-2 text-right">
                      {c.cold_start_docs > 0 ? <span className="text-amber-600">{c.cold_start_docs}</span> : '—'}
                    </td>
                    <td className="p-2 text-right">
                      {c.actionable_docs > 0 ? <span className="text-amber-600 font-medium">{c.actionable_docs}</span> : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Pattern Health (Phase D — feedback loop) */}
      <div className="rounded-lg border border-border bg-card" data-testid="pattern-health-panel">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="text-sm font-semibold flex items-center gap-2">
            <ShieldCheck className="h-4 w-4 text-emerald-500" /> Pattern Health
          </div>
          {health?.generated_at && (
            <div className="text-[10px] text-muted-foreground">
              {new Date(health.generated_at).toLocaleString()}
            </div>
          )}
        </div>
        <div className="p-3 grid grid-cols-2 sm:grid-cols-4 gap-3">
          <Metric label="Trusted" value={health?.summary?.trusted ?? 0} tone="text-emerald-600" hint="Acceptance ≥ 90%" />
          <Metric label="Drifting" value={health?.summary?.drifting ?? 0} tone="text-amber-600" hint="Needs feedback" />
          <Metric label="Retired" value={health?.summary?.retired ?? 0} tone="text-red-600" hint="Acceptance < 40%" />
          <Metric label="Unscored" value={health?.summary?.unscored ?? 0} hint="No feedback yet" />
        </div>
        {health?.per_customer?.length > 0 && (
          <div className="overflow-x-auto border-t border-border">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="p-2">Customer</th>
                  <th className="p-2 text-right">Patterns</th>
                  <th className="p-2 text-right">Trusted</th>
                  <th className="p-2 text-right">Drifting</th>
                  <th className="p-2 text-right">Retired</th>
                  <th className="p-2">Last feedback</th>
                </tr>
              </thead>
              <tbody>
                {health.per_customer.slice(0, 15).map((c) => (
                  <tr key={c.customer_no} className="border-b border-border/50 hover:bg-muted/30" data-testid={`pattern-health-row-${c.customer_no}`}>
                    <td className="p-2 font-mono">{c.customer_no}</td>
                    <td className="p-2 text-right">{c.patterns_total}</td>
                    <td className="p-2 text-right text-emerald-600">{c.trusted || '—'}</td>
                    <td className="p-2 text-right text-amber-600">{c.drifting || '—'}</td>
                    <td className="p-2 text-right text-red-600">{c.retired || '—'}</td>
                    <td className="p-2 text-xs text-muted-foreground">
                      {c.last_feedback_at ? new Date(c.last_feedback_at).toLocaleDateString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {health?.recent_events?.length > 0 && (
          <div className="border-t border-border p-3">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground mb-2 flex items-center gap-1">
              <Archive className="h-3 w-3" /> Recent reviewer feedback
            </div>
            <div className="space-y-1 text-xs max-h-48 overflow-y-auto">
              {health.recent_events.slice(0, 10).map((e) => (
                <div key={e.id} className="flex items-center justify-between gap-2 py-0.5">
                  <div className="truncate">
                    <span className="font-mono text-[10px] uppercase text-muted-foreground">{e.event_type}</span>
                    {e.customer_no && <span className="ml-2">{e.customer_no}</span>}
                    {e.item_no && <span className="ml-2 font-mono">{e.item_no}</span>}
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

      {/* Flagged docs */}
      <div className="rounded-lg border border-border bg-card">
        <div className="flex items-center justify-between p-3 border-b border-border">
          <div className="text-sm font-semibold flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-amber-500" /> Flagged for Review
          </div>
          <div className="text-xs text-muted-foreground">{flagged.length}</div>
        </div>
        {flagged.length === 0 ? (
          <div className="p-6 text-sm text-muted-foreground flex items-center justify-center gap-2">
            <Info className="h-4 w-4" /> No docs currently flagged by intake learning.
          </div>
        ) : (
          <div className="divide-y divide-border">
            {flagged.map((d) => {
              const ins = d.intake_insights || {};
              const bv = (ins.bounds_check?.violations || []).length;
              const sl = (ins.suggested_lines || []).length;
              const un = ins.item_validation?.lines_unmatched || 0;
              return (
                <a
                  key={d.id}
                  href={`/documents/${d.id}`}
                  className="block p-3 hover:bg-muted/40"
                  data-testid={`flagged-doc-${d.id.slice(0,8)}`}
                >
                  <div className="flex items-center justify-between gap-3 flex-wrap">
                    <div className="min-w-0">
                      <div className="font-medium truncate">{d.file_name || d.id}</div>
                      <div className="text-xs text-muted-foreground">
                        {d.doc_type} · {ins.customer_no || ins.customer_name || 'no customer'}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 text-[11px]">
                      {bv > 0 && <span className="px-1.5 py-0.5 rounded bg-red-500/10 text-red-600">{bv} bounds</span>}
                      {sl > 0 && <span className="px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-600">{sl} suggested</span>}
                      {un > 0 && <span className="px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-600">{un} unmatched</span>}
                    </div>
                  </div>
                </a>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
