import { useState, useEffect, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { ClipboardList, RefreshCw, Loader2, CheckCircle2, XCircle, PauseCircle, PlayCircle, ExternalLink } from 'lucide-react';
import api from '@/lib/api';

const ACTOR_KEY = 'gpi.apActor';

function readActor() {
  try { return localStorage.getItem(ACTOR_KEY) || ''; } catch (e) { return ''; }
}

function money(value) {
  if (value == null) return '—';
  return Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export default function APWorkflowPage() {
  const [view, setView] = useState('approvals');
  const [data, setData] = useState(null);
  const [people, setPeople] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approverFilter, setApproverFilter] = useState('all');
  const [actor, setActor] = useState(readActor());
  const [busy, setBusy] = useState(null);
  const [notes, setNotes] = useState({});
  const [done, setDone] = useState(new Set());

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [{ data: queueData }, { data: peopleData }] = await Promise.all([
        api.get('/ap-workflow/queue', { params: { view } }),
        api.get('/ap-workflow/people'),
      ]);
      setData(queueData);
      setPeople(peopleData.people || []);
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

  const items = useMemo(() => {
    const list = (data?.items || []).filter(d => !done.has(d.id));
    if (view !== 'approvals' || approverFilter === 'all') return list;
    return list.filter(d => (d.ap_approval?.approver || d.suggested_approver || 'unassigned') === approverFilter);
  }, [data, done, view, approverFilter]);

  const act = async (doc, action) => {
    if (!actor) {
      toast.error('Choose who you are first (top right)');
      return;
    }
    const note = notes[doc.id] || '';
    if (action === 'reject' && !note.trim()) {
      toast.error('Say why it is rejected, so the next person knows what to fix');
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
        toast.success(action === 'approve' ? `Approved — ${doc.file_name}` : `Rejected — ${doc.file_name}`);
      } else if (action === 'release') {
        await api.post(`/ap-workflow/document/${encodeURIComponent(doc.id)}/release`, { by: actor, notes: note });
        toast.success(`Released from hold — ${doc.file_name}`);
      }
      setDone(previous => new Set(previous).add(doc.id));
    } catch (error) {
      toast.error(error.response?.data?.detail || 'The action did not save');
    } finally {
      setBusy(null);
    }
  };

  const approverCounts = data?.awaiting_by_approver || {};
  const today = new Date().toISOString().slice(0, 10);

  return (
    <div className="space-y-6" data-testid="ap-workflow-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <ClipboardList className="w-6 h-6 mt-1 text-primary" />
          <div>
            <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>AP Workflow</h1>
            <p className="text-sm text-muted-foreground max-w-3xl">
              Approvals and holds that Square9 kept in folder names ("Ellie to approve", "Hold until ship dates
              confirmed"). Every action records who did it and why, and nothing is sent to Business Central from here.
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-muted-foreground" htmlFor="ap-actor">Approving as</label>
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
          <Button type="button" size="sm" variant="outline" onClick={load}>
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
          </Button>
        </div>
      </div>

      <div className="flex items-center gap-1 border-b border-border">
        {[['approvals', 'Awaiting approval', Object.values(approverCounts).reduce((a, b) => a + b, 0)],
          ['holds', 'On hold', data?.holds || 0]].map(([key, label, count]) => (
          <button
            key={key}
            type="button"
            onClick={() => { setView(key); setApproverFilter('all'); }}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              view === key ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
          >
            {label} <span className="opacity-60">{count}</span>
          </button>
        ))}
      </div>

      {view === 'approvals' && Object.keys(approverCounts).length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground mr-1">Approver:</span>
          {[['all', 'Everyone'], ...Object.keys(approverCounts).map(k => [k, k])].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setApproverFilter(key)}
              className={`rounded-full border px-3 py-1 text-xs ${
                approverFilter === key ? 'border-primary bg-primary/10 text-primary' : 'border-border text-muted-foreground hover:text-foreground'}`}
            >
              {label}{key !== 'all' ? ` ${approverCounts[key]}` : ''}
            </button>
          ))}
        </div>
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
            return (
              <Card key={doc.id} className={overdue ? 'border-amber-500/50' : ''}>
                <CardContent className="p-4 space-y-3">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <div>
                      <Link to={`/documents/${encodeURIComponent(doc.id)}`} className="font-mono text-sm hover:underline">
                        {doc.file_name}
                      </Link>
                      <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground">
                        <span><span className="text-foreground font-medium">Vendor</span> {doc.vendor_canonical || doc.vendor_raw || '—'}</span>
                        <span><span className="text-foreground font-medium">Invoice</span> {doc.invoice_number_clean || '—'}</span>
                        <span><span className="text-foreground font-medium">Amount</span> {money(doc.amount_float)}</span>
                        {doc.po_number_clean && <span><span className="text-foreground font-medium">PO</span> {doc.po_number_clean}</span>}
                        <span><span className="text-foreground font-medium">Received</span> {(doc.created_utc || '').slice(0, 10)}</span>
                        {doc.suggested_folder && <span><span className="text-foreground font-medium">Folder</span> {doc.suggested_folder}</span>}
                      </div>
                    </div>
                    {view === 'approvals' ? (
                      <Badge variant="outline" className="border-sky-500/40 text-sky-400">
                        {approver ? `${approver} to approve` : 'No approver yet'}
                        {!doc.ap_approval && approver ? ' (suggested)' : ''}
                      </Badge>
                    ) : (
                      <Badge variant="outline" className={overdue ? 'border-amber-500/50 text-amber-400' : ''}>
                        <PauseCircle className="w-3 h-3 mr-1" />
                        {overdue ? 'Review date passed' : doc.ap_hold?.until ? `Until ${doc.ap_hold.until.slice(0, 10)}` : 'On hold'}
                      </Badge>
                    )}
                  </div>
                  {view === 'holds' && doc.ap_hold && (
                    <p className="text-sm">
                      <span className="text-muted-foreground">Held by {doc.ap_hold.by || 'someone'} on {(doc.ap_hold.at || '').slice(0, 10)}:</span> {doc.ap_hold.reason}
                    </p>
                  )}
                  {view === 'approvals' && doc.ap_approval?.notes && (
                    <p className="text-sm"><span className="text-muted-foreground">Requested by {doc.ap_approval.requested_by}:</span> {doc.ap_approval.notes}</p>
                  )}
                  <textarea
                    rows={2}
                    maxLength={1000}
                    value={notes[doc.id] || ''}
                    onChange={event => setNotes(previous => ({ ...previous, [doc.id]: event.target.value }))}
                    placeholder={view === 'approvals' ? 'Note (required to reject)' : 'Note (optional)'}
                    className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  />
                  <div className="flex flex-wrap gap-2">
                    {view === 'approvals' ? (
                      <>
                        <Button type="button" size="sm" disabled={busy === doc.id} onClick={() => act(doc, 'approve')}>
                          {busy === doc.id ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />}
                          Approve
                        </Button>
                        <Button type="button" size="sm" variant="outline" disabled={busy === doc.id} onClick={() => act(doc, 'reject')}>
                          <XCircle className="w-3.5 h-3.5 mr-1.5" /> Reject
                        </Button>
                      </>
                    ) : (
                      <Button type="button" size="sm" disabled={busy === doc.id} onClick={() => act(doc, 'release')}>
                        {busy === doc.id ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <PlayCircle className="w-3.5 h-3.5 mr-1.5" />}
                        Release hold
                      </Button>
                    )}
                    <Button asChild type="button" size="sm" variant="ghost">
                      <Link to={`/documents/${encodeURIComponent(doc.id)}`}>
                        <ExternalLink className="w-3.5 h-3.5 mr-1.5" /> Open document
                      </Link>
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

