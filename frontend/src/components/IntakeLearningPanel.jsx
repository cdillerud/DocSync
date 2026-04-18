/**
 * IntakeLearningPanel — drop-in component that renders the
 * Giovanni-style BC+Spiro intake insights for any document or
 * XLS staging record.
 *
 * Handles all three states transparently:
 *   1. No insights yet  → small empty state
 *   2. Cold start       → shows "no BC learning yet" with reason
 *   3. Learned          → customer chip + suggestions + bounds +
 *                         item-catalog match summary + actionable flag
 */
import { AlertTriangle, Check, Sparkles, Info, TrendingUp, Package } from 'lucide-react';

function Pill({ children, tone = 'neutral' }) {
  const map = {
    neutral: 'bg-muted text-muted-foreground border-border',
    success: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/30',
    warn: 'bg-amber-500/10 text-amber-600 border-amber-500/30',
    danger: 'bg-red-500/10 text-red-600 border-red-500/30',
    info: 'bg-sky-500/10 text-sky-600 border-sky-500/30',
  };
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[11px] font-medium ${map[tone]}`}>
      {children}
    </span>
  );
}

export default function IntakeLearningPanel({ insights, compact = false }) {
  if (!insights) {
    return (
      <div
        className="rounded-lg border border-dashed border-border p-4 bg-card/50"
        data-testid="intake-learning-empty"
      >
        <div className="text-sm text-muted-foreground flex items-center gap-2">
          <Info className="h-4 w-4" />
          No BC/Spiro learning insights yet — will generate on next readiness pass.
        </div>
      </div>
    );
  }

  if (insights.skipped) {
    return (
      <div className="rounded-lg border border-border p-3 bg-card/50 text-xs text-muted-foreground" data-testid="intake-learning-skipped">
        Intake learning skipped: {insights.skip_reason}
      </div>
    );
  }

  const coldStart = insights.cold_start === true;
  const bounds = insights.bounds_check || {};
  const violations = bounds.violations || [];
  const suggestions = insights.suggested_lines || [];
  const iv = insights.item_validation || {};
  const actionable = insights.has_actionable_findings;
  const spiroIsr = insights.spiro_assigned_isr;
  const ran = insights.ran_at ? new Date(insights.ran_at).toLocaleString() : null;

  return (
    <div
      className="rounded-lg border border-border bg-card p-4 space-y-3"
      data-testid="intake-learning-panel"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-amber-500" />
          <div className="text-sm font-semibold">BC + Spiro Intake Intelligence</div>
        </div>
        <div className="flex items-center gap-2">
          {actionable && !coldStart ? (
            <Pill tone="warn"><AlertTriangle className="h-3 w-3" /> Review suggested</Pill>
          ) : actionable && coldStart ? (
            <Pill tone="info"><Info className="h-3 w-3" /> New customer — needs mapping</Pill>
          ) : (
            <Pill tone="success"><Check className="h-3 w-3" /> No issues</Pill>
          )}
          {ran && <span className="text-[10px] text-muted-foreground">{ran}</span>}
        </div>
      </div>

      {/* Customer + Spiro row */}
      <div className="flex flex-wrap gap-2 items-center">
        {insights.customer_no ? (
          <Pill tone="info">BC: {insights.customer_no}{insights.customer_name ? ` — ${insights.customer_name}` : ''}</Pill>
        ) : insights.customer_name ? (
          <Pill tone="warn">Unmatched: {insights.customer_name}</Pill>
        ) : (
          <Pill tone="neutral">No customer extracted</Pill>
        )}
        {insights.spiro_company_name && (
          <Pill tone="info">Spiro: {insights.spiro_company_name}</Pill>
        )}
        {spiroIsr && <Pill tone="neutral">ISR: {spiroIsr}</Pill>}
        {insights.spiro_opportunities > 0 && (
          <Pill tone="success"><TrendingUp className="h-3 w-3" /> {insights.spiro_opportunities} opp</Pill>
        )}
        {insights.patterns_available > 0 ? (
          <Pill tone="success">{insights.patterns_available} learned pattern{insights.patterns_available === 1 ? '' : 's'}</Pill>
        ) : (
          <Pill tone="neutral">0 patterns</Pill>
        )}
      </div>

      {/* Cold-start notice (always transparent when true) */}
      {coldStart && (
        <div
          className="rounded-md border border-sky-500/30 bg-sky-500/5 p-3 text-xs"
          data-testid="intake-learning-cold-start"
        >
          <div className="flex items-center gap-2 font-medium text-sky-700">
            <Info className="h-3.5 w-3.5" /> No BC learning available yet
          </div>
          <div className="text-muted-foreground mt-1">
            {insights.cold_start_reason || 'Not enough historical data to generate predictions.'}
          </div>
        </div>
      )}

      {compact ? null : (
        <>
          {/* Bounds violations */}
          {violations.length > 0 && (
            <div data-testid="intake-learning-bounds">
              <div className="text-xs font-medium mb-1 text-amber-600 flex items-center gap-1">
                <AlertTriangle className="h-3.5 w-3.5" /> Quantity Bounds ({violations.length})
              </div>
              <div className="space-y-1 text-xs">
                {violations.slice(0, 6).map((v, i) => (
                  <div key={i} className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1">
                    <span className="font-mono">{v.item_no}</span> — ordered{' '}
                    <b>{v.po_quantity}</b>, expected {v.expected_min}–{v.expected_max}{' '}
                    (mean {v.mean}, ±2σ · {v.severity})
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Suggested recurring lines */}
          {suggestions.length > 0 && (
            <div data-testid="intake-learning-suggestions">
              <div className="text-xs font-medium mb-1 flex items-center gap-1">
                <Sparkles className="h-3.5 w-3.5 text-amber-500" /> Suggested Recurring Lines ({suggestions.length})
              </div>
              <div className="space-y-1 text-xs">
                {suggestions.slice(0, 8).map((s, i) => (
                  <div key={i} className="rounded border border-border bg-muted/30 px-2 py-1 flex items-center justify-between">
                    <div>
                      <span className="font-mono">{s.item_no || '—'}</span>
                      {s.description ? ` · ${s.description}` : ''} · qty{' '}
                      <b>{s.quantity}</b>
                    </div>
                    <div className="text-muted-foreground">
                      seen {s.occurrences}× ({Math.round((s.frequency || 0) * 100)}%)
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Item-catalog match summary */}
          {iv && iv.lines_total > 0 && !iv.skipped && (
            <div data-testid="intake-learning-items">
              <div className="text-xs font-medium mb-1 flex items-center gap-1">
                <Package className="h-3.5 w-3.5" /> BC Item Catalog ({iv.lines_matched}/{iv.lines_total} matched · {iv.match_rate}%)
              </div>
              {iv.lines_unmatched > 0 && iv.unmatched_items && (
                <div className="text-xs text-muted-foreground space-y-0.5">
                  {iv.unmatched_items.slice(0, 5).map((u, i) => (
                    <div key={i}>
                      <span className="font-mono">{u.item_no || '(no item_no)'}</span>
                      {u.description ? ` — ${u.description}` : ''}
                    </div>
                  ))}
                  {iv.lines_unmatched > 5 && (
                    <div>…and {iv.lines_unmatched - 5} more</div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Errors */}
          {insights.errors && insights.errors.length > 0 && (
            <div className="text-[11px] text-red-600 space-y-0.5" data-testid="intake-learning-errors">
              {insights.errors.slice(0, 3).map((e, i) => (
                <div key={i}>• {e}</div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}
