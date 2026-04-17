import { useState, useEffect, useCallback } from 'react';
import { UploadCloud, CheckCircle2, XCircle, FileSpreadsheet, Database, Sparkles, AlertTriangle, RefreshCw } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_COLORS = {
  pending_review: 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  applied: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  rejected: 'bg-slate-500/20 text-slate-300 border-slate-500/40',
  superseded: 'bg-slate-500/10 text-slate-400 border-slate-500/20',
};

const CLASSIFICATION_LABEL = {
  inventory_open_orders: 'Open Orders',
  inventory_forecast: 'Forecast',
  inventory_dunnage: 'Dunnage',
  inventory_snapshot: 'Snapshot',
  inventory_receipt: 'Receipt',
  inventory_outbound: 'Outbound BOL',
  not_inventory: 'Skipped',
};

function ConfidencePill({ value }) {
  const v = value || 0;
  const color = v >= 0.85 ? 'text-emerald-400' : v >= 0.7 ? 'text-amber-400' : 'text-orange-400';
  return <span className={`font-mono text-xs ${color}`}>{(v * 100).toFixed(0)}%</span>;
}

function StagingListRow({ item, onOpen }) {
  const c = item.classification || {};
  const cm = item.column_map || {};
  return (
    <tr className="border-b border-border/50 hover:bg-muted/30 cursor-pointer" onClick={() => onOpen(item.id)} data-testid={`staging-row-${item.id}`}>
      <td className="py-2.5 pr-3 max-w-[220px] truncate font-mono text-xs">{item.filename}</td>
      <td className="py-2.5 pr-3 text-xs">
        <span className="px-1.5 py-0.5 rounded bg-muted">{CLASSIFICATION_LABEL[c.classification] || c.classification}</span>
      </td>
      <td className="py-2.5 pr-3"><ConfidencePill value={c.confidence} /></td>
      <td className="py-2.5 pr-3"><ConfidencePill value={cm.confidence} /></td>
      <td className="py-2.5 pr-3 text-xs text-muted-foreground">{cm.source || '—'}</td>
      <td className="py-2.5 pr-3 font-mono text-xs">{item.row_count}</td>
      <td className="py-2.5 pr-3 text-xs truncate max-w-[150px]">{item.sender_domain || '—'}</td>
      <td className="py-2.5 pr-3">
        <span className={`text-[10px] px-2 py-0.5 rounded border ${STATUS_COLORS[item.status] || ''}`}>{item.status}</span>
      </td>
    </tr>
  );
}

function StagingDetail({ staging, customers, onClose, onApproved, onRejected, onUpdated }) {
  const [assignedCustomerId, setAssignedCustomerId] = useState(staging.assigned_customer_id || '');
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState(null);
  const [editMap, setEditMap] = useState(false);
  const [mapDraft, setMapDraft] = useState(staging.column_map?.mapping || {});

  const cm = staging.column_map || {};
  const cls = staging.classification || {};
  const rows = staging.rows || [];
  const errs = staging.row_errors || [];

  const CANONICAL_FIELDS = [
    { key: 'item', label: 'Item / SKU', required: true },
    { key: 'item_description', label: 'Description', required: false },
    { key: 'qty', label: 'Quantity', required: true },
    { key: 'warehouse', label: 'Warehouse', required: false },
    { key: 'uom', label: 'UoM', required: false },
    { key: 'reference', label: 'Reference (PO/SO)', required: false },
    { key: 'effective_date', label: 'Effective Date', required: false },
    { key: 'ownership_type', label: 'Ownership', required: false },
    { key: 'notes', label: 'Notes', required: false },
  ];

  const saveMap = async () => {
    setBusy(true); setMsg(null);
    try {
      const cleaned = Object.fromEntries(Object.entries(mapDraft).filter(([, v]) => v && String(v).trim()));
      const res = await fetch(`${API}/api/inventory-xls/staging/${staging.id}/update`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ column_map: { ...cm, mapping: cleaned, source: 'manual' } }),
      });
      const d = await res.json();
      if (!d.updated) throw new Error(d.reason || 'update failed');

      // Now re-normalize rows against the saved mapping (no re-upload needed)
      const renorm = await fetch(`${API}/api/inventory-xls/staging/${staging.id}/re-normalize`, { method: 'POST' });
      const rd = await renorm.json();
      if (renorm.status >= 400) {
        setMsg({ type: 'err', text: `Saved map, but re-normalize failed: ${rd.detail || JSON.stringify(rd)}` });
      } else {
        setMsg({ type: 'ok', text: `Mapping saved. Re-normalized: ${rd.parsed} row(s), ${rd.errors} errors.` });
      }
      setEditMap(false);
      onUpdated && onUpdated();
    } catch (e) { setMsg({ type: 'err', text: String(e) }); }
    finally { setBusy(false); }
  };

  const save = async () => {
    setBusy(true); setMsg(null);
    try {
      const res = await fetch(`${API}/api/inventory-xls/staging/${staging.id}/update`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ assigned_customer_id: assignedCustomerId }),
      });
      const d = await res.json();
      if (!d.updated) throw new Error(d.reason || 'update failed');
      setMsg({ type: 'ok', text: 'Customer assigned.' });
    } catch (e) { setMsg({ type: 'err', text: String(e) }); }
    finally { setBusy(false); }
  };

  const approve = async () => {
    if (!assignedCustomerId) { setMsg({ type: 'err', text: 'Assign a customer first.' }); return; }
    if (rows.length === 0) {
      setMsg({ type: 'err', text: `Cannot approve — staging has 0 normalized rows (${errs.length} rows failed parsing). Fix the column map and re-ingest first.` });
      return;
    }
    setBusy(true); setMsg(null);
    try {
      if (assignedCustomerId !== staging.assigned_customer_id) await save();
      const res = await fetch(`${API}/api/inventory-xls/staging/${staging.id}/approve?approved_by=user`, { method: 'POST' });
      const d = await res.json();
      if (res.status >= 400) {
        setMsg({ type: 'err', text: `HTTP ${res.status}: ${d.detail || JSON.stringify(d)}` });
      } else if (d.status === 'applied') {
        setMsg({ type: 'ok', text: `Applied ${d.applied_count} movement(s). ${d.error_count || 0} errors.` });
        onApproved && onApproved(d);
      } else {
        setMsg({ type: 'err', text: `Status: ${d.status || 'unknown'}. Applied: ${d.applied_count ?? 0}, errors: ${d.error_count ?? 0}. First error: ${(d.errors || [])[0]?.error || '—'}` });
      }
    } catch (e) { setMsg({ type: 'err', text: String(e) }); }
    finally { setBusy(false); }
  };

  const reject = async () => {
    if (!window.confirm('Reject this import? It will be kept for audit but no ledger rows will be created.')) return;
    setBusy(true); setMsg(null);
    try {
      await fetch(`${API}/api/inventory-xls/staging/${staging.id}/reject?rejected_by=user&reason=manual`, { method: 'POST' });
      setMsg({ type: 'ok', text: 'Rejected.' });
      onRejected && onRejected();
    } catch (e) { setMsg({ type: 'err', text: String(e) }); }
    finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-background/80 backdrop-blur-sm z-50 flex items-stretch justify-end" data-testid="staging-detail">
      <div className="w-full max-w-3xl bg-card border-l border-border overflow-y-auto">
        <div className="sticky top-0 bg-card border-b border-border p-4 flex items-center justify-between z-10">
          <div>
            <h3 className="text-base font-semibold flex items-center gap-2">
              <FileSpreadsheet className="h-4 w-4 text-emerald-400" />
              {staging.filename}
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">id: <span className="font-mono">{staging.id.slice(0, 12)}</span></p>
          </div>
          <button data-testid="close-detail-btn" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <XCircle className="h-5 w-5" />
          </button>
        </div>

        <div className="p-4 space-y-4">
          {/* Classification */}
          <div className="bg-muted/30 rounded-lg p-3">
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Classification</div>
            <div className="flex items-center gap-3 text-sm">
              <span className="font-medium">{CLASSIFICATION_LABEL[cls.classification] || cls.classification}</span>
              <ConfidencePill value={cls.confidence} />
              <span className="text-xs text-muted-foreground">→ {cls.movement_intent}</span>
              {cls.ownership_hint && <span className="text-xs px-1.5 py-0.5 rounded bg-sky-500/10 text-sky-300">{cls.ownership_hint}</span>}
            </div>
            {cls.signals?.length > 0 && (
              <div className="text-[11px] text-muted-foreground mt-1 font-mono truncate">Signals: {cls.signals.join(' · ')}</div>
            )}
          </div>

          {/* Column Map */}
          <div className="bg-muted/30 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Column Map</div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted uppercase tracking-wide">{cm.source}</span>
                <ConfidencePill value={cm.confidence} />
                {staging.status === 'pending_review' && (
                  <button
                    data-testid="edit-map-btn"
                    onClick={() => setEditMap(e => !e)}
                    className="text-[10px] px-1.5 py-0.5 rounded border border-border hover:bg-muted text-muted-foreground"
                  >
                    {editMap ? 'Cancel' : 'Edit'}
                  </button>
                )}
              </div>
            </div>
            {!editMap ? (
              <div className="grid grid-cols-2 gap-1.5 text-xs">
                {Object.entries(cm.mapping || {}).map(([canonical, src]) => (
                  <div key={canonical} className="flex items-center gap-2">
                    <span className="font-mono text-emerald-300">{canonical}</span>
                    <span className="text-muted-foreground">←</span>
                    <span className="truncate">{src}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-1.5" data-testid="map-editor">
                {CANONICAL_FIELDS.map(f => (
                  <div key={f.key} className="flex items-center gap-2 text-xs">
                    <span className={`font-mono w-32 shrink-0 ${f.required ? 'text-emerald-300' : 'text-muted-foreground'}`}>
                      {f.key}{f.required ? '*' : ''}
                    </span>
                    <select
                      data-testid={`map-sel-${f.key}`}
                      value={mapDraft[f.key] || ''}
                      onChange={(e) => setMapDraft(d => ({ ...d, [f.key]: e.target.value }))}
                      className="flex-1 bg-background border border-border rounded px-2 py-1 text-xs"
                    >
                      <option value="">— skip —</option>
                      {(staging.headers || []).map(h => (
                        <option key={h} value={h}>{h}</option>
                      ))}
                    </select>
                  </div>
                ))}
                <div className="flex justify-end pt-2">
                  <button data-testid="save-map-btn" onClick={saveMap} disabled={busy}
                    className="px-3 py-1 bg-primary/20 border border-primary text-primary rounded text-xs hover:bg-primary/30 disabled:opacity-50">
                    Save Mapping
                  </button>
                </div>
                <div className="text-[10px] text-muted-foreground pt-1">
                  * = required. You'll need to re-ingest the file after saving (the rows were normalized with the old map).
                </div>
              </div>
            )}
            {cm.missing_required?.length > 0 && !editMap && (
              <div className="text-xs text-red-400 mt-2 flex items-center gap-1">
                <AlertTriangle className="h-3 w-3" /> Missing required: {cm.missing_required.join(', ')}
              </div>
            )}
          </div>

          {/* Customer assignment */}
          <div className="bg-muted/30 rounded-lg p-3">
            <div className="text-xs uppercase tracking-wide text-muted-foreground mb-2">Assign Customer Workspace</div>
            <select
              value={assignedCustomerId}
              onChange={(e) => setAssignedCustomerId(e.target.value)}
              data-testid="customer-select"
              className="w-full bg-background border border-border rounded px-2 py-1.5 text-sm"
              disabled={staging.status !== 'pending_review'}
            >
              <option value="">— Select —</option>
              {(customers || []).map(c => (
                <option key={c.id} value={c.id}>
                  {c.name} ({c.code}){c.id === staging.suggested_customer_id ? '  [suggested]' : ''}
                </option>
              ))}
            </select>
          </div>

          {/* Rows */}
          <div className="bg-muted/30 rounded-lg p-3">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase tracking-wide text-muted-foreground">Normalized Rows ({rows.length})</div>
              {errs.length > 0 && <span className="text-[11px] text-red-400">{errs.length} errors skipped</span>}
            </div>
            <div className="overflow-x-auto max-h-80 overflow-y-auto">
              <table className="w-full text-xs">
                <thead className="text-[10px] uppercase tracking-wide text-muted-foreground">
                  <tr><th className="text-left pr-2">Item</th><th className="text-right pr-2">Qty</th><th className="text-left pr-2">Whs</th><th className="text-left pr-2">UoM</th><th className="text-left pr-2">Ref</th><th className="text-left">Eff Date</th></tr>
                </thead>
                <tbody>
                  {rows.map((r, i) => (
                    <tr key={i} className="border-t border-border/30">
                      <td className="font-mono pr-2 py-1">{r.item}</td>
                      <td className="text-right font-mono pr-2">{r.qty}</td>
                      <td className="pr-2">{r.warehouse}</td>
                      <td className="pr-2">{r.uom}</td>
                      <td className="pr-2 font-mono truncate max-w-[100px]">{r.reference || '—'}</td>
                      <td className="truncate">{r.effective_date ? r.effective_date.split('T')[0] : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {msg && (
            <div className={`text-sm rounded-md px-3 py-2 ${msg.type === 'ok' ? 'bg-emerald-500/10 text-emerald-300' : 'bg-red-500/10 text-red-300'}`}>
              {msg.text}
            </div>
          )}

          {/* Actions */}
          {staging.status === 'pending_review' && (
            <div className="flex items-center gap-2 pt-2">
              <button data-testid="approve-btn" onClick={approve} disabled={busy || !assignedCustomerId} className="flex-1 bg-emerald-500/20 border border-emerald-500/40 text-emerald-300 rounded-md py-2 text-sm font-medium hover:bg-emerald-500/30 disabled:opacity-50 flex items-center justify-center gap-2">
                <CheckCircle2 className="h-4 w-4" /> Approve & Apply to Ledger
              </button>
              <button data-testid="reject-btn" onClick={reject} disabled={busy} className="px-4 py-2 text-sm border border-border rounded-md hover:bg-muted disabled:opacity-50 flex items-center gap-2">
                <XCircle className="h-4 w-4" /> Reject
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function InventoryImportsPage() {
  const [staging, setStaging] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [statusFilter, setStatusFilter] = useState('pending_review');
  const [selectedId, setSelectedId] = useState(null);
  const [selectedStaging, setSelectedStaging] = useState(null);
  const [learnSummary, setLearnSummary] = useState(null);
  const [backfilling, setBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const q = statusFilter ? `?status=${statusFilter}&limit=100` : '?limit=100';
      const [sRes, cRes, lRes] = await Promise.all([
        fetch(`${API}/api/inventory-xls/staging${q}`),
        fetch(`${API}/api/inventory-ledger/customers`),
        fetch(`${API}/api/inventory-xls/learning-summary`),
      ]);
      const sData = await sRes.json();
      const cData = await cRes.json();
      const lData = await lRes.json();
      setStaging(sData.staging || []);
      setCustomers(Array.isArray(cData) ? cData : (cData.customers || []));
      setLearnSummary(lData);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, [statusFilter]);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  const openDetail = async (id) => {
    setSelectedId(id);
    const res = await fetch(`${API}/api/inventory-xls/staging/${id}`);
    setSelectedStaging(await res.json());
  };
  const closeDetail = () => { setSelectedId(null); setSelectedStaging(null); };

  const handleUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append('file', file);
      const senderGuess = window.prompt('Sender email (used for customer auto-suggest + learning) — leave blank to skip', '');
      if (senderGuess) fd.append('sender_email', senderGuess);
      const res = await fetch(`${API}/api/inventory-xls/ingest`, { method: 'POST', body: fd });
      const data = await res.json();
      if (data.already_staged) {
        alert('This file is already staged. Check the list.');
      } else if (!data.staged) {
        alert(`Not staged: ${data.reason || 'unknown'}`);
      }
      await fetchAll();
    } catch (err) { alert(String(err)); }
    finally { setUploading(false); e.target.value = ''; }
  };

  const handleBackfill = async (dryRun) => {
    if (!dryRun && !window.confirm(
      "Scan all pilot-ingested XLS/CSV files in hub_documents and stage any that classify as inventory. " +
      "Staging rows will require human approval before hitting the ledger. Continue?"
    )) return;
    setBackfilling(true); setBackfillResult(null);
    try {
      const res = await fetch(`${API}/api/inventory-xls/backfill-pilot-docs?dry_run=${dryRun}&limit=200`, { method: 'POST' });
      const data = await res.json();
      setBackfillResult(data);
      if (!dryRun) await fetchAll();
    } catch (err) {
      setBackfillResult({ error: String(err) });
    } finally {
      setBackfilling(false);
    }
  };

  const handleResuggest = async () => {
    if (!window.confirm("Re-run customer auto-suggest on all pending staging records using the latest filename-aware logic?")) return;
    setBackfilling(true); setBackfillResult(null);
    try {
      const res = await fetch(`${API}/api/inventory-xls/staging/re-suggest-customers?only_unassigned=false`, { method: 'POST' });
      const data = await res.json();
      setBackfillResult({
        scanned: data.total_pending,
        classified_inventory: data.total_pending,
        staged: data.updated,
        already_staged: 0,
        skipped_not_inventory: data.total_pending - data.updated,
        errors: 0,
        by_classification: Object.fromEntries(
          (data.changed || []).reduce((acc, c) => {
            acc.set(c.new_customer, (acc.get(c.new_customer) || 0) + 1);
            return acc;
          }, new Map())
        ),
      });
      await fetchAll();
    } catch (err) {
      setBackfillResult({ error: String(err) });
    } finally {
      setBackfilling(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="inventory-imports-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-emerald-400" /> Inventory Imports
          </h2>
          <p className="text-sm text-muted-foreground">
            Classify → parse → stage → human approval → apply to ledger.
            No XLS ever writes to the ledger without approval.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button data-testid="refresh-btn" onClick={fetchAll} className="p-2 rounded border border-border hover:bg-muted" title="Refresh">
            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
          <button
            data-testid="resuggest-btn"
            onClick={handleResuggest}
            disabled={backfilling}
            className="px-3 py-2 rounded-md border border-violet-500/40 text-violet-300 bg-violet-500/10 hover:bg-violet-500/20 text-sm disabled:opacity-50 flex items-center gap-2"
            title="Re-run customer auto-suggest on all pending staging using filename-aware logic"
          >
            <Sparkles className="h-4 w-4" />
            Re-suggest Customers
          </button>
          <button
            data-testid="backfill-dry-btn"
            onClick={() => handleBackfill(true)}
            disabled={backfilling}
            className="px-3 py-2 rounded-md border border-amber-500/40 text-amber-300 bg-amber-500/10 hover:bg-amber-500/20 text-sm disabled:opacity-50 flex items-center gap-2"
            title="Dry run: classify all pilot XLS but don't stage"
          >
            <Sparkles className="h-4 w-4" />
            {backfilling ? 'Scanning…' : 'Scan Pilot XLS'}
          </button>
          <button
            data-testid="backfill-btn"
            onClick={() => handleBackfill(false)}
            disabled={backfilling}
            className="px-3 py-2 rounded-md border border-sky-500/40 text-sky-300 bg-sky-500/10 hover:bg-sky-500/20 text-sm disabled:opacity-50 flex items-center gap-2"
            title="Classify + stage all pilot XLS files"
          >
            <Database className="h-4 w-4" />
            Backfill Pilot XLS
          </button>
          <label className="flex items-center gap-2 px-3 py-2 rounded-md border border-emerald-500/40 text-emerald-300 bg-emerald-500/10 hover:bg-emerald-500/20 cursor-pointer text-sm">
            <UploadCloud className="h-4 w-4" />
            {uploading ? 'Uploading…' : 'Upload XLS'}
            <input data-testid="upload-input" type="file" accept=".xlsx,.xls,.csv" onChange={handleUpload} className="hidden" disabled={uploading} />
          </label>
        </div>
      </div>

      {backfillResult && (
        <div className="bg-card border border-border rounded-lg p-4 space-y-2" data-testid="backfill-result">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Backfill Result</h3>
            <button onClick={() => setBackfillResult(null)} className="text-xs text-muted-foreground hover:text-foreground">dismiss</button>
          </div>
          {backfillResult.error ? (
            <div className="text-sm text-red-400">{backfillResult.error}</div>
          ) : (
            <>
              <div className="grid grid-cols-6 gap-3 text-center">
                <div>
                  <div className="text-xl font-bold">{backfillResult.scanned}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Scanned</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-emerald-400">{backfillResult.classified_inventory}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Inventory</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-sky-400">{backfillResult.staged}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Staged</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-amber-400">{backfillResult.already_staged}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Dup / Prior</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-muted-foreground">{backfillResult.skipped_not_inventory}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Not Inventory</div>
                </div>
                <div>
                  <div className="text-xl font-bold text-red-400">{backfillResult.errors}</div>
                  <div className="text-[10px] uppercase text-muted-foreground">Errors</div>
                </div>
              </div>
              {Object.keys(backfillResult.by_classification || {}).length > 0 && (
                <div className="flex flex-wrap gap-2 pt-2 border-t border-border/50">
                  {Object.entries(backfillResult.by_classification).map(([k, v]) => (
                    <span key={k} className="text-[11px] px-2 py-0.5 rounded bg-muted font-mono">
                      {k}: <span className="font-bold">{v}</span>
                    </span>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Learning summary strip */}
      {learnSummary && learnSummary.total_learned_mappings > 0 && (
        <div className="bg-card border border-border rounded-lg p-3 flex items-center gap-4" data-testid="learning-summary">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-amber-400" />
            <span className="text-sm"><span className="font-bold">{learnSummary.total_learned_mappings}</span> learned mapping(s)</span>
          </div>
          <div className="h-4 w-px bg-border" />
          <div className="flex gap-3 overflow-x-auto text-xs">
            {(learnSummary.top_senders || []).slice(0, 5).map((s, i) => (
              <div key={i} className="whitespace-nowrap text-muted-foreground">
                <span className="font-mono">{s.sender_domain}</span>: <span className="text-foreground">{s.approvals}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Status filter */}
      <div className="flex items-center gap-2" data-testid="status-filter">
        {['pending_review', 'applied', 'rejected', ''].map(s => (
          <button key={s || 'all'} onClick={() => setStatusFilter(s)}
            className={`px-3 py-1 rounded-md text-xs border ${statusFilter === s ? 'bg-primary/20 border-primary text-primary' : 'border-border text-muted-foreground hover:bg-muted'}`}
          >
            {s || 'All'}
          </button>
        ))}
      </div>

      {/* Staging list */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        {staging.length === 0 ? (
          <div className="py-16 flex flex-col items-center gap-2 text-muted-foreground text-sm">
            <Database className="h-6 w-6 opacity-50" />
            No {statusFilter || 'staged'} imports. Upload an XLS above to begin.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pt-3 pl-4 pr-3">File</th>
                  <th className="pb-2 pt-3 pr-3">Classification</th>
                  <th className="pb-2 pt-3 pr-3">Conf</th>
                  <th className="pb-2 pt-3 pr-3">Map Conf</th>
                  <th className="pb-2 pt-3 pr-3">Source</th>
                  <th className="pb-2 pt-3 pr-3">Rows</th>
                  <th className="pb-2 pt-3 pr-3">Sender</th>
                  <th className="pb-2 pt-3 pr-3">Status</th>
                </tr>
              </thead>
              <tbody>
                {staging.map(s => (
                  <StagingListRow key={s.id} item={s} onOpen={openDetail} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {selectedStaging && (
        <StagingDetail
          staging={selectedStaging}
          customers={customers}
          onClose={closeDetail}
          onApproved={() => { closeDetail(); fetchAll(); }}
          onRejected={() => { closeDetail(); fetchAll(); }}
          onUpdated={async () => {
            const res = await fetch(`${API}/api/inventory-xls/staging/${selectedId}`);
            setSelectedStaging(await res.json());
            fetchAll();
          }}
        />
      )}
    </div>
  );
}
