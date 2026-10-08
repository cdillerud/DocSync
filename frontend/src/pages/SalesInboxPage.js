import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { ShoppingCart, Loader2, ChevronDown, ChevronRight, RefreshCw } from 'lucide-react';
import api from '@/lib/api';

// One stage per sales-mailbox document (sales_stage_service). BC is the
// ground truth: a customer PO is "Entered in BC" once inside sales' Production order carries it.
const STAGES = [
  { key: 'needs_rep', label: 'Needs a rep', help: 'A person must decide; the reason is shown', tone: 'amber' },
  { key: 'ready', label: 'Ready to draft', help: 'Customer and every line known; the Hub drafts it in the BC sandbox within the hour', tone: 'emerald' },
  { key: 'drafted', label: 'Drafted (sandbox)', help: 'The Hub drafted the sales order in the PRE sandbox, a test copy of BC. Not a real order: it moves to Entered in BC once inside sales enters it in Production', tone: 'emerald' },
  { key: 'in_bc', label: 'Entered in BC', help: 'Inside sales entered it: a Production BC sales order carries this customer PO', tone: 'muted' },
  { key: 'duplicate', label: 'Duplicate', help: 'Another copy or page of a PO already counted', tone: 'muted' },
  { key: 'purchasing', label: 'Purchasing', help: "A supplier's document about a Gamer purchase order", tone: 'muted' },
  { key: 'to_ap', label: 'To AP', help: 'An AP invoice that came to sales', tone: 'muted' },
  { key: 'filed', label: 'Filed', help: "Gamer's own order copies, AR invoices and other customer mail: evidence, not work", tone: 'muted' },
];
const TONE = {
  amber: 'border-amber-500/40 bg-amber-500/10',
  emerald: 'border-emerald-500/40 bg-emerald-500/10',
  muted: 'border-border bg-muted/40',
};

function money(v) {
  return v == null ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Lines({ resolution }) {
  if (!resolution?.lines?.length) return <p className="text-xs text-muted-foreground">No lines read from the document.</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border">
            <th className="py-1 pr-3">On the PO</th><th className="py-1 pr-3 text-right">PO qty</th><th className="py-1 pr-3">Gamer item</th>
            <th className="py-1 pr-3 text-right">BC qty</th><th className="py-1 pr-3 text-right">Price</th><th className="py-1">How the Hub knows</th>
          </tr>
        </thead>
        <tbody>
          {[...resolution.lines, ...(resolution.charges || []).map(c => ({ ...c, po_description: 'Charge inside sales adds', po_quantity: null }))].map((l, i) => (
            <tr key={i} className="border-b border-border/60 align-top">
              <td className="py-1 pr-3 max-w-[320px]">{l.po_description}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{l.po_quantity ?? '—'}</td>
              <td className={`py-1 pr-3 font-mono ${l.item ? '' : 'text-amber-600'}`}>{l.item || 'not matched'}{l.charge && <span className="ml-1 rounded bg-muted px-1 text-[10px] font-sans">charge</span>}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{l.quantity ?? '—'} {l.unit_of_measure || ''}</td>
              <td className="py-1 pr-3 text-right tabular-nums">{l.unit_price ?? '—'}</td>
              <td className="py-1 text-muted-foreground">{l.how || '—'}{l.price_source ? `; price: ${l.price_source}` : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {resolution.to_complete?.length > 0 && (
        <div className="mt-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-xs">
          <b>Rep to add before releasing</b> (usual for this customer; the Hub could not size or price them reliably, and notes them on the BC draft):
          <ul className="mt-1 space-y-0.5">
            {resolution.to_complete.map(t => (
              <li key={t.item}><span className="font-mono">{t.item}</span>{t.description ? ` - ${t.description}` : ''} · on {Math.round(t.rate * 100)}% of {t.orders} orders · typical qty {t.typical_qty}{t.when === 'shipping / invoicing' ? ' · usually added at shipping / invoicing' : ''}</li>
            ))}
          </ul>
        </div>
      )}
      {(resolution.planned_total != null || resolution.po_total != null) && (
        <p className="mt-1 text-xs text-muted-foreground tabular-nums">Products {money(resolution.planned_total)}{resolution.charges?.length ? ` · with charges ${money(resolution.planned_total_with_charges)}` : ''} · PO total {money(resolution.po_total)}</p>
      )}
    </div>
  );
}

export default function SalesInboxPage() {
  const [summary, setSummary] = useState(null);
  const [stage, setStage] = useState('needs_rep');
  const [q, setQ] = useState('');
  const [data, setData] = useState(null);
  const [open, setOpen] = useState({});
  const [loading, setLoading] = useState(false);
  const [reps, setReps] = useState(null);
  const [rep, setRep] = useState(null);      // null until we know who is signed in

  const loadReps = useCallback(async () => {
    const { data: r } = await api.get('/sales-inbox/reps');
    setReps(r);
    setRep(cur => (cur === null ? (r.me || '') : cur));
  }, []);
  useEffect(() => { loadReps(); }, [loadReps]);

  const load = useCallback(async () => {
    if (rep === null) return;
    setLoading(true);
    try {
      const [{ data: s }, { data: l }] = await Promise.all([
        api.get('/sales-inbox/summary', { params: { rep } }),
        api.get('/sales-inbox/list', { params: { stage, q, rep, limit: 100 } }),
      ]);
      setSummary(s);
      setData(l);
    } finally {
      setLoading(false);
    }
  }, [stage, q, rep]);

  const reassign = async (row, email, scope) => {
    try {
      await api.post(`/sales-inbox/document/${row.id}/assign`, { rep_email: email, scope });
      toast.success(scope === 'customer' ? `All ${row.customer_name || row.customer_no} POs reassigned` : 'Reassigned');
      load(); loadReps();
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Could not reassign');
    }
  };
  const repName = r => r.name || r.email.split('@')[0];

  useEffect(() => { const t = setTimeout(load, q ? 300 : 0); return () => clearTimeout(t); }, [load, q]);

  const current = STAGES.find(s => s.key === stage);

  return (
    <div className="space-y-5" data-testid="sales-inbox-page">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-semibold flex items-center gap-2"><ShoppingCart className="w-5 h-5" /> Sales Inbox</h1>
          <p className="text-sm text-muted-foreground max-w-3xl">Every document that reaches the inside sales mailboxes, in one stage. Customer POs are matched to the customer, Gamer items, quantities and prices from your BC order history, and drafted as sales orders in the BC sandbox. Nothing is released or shipped.</p>
        </div>
        <Button variant="outline" size="sm" onClick={load}><RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh</Button>
      </div>

      {summary && (
        <p className="text-sm text-muted-foreground">
          Last {summary.days} days: <b className="text-foreground">{summary.customer_pos}</b> customer POs, <b className="text-foreground">{summary.customer_pos_in_bc}</b> already on a BC sales order.
          {summary.draft_accuracy?.orders > 0 && (
            <> Hub drafts graded against inside sales' own orders: <b className="text-foreground">{summary.draft_accuracy.exact}/{summary.draft_accuracy.orders}</b> exact,
              products {summary.draft_accuracy.products_right}/{summary.draft_accuracy.products}, charges {summary.draft_accuracy.charges_right || 0}/{summary.draft_accuracy.charges || 0}.</>
          )}
        </p>
      )}

      {reps && (
        <div className="flex flex-wrap items-center gap-1.5" data-testid="rep-queues">
          <span className="text-xs text-muted-foreground mr-1">Queue</span>
          {[{ email: '', name: 'Everyone' }, ...reps.reps].map(r => {
            const open = r.counts ? (r.counts.needs_rep + r.counts.ready + r.counts.drafted) : null;
            const active = rep === r.email;
            return (
              <button key={r.email || 'all'} type="button" onClick={() => setRep(r.email)}
                className={`rounded-full border px-3 py-1 text-xs ${active ? 'border-primary bg-primary/10 text-primary' : 'border-border hover:bg-muted'}`}
                title={r.counts ? `${r.counts.needs_rep} need a rep · ${r.counts.ready} ready · ${r.counts.drafted} drafted` : 'All reps'}>
                {r.email && r.email === reps.me ? 'My queue' : repName(r)}{open != null && <b className="ml-1 tabular-nums">{open}</b>}
              </button>
            );
          })}
        </div>
      )}

      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
        {STAGES.map(s => (
          <button key={s.key} type="button" onClick={() => setStage(s.key)} title={s.help}
            className={`rounded-lg border px-3 py-2 text-left transition-colors ${TONE[s.tone]} ${stage === s.key ? 'ring-2 ring-primary' : 'hover:bg-muted'}`}>
            <div className="text-xs text-muted-foreground">{s.label}</div>
            <div className="text-xl font-semibold tabular-nums">{summary?.stages?.[s.key] ?? '—'}</div>
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <div>
              <h2 className="font-semibold">{current?.label}</h2>
              <p className="text-xs text-muted-foreground">{current?.help}</p>
            </div>
            {stage === 'needs_rep' && summary?.needs_rep_reasons && (
              <div className="flex flex-wrap gap-1.5 text-xs">
                {Object.entries(summary.needs_rep_reasons).map(([k, n]) => (
                  <span key={k} className="rounded-full border border-border px-2 py-0.5" title={summary.reason_text?.[k]}>{(summary.reason_text?.[k] || k).split(/[.?]/)[0]}: {n}</span>
                ))}
              </div>
            )}
            <Input className="ml-auto max-w-xs" placeholder="Search customer, PO, file…" value={q} onChange={e => setQ(e.target.value)} />
          </div>

          {loading && !data ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>
          ) : !data?.rows?.length ? (
            <p className="text-sm text-muted-foreground">Nothing here.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
                    <th className="py-2 pr-2"></th><th className="py-2 pr-3">Received</th><th className="py-2 pr-3">Customer</th><th className="py-2 pr-3">Customer PO</th>
                    <th className="py-2 pr-3">Document</th><th className="py-2 pr-3">Why / BC</th><th className="py-2 pr-3">Rep</th><th className="py-2 pr-3 text-right">Lines</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.map(r => (
                    <>
                      <tr key={r.id} className="border-b border-border align-top hover:bg-muted/40 cursor-pointer" onClick={() => setOpen(o => ({ ...o, [r.id]: !o[r.id] }))}>
                        <td className="py-2 pr-2">{r.resolution ? (open[r.id] ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />) : null}</td>
                        <td className="py-2 pr-3 whitespace-nowrap text-xs">{(r.received || '').slice(0, 10)}</td>
                        <td className="py-2 pr-3">{r.customer_name || r.customer_on_doc || '—'}{r.customer_no && <span className="text-xs text-muted-foreground"> ({r.customer_no})</span>}
                          <div className="text-xs text-muted-foreground truncate max-w-[220px]">{r.sender}</div></td>
                        <td className="py-2 pr-3 font-mono text-xs">{r.customer_po || '—'}</td>
                        <td className="py-2 pr-3 max-w-[260px]"><Link className="text-primary underline" to={`/documents/${r.id}`} onClick={e => e.stopPropagation()}>{r.file_name}</Link>
                          <div className="text-xs text-muted-foreground truncate">{r.subject}</div></td>
                        <td className="py-2 pr-3 text-xs max-w-[280px]">
                          {r.stage === 'in_bc' && <>Production order <b className="font-mono">{r.bc_order_no}</b> ({r.match === 'customer_po' ? 'by customer PO' : r.match === 'items_and_quantities' ? 'same items and quantities' : 'by order no.'})</>}
                          {r.stage === 'drafted' && r.draft && <>Sandbox draft <b className="font-mono">{r.draft.bc_order_no}</b> (PRE) · {money(r.draft.total)} · <span className="text-muted-foreground">not a real order</span>
                            {r.draft.to_complete?.length > 0 && <div className="text-amber-700 dark:text-amber-400">Rep to add: {r.draft.to_complete.map(t => t.item).join(', ')}</div>}
                            {r.readback?.edits?.length > 0 && <div className="text-muted-foreground">Rep changed: {r.readback.edits.slice(0, 3).join('; ')}</div>}</>}
                          {r.stage === 'needs_rep' && <span className="text-amber-700 dark:text-amber-400">{r.reason_text}{r.detail ? ` (${r.detail})` : ''}</span>}
                          {r.stage === 'duplicate' && <>Copy of <Link className="underline" to={`/documents/${r.duplicate_of}`} onClick={e => e.stopPropagation()}>another document</Link></>}
                          {['filed', 'purchasing', 'to_ap', 'ready'].includes(r.stage) && <span className="text-muted-foreground">{(r.role || '').replace(/_/g, ' ')}</span>}
                        </td>
                        <td className="py-2 pr-3 text-xs" onClick={e => e.stopPropagation()}>
                          <div title={r.rep?.how}>{r.rep?.name || 'Unassigned'}</div>
                          {reps && (
                            <select className="mt-0.5 max-w-[140px] rounded border border-border bg-background px-1 py-0.5 text-[11px]" value=""
                              onChange={e => { const [email, scope] = e.target.value.split('|'); if (scope) reassign(r, email, scope); }}>
                              <option value="">Reassign…</option>
                              {reps.reps.filter(x => x.email !== 'unassigned').map(x => (
                                <optgroup key={x.email} label={repName(x)}>
                                  <option value={`${x.email}|document`}>This PO</option>
                                  {r.customer_no && <option value={`${x.email}|customer`}>All {r.customer_no} POs</option>}
                                </optgroup>
                              ))}
                            </select>
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right text-xs tabular-nums">{r.resolution ? `${r.resolution.resolved}/${r.resolution.total}` : '—'}</td>
                      </tr>
                      {open[r.id] && r.resolution && (
                        <tr key={`${r.id}-lines`} className="border-b border-border bg-muted/20"><td></td><td colSpan={7} className="py-2 pr-3"><Lines resolution={r.resolution} /></td></tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
              {data.total > data.rows.length && <p className="mt-2 text-xs text-muted-foreground">Showing {data.rows.length} of {data.total}. Use search to narrow.</p>}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

