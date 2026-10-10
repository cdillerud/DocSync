import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import {
  Send, PauseCircle, PlayCircle, CheckCircle2, XCircle, PencilLine, Tags, ScanText, Upload,
  Trash2, Undo2, UserRound, FolderInput, Loader2, Lightbulb,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Input } from './ui/input';
import api from '../lib/api';
import { plainBcError } from '../lib/plainText';

// One place on the document page for everything a person can do with the
// document, grouped by intent (move it along / fix it / remove it), with the
// Hub's suggestion first. Replaces buttons scattered across the page.

const REMOVE_REASONS = [
  { value: 'duplicate_document', label: 'Duplicate', help: 'Another copy is already in the Hub' },
  { value: 'not_business_document', label: 'Not a business document', help: 'Newsletter, reply, signature image…' },
  { value: 'spam_irrelevant', label: 'Spam / irrelevant', help: 'Nobody needs to act on it' },
  { value: 'graphics_artwork', label: 'Artwork / graphics', help: 'Proofs, logos, label art' },
  { value: 'unsupported_document', label: 'Something we don’t process', help: 'Real document, but not AP or Sales work' },
  { value: 'other', label: 'Other', help: 'Say why in the note' },
];

const STAFF_REASON_ADVICE = {
  vendor_unknown: ['The Hub can’t tell which BC vendor sent this.', 'Fix the vendor under “Fix the invoice data”, or remove it if it isn’t an invoice.'],
  number_or_amount_missing: ['The invoice number or amount couldn’t be read.', 'Try “Read the file again”, or type them in under “Fix the invoice data”.'],
  po_not_in_bc: ['The PO on the invoice isn’t in BC.', 'Check the PO number in the invoice data. If it’s right, put it on hold until the PO exists, or send it for approval.'],
  invoice_check: ['The invoice looks unusual (odd number, statement, or maybe a duplicate).', 'Check it against the document. If it is fine, AP enters it; if not, remove it.'],
  draft_lines_problem: ['The Hub couldn’t build the BC lines for a draft.', 'AP enters this one in BC as usual; nothing to fix here.'],
  routing_uncertain: ['The Hub isn’t sure which folder this belongs in.', 'Pick the folder in the Decision Queue; the Hub learns from it.'],
  approval_rejected: ['The approver rejected it.', 'Send it to another approver, put it on hold, or remove it.'],
  routing_error: ['The Hub hit an error choosing a folder.', 'Pick the folder in the Decision Queue.'],
};

// Same wording as sales_stage_service.REASONS.
const SALES_REASON = {
  customer_unknown: 'Which customer is this? The sender is not linked to a BC customer.',
  customer_po_missing: 'No customer PO number was read from the document.',
  items_unknown: 'Some lines could not be matched to a Gamer item.',
  no_lines: 'No order lines were read from the document.',
  draft_problem: 'The Hub could not draft this order in BC.',
  price_unknown: 'No price for some lines (the customer has not bought these items before).',
  totals_differ: 'The lines the Hub would draft do not add up to the PO total.',
};

function advice(doc) {
  const st = doc.ap_stage;
  if (doc.non_transactional || doc.excluded_from_processing) {
    return ['Removed from the queues' + (doc.non_transactional_label ? ` (${doc.non_transactional_label})` : '') + '.', 'Put it back if that was a mistake.', 'muted'];
  }
  if (st === 'needs_staff') {
    const a = STAFF_REASON_ADVICE[doc.staff_reason] || ['A person needs to decide.', 'Use one of the actions below.'];
    return [...a, 'amber'];
  }
  if (st === 'awaiting_approval') return [`Waiting for ${doc.ap_approval?.approver || doc.suggested_approver || 'an approver'} to approve.`, 'Approve or reject it below.', 'sky'];
  if (st === 'on_hold') return [`On hold${doc.ap_hold?.reason ? `: ${doc.ap_hold.reason}` : ''}.`, 'Release it when it can go ahead.', 'sky'];
  if (st === 'ready' && doc.no_draft_reason) return ['Ready for AP to enter in BC. The Hub could not draft it in the sandbox.', `Why no draft: ${doc.no_draft_reason}`, 'emerald'];
  if (['ready', 'drafted', 'awaiting_receipt'].includes(st)) return ['The Hub is handling this one.', 'Nothing to do unless something on it is wrong.', 'emerald'];
  if (['in_bc', 'paid', 'filed_by_staff', 'file_only', 'no_action', 'container'].includes(st)) return ['Done. It is entered, filed, or needs no action.', 'Nothing to do.', 'muted'];
  if (doc.sales_stage === 'needs_rep') {
    const why = SALES_REASON[doc.sales_stage_reason] || 'A rep needs to look at this.';
    const detail = plainBcError(doc.sales_stage_detail);
    return [why + (detail ? ` (${detail})` : ''), 'The assigned rep enters it in BC, or reassign it to the right rep. Remove it if nobody needs to act on it.', 'amber'];
  }
  if (['ready', 'drafted'].includes(doc.sales_stage)) return ['The Hub is drafting this sales order.', 'The rep reviews the draft; nothing else to do.', 'emerald'];
  if (doc.sales_stage) return ['Nothing waiting on a person.', 'Use the actions below only if something is wrong.', 'muted'];
  return ['Not in an AP or Sales queue.', 'Change the document type if it was read as the wrong kind.', 'muted'];
}

const TONE = {
  amber: 'border-l-amber-500 bg-amber-500/5',
  sky: 'border-l-sky-500 bg-sky-500/5',
  emerald: 'border-l-emerald-500 bg-emerald-500/5',
  muted: 'border-l-border',
};

function Action({ icon: Icon, label, help, onClick, active, tone = '', disabled, busy, testid }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled || busy} data-testid={testid}
      className={`flex items-start gap-2 rounded-md border px-3 py-2 text-left transition-colors disabled:opacity-50
        ${active ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'} ${tone}`}>
      {busy ? <Loader2 className="w-4 h-4 mt-0.5 shrink-0 animate-spin" /> : <Icon className="w-4 h-4 mt-0.5 shrink-0" />}
      <span className="min-w-0">
        <span className="block text-sm font-medium leading-tight">{label}</span>
        <span className="block text-[11px] text-muted-foreground leading-snug">{help}</span>
      </span>
    </button>
  );
}

function Group({ title, children }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">{children}</div>
    </div>
  );
}

function actorName() {
  try { return localStorage.getItem('gpi.apActor') || ''; } catch (e) { return ''; }
}

export default function ReviewActionsPanel({ doc, onChanged, onEditType, onReplaceFile }) {
  const navigate = useNavigate();
  const [open, setOpen] = useState(null);           // which inline form is open
  const [busy, setBusy] = useState(null);
  const [note, setNote] = useState('');
  const [holdUntil, setHoldUntil] = useState('');
  const [approvers, setApprovers] = useState([]);
  const [approver, setApprover] = useState('');
  const [reps, setReps] = useState([]);
  const [rep, setRep] = useState('');
  const [removeReason, setRemoveReason] = useState('');

  const isAp = doc.mailbox_category === 'AP' || doc.document_type === 'AP_Invoice' || !!doc.ap_stage;
  const isSales = !!doc.sales_stage || ['SALES', 'Sales'].includes(doc.mailbox_category);
  // The invoice-data form is only on AP invoices (DocumentDetailPage).
  const hasInvoiceForm = doc.document_type === 'AP_Invoice' || doc.suggested_job_type === 'AP_Invoice';
  const removed = !!(doc.non_transactional || doc.excluded_from_processing);
  const st = doc.ap_stage;
  const finished = ['in_bc', 'paid'].includes(st);
  const enc = encodeURIComponent(doc.id);

  useEffect(() => { setOpen(null); setNote(''); setRemoveReason(''); }, [doc.id]);

  const toggle = async (name) => {
    const next = open === name ? null : name;
    setOpen(next);
    setNote('');
    if (next === 'approval' && approvers.length === 0) {
      try {
        const [{ data: p }, { data: s }] = await Promise.all([
          api.get('/ap-workflow/people'),
          api.get(`/ap-workflow/document/${enc}/suggested-approver`).catch(() => ({ data: {} })),
        ]);
        setApprovers((p.people || []).filter(x => x.active !== false && (x.roles || []).includes('approver')));
        if (s?.approver) setApprover(s.approver);
      } catch (e) { toast.error('Could not load approvers'); }
    }
    if (next === 'rep' && reps.length === 0) {
      try {
        const { data } = await api.get('/sales-inbox/reps');
        setReps((data.reps || []).filter(r => r.email !== 'unassigned'));
        setRep(doc.sales_rep?.email || '');
      } catch (e) { toast.error('Could not load reps'); }
    }
  };

  const run = async (name, fn, success) => {
    setBusy(name);
    try {
      await fn();
      toast.success(success);
      setOpen(null);
      setNote('');
      if (onChanged) onChanged();
    } catch (e) {
      toast.error(e.response?.data?.detail || e.message || 'That did not save');
    } finally {
      setBusy(null);
    }
  };

  const by = actorName();
  const post = (path, body) => api.post(`/ap-workflow/document/${enc}/${path}`, { by, ...body });
  const scrollTo = (id) => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

  const [headline, next, tone] = advice(doc);

  return (
    <Card className={`border border-border border-l-4 ${TONE[tone]}`} data-testid="review-actions-panel">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
          What to do with this document
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-2 text-sm">
          <Lightbulb className="w-4 h-4 mt-0.5 shrink-0 text-amber-500" />
          <div><b>{headline}</b> <span className="text-muted-foreground">{next}</span></div>
        </div>

        {!removed && (
          <Group title="Move it along">
            {isAp && st === 'awaiting_approval' && (<>
              <Action icon={CheckCircle2} label="Approve" help="OK to pay; AP enters it in BC" onClick={() => toggle('approve')} active={open === 'approve'} testid="act-approve" />
              <Action icon={XCircle} label="Reject" help="Don't pay; it comes back to AP with your note" onClick={() => toggle('reject')} active={open === 'reject'} testid="act-reject" />
            </>)}
            {isAp && !finished && st !== 'awaiting_approval' && (
              <Action icon={Send} label="Send for approval" help="Ask a named approver to OK it" onClick={() => toggle('approval')} active={open === 'approval'} testid="act-send-approval" />
            )}
            {isAp && !finished && (st === 'on_hold'
              ? <Action icon={PlayCircle} label="Release hold" help="Let it continue where it left off" onClick={() => toggle('release')} active={open === 'release'} testid="act-release" />
              : <Action icon={PauseCircle} label="Put on hold" help="Park it with a reason and a review date" onClick={() => toggle('hold')} active={open === 'hold'} testid="act-hold" />)}
            {isAp && ['routing_uncertain', 'routing_error'].includes(doc.staff_reason) && (
              <Action icon={FolderInput} label="Pick the folder" help="Opens the Decision Queue for this choice" onClick={() => navigate('/decision-queue')} testid="act-folder" />
            )}
            {isSales && (
              <Action icon={UserRound} label={doc.sales_rep?.name ? `Reassign (now ${doc.sales_rep.name})` : 'Assign to a rep'} help="Give it to the inside sales rep who owns it" onClick={() => toggle('rep')} active={open === 'rep'} testid="act-assign-rep" />
            )}
            {!isAp && !isSales && (
              <p className="text-xs text-muted-foreground sm:col-span-2">Nothing to move along: this document isn’t in an AP or Sales queue.</p>
            )}
          </Group>
        )}

        {open === 'approve' || open === 'reject' || open === 'release' ? (
          <div className="rounded-md border border-border p-3 space-y-2">
            <Input placeholder="Note (optional)" value={note} onChange={e => setNote(e.target.value)} className="h-8 text-xs" />
            <div className="flex gap-2">
              <Button size="sm" disabled={!!busy} data-testid="act-confirm"
                onClick={() => run(open, () => post(open === 'release' ? 'release' : open, { notes: note }),
                  open === 'approve' ? 'Approved' : open === 'reject' ? 'Rejected' : 'Released from hold')}>
                {busy ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : null}
                {open === 'approve' ? 'Approve' : open === 'reject' ? 'Reject' : 'Release'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        ) : null}

        {open === 'hold' && (
          <div className="rounded-md border border-border p-3 space-y-2">
            <Input placeholder="Why is it on hold? (required)" value={note} onChange={e => setNote(e.target.value)} className="h-8 text-xs" />
            <label className="flex items-center gap-2 text-xs text-muted-foreground">Review on
              <Input type="date" value={holdUntil} onChange={e => setHoldUntil(e.target.value)} className="h-8 text-xs w-40" />
            </label>
            <div className="flex gap-2">
              <Button size="sm" disabled={!!busy || note.trim().length < 2}
                onClick={() => run('hold', () => api.post(`/ap-workflow/document/${enc}/hold`, { reason: note.trim(), until: holdUntil || null, by }), 'Put on hold')}>
                Put on hold
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        )}

        {open === 'approval' && (
          <div className="rounded-md border border-border p-3 space-y-2">
            <select value={approver} onChange={e => setApprover(e.target.value)} className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs">
              <option value="">Choose an approver…</option>
              {approvers.map(p => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
            <Input placeholder="Note to the approver (optional)" value={note} onChange={e => setNote(e.target.value)} className="h-8 text-xs" />
            <div className="flex gap-2">
              <Button size="sm" disabled={!!busy || !approver}
                onClick={() => run('approval', () => post('request-approval', { approver, notes: note }), `Sent to ${approver}`)}>
                Send
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        )}

        {open === 'rep' && (
          <div className="rounded-md border border-border p-3 space-y-2">
            <select value={rep} onChange={e => setRep(e.target.value)} className="h-8 w-full rounded-md border border-border bg-background px-2 text-xs">
              <option value="">Choose a rep…</option>
              {reps.map(r => <option key={r.email} value={r.email}>{r.name || r.email}</option>)}
            </select>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" disabled={!!busy || !rep}
                onClick={() => run('rep', () => api.post(`/sales-inbox/document/${enc}/assign`, { rep_email: rep, scope: 'document' }), 'Assigned')}>
                This document
              </Button>
              {doc.sales_link?.bc_customer_no && (
                <Button size="sm" variant="outline" disabled={!!busy || !rep}
                  onClick={() => run('rep', () => api.post(`/sales-inbox/document/${enc}/assign`, { rep_email: rep, scope: 'customer' }), `All ${doc.sales_link.bc_customer_no} documents assigned`)}>
                  Every document from this customer
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        )}

        {!removed && (
          <Group title="Fix it">
            {hasInvoiceForm && !finished && (
              <Action icon={PencilLine} label="Fix the invoice data" help="Vendor, number, amount, PO, lines" onClick={() => scrollTo('ap-review-panel')} testid="act-fix-data" />
            )}
            <Action icon={Tags} label="Change the document type" help="It was read as the wrong kind of document" onClick={() => { onEditType && onEditType(); }} testid="act-change-type" />
            {isAp && !finished && (
              <Action icon={ScanText} label="Read the file again" help="Re-read this PDF with AI, then re-check the stage" busy={busy === 'reread'}
                onClick={() => run('reread', async () => {
                  const r = await api.post(`/ap-review/documents/${enc}/extract-invoice-data`);
                  if (r.data && r.data.success === false) throw new Error(r.data.error || 'The file could not be read');
                  await api.post(`/ap-workflow/document/${enc}/restage`);
                }, 'Read again; data and stage updated')} testid="act-reread" />
            )}
            <Action icon={Upload} label="Replace the file" help="Upload a better copy; the Hub reads it again" onClick={() => onReplaceFile && onReplaceFile()} testid="act-replace-file" />
          </Group>
        )}

        <Group title={removed ? 'Removed' : 'Remove it'}>
          {removed ? (
            <Action icon={Undo2} label="Put it back" help="Return it to the queues; the Hub re-checks it" busy={busy === 'restore'}
              onClick={() => run('restore', () => post('restore', {}), 'Put back in the queues')} testid="act-restore" />
          ) : (
            <Action icon={Trash2} label="Remove from the queues" help="Not something anyone acts on. File and history are kept; can be undone"
              onClick={() => toggle('remove')} active={open === 'remove'} tone="hover:border-red-500/50" testid="act-remove" />
          )}
        </Group>

        {open === 'remove' && (
          <div className="rounded-md border border-red-500/40 p-3 space-y-2" data-testid="remove-form">
            <div className="text-xs font-medium">Why remove it?</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              {REMOVE_REASONS.map(r => (
                <label key={r.value} className={`flex items-start gap-2 rounded border px-2 py-1.5 text-xs cursor-pointer ${removeReason === r.value ? 'border-primary bg-primary/10' : 'border-border hover:bg-muted'}`}>
                  <input type="radio" name="remove-reason" className="mt-0.5" checked={removeReason === r.value} onChange={() => setRemoveReason(r.value)} />
                  <span><b className="font-medium">{r.label}</b><span className="block text-muted-foreground">{r.help}</span></span>
                </label>
              ))}
            </div>
            <Input placeholder={removeReason === 'other' ? 'Why? (required)' : 'Note (optional)'} value={note} onChange={e => setNote(e.target.value)} className="h-8 text-xs" />
            <div className="flex gap-2">
              <Button size="sm" variant="destructive" disabled={!!busy || !removeReason || (removeReason === 'other' && !note.trim())}
                onClick={() => run('remove', () => post('remove', { disposition: removeReason, notes: note }), 'Removed from the queues')}>
                Remove
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setOpen(null)}>Cancel</Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
