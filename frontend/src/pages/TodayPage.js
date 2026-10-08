import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Sun, ArrowRight, Upload, ShieldAlert, ClipboardList, ShoppingCart, PauseCircle, CheckCircle2, Loader2 } from 'lucide-react';
import api from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

// The landing page: what needs a person today across AP and Sales, what the
// Hub did on its own, and how its drafts compare with what people entered.
function Tile({ to, label, value, help, tone = 'muted', icon: Icon }) {
  const toneCls = {
    amber: 'border-amber-500/40 bg-amber-500/10',
    red: 'border-red-500/40 bg-red-500/10',
    emerald: 'border-emerald-500/40 bg-emerald-500/10',
    sky: 'border-sky-500/40 bg-sky-500/10',
    muted: 'border-border bg-muted/30',
  }[tone];
  return (
    <Link to={to} className={`group rounded-lg border p-3 transition-colors hover:bg-muted ${toneCls}`} title={help}>
      <div className="flex items-center gap-1.5 text-xs text-muted-foreground">{Icon && <Icon className="w-3.5 h-3.5" />}{label}</div>
      <div className="mt-1 flex items-end justify-between">
        <span className="text-2xl font-semibold tabular-nums">{value ?? '—'}</span>
        <ArrowRight className="w-4 h-4 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100" />
      </div>
      {help && <div className="mt-0.5 text-[11px] text-muted-foreground line-clamp-2">{help}</div>}
    </Link>
  );
}

function pct(a, b) {
  return b ? `${Math.round((100 * a) / b)}%` : '—';
}

export default function TodayPage() {
  const { user } = useAuth();
  const [ap, setAp] = useState(null);
  const [sales, setSales] = useState(null);
  const [reps, setReps] = useState(null);
  const [mine, setMine] = useState(null);
  const [fraud, setFraud] = useState(null);

  useEffect(() => {
    (async () => {
      const [a, s, r, f] = await Promise.allSettled([
        api.get('/ap-workflow/worklist', { params: { stage: 'needs_staff', days: 30, limit: 1 } }),
        api.get('/sales-inbox/summary'),
        api.get('/sales-inbox/reps'),
        api.get('/ap-workflow/worklist', { params: { stage: 'needs_staff', days: 30, limit: 200 } }),
      ]);
      if (a.status === 'fulfilled') setAp(a.value.data);
      if (s.status === 'fulfilled') setSales(s.value.data);
      if (r.status === 'fulfilled') {
        setReps(r.value.data);
        if (r.value.data.me) {
          const m = await api.get('/sales-inbox/summary', { params: { rep: r.value.data.me } }).catch(() => null);
          setMine(m?.data || null);
        }
      }
      if (f.status === 'fulfilled') setFraud((f.value.data.items || []).filter(d => d.staff_reason === 'suspected_fraud').length);
    })();
  }, []);

  const c = new Proxy(ap?.counts || {}, { get: (o, k) => (k in o ? o[k] : (ap ? 0 : undefined)) });
  const st = new Proxy(sales?.stages || {}, { get: (o, k) => (k in o ? o[k] : (sales ? 0 : undefined)) });
  const apAcc = ap?.draft_accuracy || {};
  const lineReplay = ap?.line_replay?.ap_lines || null;
  const sAcc = sales?.draft_accuracy || {};
  const first = (user?.display_name || '').split(' ')[0];
  const loading = !ap && !sales;

  return (
    <div className="max-w-6xl mx-auto space-y-6 pb-12" data-testid="today-page">
      <div className="flex flex-wrap items-start gap-3">
        <div className="flex-1 min-w-0">
          <h1 className="text-2xl font-semibold flex items-center gap-2"><Sun className="w-5 h-5 text-amber-500" /> {first ? `Good day, ${first}` : 'Today'}</h1>
          <p className="text-sm text-muted-foreground">What needs a person, what the Hub did on its own, and how its drafts compare with what your team entered in BC.</p>
        </div>
        <Button asChild variant="outline" size="sm"><Link to="/documents?tab=upload"><Upload className="w-3.5 h-3.5 mr-1.5" /> Upload documents</Link></Button>
      </div>

      {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>}

      {fraud > 0 && (
        <Link to="/decision-queue" className="flex items-center gap-3 rounded-lg border border-red-500/50 bg-red-500/10 px-4 py-3 text-sm hover:bg-red-500/15">
          <ShieldAlert className="w-5 h-5 text-red-500 shrink-0" />
          <span><b>{fraud} suspected fraud {fraud === 1 ? 'document' : 'documents'}</b> waiting for a person: invoices or payment requests from senders that do not match the vendor. Verify by phone before anything is paid.</span>
          <ArrowRight className="w-4 h-4 ml-auto" />
        </Link>
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Needs a person</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
          <Tile to="/decision-queue" icon={ClipboardList} label="AP: needs staff" value={c.needs_staff} tone={c.needs_staff ? 'amber' : 'muted'} help="A person must decide; the reason is shown in the Decision Queue" />
          <Tile to="/ap-workflow" icon={CheckCircle2} label="AP: awaiting approval" value={c.awaiting_approval} tone={c.awaiting_approval ? 'sky' : 'muted'} help="Waiting for a named approver" />
          <Tile to="/ap-workflow" icon={PauseCircle} label="AP: on hold" value={c.on_hold} tone={c.on_hold ? 'sky' : 'muted'} help="Held by staff with a reason" />
          <Tile to="/sales" icon={ShoppingCart} label="Sales: needs a rep" value={st.needs_rep} tone={st.needs_rep ? 'amber' : 'muted'} help="Customer POs a rep must look at" />
          {mine ? (
            <Tile to="/sales" icon={ShoppingCart} label="Sales: my queue" value={(mine.stages?.needs_rep || 0) + (mine.stages?.ready || 0) + (mine.stages?.drafted || 0)} tone="sky" help="Your customers' POs: needing you, ready, or drafted for your review" />
          ) : (
            <Tile to="/sales" icon={ShoppingCart} label="Sales: drafts to review" value={st.drafted} tone={st.drafted ? 'sky' : 'muted'} help="Sales orders drafted in the sandbox for reps to review" />
          )}
        </div>
      </section>

      <section className="space-y-2">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Done by the Hub</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <Tile to="/ap" label="AP drafted (sandbox)" value={c.drafted} tone="emerald" help="Purchase invoices drafted in the PRE sandbox for AP" />
          <Tile to="/ap" label="AP waiting for receipt" value={c.awaiting_receipt} help="Product invoices drafted once the goods are received in BC" />
          <Tile to="/ap" label="AP entered in BC" value={c.in_bc} help="Entered by AP; linked to the BC invoice" />
          <Tile to="/sales" label="Sales drafted (sandbox)" value={st.drafted} tone="emerald" help="Sales orders drafted in the PRE sandbox" />
          <Tile to="/sales" label="Sales ready to draft" value={st.ready} help="Customer and every line known; drafted within the hour" />
          <Tile to="/sales" label="Sales entered in BC" value={st.in_bc} help="Customer POs already on a Production sales order" />
        </div>
      </section>

      <section className="grid md:grid-cols-2 gap-3">
        <Card>
          <CardContent className="p-4 space-y-1.5 text-sm">
            <h3 className="font-semibold">AP drafts vs what AP entered</h3>
            {apAcc.drafts ? (
              <>
                <p><b className="tabular-nums">{apAcc.exact}/{apAcc.drafts}</b> drafts exact ({pct(apAcc.exact, apAcc.drafts)}) · totals right {pct(apAcc.total_right, apAcc.drafts)}</p>
                <p className="text-muted-foreground">Items {apAcc.items_right}/{apAcc.ap_items} · quantities {apAcc.qty_right}/{apAcc.items_right} · costs {apAcc.cost_right}/{apAcc.items_right}</p>
              </>
            ) : <p className="text-muted-foreground">Graded as AP enters drafted invoices in Production; nothing graded yet.</p>}
            {lineReplay && lineReplay.graded ? (
              <p className="text-muted-foreground" title="Every day the Hub plans the lines of the invoices AP entered in the last 21 days, as it would draft them, and compares item, quantity and cost with AP's BC lines">
                Daily replay: lines right on <b className="tabular-nums text-foreground">{lineReplay.exact}/{lineReplay.graded}</b> invoices AP entered ({lineReplay.exact_pct}%)
              </p>
            ) : null}
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 space-y-1.5 text-sm">
            <h3 className="font-semibold">Sales drafts vs what inside sales entered</h3>
            {sAcc.orders ? (
              <>
                <p><b className="tabular-nums">{sAcc.exact}/{sAcc.orders}</b> orders exact ({pct(sAcc.exact, sAcc.orders)})</p>
                <p className="text-muted-foreground">Products {sAcc.products_right}/{sAcc.products} · quantities {sAcc.qty_right}/{sAcc.products_right} · prices {sAcc.price_right}/{sAcc.products_right} · charges {sAcc.charges_right || 0}/{sAcc.charges || 0}</p>
              </>
            ) : <p className="text-muted-foreground">Graded as inside sales enters drafted POs in Production; nothing graded yet.</p>}
          </CardContent>
        </Card>
      </section>

      {reps?.reps?.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">Inside sales queues</h2>
          <div className="flex flex-wrap gap-2">
            {reps.reps.filter(r => r.email !== 'unassigned' || (r.counts.needs_rep + r.counts.ready + r.counts.drafted) > 0).map(r => (
              <Link key={r.email} to="/sales" className="rounded-full border border-border px-3 py-1 text-xs hover:bg-muted">
                {r.name || r.email.split('@')[0]} <b className="tabular-nums ml-1">{r.counts.needs_rep + r.counts.ready + r.counts.drafted}</b>
                {r.counts.needs_rep > 0 && <span className="ml-1 text-amber-600">({r.counts.needs_rep} need them)</span>}
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

