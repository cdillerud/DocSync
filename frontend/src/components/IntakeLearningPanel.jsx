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
 *
 * v2.3.0: inline reviewer feedback buttons — every click becomes
 * training data for the underlying pattern.
 */
import { useState } from 'react';
import { AlertTriangle, Check, Sparkles, Info, TrendingUp, Package, ThumbsUp, ThumbsDown, Users, ArrowUpRight } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

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

export default function IntakeLearningPanel({ insights, compact = false, docId, stagingId }) {
  const [feedbackState, setFeedbackState] = useState({}); // key → 'accepted'|'rejected'|'loading'

  const sendFeedback = async (key, eventType, payload) => {
    setFeedbackState((s) => ({ ...s, [key]: 'loading' }));
    try {
      await fetch(`${API}/api/intake/insights/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: eventType,
          doc_id: docId || null,
          staging_id: stagingId || null,
          customer_no: insights?.customer_no || null,
          ...payload,
        }),
      });
      setFeedbackState((s) => ({
        ...s,
        [key]: eventType.includes('accepted') || eventType.includes('confirmed') || eventType === 'unmatched_item_confirmed_new'
          ? 'accepted'
          : 'rejected',
      }));
    } catch {
      setFeedbackState((s) => ({ ...s, [key]: 'error' }));
    }
  };

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

      {/* Peer matches (v2.4.0 — cold-start bootstrap from similar customers) */}
      {insights.peer_matches && insights.peer_matches.length > 0 && !compact && (
        <div data-testid="intake-learning-peer-matches" className="rounded-md border border-purple-500/30 bg-purple-500/5 p-3 space-y-2">
          <div className="flex items-center gap-2 text-xs font-medium text-purple-700">
            <Users className="h-3.5 w-3.5" /> Peer-matched suggestions ({insights.peer_matches.length} similar customer{insights.peer_matches.length === 1 ? '' : 's'})
          </div>
          <div className="text-[10px] text-muted-foreground">
            Cold-start bootstrap — inherited from the most similar known customer. Review carefully before accepting; accepted items become this customer's own learned pattern.
          </div>
          {insights.peer_matches.map((m, idx) => (
            <div key={`peer-${idx}`} className="rounded border border-border bg-card/50 p-2 space-y-1">
              <div className="flex items-center justify-between">
                <div className="text-xs font-mono">
                  {m.customer_no} <span className="text-muted-foreground">· {Math.round((m.similarity || 0) * 100)}% similar · {m.pattern_count} pattern{m.pattern_count === 1 ? '' : 's'}</span>
                </div>
              </div>
              {m.matched_tokens && m.matched_tokens.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {m.matched_tokens.slice(0, 8).map((t, i) => (
                    <span key={i} className="text-[10px] font-mono bg-purple-500/10 text-purple-700 px-1 rounded">{t}</span>
                  ))}
                </div>
              )}
              {m.inherited_suggestions && m.inherited_suggestions.length > 0 && (
                <div className="space-y-1 pt-1">
                  {m.inherited_suggestions.slice(0, 5).map((s, i) => {
                    const key = `peer-${m.customer_no}-${s.item_no}-${i}`;
                    const state = feedbackState[key];
                    return (
                      <div key={i} className="flex items-center justify-between gap-2 text-xs bg-background/50 rounded px-2 py-1">
                        <div className="min-w-0 truncate">
                          <span className="font-mono">{s.item_no || '—'}</span>
                          {s.description ? ` · ${s.description}` : ''} · qty <b>{s.quantity}</b>
                          <span className="text-muted-foreground ml-1">({s.occurrences}×)</span>
                        </div>
                        <div className="shrink-0">
                          {state === 'accepted' && <span className="text-emerald-600 text-[10px]">promoted ✓</span>}
                          {state === 'loading' && <span className="text-[10px] text-muted-foreground">…</span>}
                          {!state && insights.customer_no && (
                            <button
                              onClick={async () => {
                                setFeedbackState((st) => ({ ...st, [key]: 'loading' }));
                                try {
                                  await fetch(`${API}/api/intake/insights/promote-inherited`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({
                                      target_customer_no: insights.customer_no,
                                      source_customer_no: m.customer_no,
                                      item_no: s.item_no,
                                      trigger_item: s.trigger_item,
                                      doc_id: docId,
                                    }),
                                  });
                                  setFeedbackState((st) => ({ ...st, [key]: 'accepted' }));
                                } catch {
                                  setFeedbackState((st) => ({ ...st, [key]: 'error' }));
                                }
                              }}
                              className="p-1 rounded hover:bg-purple-500/20 text-muted-foreground hover:text-purple-700"
                              title={`Promote this inherited line into ${insights.customer_no}'s own pattern`}
                              data-testid={`peer-promote-${idx}-${i}`}
                            >
                              <ArrowUpRight className="h-3 w-3" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          ))}
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
                {violations.slice(0, 6).map((v, i) => {
                  const key = `bounds-${v.item_no}-${i}`;
                  const state = feedbackState[key];
                  return (
                    <div key={i} className="rounded border border-amber-500/30 bg-amber-500/5 px-2 py-1 flex items-center justify-between gap-2">
                      <div className="min-w-0">
                        <span className="font-mono">{v.item_no}</span> — ordered{' '}
                        <b>{v.po_quantity}</b>, expected {v.expected_min}–{v.expected_max}{' '}
                        (mean {v.mean}, ±2σ · {v.severity})
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {state === 'accepted' && <span className="text-emerald-600 text-[10px]">confirmed</span>}
                        {state === 'rejected' && <span className="text-sky-600 text-[10px]">overridden</span>}
                        {!state && (
                          <>
                            <button
                              onClick={() => sendFeedback(key, 'bounds_violation_confirmed', { item_no: v.item_no })}
                              className="p-1 rounded hover:bg-amber-500/20 text-muted-foreground hover:text-amber-700"
                              title="Confirm this was abnormal — tightens pattern"
                              data-testid={`bounds-confirm-${i}`}
                            >
                              <ThumbsUp className="h-3 w-3" />
                            </button>
                            <button
                              onClick={() => sendFeedback(key, 'bounds_violation_overridden', { item_no: v.item_no })}
                              className="p-1 rounded hover:bg-sky-500/20 text-muted-foreground hover:text-sky-700"
                              title="Qty is fine — widens the pattern's accepted range"
                              data-testid={`bounds-override-${i}`}
                            >
                              <ThumbsDown className="h-3 w-3" />
                            </button>
                          </>
                        )}
                        {state === 'loading' && <span className="text-[10px] text-muted-foreground">…</span>}
                      </div>
                    </div>
                  );
                })}
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
                {suggestions.slice(0, 8).map((s, i) => {
                  const key = `sug-${s.item_no}-${i}`;
                  const state = feedbackState[key];
                  return (
                    <div key={i} className="rounded border border-border bg-muted/30 px-2 py-1 flex items-center justify-between gap-2">
                      <div className="min-w-0 truncate">
                        <span className="font-mono">{s.item_no || '—'}</span>
                        {s.description ? ` · ${s.description}` : ''} · qty{' '}
                        <b>{s.quantity}</b>
                        <span className="text-muted-foreground ml-1">({s.occurrences}×, {Math.round((s.frequency || 0) * 100)}%)</span>
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        {state === 'accepted' && <span className="text-emerald-600 text-[10px]">kept ✓</span>}
                        {state === 'rejected' && <span className="text-red-600 text-[10px]">dropped</span>}
                        {!state && (
                          <>
                            <button
                              onClick={() => sendFeedback(key, 'suggestion_accepted', { item_no: s.item_no, trigger_item: s.trigger_item })}
                              className="p-1 rounded hover:bg-emerald-500/20 text-muted-foreground hover:text-emerald-700"
                              title="Keep this suggestion — boosts pattern"
                              data-testid={`sug-accept-${i}`}
                            >
                              <ThumbsUp className="h-3 w-3" />
                            </button>
                            <button
                              onClick={() => sendFeedback(key, 'suggestion_rejected', { item_no: s.item_no, trigger_item: s.trigger_item })}
                              className="p-1 rounded hover:bg-red-500/20 text-muted-foreground hover:text-red-700"
                              title="Drop — decays pattern"
                              data-testid={`sug-reject-${i}`}
                            >
                              <ThumbsDown className="h-3 w-3" />
                            </button>
                          </>
                        )}
                        {state === 'loading' && <span className="text-[10px] text-muted-foreground">…</span>}
                      </div>
                    </div>
                  );
                })}
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
                <div className="text-xs space-y-1">
                  {iv.unmatched_items.slice(0, 5).map((u, i) => {
                    const key = `item-${u.item_no}-${i}`;
                    const state = feedbackState[key];
                    return (
                      <div key={i} className="rounded border border-border/50 px-2 py-1 flex items-center justify-between gap-2">
                        <div className="min-w-0 truncate">
                          <span className="font-mono">{u.item_no || '(no item_no)'}</span>
                          {u.description ? ` — ${u.description}` : ''}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          {state === 'accepted' && <span className="text-emerald-600 text-[10px]">new ✓</span>}
                          {!state && (
                            <button
                              onClick={() => sendFeedback(key, 'unmatched_item_confirmed_new', { item_no: u.item_no, extra: { description: u.description } })}
                              className="p-1 rounded hover:bg-emerald-500/20 text-muted-foreground hover:text-emerald-700"
                              title="Confirm this is a new item — queues for BC admin"
                              data-testid={`item-confirm-${i}`}
                            >
                              <Check className="h-3 w-3" />
                            </button>
                          )}
                          {state === 'loading' && <span className="text-[10px] text-muted-foreground">…</span>}
                        </div>
                      </div>
                    );
                  })}
                  {iv.lines_unmatched > 5 && (
                    <div className="text-muted-foreground">…and {iv.lines_unmatched - 5} more</div>
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
