import { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { Inbox, RefreshCw, Loader2, Search, ArrowRight } from 'lucide-react';
import api from '@/lib/api';

// One stage per document (ap_stage_service). Order = what needs a person first.
const STAGES = [
  { key: 'needs_staff', label: 'Needs staff', help: 'A person must decide; the reason is shown', action: { to: '/decision-queue', label: 'Open decision queue' }, tone: 'amber' },
  { key: 'awaiting_approval', label: 'Awaiting approval', help: 'Waiting for a named approver', action: { to: '/ap-workflow', label: 'Open approvals' }, tone: 'sky' },
  { key: 'on_hold', label: 'On hold', help: 'Held by staff with a reason', action: { to: '/ap-workflow', label: 'Open holds' }, tone: 'sky' },
  { key: 'drafted', label: 'Drafted (sandbox)', help: 'The Hub drafted it in the PRE sandbox, a test copy of BC. Not a real invoice: it moves to Entered in BC once AP enters it in Production', tone: 'emerald' },
  { key: 'awaiting_receipt', label: 'Waiting for receipt', help: 'Product invoice that arrived before the goods were received in BC; the Hub drafts it from the receipt once it posts', tone: 'sky' },
  { key: 'ready', label: 'Ready for AP', help: 'Vendor, number, amount and folder known; waiting for AP to enter it in BC', tone: 'emerald' },
  { key: 'in_bc_check', label: 'Entered in BC, check', help: "Entered in Production BC, but BC's amount or invoice number differs from the document", tone: 'amber' },
  { key: 'in_bc', label: 'Entered in BC', help: 'AP entered it in Production BC; BC is now the record', tone: 'muted' },
  { key: 'paid', label: 'Paid', help: 'BC shows it paid', tone: 'muted' },
  { key: 'filed_by_staff', label: 'Filed by staff', help: 'Staff already filed it in Square9', tone: 'muted' },
  { key: 'file_only', label: 'File only', help: 'Supporting paperwork (BOLs, packing lists, receipts); no AP decision', tone: 'muted' },
  { key: 'no_action', label: 'No action', help: 'Duplicate, companion copy, continuation page, or not an AP document', tone: 'muted' },
];

const REASONS = {
  suspected_fraud: 'Suspected fraud',
  vendor_unknown: 'Vendor unknown',
  number_or_amount_missing: 'Number or amount missing',
  po_not_in_bc: 'PO not found in BC',
  draft_lines_problem: "Draft lines don't add up",
  routing_uncertain: 'Folder uncertain',
  approval_rejected: 'Approval rejected',
  amount_differs: 'BC amount differs',
  number_differs: 'BC invoice number differs',
};

const TONE = {
  amber: 'border-amber-500/40 text-amber-400',
  sky: 'border-sky-500/40 text-sky-400',
  emerald: 'border-emerald-500/40 text-emerald-400',
  muted: 'border-border text-muted-foreground',
};

function money(value, currency) {
  if (value == null) return '—';
  const text = Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency && currency !== 'USD' ? `${text} ${currency}` : text;
}

function why(doc) {
  if (doc.staff_reason) return REASONS[doc.staff_reason] || doc.staff_reason;
  if (doc.check_reason) return REASONS[doc.check_reason] || doc.check_reason;
  if (doc.ap_hold) return doc.ap_hold.reason;
  if (doc.ap_approval) return `${doc.ap_approval.approver} to approve`;
  if (doc.suggested_approver) return `${doc.suggested_approver} to approve (suggested)`;
  if (doc.no_action_reason) return String(doc.no_action_reason).replace(/_/g, ' ').replace(/^excluded by staff:/, 'excluded by staff ');
  if (doc.bc_draft_no) return `Sandbox draft ${doc.bc_draft_no} (${doc.bc_draft_environment && doc.bc_draft_environment.startsWith('PRE') ? 'PRE' : doc.bc_draft_environment}), not a real invoice`;
  if (doc.bc_link?.bc_document_no) return `BC ${doc.bc_link.bc_document_no}${doc.bc_link.bc_status ? ` (${doc.bc_link.bc_status})` : ''}`;
  if (doc.staff_decided) return 'Folder decided by staff';
  return '';
}

export default function APInboxPage() {
  const [stage, setStage] = useState('needs_staff');
  const [query, setQuery] = useState('');
  const [search, setSearch] = useState('');
  const [days, setDays] = useState(30);
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const PAGE = 50;

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data: result } = await api.get('/ap-workflow/worklist', {
        params: { stage, q: search, days, skip: page * PAGE, limit: PAGE },
      });
      setData(result);
    } catch (error) {
      toast.error('Failed to load the AP inbox');
    } finally {
      setLoading(false);
    }
  }, [stage, search, days, page]);

  useEffect(() => { load(); }, [load]);

  const counts = data?.counts || {};
  const current = STAGES.find(s => s.key === stage);

  return (
    <div className="space-y-5" data-testid="ap-inbox-page">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <Inbox className="w-6 h-6 mt-1 text-primary" />
          <div>
            <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>AP Inbox</h1>
            <p className="text-sm text-muted-foreground max-w-3xl">
              Every AP document is in exactly one stage. Only the first three need a person; everything else is
              handled, waiting for AP to enter it in Business Central, or already there.
            </p>
            {data?.draft_accuracy?.drafts > 0 && (
              <p className="text-xs text-muted-foreground mt-1" data-testid="ap-draft-accuracy">
                Sandbox drafts graded against what AP then entered in Production: <b className="text-foreground">{data.draft_accuracy.exact}/{data.draft_accuracy.drafts}</b> exact ·
                items {data.draft_accuracy.items_right}/{data.draft_accuracy.ap_items} · totals right {data.draft_accuracy.total_right}/{data.draft_accuracy.drafts}
              </p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <select value={days} onChange={event => { setDays(Number(event.target.value)); setPage(0); }}
            className="rounded-md border border-border bg-background px-2 py-1.5 text-sm" aria-label="Period">
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
          <Button type="button" size="sm" variant="outline" onClick={load}>
            <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 xl:grid-cols-11 gap-2">
        {STAGES.map(s => (
          <button
            key={s.key}
            type="button"
            title={s.help}
            onClick={() => { setStage(s.key); setPage(0); }}
            className={`rounded-md border p-2 text-left transition-colors ${
              stage === s.key ? 'border-primary bg-primary/10' : 'border-border hover:border-foreground/30'}`}
            data-testid={`ap-stage-${s.key}`}
          >
            <div className="text-[11px] text-muted-foreground leading-tight">{s.label}</div>
            <div className={`text-lg font-semibold ${s.tone === 'amber' && counts[s.key] ? 'text-amber-400' : ''}`}>{counts[s.key] || 0}</div>
          </button>
        ))}
      </div>

      <Card>
        <CardContent className="p-4 space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="font-semibold">{current?.label}</div>
              <div className="text-xs text-muted-foreground">{current?.help}</div>
            </div>
            <div className="flex items-center gap-2">
              {current?.action && (
                <Button asChild size="sm">
                  <Link to={current.action.to}>{current.action.label} <ArrowRight className="w-3.5 h-3.5 ml-1.5" /></Link>
                </Button>
              )}
              <form
                onSubmit={event => { event.preventDefault(); setSearch(query); setPage(0); }}
                className="flex items-center gap-1"
              >
                <input
                  value={query}
                  onChange={event => setQuery(event.target.value)}
                  placeholder="Vendor, invoice, PO, file, BC no."
                  className="w-64 rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                  aria-label="Search"
                />
                <Button type="submit" size="sm" variant="outline"><Search className="w-3.5 h-3.5" /></Button>
              </form>
            </div>
          </div>

          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground">
              <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
            </div>
          ) : (data?.items || []).length === 0 ? (
            <div className="py-12 text-center text-sm text-muted-foreground">Nothing in this stage{search ? ` matching “${search}”` : ''}.</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs text-muted-foreground text-left border-b">
                    <th className="py-1.5 pr-3">Received</th>
                    <th className="py-1.5 pr-3">Vendor</th>
                    <th className="py-1.5 pr-3">Invoice</th>
                    <th className="py-1.5 pr-3 text-right">Amount</th>
                    <th className="py-1.5 pr-3">PO</th>
                    <th className="py-1.5 pr-3">Folder</th>
                    <th className="py-1.5 pr-3">Why</th>
                    <th className="py-1.5 pr-3">Document</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map(doc => (
                    <tr key={doc.id} className="border-b last:border-0 align-top hover:bg-muted/30">
                      <td className="py-1.5 pr-3 whitespace-nowrap">{(doc.created_utc || '').slice(0, 10)}</td>
                      <td className="py-1.5 pr-3">{doc.vendor_canonical || doc.vendor_raw || '—'}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{doc.invoice_number_clean || '—'}
                        {doc.document_type === 'Credit_Memo' && <Badge variant="outline" className="ml-1 text-[10px]">credit</Badge>}
                      </td>
                      <td className="py-1.5 pr-3 text-right whitespace-nowrap">{money(doc.amount_float, doc.currency)}</td>
                      <td className="py-1.5 pr-3 font-mono text-xs">{doc.po_number_clean || '—'}</td>
                      <td className="py-1.5 pr-3 text-xs">{doc.suggested_folder || '—'}</td>
                      <td className="py-1.5 pr-3 text-xs">
                        <Badge variant="outline" className={TONE[current?.tone || 'muted']}>{why(doc) || current?.label}</Badge>
                      </td>
                      <td className="py-1.5 pr-3 text-xs">
                        <Link className="hover:underline" to={`/documents/${encodeURIComponent(doc.id)}`}>{doc.file_name}</Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && data.total > PAGE && (
            <div className="flex items-center justify-end gap-2 text-xs text-muted-foreground">
              {page * PAGE + 1}–{Math.min((page + 1) * PAGE, data.total)} of {data.total}
              <Button type="button" size="sm" variant="outline" disabled={page === 0} onClick={() => setPage(p => p - 1)}>Previous</Button>
              <Button type="button" size="sm" variant="outline" disabled={(page + 1) * PAGE >= data.total} onClick={() => setPage(p => p + 1)}>Next</Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

