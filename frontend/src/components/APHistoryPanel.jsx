import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import api from '../lib/api';

const REASON_LABELS = {
  suspected_fraud: 'Suspected fraud',
  vendor_unknown: 'Vendor unknown',
  number_or_amount_missing: 'Invoice number or amount missing',
  po_not_in_bc: 'PO not found in BC',
  draft_lines_problem: "Draft lines don't add up",
  routing_uncertain: 'Folder uncertain',
  approval_rejected: 'Approval rejected',
};

const ACTION_LABELS = {
  hold: 'Put on hold',
  release_hold: 'Released from hold',
  request_approval: 'Sent for approval',
  approve: 'Approved',
  reject: 'Rejected',
  folder_decision: 'Folder decided',
  excluded: 'Excluded from processing',
};

function when(value) {
  if (!value) return '';
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? String(value).slice(0, 16) : d.toLocaleString();
}

function money(value) {
  return value == null ? '—' : Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function APHistoryPanel({ documentId }) {
  const [data, setData] = useState(null);

  useEffect(() => {
    let alive = true;
    api.get(`/ap-workflow/document/${encodeURIComponent(documentId)}/ap-summary`)
      .then(({ data: summary }) => { if (alive) setData(summary); })
      .catch(() => { if (alive) setData(null); });
    return () => { alive = false; };
  }, [documentId]);

  if (!data || (!data.stage && !data.bc && data.corrections.length === 0 && data.events.length === 0)) return null;
  const tone = data.stage === 'needs_staff' ? 'border-amber-500/50 text-amber-400'
    : ['in_bc', 'paid', 'ready', 'filed_by_staff'].includes(data.stage) ? 'border-emerald-500/40 text-emerald-400'
      : 'border-border text-muted-foreground';

  return (
    <Card className="border border-border" data-testid="ap-history-panel">
      <CardHeader className="pb-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
            AP history
          </CardTitle>
          <Badge variant="outline" className={tone}>
            {data.stage_label || (data.bc ? 'In BC' : 'Not staged (older than 30 days)')}{data.staff_reason ? ` — ${REASON_LABELS[data.staff_reason] || data.staff_reason}` : ''}
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-1 text-xs">
          {data.suggested_folder && (
            <div><span className="text-muted-foreground">Folder</span> <span className="font-mono">{data.suggested_folder}</span>
              {data.staff_decision ? ' (decided by staff)' : ''}</div>
          )}
          {data.routing_path_accuracy?.n > 0 && (
            <div><span className="text-muted-foreground">This kind of decision matched staff</span> {data.routing_path_accuracy.pct}% of {data.routing_path_accuracy.n}</div>
          )}
          {data.bc && (
            <div><span className="text-muted-foreground">Business Central</span> {data.bc.bc_entity === 'purchase_credit_memo' ? 'credit memo' : 'invoice'} {data.bc.bc_document_no}
              {' '}({data.bc.bc_status}), vendor {data.bc.bc_vendor_no}, {money(data.bc.bc_amount)}{data.bc.bc_order_number ? `, order ${data.bc.bc_order_number}` : ''}</div>
          )}
          {data.bc_draft && (
            <div><span className="text-muted-foreground">Hub draft</span> purchase invoice {data.bc_draft.bc_record_no} in {data.bc_draft.environment} ({data.bc_draft.status}, {data.bc_draft.lines_added}/{data.bc_draft.lines_total} lines)
              {data.bc_draft_readback && (
                <span className="text-muted-foreground">
                  {' '}— checked in BC {when(data.bc_draft_readback.checked_at)}: {data.bc_draft_readback.state === 'gone' ? 'no longer an unposted draft (posted or deleted by AP)' : data.bc_draft_readback.state}
                  {(data.bc_draft_readback.edits || []).length > 0 ? `; AP changed ${data.bc_draft_readback.edits.join('; ')}` : (data.bc_draft_readback.state !== 'gone' ? '; unchanged' : '')}
                </span>
              )}
            </div>
          )}
          {data.approval && (
            <div><span className="text-muted-foreground">Approval</span> {data.approval.approver}: {data.approval.status}
              {data.approval.decided_by ? ` by ${data.approval.decided_by}` : ''}</div>
          )}
          {!data.approval && data.suggested_approver && (
            <div><span className="text-muted-foreground">Approver</span> {data.suggested_approver} (suggested)</div>
          )}
          {data.hold && (
            <div><span className="text-muted-foreground">On hold</span> {data.hold.reason}{data.hold.until ? ` (review ${data.hold.until.slice(0, 10)})` : ''}</div>
          )}
          {data.duplicate_of && (
            <div><span className="text-muted-foreground">Duplicate of</span> <Link className="underline" to={`/documents/${encodeURIComponent(data.duplicate_of)}`}>the original</Link></div>
          )}
          {data.bc_number_typo_suspect && (
            <div className="text-amber-400">Possible typo in BC: invoice {data.bc_number_typo_suspect.hub} was entered as {data.bc_number_typo_suspect.bc}</div>
          )}
          {data.bc_amount_mismatch && (
            <div className="text-amber-400">BC amount {money(data.bc_amount_mismatch.bc)} differs from the document {money(data.bc_amount_mismatch.hub)}</div>
          )}
        </div>

        {data.corrections.length > 0 && (
          <div>
            <div className="text-xs text-muted-foreground mb-1">Corrections the Hub made (and why)</div>
            <ul className="space-y-1 text-xs">
              {data.corrections.map((c, i) => (
                <li key={i} className="flex flex-wrap gap-x-2">
                  <span className="font-medium">{c.what}</span>
                  <span>{c.detail}</span>
                  <span className="text-muted-foreground">— {c.source}{c.at ? `, ${when(c.at)}` : ''}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        <div>
          <div className="text-xs text-muted-foreground mb-1">People</div>
          {data.events.length === 0 ? (
            <p className="text-xs text-muted-foreground">No staff action recorded on this document yet.</p>
          ) : (
            <ul className="space-y-1 text-xs">
              {data.events.map((e, i) => (
                <li key={i} className="flex flex-wrap gap-x-2">
                  <span className="text-muted-foreground">{when(e.at)}</span>
                  <span className="font-medium">{ACTION_LABELS[e.action] || e.action}</span>
                  {e.by && <span>by {e.by}</span>}
                  {e.folder && <span>to <span className="font-mono">{e.folder}</span>{e.hub_suggested && e.hub_suggested !== e.folder ? ` (Hub suggested ${e.hub_suggested})` : ''}</span>}
                  {e.approver && <span>to {e.approver}</span>}
                  {e.reason && <span>— {e.reason}</span>}
                  {e.notes && <span className="italic">“{e.notes}”</span>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

