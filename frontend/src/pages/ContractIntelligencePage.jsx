import { useEffect, useMemo, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '../components/ui/tabs';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from '../components/ui/table';
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger,
} from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  FileSignature, AlertTriangle, Link2, CalendarClock, BarChart3, RefreshCw,
  UploadCloud, FileSpreadsheet, CheckCircle2, XCircle, AlertCircle,
} from 'lucide-react';
import {
  getContractSummary,
  getContractExpiring,
  getContractCoverage,
  getContractThresholdTelemetry,
  listAgreements,
  getAgreementDetail,
  listAgreementExceptions,
  resolveAgreementException,
  confirmAgreementLink,
  rejectAgreementLink,
  createManualAgreementLink,
  getAgreementAudit,
  getContractsHealth,
  contractsBCSearch,
  importNavigatorExport,
} from '../lib/api';

// =============================================================================
// Helpers
// =============================================================================

function StatusBadge({ status }) {
  const map = {
    completed: 'bg-emerald-600',
    sent: 'bg-blue-600',
    delivered: 'bg-blue-500',
    drafted: 'bg-zinc-500',
    declined: 'bg-rose-600',
    voided: 'bg-zinc-700',
    expired: 'bg-amber-600',
    unknown: 'bg-zinc-500',
    auto_confirmed: 'bg-emerald-600',
    confirmed: 'bg-emerald-700',
    proposed: 'bg-blue-600',
    rejected: 'bg-rose-600',
    open: 'bg-amber-600',
    resolved: 'bg-emerald-600',
    in_review: 'bg-blue-600',
    wont_fix: 'bg-zinc-600',
    high: 'bg-rose-600',
    medium: 'bg-amber-600',
    low: 'bg-zinc-500',
    critical: 'bg-rose-700',
  };
  const cls = map[status] || 'bg-zinc-500';
  return (
    <Badge className={`${cls} text-white capitalize`} data-testid={`status-badge-${status}`}>
      {String(status || 'unknown').replace(/_/g, ' ')}
    </Badge>
  );
}

function pct(v) {
  if (v == null) return '—';
  return `${Math.round(Number(v) * 100)}%`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

// =============================================================================
// Tab: Analytics — dashboard cards + threshold telemetry
// =============================================================================

function AnalyticsTab() {
  const [summary, setSummary] = useState(null);
  const [coverage, setCoverage] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const [s, c, t, h] = await Promise.all([
        getContractSummary(),
        getContractCoverage(),
        getContractThresholdTelemetry({ days: 30 }),
        getContractsHealth(),
      ]);
      setSummary(s.data); setCoverage(c.data);
      setTelemetry(t.data); setHealth(h.data);
    } catch (e) {
      toast.error('Failed to load analytics: ' + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, []);

  return (
    <div className="space-y-6" data-testid="analytics-tab">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Contract Analytics</h2>
        <Button size="sm" variant="outline" onClick={refresh}
                disabled={loading} data-testid="analytics-refresh-btn">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Top-level counts */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card data-testid="card-agreements-total">
          <CardHeader><CardTitle className="text-sm font-medium">Agreements</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary?.agreements?.total ?? '—'}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.agreements?.with_unmatched_exceptions ?? 0} with open exceptions
            </p>
          </CardContent>
        </Card>
        <Card data-testid="card-exceptions-open">
          <CardHeader><CardTitle className="text-sm font-medium">Open Exceptions</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-amber-500">
              {summary?.exceptions?.open ?? '—'}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.exceptions?.resolved ?? 0} resolved
            </p>
          </CardContent>
        </Card>
        <Card data-testid="card-links-total">
          <CardHeader><CardTitle className="text-sm font-medium">BC Links</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary?.links?.total ?? '—'}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.links?.by_status?.confirmed ?? 0} confirmed,
              {' '}{summary?.links?.by_status?.proposed ?? 0} proposed
            </p>
          </CardContent>
        </Card>
        <Card data-testid="card-events-unprocessed">
          <CardHeader><CardTitle className="text-sm font-medium">Events</CardTitle></CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{summary?.events?.total ?? '—'}</div>
            <p className="text-xs text-muted-foreground mt-1">
              {summary?.events?.unprocessed ?? 0} unprocessed
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Coverage */}
      {coverage && (
        <Card data-testid="card-coverage">
          <CardHeader><CardTitle className="text-base">BC Coverage (advisory)</CardTitle></CardHeader>
          <CardContent>
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
              <div>
                <div className="text-xs text-muted-foreground">Customer coverage</div>
                <div className="text-2xl font-semibold">{pct(coverage.customer_coverage?.ratio)}</div>
                <div className="text-xs">{coverage.customer_coverage?.covered} / {coverage.agreements_total}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Vendor coverage</div>
                <div className="text-2xl font-semibold">{pct(coverage.vendor_coverage?.ratio)}</div>
                <div className="text-xs">{coverage.vendor_coverage?.covered} / {coverage.agreements_total}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Item coverage</div>
                <div className="text-2xl font-semibold">{pct(coverage.item_coverage?.ratio)}</div>
                <div className="text-xs">{coverage.item_coverage?.agreements_with_item_links} / {coverage.agreements_total}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Pricing match ratio</div>
                <div className="text-2xl font-semibold">{pct(coverage.pricing_lines?.match_ratio)}</div>
                <div className="text-xs">{coverage.pricing_lines?.matched} / {coverage.pricing_lines?.total}</div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Threshold telemetry */}
      {telemetry && (
        <Card data-testid="card-threshold-telemetry">
          <CardHeader>
            <CardTitle className="text-base">
              Auto-Confirm Threshold Telemetry (last {telemetry.window_days} days)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Auto-confirm threshold</div>
                <div className="text-2xl font-semibold">{telemetry.thresholds?.auto_confirm}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Propose threshold</div>
                <div className="text-2xl font-semibold">{telemetry.thresholds?.propose}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">System-emitted</div>
                <div className="text-2xl font-semibold">{telemetry.system_emitted}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Human overrides</div>
                <div className="text-2xl font-semibold text-rose-500">{telemetry.human_overrides}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Combined override rate</div>
                <div className="text-2xl font-semibold">
                  {telemetry.override_rate != null ? pct(telemetry.override_rate) : '—'}
                </div>
              </div>
            </div>

            {/* Phase 3.1 — separated band-level override rates */}
            <div className="mt-5 grid grid-cols-1 md:grid-cols-2 gap-4 text-sm border-t pt-4">
              <div data-testid="telemetry-auto-confirm-band">
                <div className="flex items-baseline justify-between">
                  <div>
                    <div className="text-xs text-muted-foreground">
                      Auto-confirm band override rate
                    </div>
                    <div className="text-3xl font-semibold">
                      {pct(telemetry.auto_confirm_override_rate)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-muted-foreground">
                      {telemetry.by_band_overrides?.auto_confirm ?? 0} rejected of
                      {' '}{telemetry.by_threshold_band?.auto_confirm ?? 0}
                    </div>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Higher than ~5% suggests the auto-confirm threshold is too low.
                </p>
              </div>
              <div data-testid="telemetry-propose-band">
                <div className="flex items-baseline justify-between">
                  <div>
                    <div className="text-xs text-muted-foreground">
                      Propose band override rate
                    </div>
                    <div className="text-3xl font-semibold">
                      {pct(telemetry.propose_override_rate)}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-xs text-muted-foreground">
                      {telemetry.by_band_overrides?.propose ?? 0} rejected of
                      {' '}{telemetry.by_threshold_band?.propose ?? 0}
                    </div>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground mt-1">
                  Higher rejection here is expected — propose links are reviewed by humans.
                </p>
              </div>
            </div>

            <div className="mt-3 text-xs text-muted-foreground">
              Band distribution: auto-confirm {telemetry.by_threshold_band?.auto_confirm ?? 0} ·
              propose {telemetry.by_threshold_band?.propose ?? 0} ·
              below propose {telemetry.by_threshold_band?.below_propose ?? 0}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Vendor link telemetry (volume of suppressed misses) */}
      {health?.vendor_link_telemetry && (
        <Card data-testid="card-vendor-telemetry">
          <CardHeader>
            <CardTitle className="text-base">Vendor-side activity (suppressed exceptions)</CardTitle>
          </CardHeader>
          <CardContent className="text-sm">
            <p className="text-muted-foreground mb-2">
              Vendor-side party misses are not surfaced as exceptions by default
              (would be too noisy). Volume tracked here for visibility.
            </p>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-xs text-muted-foreground">Proposed vendor links (lifetime)</div>
                <div className="text-2xl font-semibold">
                  {health.vendor_link_telemetry.proposed_vendor_links_total}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Confirmed vendor links (lifetime)</div>
                <div className="text-2xl font-semibold">
                  {health.vendor_link_telemetry.confirmed_vendor_links_total}
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

// =============================================================================
// Tab: Agreements — list + drill-in detail (with manual mapping + audit)
// =============================================================================

function AgreementsTab() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState(null);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await listAgreements({
        status: statusFilter || undefined, limit: 100,
      });
      setItems(r.data.items || []);
    } catch (e) {
      toast.error('Failed to load agreements: ' + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [statusFilter]);

  return (
    <div className="space-y-4" data-testid="agreements-tab">
      <div className="flex items-center gap-2 flex-wrap">
        <Label htmlFor="agr-status-filter" className="text-sm">Status:</Label>
        <select
          id="agr-status-filter"
          className="bg-background border rounded px-2 py-1 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          data-testid="agreements-status-filter"
        >
          <option value="">All</option>
          {['drafted','sent','delivered','completed','declined','voided','expired'].map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <Button size="sm" variant="outline" onClick={refresh}
                disabled={loading} data-testid="agreements-refresh-btn">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
        <span className="text-xs text-muted-foreground ml-auto">{items.length} shown</span>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table data-testid="agreements-table">
            <TableHeader>
              <TableRow>
                <TableHead>Envelope</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Sender</TableHead>
                <TableHead>Completed</TableHead>
                <TableHead>Expires</TableHead>
                <TableHead>Open Exc.</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={8} className="text-center text-muted-foreground py-8">
                    No agreements found.
                  </TableCell>
                </TableRow>
              )}
              {items.map(a => (
                <TableRow key={a.id} data-testid={`agreement-row-${a.id}`}>
                  <TableCell className="font-mono text-xs">
                    {a.provider_envelope_id}
                  </TableCell>
                  <TableCell className="max-w-[300px] truncate">
                    {a.title || a.email_subject || '—'}
                  </TableCell>
                  <TableCell><StatusBadge status={a.status} /></TableCell>
                  <TableCell className="text-sm">{a.sender_name || '—'}</TableCell>
                  <TableCell className="text-xs">{fmtDate(a.completed_at)}</TableCell>
                  <TableCell className="text-xs">{fmtDate(a.expires_at)}</TableCell>
                  <TableCell>
                    {a.has_unmatched_exceptions
                      ? <Badge className="bg-amber-600 text-white">Yes</Badge>
                      : <span className="text-xs text-muted-foreground">No</span>}
                  </TableCell>
                  <TableCell>
                    <Button size="sm" variant="ghost"
                            onClick={() => setSelectedId(a.id)}
                            data-testid={`open-detail-${a.id}`}>
                      Open
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {selectedId && (
        <AgreementDetailDialog
          agreementId={selectedId}
          onClose={() => { setSelectedId(null); refresh(); }}
        />
      )}
    </div>
  );
}

function AgreementDetailDialog({ agreementId, onClose }) {
  const [data, setData] = useState(null);
  const [audit, setAudit] = useState([]);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(true);
  const [rejectDialog, setRejectDialog] = useState(null); // { linkId }

  const refresh = async () => {
    setBusy(true);
    try {
      const [d, a] = await Promise.all([
        getAgreementDetail(agreementId),
        getAgreementAudit(agreementId),
      ]);
      setData(d.data);
      setAudit(a.data?.items || []);
    } catch (e) {
      toast.error('Failed to load agreement: ' + (e?.response?.data?.detail || e.message));
    } finally { setBusy(false); }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [agreementId]);

  const handleConfirmLink = async (linkId) => {
    try {
      await confirmAgreementLink(agreementId, linkId);
      toast.success('Link confirmed');
      refresh();
    } catch (e) { toast.error(e?.response?.data?.detail || e.message); }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => { setOpen(v); if (!v) onClose(); }}>
      <DialogContent className="max-w-5xl max-h-[90vh] overflow-y-auto"
                     data-testid="agreement-detail-dialog">
        <DialogHeader>
          <DialogTitle>
            {data?.agreement?.title || data?.agreement?.email_subject || 'Agreement'}
          </DialogTitle>
        </DialogHeader>
        {data && (
          <div className="space-y-6">
            {/* Header summary */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <div className="text-xs text-muted-foreground">Envelope</div>
                <div className="font-mono">{data.agreement.provider_envelope_id}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Status</div>
                <StatusBadge status={data.agreement.status} />
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Sender</div>
                <div>{data.agreement.sender_name || '—'}</div>
              </div>
              <div>
                <div className="text-xs text-muted-foreground">Expires</div>
                <div>{fmtDate(data.agreement.expires_at)}</div>
              </div>
            </div>

            {/* Parties */}
            <Section title="Parties" count={data.parties.length}>
              <Table>
                <TableHeader><TableRow>
                  <TableHead>Role</TableHead><TableHead>Name</TableHead>
                  <TableHead>Email</TableHead><TableHead>Org</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {data.parties.map(p => (
                    <TableRow key={p.id} data-testid={`party-row-${p.id}`}>
                      <TableCell className="capitalize">{p.role.replace(/_/g, ' ')}</TableCell>
                      <TableCell>{p.name || '—'}</TableCell>
                      <TableCell className="text-xs">{p.email || '—'}</TableCell>
                      <TableCell>{p.organization || '—'}</TableCell>
                      <TableCell><StatusBadge status={p.signing_status} /></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Section>

            {/* BC Links */}
            <Section title="BC Links" count={data.bc_links.length}>
              <Table>
                <TableHeader><TableRow>
                  <TableHead>Type</TableHead><TableHead>BC No</TableHead>
                  <TableHead>BC Name</TableHead><TableHead>Method</TableHead>
                  <TableHead>Confidence</TableHead><TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow></TableHeader>
                <TableBody>
                  {data.bc_links.map(l => (
                    <TableRow key={l.id} data-testid={`link-row-${l.id}`}>
                      <TableCell className="capitalize">{l.link_type}</TableCell>
                      <TableCell className="font-mono text-xs">{l.bc_no}</TableCell>
                      <TableCell>{l.bc_name_snapshot || '—'}</TableCell>
                      <TableCell className="text-xs">{l.match_method}</TableCell>
                      <TableCell>{(l.confidence * 100).toFixed(0)}%</TableCell>
                      <TableCell><StatusBadge status={l.status} /></TableCell>
                      <TableCell>
                        {(l.status === 'proposed' || l.status === 'auto_confirmed') && (
                          <div className="flex gap-2">
                            <Button size="sm" variant="default"
                                    onClick={() => handleConfirmLink(l.id)}
                                    data-testid={`confirm-link-${l.id}`}>
                              Confirm
                            </Button>
                            <Button size="sm" variant="destructive"
                                    onClick={() => setRejectDialog({ linkId: l.id })}
                                    data-testid={`reject-link-${l.id}`}>
                              Reject
                            </Button>
                          </div>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <ManualLinkForm agreementId={agreementId} onSaved={refresh} />
            </Section>

            {/* Pricing */}
            {data.pricing.length > 0 && (
              <Section title="Pricing" count={data.pricing.length}>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>Line</TableHead><TableHead>Item</TableHead>
                    <TableHead>Qty</TableHead><TableHead>UOM</TableHead>
                    <TableHead>Unit</TableHead><TableHead>Total</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.pricing.map(p => (
                      <TableRow key={p.id}>
                        <TableCell>{p.line_no}</TableCell>
                        <TableCell>{p.item_label || '—'}</TableCell>
                        <TableCell>{p.quantity ?? '—'}</TableCell>
                        <TableCell>{p.uom || '—'}</TableCell>
                        <TableCell>{p.unit_price != null ? `$${p.unit_price}` : '—'}</TableCell>
                        <TableCell>{p.line_total != null ? `$${p.line_total}` : '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Section>
            )}

            {/* Terms */}
            {data.terms.length > 0 && (
              <Section title="Terms" count={data.terms.length}>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>Key</TableHead><TableHead>Value</TableHead>
                    <TableHead>Source</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.terms.map(t => (
                      <TableRow key={t.id}>
                        <TableCell className="font-mono text-xs">{t.term_key}</TableCell>
                        <TableCell>{t.term_value || '—'}</TableCell>
                        <TableCell className="text-xs">{t.source}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Section>
            )}

            {/* Exceptions */}
            {data.exceptions.length > 0 && (
              <Section title="Exceptions" count={data.exceptions.length}>
                <Table>
                  <TableHeader><TableRow>
                    <TableHead>Code</TableHead><TableHead>Severity</TableHead>
                    <TableHead>Status</TableHead><TableHead>Details</TableHead>
                  </TableRow></TableHeader>
                  <TableBody>
                    {data.exceptions.map(e => (
                      <TableRow key={e.id}>
                        <TableCell className="text-xs">{e.code}</TableCell>
                        <TableCell><StatusBadge status={e.severity} /></TableCell>
                        <TableCell><StatusBadge status={e.status} /></TableCell>
                        <TableCell className="text-xs max-w-md">
                          <pre className="whitespace-pre-wrap break-words">
                            {JSON.stringify(e.details, null, 2)}
                          </pre>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Section>
            )}

            {/* Audit */}
            <Section title="Audit Trail" count={audit.length}>
              <div className="text-xs space-y-2 max-h-64 overflow-y-auto">
                {audit.map(a => (
                  <div key={a.id} className="border-l-2 border-zinc-700 pl-2"
                       data-testid={`audit-row-${a.id}`}>
                    <div>
                      <span className="font-mono">{fmtDate(a.at)}</span>
                      {' · '}<span className="font-semibold">{a.action}</span>
                      {' · '}<span className="text-muted-foreground">{a.actor}</span>
                    </div>
                    {a.notes && <div className="text-muted-foreground">{a.notes}</div>}
                  </div>
                ))}
                {audit.length === 0 && (
                  <div className="text-muted-foreground">No audit entries.</div>
                )}
              </div>
            </Section>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => { setOpen(false); onClose(); }}
                  data-testid="agreement-detail-close">
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
      {rejectDialog && (
        <NoteDialog
          title="Reject BC link"
          description="Why are you rejecting this link? (Optional, written to audit trail.)"
          confirmLabel="Reject link"
          confirmVariant="destructive"
          testIdPrefix="reject-link-dialog"
          onCancel={() => setRejectDialog(null)}
          onSubmit={async (note) => {
            try {
              await rejectAgreementLink(agreementId, rejectDialog.linkId, { notes: note || null });
              toast.success('Link rejected');
              setRejectDialog(null);
              refresh();
            } catch (e) {
              toast.error(e?.response?.data?.detail || e.message);
            }
          }}
        />
      )}
    </Dialog>
  );
}

// Reusable dialog for capturing an optional note. Replaces window.prompt().
function NoteDialog({
  title, description, confirmLabel, confirmVariant = 'default',
  testIdPrefix, onCancel, onSubmit,
}) {
  const [note, setNote] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const handle = async () => {
    setSubmitting(true);
    try { await onSubmit(note.trim()); }
    finally { setSubmitting(false); }
  };
  return (
    <Dialog open onOpenChange={(v) => { if (!v) onCancel(); }}>
      <DialogContent className="max-w-md" data-testid={`${testIdPrefix}-dialog`}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {description && (
          <p className="text-sm text-muted-foreground" data-testid={`${testIdPrefix}-description`}>
            {description}
          </p>
        )}
        <Textarea
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={4}
          placeholder="Optional note…"
          data-testid={`${testIdPrefix}-textarea`}
        />
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={submitting}
                  data-testid={`${testIdPrefix}-cancel`}>
            Cancel
          </Button>
          <Button variant={confirmVariant} onClick={handle} disabled={submitting}
                  data-testid={`${testIdPrefix}-submit`}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Section({ title, count, children }) {
  return (
    <section>
      <h3 className="text-sm font-semibold mb-2">
        {title} <span className="text-muted-foreground">({count})</span>
      </h3>
      {children}
    </section>
  );
}

function ManualLinkForm({ agreementId, onSaved }) {
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({
    link_type: 'customer', bc_entity: 'customers', bc_no: '',
    bc_name_snapshot: '', notes: '',
  });
  const submit = async () => {
    try {
      await createManualAgreementLink(agreementId, form);
      toast.success('Manual link added');
      setOpen(false);
      onSaved();
    } catch (e) { toast.error(e?.response?.data?.detail || e.message); }
  };
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" variant="outline" className="mt-2"
                data-testid="manual-link-trigger">
          + Manual link
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-md" data-testid="manual-link-dialog">
        <DialogHeader><DialogTitle>Add manual BC link</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div>
            <Label htmlFor="link_type">Link type</Label>
            <select
              id="link_type"
              className="w-full bg-background border rounded px-2 py-2 text-sm"
              value={form.link_type}
              onChange={(e) => {
                const lt = e.target.value;
                const entityMap = {
                  customer: 'customers', vendor: 'vendors', item: 'items',
                  sales_order: 'sales_orders', purchase_order: 'purchase_orders',
                  contact: 'contacts',
                };
                setForm(f => ({
                  ...f, link_type: lt, bc_entity: entityMap[lt] || lt,
                }));
              }}
              data-testid="manual-link-type"
            >
              {['customer','vendor','item','sales_order','purchase_order','contact'].map(t => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="bc_no">BC No.</Label>
            <Input id="bc_no" value={form.bc_no}
                   onChange={(e) => setForm(f => ({ ...f, bc_no: e.target.value }))}
                   data-testid="manual-link-bcno" />
          </div>
          <div>
            <Label htmlFor="bc_name">Name (snapshot)</Label>
            <Input id="bc_name" value={form.bc_name_snapshot}
                   onChange={(e) => setForm(f => ({ ...f, bc_name_snapshot: e.target.value }))}
                   data-testid="manual-link-bcname" />
          </div>
          <div>
            <Label htmlFor="notes">Notes</Label>
            <Input id="notes" value={form.notes}
                   onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))}
                   data-testid="manual-link-notes" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
          <Button onClick={submit} disabled={!form.bc_no}
                  data-testid="manual-link-submit">
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// =============================================================================
// Tab: Exceptions — list + resolve
// =============================================================================

function ExceptionsTab() {
  const [items, setItems] = useState([]);
  const [statusFilter, setStatusFilter] = useState('open');
  const [codeFilter, setCodeFilter] = useState('');
  const [loading, setLoading] = useState(true);
  const [resolveDialog, setResolveDialog] = useState(null); // { id }
  const [mapDialog, setMapDialog] = useState(null); // { exception }

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await listAgreementExceptions({
        status: statusFilter || undefined,
        code: codeFilter || undefined,
        limit: 200,
      });
      setItems(r.data.items || []);
    } catch (e) {
      toast.error('Failed to load exceptions: ' + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [statusFilter, codeFilter]);

  const exceptionToDefaultLinkType = (ex) => {
    if (ex?.code === 'item_unmatched') return 'item';
    return 'customer'; // most party_unmatched cases
  };

  return (
    <div className="space-y-4" data-testid="exceptions-tab">
      <div className="flex items-center gap-3 flex-wrap">
        <Label className="text-sm">Status:</Label>
        <select
          className="bg-background border rounded px-2 py-1 text-sm"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          data-testid="exceptions-status-filter"
        >
          <option value="">All</option>
          {['open','in_review','resolved','wont_fix'].map(s => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <Label className="text-sm">Code:</Label>
        <select
          className="bg-background border rounded px-2 py-1 text-sm"
          value={codeFilter}
          onChange={(e) => setCodeFilter(e.target.value)}
          data-testid="exceptions-code-filter"
        >
          <option value="">All</option>
          {['party_unmatched','item_unmatched','term_missing','pricing_unparsable',
            'normalization_failed','other'].map(c => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <Button size="sm" variant="outline" onClick={refresh}
                disabled={loading} data-testid="exceptions-refresh-btn">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
        <span className="text-xs text-muted-foreground ml-auto">{items.length} shown</span>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table data-testid="exceptions-table">
            <TableHeader>
              <TableRow>
                <TableHead>Code</TableHead>
                <TableHead>Severity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Agreement</TableHead>
                <TableHead>Opened</TableHead>
                <TableHead>Details</TableHead>
                <TableHead></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                    No exceptions match the current filter.
                  </TableCell>
                </TableRow>
              )}
              {items.map(e => (
                <TableRow key={e.id} data-testid={`exception-row-${e.id}`}>
                  <TableCell className="text-xs">{e.code}</TableCell>
                  <TableCell><StatusBadge status={e.severity} /></TableCell>
                  <TableCell><StatusBadge status={e.status} /></TableCell>
                  <TableCell className="font-mono text-xs">{e.agreement_id}</TableCell>
                  <TableCell className="text-xs">{fmtDate(e.opened_at)}</TableCell>
                  <TableCell className="text-xs max-w-md truncate">
                    {Object.entries(e.details || {}).map(([k, v]) => (
                      <div key={k}><span className="text-muted-foreground">{k}:</span> {String(v)}</div>
                    ))}
                  </TableCell>
                  <TableCell>
                    {e.status === 'open' && (
                      <div className="flex gap-2">
                        {(e.code === 'party_unmatched' || e.code === 'item_unmatched') && (
                          <Button size="sm" variant="default"
                                  onClick={() => setMapDialog({ exception: e })}
                                  data-testid={`map-exception-${e.id}`}>
                            Map
                          </Button>
                        )}
                        <Button size="sm" variant="outline"
                                onClick={() => setResolveDialog({ id: e.id })}
                                data-testid={`resolve-exception-${e.id}`}>
                          Resolve
                        </Button>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {resolveDialog && (
        <NoteDialog
          title="Resolve exception"
          description="Add a note explaining how this exception was handled. Written to audit trail."
          confirmLabel="Mark resolved"
          testIdPrefix="resolve-exception-dialog"
          onCancel={() => setResolveDialog(null)}
          onSubmit={async (note) => {
            try {
              await resolveAgreementException(resolveDialog.id, { note: note || null });
              toast.success('Exception resolved');
              setResolveDialog(null);
              refresh();
            } catch (err) {
              toast.error(err?.response?.data?.detail || err.message);
            }
          }}
        />
      )}

      {mapDialog && (
        <ExceptionMappingDialog
          exception={mapDialog.exception}
          defaultLinkType={exceptionToDefaultLinkType(mapDialog.exception)}
          onCancel={() => setMapDialog(null)}
          onMapped={() => { setMapDialog(null); refresh(); }}
        />
      )}
    </div>
  );
}

// Inline workflow: search BC → confirm a link → resolve exception in one shot.
function ExceptionMappingDialog({ exception, defaultLinkType, onCancel, onMapped }) {
  const [linkType, setLinkType] = useState(defaultLinkType);
  const [query, setQuery] = useState(
    exception?.details?.party_org
    || exception?.details?.party_name
    || exception?.details?.item_label
    || ''
  );
  const [results, setResults] = useState([]);
  const [hint, setHint] = useState(null);
  const [searching, setSearching] = useState(false);
  const [bcNo, setBcNo] = useState('');
  const [bcName, setBcName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [resolveAfter, setResolveAfter] = useState(true);

  const linkTypeMeta = useMemo(() => ({
    customer: { entity: 'customers' },
    vendor: { entity: 'vendors' },
    item: { entity: 'items' },
  }[linkType] || { entity: linkType }), [linkType]);

  const runSearch = async () => {
    if (!query.trim()) return;
    setSearching(true);
    setHint(null);
    try {
      const r = await contractsBCSearch({ q: query.trim(), link_type: linkType, limit: 10 });
      setResults(r.data?.matches || []);
      setHint(r.data?.hint || null);
    } catch (e) {
      toast.error('BC search failed: ' + (e?.response?.data?.detail || e.message));
    } finally { setSearching(false); }
  };

  // Auto-search on open + when link_type changes.
  useEffect(() => { runSearch(); /* eslint-disable-next-line */ }, [linkType]);

  const pickResult = (m) => {
    setBcNo(m.bc_no);
    setBcName(m.bc_name);
  };

  const submit = async () => {
    if (!bcNo.trim()) {
      toast.error('Pick a BC entity (or enter a BC number) before saving.');
      return;
    }
    setSubmitting(true);
    try {
      await createManualAgreementLink(exception.agreement_id, {
        link_type: linkType,
        bc_entity: linkTypeMeta.entity,
        bc_no: bcNo.trim(),
        bc_name_snapshot: bcName.trim() || null,
        notes: `mapped from exception ${exception.id} (${exception.code})`,
      });
      if (resolveAfter) {
        await resolveAgreementException(exception.id, {
          note: `mapped to ${linkType}=${bcNo.trim()}`,
        });
      }
      toast.success(
        resolveAfter
          ? 'Link created and exception resolved'
          : 'Link created (exception left open)'
      );
      onMapped();
    } catch (e) {
      toast.error(e?.response?.data?.detail || e.message);
    } finally { setSubmitting(false); }
  };

  return (
    <Dialog open onOpenChange={(v) => { if (!v) onCancel(); }}>
      <DialogContent className="max-w-2xl" data-testid="exception-mapping-dialog">
        <DialogHeader>
          <DialogTitle>Map exception → BC entity</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="text-xs text-muted-foreground">
            Exception <span className="font-mono">{exception.id}</span> ·
            code <span className="font-mono">{exception.code}</span> ·
            agreement <span className="font-mono">{exception.agreement_id}</span>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="map-link-type">Link type</Label>
              <select
                id="map-link-type"
                className="w-full bg-background border rounded px-2 py-2 text-sm"
                value={linkType}
                onChange={(e) => { setLinkType(e.target.value); setBcNo(''); setBcName(''); }}
                data-testid="exception-mapping-link-type"
              >
                {['customer','vendor','item'].map(t => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
            </div>
            <div>
              <Label htmlFor="map-search">Search BC</Label>
              <div className="flex gap-2">
                <Input
                  id="map-search"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') runSearch(); }}
                  placeholder="Name or BC number…"
                  data-testid="exception-mapping-query"
                />
                <Button size="sm" variant="secondary" onClick={runSearch}
                        disabled={searching}
                        data-testid="exception-mapping-search-btn">
                  {searching ? '…' : 'Search'}
                </Button>
              </div>
            </div>
          </div>

          {hint && (
            <div className="text-xs p-2 rounded bg-amber-950/40 border border-amber-700"
                 data-testid="exception-mapping-hint">
              {hint}
            </div>
          )}

          <div className="border rounded max-h-48 overflow-y-auto"
               data-testid="exception-mapping-results">
            {results.length === 0 && !searching && (
              <div className="text-xs text-muted-foreground p-3">
                No candidates yet. Adjust the search or enter a BC number directly below.
              </div>
            )}
            {results.map((m) => (
              <button
                key={m.bc_no + m.source}
                type="button"
                onClick={() => pickResult(m)}
                className={`w-full text-left p-2 hover:bg-zinc-800/60 border-b last:border-b-0
                            ${bcNo === m.bc_no ? 'bg-zinc-800/80' : ''}`}
                data-testid={`exception-mapping-pick-${m.bc_no}`}
              >
                <div className="text-sm font-medium">{m.bc_name || '(no name)'}</div>
                <div className="text-xs text-muted-foreground">
                  <span className="font-mono">{m.bc_no}</span> · {m.source}
                </div>
              </button>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="map-bc-no">BC No.</Label>
              <Input id="map-bc-no" value={bcNo}
                     onChange={(e) => setBcNo(e.target.value)}
                     data-testid="exception-mapping-bcno" />
            </div>
            <div>
              <Label htmlFor="map-bc-name">Name (snapshot)</Label>
              <Input id="map-bc-name" value={bcName}
                     onChange={(e) => setBcName(e.target.value)}
                     data-testid="exception-mapping-bcname" />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={resolveAfter}
                   onChange={(e) => setResolveAfter(e.target.checked)}
                   data-testid="exception-mapping-resolve-after" />
            Mark exception as resolved after creating the link
          </label>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={submitting}
                  data-testid="exception-mapping-cancel">
            Cancel
          </Button>
          <Button onClick={submit} disabled={submitting || !bcNo.trim()}
                  data-testid="exception-mapping-submit">
            {submitting ? 'Saving…' : 'Map & Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

// =============================================================================
// Tab: BC Links — flat view across all agreements
// =============================================================================

function BCLinksTab() {
  const [data, setData] = useState({ summary: null, agreements: [] });
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const [s, a] = await Promise.all([
        getContractSummary(),
        listAgreements({ limit: 200 }),
      ]);
      setData({ summary: s.data, agreements: a.data?.items || [] });
    } catch (e) {
      toast.error('Failed to load BC links: ' + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); }, []);

  const byStatus = data.summary?.links?.by_status || {};
  const byType = data.summary?.links?.by_type || {};

  return (
    <div className="space-y-4" data-testid="bc-links-tab">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">BC Links Overview</h2>
        <Button size="sm" variant="outline" onClick={refresh} disabled={loading}
                data-testid="bc-links-refresh-btn">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {['confirmed','auto_confirmed','proposed','rejected'].map(s => (
          <Card key={s} data-testid={`bc-links-card-${s}`}>
            <CardHeader>
              <CardTitle className="text-sm capitalize">{s.replace('_', ' ')}</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{byStatus[s] ?? 0}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Card>
        <CardHeader><CardTitle className="text-base">By link type</CardTitle></CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            {['customer','vendor','item','sales_order','purchase_order','contact'].map(t => (
              <div key={t}>
                <div className="text-xs text-muted-foreground capitalize">{t}</div>
                <div className="text-xl font-semibold">{byType[t] ?? 0}</div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// =============================================================================
// Tab: Expirations
// =============================================================================

function ExpirationsTab() {
  const [items, setItems] = useState([]);
  const [days, setDays] = useState(60);
  const [loading, setLoading] = useState(true);

  const refresh = async () => {
    setLoading(true);
    try {
      const r = await getContractExpiring({ within_days: days, limit: 200 });
      setItems(r.data?.items || []);
    } catch (e) {
      toast.error('Failed to load expirations: ' + (e?.response?.data?.detail || e.message));
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); /* eslint-disable-next-line */ }, [days]);

  return (
    <div className="space-y-4" data-testid="expirations-tab">
      <div className="flex items-center gap-3 flex-wrap">
        <Label className="text-sm">Within</Label>
        <Input type="number" min={1} max={365}
               className="w-24" value={days}
               onChange={(e) => setDays(Math.max(1, Math.min(365, +e.target.value || 60)))}
               data-testid="expirations-days-input" />
        <span className="text-sm">days</span>
        <Button size="sm" variant="outline" onClick={refresh}
                disabled={loading} data-testid="expirations-refresh-btn">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
        <span className="text-xs text-muted-foreground ml-auto">{items.length} expiring</span>
      </div>

      <Card>
        <CardContent className="p-0">
          <Table data-testid="expirations-table">
            <TableHeader>
              <TableRow>
                <TableHead>Envelope</TableHead>
                <TableHead>Subject</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Expires</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items.length === 0 && !loading && (
                <TableRow>
                  <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                    No agreements expiring in this window.
                  </TableCell>
                </TableRow>
              )}
              {items.map(a => (
                <TableRow key={a.id} data-testid={`expiring-row-${a.id}`}>
                  <TableCell className="font-mono text-xs">{a.provider_envelope_id}</TableCell>
                  <TableCell className="max-w-[400px] truncate">
                    {a.title || a.email_subject || '—'}
                  </TableCell>
                  <TableCell><StatusBadge status={a.status} /></TableCell>
                  <TableCell className="text-xs">{fmtDate(a.expires_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}


// =============================================================================
// Tab: Import Navigator Export — Phase 4C(a)
// =============================================================================

function NavigatorImportTab() {
  const [file, setFile] = useState(null);
  const [dragActive, setDragActive] = useState(false);
  const [dryrunResult, setDryrunResult] = useState(null);
  const [commitResult, setCommitResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const onPick = (f) => {
    if (!f) return;
    const ok = /\.(xlsx|xlsm|csv|json)$/i.test(f.name);
    if (!ok) {
      toast.error(`Unsupported file type: ${f.name}`);
      return;
    }
    setFile(f);
    setDryrunResult(null);
    setCommitResult(null);
    setError(null);
  };

  const reset = () => {
    setFile(null);
    setDryrunResult(null);
    setCommitResult(null);
    setError(null);
  };

  const runDryrun = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    setCommitResult(null);
    try {
      const r = await importNavigatorExport(file, { commit: false });
      setDryrunResult(r.data);
      toast.success(`Dry-run complete: ${r.data.row_count} rows, ${r.data.error_count} errors`);
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      toast.error(`Dry-run failed: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const runCommit = async () => {
    if (!file || !dryrunResult) return;
    if (!window.confirm(
      `Commit ${dryrunResult.row_count} row(s)?\n\n` +
      `Would create: ${dryrunResult.would_create}\n` +
      `Would update: ${dryrunResult.would_update}\n\n` +
      `Manual mappings already in place will be preserved. ` +
      `Duplicate envelope ids will be skipped.`,
    )) return;
    setBusy(true);
    setError(null);
    try {
      const r = await importNavigatorExport(file, { commit: true });
      setCommitResult(r.data);
      toast.success(
        `Imported: ${r.data.committed} committed, ${r.data.skipped} skipped, ` +
        `${r.data.error_count} errors`
      );
    } catch (e) {
      const msg = e?.response?.data?.detail || e.message;
      setError(msg);
      toast.error(`Commit failed: ${msg}`);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (e) => {
    e.preventDefault();
    setDragActive(false);
    const f = e.dataTransfer?.files?.[0];
    if (f) onPick(f);
  };

  const renderSummary = (summary, label) => {
    if (!summary) return null;
    const isCommit = summary.mode === 'commit';
    return (
      <Card data-testid={`navigator-import-${label}-summary`}>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            {isCommit ? <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      : <FileSpreadsheet className="h-4 w-4 text-blue-600" />}
            {isCommit ? 'Commit summary' : 'Dry-run summary'} — {summary.filename}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
            <div><div className="text-muted-foreground">Rows</div>
                 <div className="font-semibold text-lg" data-testid={`${label}-row-count`}>{summary.row_count}</div></div>
            <div><div className="text-muted-foreground">Errors</div>
                 <div className={`font-semibold text-lg ${summary.error_count ? 'text-red-600' : ''}`}
                      data-testid={`${label}-error-count`}>{summary.error_count}</div></div>
            <div><div className="text-muted-foreground">Agreements</div>
                 <div className="font-semibold text-lg">{summary.agreements_detected}</div></div>
            <div><div className="text-muted-foreground">Warnings</div>
                 <div className="font-semibold text-lg">{summary.warning_count}</div></div>
            <div><div className="text-muted-foreground">Parties</div>
                 <div className="font-semibold">{summary.parties_detected}</div></div>
            <div><div className="text-muted-foreground">Terms</div>
                 <div className="font-semibold">{summary.terms_detected}</div></div>
            <div><div className="text-muted-foreground">Pricing rows</div>
                 <div className="font-semibold">{summary.pricing_detected}</div></div>
            <div><div className="text-muted-foreground">Documents</div>
                 <div className="font-semibold">{summary.documents_detected}</div></div>
            {isCommit ? (
              <>
                <div><div className="text-muted-foreground">Committed</div>
                     <div className="font-semibold text-emerald-600" data-testid="commit-committed-count">{summary.committed}</div></div>
                <div><div className="text-muted-foreground">Skipped (dup)</div>
                     <div className="font-semibold" data-testid="commit-skipped-count">{summary.skipped}</div></div>
                <div><div className="text-muted-foreground">Ambiguity excs</div>
                     <div className={`font-semibold ${summary.ambiguity_exceptions ? 'text-amber-600' : ''}`}
                          data-testid="commit-ambiguity-count">{summary.ambiguity_exceptions}</div></div>
                <div><div className="text-muted-foreground">Schema gaps</div>
                     <div className="font-semibold">{summary.schema_gap_warnings}</div></div>
              </>
            ) : (
              <>
                <div><div className="text-muted-foreground">Would create</div>
                     <div className="font-semibold text-emerald-600" data-testid="dryrun-would-create">{summary.would_create}</div></div>
                <div><div className="text-muted-foreground">Would update</div>
                     <div className="font-semibold" data-testid="dryrun-would-update">{summary.would_update}</div></div>
                <div><div className="text-muted-foreground">Schema gaps</div>
                     <div className="font-semibold">{summary.schema_gap_warnings}</div></div>
                <div></div>
              </>
            )}
          </div>

          {summary.rows && summary.rows.length > 0 && (
            <div className="border rounded-md max-h-72 overflow-auto"
                 data-testid={`${label}-row-list`}>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-12">#</TableHead>
                    <TableHead>Envelope</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead>Title</TableHead>
                    <TableHead>P/T/Pr/D</TableHead>
                    <TableHead>Outcome</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {summary.rows.map((row) => (
                    <TableRow key={row.index} data-testid={`${label}-row-${row.index}`}>
                      <TableCell className="font-mono text-xs">{row.index}</TableCell>
                      <TableCell className="font-mono text-xs">
                        {row.error ? <span className="text-red-600">—</span>
                                   : (row.envelope_id || '').slice(0, 12) + '…'}
                      </TableCell>
                      <TableCell>
                        {row.status && <StatusBadge status={row.status} />}
                      </TableCell>
                      <TableCell className="text-sm max-w-xs truncate">
                        {row.title || '—'}
                      </TableCell>
                      <TableCell className="text-xs font-mono">
                        {row.error ? '—' :
                         `${row.party_count}/${row.term_count}/${row.pricing_count}/${row.document_count}`}
                      </TableCell>
                      <TableCell className="text-xs">
                        {row.error ? (
                          <span className="text-red-600 flex items-center gap-1">
                            <XCircle className="h-3 w-3" /> {row.error}
                          </span>
                        ) : isCommit ? (
                          row.duplicate ? <span className="text-zinc-500">skipped</span>
                          : row.committed ? (
                              <span className="text-emerald-600 flex items-center gap-1">
                                <CheckCircle2 className="h-3 w-3" />
                                committed
                                {row.has_ambiguity_exception && (
                                  <Badge variant="outline" className="ml-1 text-amber-600 border-amber-600">
                                    AMBIGUOUS
                                  </Badge>
                                )}
                              </span>
                            ) : <span>—</span>
                        ) : (
                          <span className="text-blue-600">would import</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="space-y-4" data-testid="navigator-import-tab">
      <div>
        <h2 className="text-lg font-semibold">Import Navigator Export</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Upload a DocuSign Navigator AI Metadata Export (.xlsx, .csv, or .json).
          Dry-run shows exactly what will land before any DB writes; review the
          preview, then click <span className="font-semibold">Commit Import</span>.
          Replays are idempotent — duplicate envelope ids are skipped automatically.
        </p>
      </div>

      <Card>
        <CardContent className="p-6">
          <div
            onDrop={onDrop}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            className={`border-2 border-dashed rounded-md p-8 text-center transition-colors
                       ${dragActive ? 'border-blue-500 bg-blue-50/50' : 'border-zinc-300'}
                       ${file ? 'bg-emerald-50/30 border-emerald-400' : ''}`}
            data-testid="navigator-import-dropzone"
          >
            <UploadCloud className="h-10 w-10 mx-auto text-zinc-400 mb-3" />
            {file ? (
              <div className="space-y-2">
                <div className="font-medium" data-testid="navigator-import-filename">
                  {file.name}
                </div>
                <div className="text-xs text-muted-foreground">
                  {(file.size / 1024).toFixed(1)} KB · {file.type || 'unknown type'}
                </div>
                <Button variant="ghost" size="sm" onClick={reset}
                        data-testid="navigator-import-clear-btn">
                  Choose different file
                </Button>
              </div>
            ) : (
              <>
                <div className="text-sm font-medium">
                  Drop a Navigator export here, or
                </div>
                <Label htmlFor="navigator-file-input"
                       className="text-sm text-blue-600 cursor-pointer underline">
                  browse to upload
                </Label>
                <Input
                  id="navigator-file-input"
                  type="file"
                  accept=".xlsx,.xlsm,.csv,.json"
                  className="hidden"
                  onChange={(e) => onPick(e.target.files?.[0])}
                  data-testid="navigator-import-file-input"
                />
                <div className="text-xs text-muted-foreground mt-2">
                  Accepted: .xlsx, .xlsm, .csv, .json
                </div>
              </>
            )}
          </div>

          <div className="flex flex-wrap gap-2 mt-4">
            <Button
              onClick={runDryrun}
              disabled={!file || busy}
              data-testid="navigator-import-dryrun-btn"
            >
              <FileSpreadsheet className="mr-2 h-4 w-4" />
              {busy && !commitResult ? 'Running…' : 'Run Dry-Run'}
            </Button>
            <Button
              onClick={runCommit}
              disabled={!dryrunResult || busy || dryrunResult?.error_count === dryrunResult?.row_count}
              variant="default"
              className="bg-emerald-600 hover:bg-emerald-700"
              data-testid="navigator-import-commit-btn"
            >
              <CheckCircle2 className="mr-2 h-4 w-4" />
              {busy && commitResult === null && dryrunResult ? 'Committing…' : 'Commit Import'}
            </Button>
            {error && (
              <div className="flex items-center gap-1 text-sm text-red-600"
                   data-testid="navigator-import-error">
                <AlertCircle className="h-4 w-4" /> {error}
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {dryrunResult && !commitResult && renderSummary(dryrunResult, 'dryrun')}
      {commitResult && renderSummary(commitResult, 'commit')}
    </div>
  );
}


// =============================================================================
// Page
// =============================================================================

export default function ContractIntelligencePage() {
  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl space-y-6"
         data-testid="contract-intelligence-page">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <FileSignature className="h-6 w-6" />
            Contract Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            DocuSign agreements normalized + matched to Business Central — read-only,
            advisory. No BC writes.
          </p>
        </div>
      </header>

      <Tabs defaultValue="agreements" className="w-full">
        <TabsList className="grid w-full grid-cols-6" data-testid="contracts-tabs-list">
          <TabsTrigger value="agreements" data-testid="tab-agreements">
            <FileSignature className="h-4 w-4 mr-2" />Agreements
          </TabsTrigger>
          <TabsTrigger value="exceptions" data-testid="tab-exceptions">
            <AlertTriangle className="h-4 w-4 mr-2" />Exceptions
          </TabsTrigger>
          <TabsTrigger value="bc_links" data-testid="tab-bc-links">
            <Link2 className="h-4 w-4 mr-2" />BC Links
          </TabsTrigger>
          <TabsTrigger value="expirations" data-testid="tab-expirations">
            <CalendarClock className="h-4 w-4 mr-2" />Expirations
          </TabsTrigger>
          <TabsTrigger value="analytics" data-testid="tab-analytics">
            <BarChart3 className="h-4 w-4 mr-2" />Analytics
          </TabsTrigger>
          <TabsTrigger value="navigator_import" data-testid="tab-navigator-import">
            <UploadCloud className="h-4 w-4 mr-2" />Import
          </TabsTrigger>
        </TabsList>

        <TabsContent value="agreements" className="mt-6"><AgreementsTab /></TabsContent>
        <TabsContent value="exceptions" className="mt-6"><ExceptionsTab /></TabsContent>
        <TabsContent value="bc_links" className="mt-6"><BCLinksTab /></TabsContent>
        <TabsContent value="expirations" className="mt-6"><ExpirationsTab /></TabsContent>
        <TabsContent value="analytics" className="mt-6"><AnalyticsTab /></TabsContent>
        <TabsContent value="navigator_import" className="mt-6"><NavigatorImportTab /></TabsContent>
      </Tabs>
    </div>
  );
}
