import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Sun, ArrowRight, Upload, ClipboardList, ShoppingCart, PauseCircle, CheckCircle2, Loader2, Receipt, UserRound } from 'lucide-react';
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

// One half of the page: AP or Sales, each with its own colour band, so the
// two jobs never mix (2026-10-10).
function Side({ title, icon: Icon, accent, to, linkLabel, testid, children }) {
  return (
    <section className={`rounded-xl border border-border border-t-4 ${accent} bg-card p-4 space-y-4`} data-testid={testid}>
      <div className="flex items-center gap-2">
        <Icon className="w-5 h-5" />
        <h2 className="text-lg font-semibold">{title}</h2>
        <Link to={to} className="ml-auto text-xs text-muted-foreground hover:text-foreground inline-flex items-center gap-1">{linkLabel} <ArrowRight className="w-3 h-3" /></Link>
      </div>
      {children}
    </section>
  );
}

function Sub({ title, children }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">{children}</div>
    </div>
  );
}

function Accuracy({ title, children }) {
  return (
    <div className="rounded-lg border border-border bg-muted/20 p-3 space-y-1 text-sm">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">{title}</div>
      {children}
    </div>
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

  useEffect(() => {
    (async () => {
      const [a, s, r] = await Promise.allSettled([
        api.get('/ap-workflow/worklist', { params: { stage: 'needs_staff', days: 30, limit: 1 } }),
        api.get('/sales-inbox/summary'),
        api.get('/sales-inbox/reps'),
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
          <p className="text-sm text-muted-foreground">Accounts payable and sales side by side: what needs a person, what the Hub handled, and how its drafts compare with what your team entered in BC.</p>
        </div>
        <Button asChild variant="outline" size="sm"><Link to="/documents?tab=upload"><Upload className="w-3.5 h-3.5 mr-1.5" /> Upload documents</Link></Button>
      </div>

      {loading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>}

      <div className="grid lg:grid-cols-2 gap-5">
        <Side title="Accounts payable" icon={Receipt} accent="border-t-violet-500" to="/ap" linkLabel="AP workspace" testid="today-ap">
          <Sub title="Needs a person">
            <Tile to="/decision-queue" icon={ClipboardList} label="Needs staff" value={c.needs_staff} tone={c.needs_staff ? 'amber' : 'muted'} help="A person must decide; the reason is on each one" />
            <Tile to="/ap-workflow" icon={CheckCircle2} label="Awaiting approval" value={c.awaiting_approval} tone={c.awaiting_approval ? 'sky' : 'muted'} help="Waiting for a named approver" />
            <Tile to="/ap-workflow" icon={PauseCircle} label="On hold" value={c.on_hold} tone={c.on_hold ? 'sky' : 'muted'} help="Held by staff with a reason" />
            <Tile to="/ap?stage=in_bc_check" icon={ClipboardList} label="Entered in BC, check" value={c.in_bc_check} tone={c.in_bc_check ? 'amber' : 'muted'} help="BC's amount or invoice number differs from the document" />
          </Sub>
          <Sub title="Handled by the Hub">
            <Tile to="/ap?stage=drafted" label="Drafted (sandbox)" value={c.drafted} tone="emerald" help="Purchase invoices drafted in the PRE sandbox" />
            <Tile to="/ap?stage=awaiting_receipt" label="Waiting for receipt" value={c.awaiting_receipt} help="Drafted once the goods are received in BC" />
            <Tile to="/ap?stage=in_bc" label="Entered in BC" value={c.in_bc} help="Entered by AP; linked to the BC invoice" />
          </Sub>
          <Accuracy title="Hub drafts vs what AP entered">
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
          </Accuracy>
        </Side>

        <Side title="Sales" icon={ShoppingCart} accent="border-t-sky-500" to="/sales" linkLabel="Sales inbox" testid="today-sales">
          <Sub title="Needs a person">
            <Tile to="/sales?stage=needs_rep" icon={ClipboardList} label="Rep to check" value={st.needs_rep} tone={st.needs_rep ? 'amber' : 'muted'} help="Customer POs the Hub cannot draft until the rep fixes something (item, customer, PO number)" />
            {mine ? (
              <Tile to="/sales" icon={UserRound} label="My queue" value={(mine.stages?.needs_rep || 0) + (mine.stages?.ready || 0) + (mine.stages?.drafted || 0)} tone="sky" help="Your customers' POs: needing you, ready, or drafted" />
            ) : (
              <Tile to="/sales?stage=drafted" icon={CheckCircle2} label="Drafts to review" value={st.drafted} tone={st.drafted ? 'sky' : 'muted'} help="Sales orders drafted in the sandbox for reps" />
            )}
          </Sub>
          <Sub title="Handled by the Hub">
            <Tile to="/sales?stage=drafted" label="Drafted (sandbox)" value={st.drafted} tone="emerald" help="Sales orders drafted in the PRE sandbox" />
            <Tile to="/sales?stage=ready" label="Ready to draft" value={st.ready} help="Customer and every line known; drafted within the hour" />
            <Tile to="/sales?stage=in_bc" label="Entered in BC" value={st.in_bc} help="Already on a Production sales order" />
          </Sub>
          <Accuracy title="Hub drafts vs what inside sales entered">
            {sAcc.orders ? (
              <>
                <p><b className="tabular-nums">{sAcc.exact}/{sAcc.orders}</b> orders exact ({pct(sAcc.exact, sAcc.orders)})</p>
                <p className="text-muted-foreground">Products {sAcc.products_right}/{sAcc.products} · quantities {sAcc.qty_right}/{sAcc.products_right} · prices {sAcc.price_right}/{sAcc.products_right} · charges {sAcc.charges_right || 0}/{sAcc.charges || 0}</p>
              </>
            ) : <p className="text-muted-foreground">Graded as inside sales enters drafted POs in Production; nothing graded yet.</p>}
          </Accuracy>
          {reps?.reps?.length > 0 && (
            <div className="space-y-1.5">
              <div className="text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">By rep</div>
              <div className="flex flex-wrap gap-2">
                {reps.reps.filter(r => r.email !== 'unassigned' || (r.counts.needs_rep + r.counts.ready + r.counts.drafted) > 0).map(r => (
                  <Link key={r.email} to="/sales" className="rounded-full border border-border px-3 py-1 text-xs hover:bg-muted">
                    {r.name || r.email.split('@')[0]} <b className="tabular-nums ml-1">{r.counts.needs_rep + r.counts.ready + r.counts.drafted}</b>
                    {r.counts.needs_rep > 0 && <span className="ml-1 text-amber-600">({r.counts.needs_rep} need them)</span>}
                  </Link>
                ))}
              </div>
            </div>
          )}
        </Side>
      </div>
    </div>
  );
}

