import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { ClipboardList, RefreshCw, Loader2, CheckCircle2, XCircle, PauseCircle, PlayCircle, ExternalLink, Eye, EyeOff, MessageSquare } from 'lucide-react';
import api from '@/lib/api';
import PDFPreviewPanel from '@/components/PDFPreviewPanel';

const ACTOR_KEY = 'gpi.apActor';

function readActor() {
  try { return localStorage.getItem(ACTOR_KEY) || ''; } catch (e) { return ''; }
}

function money(value) {
  if (value == null) return '—';
  return Number(value).toLocaleString(undefined, { style: 'currency', currency: 'USD' });
}

function daysSince(iso) {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Number.isFinite(ms) ? Math.max(0, Math.floor(ms / 86400000)) : null;
}

function waited(iso) {
  const n = daysSince(iso);
  if (n == null) return '';
  return n === 0 ? 'today' : n === 1 ? '1 day' : `${n} days`;
}

// "S&H Invoices waiting for approval/Ellie to approve" -> "Ellie to approve"
function shortFolder(folder) {
  if (!folder) return '';
  const parts = String(folder).split('/').filter(Boolean);
  return parts[parts.length - 1] || folder;
}

const same = (a, b) => (a || '').trim().toLowerCase() === (b || '').trim().toLowerCase();

export default function APWorkflowPage() {
  const [view, setView] = useState('approvals');
  const [data, setData] = useState(null);
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approverFilter, setApproverFilter] = useState('all');
  const [actor, setActor] = useState(readActor());
  const [me, setMe] = useState(null);
  const [busy, setBusy] = useState(null);
  const [notes, setNotes] = useState({});
  const [noteOpen, setNoteOpen] = useState({});
  const [preview, setPreview] = useState(null);
  const [done, setDone] = useState(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: queueData }, { data: peopleData }, { data: meData }] = await Promise.all([
        api.get('/ap-workflow/queue', { params: { view } }),
        api.get('/ap-workflow/people'),
        api.get('/ap-workflow/me').catch(() => ({ data: null })),
      ]);
      setData(queueData);
      setPeople(peopleData.people || []);
      setMe(meData);
      // Signed in with Microsoft: you act as yourself (the server records it too).
      if (meData?.sso && meData.name) setActor(meData.name);
    } catch (error) {
      toast.error('Failed to load the AP workflow');
    } finally {
      setLoading(false);
    }
  }, [view]);

  useEffect(() => { load(); }, [load]);

  const chooseActor = (name) => {
    setActor(name);
    try { localStorage.setItem(ACTOR_KEY, name); } catch (e) { /* private window */ }
  };

  const today = new Date().toISOString().slice(0, 10);

  const items = useMemo(() => {
    let list = (data?.items || []).filter(d => !done.has(d.id));
    if (view === 'approvals' && approverFilter !== 'all') {
      list = list.filter(d => (d.ap_approval?.approver || d.suggested_approver || 'unassigned') === approverFilter);
    }
    const sorted = [...list];
    if (view === 'approvals') {
      // Oldest first: the one that has waited longest is the one to do next.
      sorted.sort((a, b) => String(a.created_utc || '').localeCompare(String(b.created_utc || '')));
    } else {
      // Review date passed first, then by review date, then holds with no date.
      const key = d => (d.ap_hold?.until ? d.ap_hold.until.slice(0, 10) : '9999');
      sorted.sort((a, b) => key(a).localeCompare(key(b)));
    }
    return sorted;
  }, [data, done, view, approverFilter]);

  const vendorName = doc => doc.vendor_raw || doc.vendor_canonical || doc.file_name;

  const act = async (doc, action) => {
    if (!actor) {
      toast.error('Choose who you are first (top right)');
      return;
    }
    const note = notes[doc.id] || '';
    if (action === 'reject' && !note.trim()) {
      setNoteOpen(previous => ({ ...previous, [doc.id]: 'reject' }));
      toast.message('Say why it is rejected, so the next person knows what to fix');
      return;
    }
    setBusy(doc.id);
    try {
      if (action === 'approve' || action === 'reject') {
        if (!doc.ap_approval) {
          // An S&H invoice waiting by default: record the request first, then the decision.
          await api.post(`/ap-workflow/document/${encodeURIComponent(doc.id)}/request-approval`,
            { approver: doc.suggested_approver || actor, by: actor, notes: 'Waiting for approval (S&H)' });
        }
        await api.post(`/ap-workflow/document/${encodeURIComponent(doc.id)}/${action}`, { by: actor, notes: note });
        toast.success(action === 'approve' ? `Approved — ${vendorName(doc)}` : `Rejected — ${vendorName(doc)}`);
      } else if (action === 'release') {
        await api.post(`/ap-workflow/document/${encodeURIComponent(doc.id)}/release`, { by: actor, notes: note });
        toast.success(`Released from hold — ${vendorName(doc)}`);
      }
      setDone(previous => new Set(previous).add(doc.id));
      if (preview === doc.id) setPreview(null);
    } catch (error) {
      toast.error(error.response?.data?.detail || 'The action did not save');
    } finally {
      setBusy(null);
    }
  };

  const approverCounts = data?.awaiting_by_approver || {};
  const awaitingTotal = Object.values(approverCounts).reduce((a, b) => a + b, 0);
  const overdueCount = view === 'holds' ? items.filter(d => d.ap_hold?.until && d.ap_hold.until.slice(0, 10) < today).length : 0;

  return (
    <div className="space-y-6" data-testid="ap-workflow-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <ClipboardList className="w-6 h-6 mt-1 text-primary" />
          <div>
            <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Approvals and holds</h1>
            <p className="text-sm text-muted-foreground max-w-3xl">
              Invoices waiting for someone to approve them, and invoices AP is holding. Oldest first. Every action
              records who did it and why; nothing is sent to Business Central from here.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {me?.sso ? (
            <span className="text-sm" data-testid="ap-actor-signed-in">
              <span className="text-xs text-muted-foreground mr-1.5">Acting as</span>
              <span className="font-medium">{me.name}</span>
              {me.full_name && me.full_name !== me.name && (
                <span className="text-xs text-muted-foreground ml-1">({me.full_name})</span>
              )}
            </span>
          ) : (<>
          <label className="text-xs text-muted-foreground" htmlFor="ap-actor">Acting as</label>
          <select
            id="ap-actor"
            value={actor}
            onChange={event => chooseActor(event.target.value)}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
            data-testid="ap-actor-select"
          >
            <option value="">Choose your name…</option>
            {people.filter(p => p.active !== false).map(p => (
              <option key={p.name} value={p.name}>{p.name}</option>
            ))}
          </select>
          </>)}
          <Button type="button" size="sm" variant="outline" onClick={load}>
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-border">
        {[['approvals', 'Waiting for approval', awaitingTotal],
          ['holds', 'On hold', data?.holds || 0]].map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            onClick={() => { setView(key); setApproverFilter('all'); setPreview(null); }}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              view === key ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          >
            {label} <span className="opacity-60">{count}</span>
          </button>
        ))}
      </div>

      {view === 'approvals' && Object.keys(approverCounts).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground mr-1">Whose:</span>
          {[['all', 'Everyone'], ...Object.keys(approverCounts).sort().map(k => [k, same(k, actor) ? `${k} (you)` : k])].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setApproverFilter(key)}
              className={`rounded-full border px-3 py-1 text-xs ${
                approverFilter === key ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
            >
              {key === 'unassigned' ? 'No approver yet' : label}{key !== 'all' ? ` ${approverCounts[key]}` : ''}
            </button>
          ))}
        </div>
      )}
      {view === 'holds' && overdueCount > 0 && (
        <p className="text-sm text-amber-500">{overdueCount} hold{overdueCount === 1 ? '' : 's'} past the review date: check whether it can be released.</p>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
        </div>
      ) : items.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <CheckCircle2 className="w-10 h-10 mb-3 text-emerald-500/50" />
          <p className="text-sm font-medium">{view === 'approvals' ? 'Nothing waiting for approval' : 'Nothing on hold'}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {items.map(doc => {
            const approver = doc.ap_approval?.approver || doc.suggested_approver;
            const overdue = doc.ap_hold?.until && doc.ap_hold.until.slice(0, 10) < today;
            const forSomeoneElse = view === 'approvals' && approver && actor && !same(approver, actor);
            const showNote = noteOpen[doc.id];
            const age = daysSince(view === 'holds' ? doc.ap_hold?.at : doc.created_utc);
            return (
              <Card key={doc.id} className={overdue ? 'border-amber-500/50' : ''} data-testid="ap-workflow-item">
                <CardContent className="p-4 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-baseline gap-x-3">
                        <Link to={`/documents/${encodeURIComponent(doc.id)}`} className="text-base font-semibold hover:underline">
                          {doc.vendor_raw || doc.vendor_canonical || 'Unknown vendor'}
                        </Link>
                        {doc.vendor_raw && doc.vendor_canonical && (
                          <span className="font-mono text-xs text-muted-foreground" title="Vendor number in Business Central">{doc.vendor_canonical}</span>
                        )}
                        <span className="text-base font-semibold tabular-nums">{money(doc.amount_float)}</span>
                      </div>
                      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span>Invoice <span className="text-foreground">{doc.invoice_number_clean || '—'}</span></span>
                        {doc.po_number_clean && <span>PO <span className="text-foreground">{doc.po_number_clean}</span></span>}
                        <span>Received {(doc.created_utc || '').slice(0, 10)}</span>
                        {age != null && (
                          <span className={age >= 7 ? 'text-amber-500' : ''}>
                            {view === 'holds' ? 'Held' : 'Waiting'} {waited(view === 'holds' ? doc.ap_hold?.at : doc.created_utc)}
                          </span>
                        )}
                        <span className="font-mono truncate max-w-[22rem]" title={doc.file_name}>{doc.file_name}</span>
                      </div>
                    </div>
                    {view === 'approvals' ? (
                      <Badge variant="outline" className="border-sky-500/40 text-sky-400" title={doc.suggested_folder || undefined}>
                        {approver ? `${approver} to approve` : 'No approver yet'}
                        {!doc.ap_approval && approver ? ' (from folder)' : ''}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className={overdue ? 'border-amber-500/50 text-amber-400' : ''} title={doc.suggested_folder || undefined}>
                        <PauseCircle className="w-3 h-3 mr-1" />
                        {overdue ? `Review date passed (${doc.ap_hold.until.slice(0, 10)})` : doc.ap_hold?.until ? `Review on ${doc.ap_hold.until.slice(0, 10)}` : 'On hold, no review date'}
                      </Badge>
                    )}
                  </div>
                  {view === 'holds' && doc.ap_hold && (
                    <p className="text-sm">
                      <span className="text-muted-foreground">Why: </span>{doc.ap_hold.reason || shortFolder(doc.suggested_folder) || '—'}
                      <span className="text-xs text-muted-foreground"> · held by {doc.ap_hold.by || 'someone'} on {(doc.ap_hold.at || '').slice(0, 10)}</span>
                    </p>
                  )}
                  {view === 'approvals' && doc.ap_approval?.notes && (
                    <p className="text-sm"><span className="text-muted-foreground">{doc.ap_approval.requested_by || 'Requested'}:</span> {doc.ap_approval.notes}</p>
                  )}
                  {forSomeoneElse && (
                    <p className="text-xs text-muted-foreground">This one is for {approver}. If you approve it, the history shows you approved it for them.</p>
                  )}
                  {showNote && (
                    <textarea
                      rows={2}
                      maxLength={1000}
                      autoFocus
                      value={notes[doc.id] || ''}
                      onChange={event => setNotes(previous => ({ ...previous, [doc.id]: event.target.value }))}
                      placeholder={showNote === 'reject' ? 'Why is it rejected? What should be fixed?' : 'Note for the history (optional)'}
                      className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                    />
                  )}
                  <div className="flex flex-wrap gap-2">
                    {view === 'approvals' ? (
                      <>
                        <Button type="button" size="sm" disabled={busy === doc.id} onClick={() => act(doc, 'approve')}>
                          {busy === doc.id ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />}
                          {forSomeoneElse ? `Approve for ${approver}` : 'Approve'}
                        </Button>
                        <Button type="button" size="sm" variant="outline" disabled={busy === doc.id} onClick={() => act(doc, 'reject')}
                          className={showNote === 'reject' ? 'border-red-500/50 text-red-500' : ''}>
                          <XCircle className="w-3.5 h-3.5 mr-1.5" /> {showNote === 'reject' ? 'Confirm reject' : 'Reject…'}
                        </Button>
                      </>
                    ) : (
                      <Button type="button" size="sm" disabled={busy === doc.id} onClick={() => act(doc, 'release')}>
                        {busy === doc.id ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5 mr-1.5" />}
                        Release hold
                      </Button>
                    )}
                    {!showNote && (
                      <Button type="button" size="sm" variant="ghost" onClick={() => setNoteOpen(previous => ({ ...previous, [doc.id]: 'note' }))}>
                        <MessageSquare className="w-3.5 h-3.5 mr-1.5" /> Add a note
                      </Button>
                    )}
                    <Button type="button" size="sm" variant="ghost" onClick={() => setPreview(preview === doc.id ? null : doc.id)}>
                      {preview === doc.id ? <EyeOff className="w-3.5 h-3.5 mr-1.5" /> : <Eye className="w-3.5 h-3.5 mr-1.5" />}
                      {preview === doc.id ? 'Hide the invoice' : 'Look at the invoice'}
                    </Button>
                    <Button asChild type="button" size="sm" variant="ghost">
                      <Link to={`/documents/${encodeURIComponent(doc.id)}`}>
                        <ExternalLink className="w-3.5 h-3.5 mr-1.5" /> Open document
                      </Link>
                    </Button>
                  </div>
                  {preview === doc.id && <PDFPreviewPanel document={doc} />}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
