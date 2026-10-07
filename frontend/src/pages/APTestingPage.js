import { useState, useEffect, useRef, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { FlaskConical, Loader2, AlertTriangle } from 'lucide-react';
import api from '@/lib/api';
import { useAuth } from '@/context/AuthContext';

// AP test round 1 (October 2026). Answers save to the Hub under the signed-in
// tester (/api/testing/my-results); the drafts list is live (/api/testing/drafts).
const CHOICES = [
  ['pass', 'Pass', 'border-emerald-500 text-emerald-600 bg-emerald-500/10'],
  ['problem', 'Problem', 'border-red-500 text-red-600 bg-red-500/10'],
  ['unsure', 'Not sure', 'border-amber-500 text-amber-600 bg-amber-500/10'],
  ['skipped', 'Skipped', 'border-border text-muted-foreground bg-muted'],
];

const TESTS = [
  {
    key: 't1', title: 'Find your way around', time: '10 min',
    steps: [
      <>Open the <Link className="text-primary underline" to="/ap">AP Inbox</Link>. Every AP document is in exactly one stage, shown as tiles along the top.</>,
      <>Click each tile and read its one-line description. Only <b>Needs staff</b>, <b>Awaiting approval</b> and <b>On hold</b> need a person.</>,
      <>Click <b>Entered in BC</b>. Use the search box (vendor or invoice number) to find three invoices you remember entering. Check the "Why" column shows the right BC document number.</>,
      <>Click a file name to open the document. <b>AP history</b> shows the stage, the BC invoice, any corrections the Hub made, and who did what.</>,
    ],
    check: 'Pass if the stages make sense to you and the three invoices show the right BC numbers. Note anything that was unclear.',
  },
  { key: 'drafts' },
  {
    key: 't3', title: 'Check the AP folders', time: '10 min',
    steps: [
      <>In the <Link className="text-primary underline" to="/ap">AP Inbox</Link>, open <b>Drafted (sandbox)</b>, then <b>Ready for AP</b> and <b>Waiting for receipt</b>.</>,
      <>For ten documents, look at the <b>Folder</b> column. Is that where you would file it in Square9 (lane and subfolder)?</>,
      <>Write down any document whose folder is wrong and where it should go.</>,
    ],
    check: 'Pass if at least 9 of 10 folders are where you would put them.',
  },
  {
    key: 't4', title: 'Work the Decision Queue', time: '15 min',
    steps: [
      <>Open the <Link className="text-primary underline" to="/decision-queue">Decision Queue</Link>, tab <b>AP: staff decision</b>. Use the <b>Show</b> chips to filter by reason.</>,
      <>For five items you understand: read the question, click <b>Review document</b>, then <b>Use suggested folder</b>, <b>Choose a different folder</b>, or <b>Exclude from processing</b> (not AP work). Type a short <b>Why?</b> each time.</>,
      <>Try one <b>Put on hold</b> with a reason, and one <b>Send for approval</b>.</>,
    ],
    check: 'Pass if the questions are clear and the actions do what you expect. Note any question you could not answer and why.',
  },
  {
    key: 't5', title: 'Approvals and holds', time: '10 min',
    steps: [
      <>Open <Link className="text-primary underline" to="/ap-workflow">AP Workflow</Link>. Check that <b>Approving as</b> shows your name (it comes from your Microsoft sign-in).</>,
      <>On <b>Awaiting approval</b>, filter by approver. Approve one item you are sure about. Reject one only if it should be rejected (a reason is required).</>,
      <>On <b>On hold</b>, find the hold you placed in Test 4 and release it.</>,
      <>Open that document and check AP history shows each step with your name and note.</>,
    ],
    check: 'Pass if approve, reject, hold and release each work and show up in AP history. Also note the approval rules you actually use (amounts, vendors, who approves what).',
  },
  { key: 't6', title: 'Overall', time: '5 min', notesOnly: true,
    intro: 'Compared with how you work in Square9 today: what is missing, what would slow you down, and what would you trust the Hub to do on its own?' },
];

function money(v) {
  return v == null ? '—' : Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function Result({ id, value, onChange, notesOnly }) {
  return (
    <div className="space-y-2">
      {!notesOnly && (
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Result">
          {CHOICES.map(([v, label, on]) => (
            <button key={v} type="button" aria-pressed={value?.status === v}
              onClick={() => onChange({ ...value, status: value?.status === v ? '' : v })}
              className={`rounded-full border px-3 py-0.5 text-xs transition-colors ${value?.status === v ? on : 'border-border hover:bg-muted'}`}>
              {label}
            </button>
          ))}
        </div>
      )}
      <Textarea id={`notes-${id}`} rows={2} value={value?.notes || ''}
        placeholder={notesOnly ? 'Your thoughts' : 'What did you find? What would you change?'}
        onChange={e => onChange({ ...value, notes: e.target.value })} className="text-sm" />
    </div>
  );
}

export default function APTestingPage() {
  const { user } = useAuth();
  const [tests, setTests] = useState({});
  const [drafts, setDrafts] = useState(null);
  const [env, setEnv] = useState('');
  const [save, setSave] = useState({ text: 'Loading your answers…', tone: '' });
  const loaded = useRef(false);
  const timer = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const [{ data: mine }, { data: d }] = await Promise.all([api.get('/testing/my-results'), api.get('/testing/drafts')]);
        setTests(mine.tests || {});
        setDrafts(d.drafts || []);
        setEnv(d.environment);
        setSave({ text: mine.updated_at ? 'All answers saved' : 'Answers save as you go', tone: mine.updated_at ? 'ok' : '' });
      } catch (e) {
        setDrafts([]);
        setSave({ text: 'Could not load your answers; refresh the page', tone: 'err' });
      } finally {
        loaded.current = true;
      }
    })();
  }, []);

  // Coming back from a document: return to the draft row you opened.
  useEffect(() => {
    if (!drafts?.length) return;
    let last = null;
    try { last = sessionStorage.getItem('gpi.apTesting.lastDraft'); sessionStorage.removeItem('gpi.apTesting.lastDraft'); } catch (e) { /* ignore */ }
    if (!last) return;
    requestAnimationFrame(() => {
      const row = document.getElementById(`draft-row-${last}`);
      if (row) row.scrollIntoView({ block: 'start' });
    });
  }, [drafts]);

  const persist = useCallback((next) => {
    clearTimeout(timer.current);
    setSave({ text: 'Saving…', tone: '' });
    timer.current = setTimeout(async () => {
      try {
        await api.put('/testing/my-results', { tests: next });
        setSave({ text: 'All answers saved', tone: 'ok' });
      } catch (e) {
        setSave({ text: 'Not saved yet. Check your connection; your next change will try again.', tone: 'err' });
      }
    }, 800);
  }, []);

  const update = (key, value) => {
    setTests(prev => {
      const next = { ...prev, [key]: value };
      if (loaded.current) persist(next);
      return next;
    });
  };

  const keys = [...TESTS.filter(t => t.key !== 'drafts').map(t => t.key), ...(drafts || []).map(d => `draft_${d.bc_draft_no}`)];
  const answered = keys.filter(k => tests[k] && (tests[k].status || (tests[k].notes || '').trim())).length;

  const draftSection = (n) => (
    <Card key="drafts">
      <CardContent className="p-5 space-y-4">
        <div className="flex flex-wrap items-baseline gap-3">
          <span className="font-mono text-primary text-sm">Test {n}</span>
          <h2 className="text-lg font-semibold">Review the Hub's BC drafts</h2>
          <span className="ml-auto text-xs text-muted-foreground">40 min</span>
        </div>
        <p className="text-sm">The most important test. For each draft, open it in the BC sandbox and compare it with the vendor's invoice (<b>Open</b> shows the Hub page and PDF; the back arrow there brings you back here).</p>
        <ol className="list-decimal pl-5 space-y-1 text-sm">
          <li>In BC, environment <code className="text-xs">{env}</code>, go to <b>Purchase Invoices</b> and open the draft by its No.</li>
          <li>Check the header: vendor, vendor invoice no., invoice date, due date, currency, total.</li>
          <li>Check the lines: item or G/L account, quantity, cost, description. Would you code it this way?</li>
          <li>Check what is missing that you always fill in (PO / order no., dimensions, attachments).</li>
          <li>Mark <b>Pass</b> if you would post it as is, <b>Problem</b> if anything is wrong, and say what.</li>
        </ol>
        {drafts == null ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin" /> Loading drafts…</div>
        ) : drafts.length === 0 ? (
          <p className="text-sm text-muted-foreground">No drafts to review right now.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="py-2 pr-3">BC draft</th><th className="py-2 pr-3">Vendor</th><th className="py-2 pr-3">Vendor inv.</th>
                  <th className="py-2 pr-3 text-right">Amount</th><th className="py-2 pr-3">PO</th><th className="py-2 pr-3">Lines from</th>
                  <th className="py-2 pr-3"></th><th className="py-2 min-w-[240px]">Your result</th>
                </tr>
              </thead>
              <tbody>
                {drafts.map(d => (
                  <tr key={d.bc_draft_no} id={`draft-row-${d.bc_draft_no}`} className="border-b border-border align-top scroll-mt-24">
                    <td className="py-2 pr-3 font-mono">{d.bc_draft_no}</td>
                    <td className="py-2 pr-3">{d.vendor_name} <span className="text-xs text-muted-foreground">({d.vendor_no})</span>
                      {d.international && <div className="text-xs text-muted-foreground">International</div>}</td>
                    <td className="py-2 pr-3 font-mono">{d.invoice_number}</td>
                    <td className="py-2 pr-3 text-right tabular-nums whitespace-nowrap">{money(d.amount)}</td>
                    <td className="py-2 pr-3 font-mono">{d.po || '—'}</td>
                    <td className="py-2 pr-3 text-xs">{d.lines_from}</td>
                    <td className="py-2 pr-3"><Link className="inline-flex items-center gap-1 text-primary underline" to={`/documents/${d.document_id}`}
                      onClick={() => { try { sessionStorage.setItem('gpi.apTesting.lastDraft', d.bc_draft_no); } catch (e) { /* private window */ } }}>Open</Link></td>
                    <td className="py-2"><Result id={`draft_${d.bc_draft_no}`} value={tests[`draft_${d.bc_draft_no}`]} onChange={v => update(`draft_${d.bc_draft_no}`, v)} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </CardContent>
    </Card>
  );

  return (
    <div className="max-w-5xl mx-auto space-y-5 pb-16" data-testid="ap-testing-page">
      <div className="space-y-2">
        <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-muted-foreground"><FlaskConical className="w-4 h-4" /> AP test round 1 · October 2026</div>
        <h1 className="text-2xl font-semibold">AP Hub test script</h1>
        <p className="text-sm text-muted-foreground max-w-3xl">The Hub reads every invoice that comes into the AP mailbox, works out the vendor, invoice number, amount, PO and AP folder, checks it against Business Central, and drafts the purchase invoice in the BC sandbox for you to review. It never posts anything. Work through the tests below; your answers save automatically under your name.</p>
      </div>

      <div className="sticky top-0 z-10 flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background/95 backdrop-blur px-4 py-2 text-sm">
        <span>Testing as <b>{user?.display_name || user?.email}</b></span>
        <span className="text-muted-foreground tabular-nums">{answered} of {keys.length} answered</span>
        <span className={`ml-auto ${save.tone === 'ok' ? 'text-emerald-600' : save.tone === 'err' ? 'text-red-600' : 'text-muted-foreground'}`}>{save.text}</span>
      </div>

      <Card className="border-l-4 border-l-amber-500">
        <CardContent className="p-5 space-y-3 text-sm">
          <h2 className="text-lg font-semibold">Before you start</h2>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-2">
            <dt className="text-muted-foreground">BC sandbox</dt><dd>Business Central, environment <code className="text-xs">{env || 'PRE_GAMERDOCS_CUTOVER_20260831'}</code>, company Gamer Packaging. All Hub drafts are under Purchase Invoices. Gaps in the numbering are drafts the Hub removed after its own checks found a problem.</dd>
            <dt className="text-muted-foreground">Time</dt><dd>About 90 minutes. You can stop and come back; your answers are kept.</dd>
          </dl>
          <div className="flex items-start gap-2 rounded-md bg-amber-500/10 p-3">
            <AlertTriangle className="w-4 h-4 mt-0.5 text-amber-600 shrink-0" />
            <ul className="space-y-1">
              <li><b>Do not post any draft in BC</b>, and do not edit or delete Hub drafts. Write what is wrong in the notes; the Hub reads its drafts back every hour.</li>
              <li>Nothing you do in the Hub reaches Production BC, SharePoint or Square9. It is safe to click around.</li>
              <li>Decisions in the Decision Queue and AP Workflow are <i>real</i>: the Hub learns from them and records your name. Make each one as you would for a real invoice; if unsure, skip it.</li>
              <li>Every finding helps, including "this was confusing". Plain words are perfect.</li>
            </ul>
          </div>
        </CardContent>
      </Card>

      {TESTS.map((t, i) => t.key === 'drafts' ? draftSection(i + 1) : (
        <Card key={t.key}>
          <CardContent className="p-5 space-y-3">
            <div className="flex flex-wrap items-baseline gap-3">
              <span className="font-mono text-primary text-sm">Test {i + 1}</span>
              <h2 className="text-lg font-semibold">{t.title}</h2>
              <span className="ml-auto text-xs text-muted-foreground">{t.time}</span>
            </div>
            {t.intro && <p className="text-sm">{t.intro}</p>}
            {t.steps && <ol className="list-decimal pl-5 space-y-1 text-sm">{t.steps.map((s, j) => <li key={j}>{s}</li>)}</ol>}
            {t.check && <p className="rounded-md bg-primary/10 px-3 py-2 text-sm">{t.check}</p>}
            <div className="border-t border-dashed border-border pt-3">
              <Result id={t.key} value={tests[t.key]} onChange={v => update(t.key, v)} notesOnly={t.notesOnly} />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

