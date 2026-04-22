import React, { useState, useEffect, useMemo } from 'react';
import { ChevronDown, ChevronRight, Clock, User, Bot, CheckCircle2, XCircle, AlertTriangle, RotateCw } from 'lucide-react';
import { getBcStatus } from '../lib/api';

/**
 * PostingAttemptsHistory — A1 (Lane A) UX for historical BC posting attempts.
 *
 * Spec (per signed declaration §1 A1 UX):
 *   - Collapsed by default.
 *   - Auto-expands if bc_posting_status ∈ {failed, partial, pending_retry}.
 *   - Most recent attempt at top.
 *   - Each entry shows timestamp, status, actor, truncated error (expand-for-full),
 *     and gate_id when the attempt was blocked pre-submission.
 *
 * Data source: GET /api/ap-review/documents/{doc_id}/bc-status → bc_posting_attempts[].
 */
const STATUS_META = {
  posted: { icon: CheckCircle2, color: 'text-emerald-600 dark:text-emerald-400', label: 'Posted', bg: 'bg-emerald-50 dark:bg-emerald-950/30' },
  failed: { icon: XCircle, color: 'text-red-600 dark:text-red-400', label: 'Failed', bg: 'bg-red-50 dark:bg-red-950/30' },
  partial: { icon: AlertTriangle, color: 'text-amber-600 dark:text-amber-400', label: 'Partial', bg: 'bg-amber-50 dark:bg-amber-950/30' },
  pending_retry: { icon: RotateCw, color: 'text-blue-600 dark:text-blue-400', label: 'Pending Retry', bg: 'bg-blue-50 dark:bg-blue-950/30' },
};

function formatTimestamp(iso) {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function ActorBadge({ actor }) {
  if (!actor) return null;
  const isUser = actor.startsWith('user:');
  const isEngine = actor.startsWith('engine:');
  const Icon = isUser ? User : isEngine ? Bot : Clock;
  const label = isUser
    ? actor.slice('user:'.length)
    : isEngine
      ? actor.slice('engine:'.length)
      : actor;
  return (
    <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground" data-testid="posting-attempt-actor">
      <Icon className="w-3 h-3" />
      {label}
    </span>
  );
}

function AttemptRow({ attempt, index }) {
  const [expanded, setExpanded] = useState(false);
  const meta = STATUS_META[attempt.status] || STATUS_META.failed;
  const Icon = meta.icon;
  const hasDetail = !!(attempt.error_full || attempt.bc_response_snippet || attempt.partial_lines || attempt.gate_id);
  return (
    <div
      className={`rounded border border-border/60 ${meta.bg} px-2.5 py-1.5 text-xs`}
      data-testid={`posting-attempt-row-${index}`}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${meta.color}`} />
          <span className={`font-medium ${meta.color}`}>#{attempt.attempt_n} · {meta.label}</span>
          <span className="text-muted-foreground truncate">{formatTimestamp(attempt.finished_utc)}</span>
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          <ActorBadge actor={attempt.actor} />
          {hasDetail && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="text-[10px] text-muted-foreground hover:text-foreground underline"
              data-testid={`posting-attempt-toggle-${index}`}
            >
              {expanded ? 'hide' : 'details'}
            </button>
          )}
        </div>
      </div>

      {attempt.error && (
        <p className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2" data-testid={`posting-attempt-error-${index}`}>
          {attempt.error}
        </p>
      )}
      {attempt.bc_record_no && attempt.status === 'posted' && (
        <p className="mt-0.5 text-[11px] font-mono text-muted-foreground">
          BC: {attempt.bc_record_no}
        </p>
      )}

      {expanded && (
        <div className="mt-2 space-y-1 border-t border-border/60 pt-1.5">
          {attempt.gate_id && (
            <p className="text-[11px]">
              <span className="text-muted-foreground">Blocked by gate:</span>{' '}
              <code className="font-mono">{attempt.gate_id}</code>
            </p>
          )}
          {attempt.partial_lines && (
            <p className="text-[11px]">
              <span className="text-muted-foreground">Lines:</span>{' '}
              {attempt.partial_lines.added ?? 0} of {attempt.partial_lines.total ?? 0} accepted
            </p>
          )}
          {attempt.retry_reason && (
            <p className="text-[11px]">
              <span className="text-muted-foreground">Retry reason:</span> {attempt.retry_reason}
            </p>
          )}
          {attempt.error_full && (
            <pre className="text-[11px] whitespace-pre-wrap break-words bg-muted/50 rounded p-1.5 max-h-40 overflow-auto">
              {attempt.error_full}
            </pre>
          )}
          {attempt.bc_response_snippet && !attempt.error_full && (
            <pre className="text-[11px] whitespace-pre-wrap break-words bg-muted/50 rounded p-1.5 max-h-40 overflow-auto">
              {attempt.bc_response_snippet}
            </pre>
          )}
          {attempt.correlation_id && (
            <p className="text-[10px] text-muted-foreground">
              correlation: <code className="font-mono">{attempt.correlation_id}</code>
            </p>
          )}
        </div>
      )}
    </div>
  );
}

export default function PostingAttemptsHistory({ document }) {
  const [attempts, setAttempts] = useState(document?.bc_posting_attempts || []);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);

  const status = document?.bc_posting_status || '';
  // Auto-expand on failure / partial / pending_retry per §1 UX spec.
  const shouldAutoExpand = ['failed', 'partial', 'pending_retry'].includes(status);

  useEffect(() => {
    // If the document doesn't already carry attempts, fetch the fresh view.
    let cancel = false;
    const load = async () => {
      if (!document?.id) return;
      if (document.bc_posting_attempts && document.bc_posting_attempts.length > 0) {
        setAttempts(document.bc_posting_attempts);
        return;
      }
      setLoading(true);
      try {
        const res = await getBcStatus(document.id);
        if (!cancel) {
          setAttempts(res.data?.bc_posting_attempts || []);
        }
      } catch {
        /* silent — absence of history isn't a user-facing failure */
      } finally {
        if (!cancel) setLoading(false);
      }
    };
    load();
    return () => { cancel = true; };
  }, [document?.id, document?.bc_posting_attempts]);

  useEffect(() => { if (shouldAutoExpand) setOpen(true); }, [shouldAutoExpand, status]);

  // Newest first in display (Mongo $push appends at the tail).
  const ordered = useMemo(() => (attempts || []).slice().reverse(), [attempts]);

  if (!document || ordered.length === 0) return null;

  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div
      className="border border-border/60 rounded-md bg-muted/30"
      data-testid="posting-attempts-history"
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs font-medium hover:bg-muted/50 rounded-md"
        data-testid="posting-attempts-toggle"
      >
        <span className="flex items-center gap-1.5">
          <Chevron className="w-3.5 h-3.5" />
          Posting History
          <span className="text-muted-foreground font-normal">({ordered.length} attempt{ordered.length === 1 ? '' : 's'})</span>
        </span>
        {loading && <span className="text-[10px] text-muted-foreground">loading…</span>}
      </button>
      {open && (
        <div className="px-2.5 pb-2 pt-0.5 space-y-1.5" data-testid="posting-attempts-list">
          {ordered.map((a, idx) => (
            <AttemptRow key={a.attempt_id || `${a.attempt_n}-${a.finished_utc}`} attempt={a} index={idx} />
          ))}
        </div>
      )}
    </div>
  );
}
