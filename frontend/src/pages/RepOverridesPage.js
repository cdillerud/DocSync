/**
 * RepOverridesPage — Admin UI for customer→rep manual overrides (v2.5.2)
 * ──────────────────────────────────────────────────────────────────────
 *
 * CRUD screen over the existing `customer_rep_overrides` collection.
 * Replaces the "run a DB script" workflow.
 *
 * Backend endpoints (all pre-existing):
 *   GET    /api/sales-dashboard/reps                  — rep picklist
 *   GET    /api/sales-dashboard/rep-overrides         — list overrides
 *   POST   /api/sales-dashboard/rep-overrides         — upsert override
 *   DELETE /api/sales-dashboard/rep-overrides/:cno    — deactivate override
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw, Plus, Trash2, Search, Check, X, UserCheck, AlertCircle } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const EMPTY_FORM = {
  customer_no: '',
  customer_name: '',
  rep_email: '',
  rep_name: '',
  salesperson_code: '',
  reason: '',
  notes: '',
  expires_at: '',
};

export default function RepOverridesPage() {
  const [overrides, setOverrides] = useState([]);
  const [reps, setReps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState(EMPTY_FORM);
  const [showForm, setShowForm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, repsRes] = await Promise.all([
        fetch(`${API}/api/sales-dashboard/rep-overrides?active_only=true`),
        fetch(`${API}/api/sales-dashboard/reps`),
      ]);
      if (ovRes.ok) {
        const d = await ovRes.json();
        setOverrides(d.overrides || []);
      }
      if (repsRes.ok) {
        const d = await repsRes.json();
        setReps(d.reps || []);
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const filtered = useMemo(() => {
    if (!query.trim()) return overrides;
    const q = query.trim().toLowerCase();
    return overrides.filter((o) =>
      (o.customer_no || '').toLowerCase().includes(q)
      || (o.customer_name || '').toLowerCase().includes(q)
      || (o.rep_name || '').toLowerCase().includes(q)
      || (o.rep_email || '').toLowerCase().includes(q),
    );
  }, [overrides, query]);

  const pickRep = (email) => {
    const r = reps.find((x) => x.rep_email === email);
    if (r) {
      setForm((f) => ({
        ...f,
        rep_email: r.rep_email,
        rep_name: r.rep_name || '',
        salesperson_code: r.salesperson_code || '',
      }));
    } else {
      setForm((f) => ({ ...f, rep_email: email }));
    }
  };

  const onSubmit = async (e) => {
    e.preventDefault();
    if (!form.rep_email) {
      setSubmitMsg({ type: 'error', text: 'Rep email is required.' });
      return;
    }
    if (!form.customer_no && !form.customer_name) {
      setSubmitMsg({ type: 'error', text: 'Customer number or name is required.' });
      return;
    }
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/rep-overrides`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(form),
      });
      if (res.ok) {
        const r = await res.json();
        setSubmitMsg({ type: 'ok', text: `Override ${r.status}: ${r.customer} → ${r.rep_email}` });
        setForm(EMPTY_FORM);
        setShowForm(false);
        await load();
      } else {
        const err = await res.json().catch(() => ({}));
        setSubmitMsg({ type: 'error', text: err.detail || `HTTP ${res.status}` });
      }
    } finally {
      setSubmitting(false);
    }
  };

  const onDelete = async (customer_no) => {
    if (!customer_no) return;
    if (!window.confirm(`Deactivate override for ${customer_no}?`)) return;
    try {
      const res = await fetch(`${API}/api/sales-dashboard/rep-overrides/${encodeURIComponent(customer_no)}`, { method: 'DELETE' });
      if (res.ok) await load();
    } catch { /* noop */ }
  };

  return (
    <div className="p-6 space-y-4 max-w-7xl mx-auto" data-testid="rep-overrides-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <UserCheck className="h-5 w-5 text-sky-500" /> Rep Overrides
          </h1>
          <p className="text-sm text-muted-foreground mt-1 max-w-3xl">
            Manual customer→rep assignments. Take precedence over BC's <span className="font-mono text-xs">salesperson_code</span> lookup.
            Use for carve-outs, interim coverage, or customers that live outside BC.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowForm((v) => !v)}
            className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 flex items-center gap-1"
            data-testid="rep-overrides-toggle-form"
          >
            {showForm ? <X className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            {showForm ? 'Cancel' : 'Add Override'}
          </button>
          <button
            onClick={load}
            disabled={loading}
            className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted disabled:opacity-50"
            data-testid="rep-overrides-reload"
          >
            <RefreshCw className={`h-4 w-4 inline ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {submitMsg && (
        <div
          className={`rounded-md px-3 py-2 text-sm flex items-center gap-2 ${
            submitMsg.type === 'ok'
              ? 'bg-emerald-500/10 text-emerald-700 border border-emerald-500/30'
              : 'bg-red-500/10 text-red-700 border border-red-500/30'
          }`}
          data-testid="rep-overrides-submit-msg"
        >
          {submitMsg.type === 'ok' ? <Check className="h-4 w-4" /> : <AlertCircle className="h-4 w-4" />}
          {submitMsg.text}
        </div>
      )}

      {showForm && (
        <form
          onSubmit={onSubmit}
          className="rounded-lg border border-border bg-card p-4 space-y-3"
          data-testid="rep-overrides-form"
        >
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Customer #</label>
              <input
                type="text"
                value={form.customer_no}
                onChange={(e) => setForm({ ...form, customer_no: e.target.value })}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                placeholder="e.g. C-10250"
                data-testid="rep-overrides-form-customer-no"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Customer Name</label>
              <input
                type="text"
                value={form.customer_name}
                onChange={(e) => setForm({ ...form, customer_name: e.target.value })}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                placeholder="Giovanni's Fine Foods"
                data-testid="rep-overrides-form-customer-name"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Rep</label>
              <select
                value={form.rep_email}
                onChange={(e) => pickRep(e.target.value)}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                data-testid="rep-overrides-form-rep-select"
                required
              >
                <option value="">-- Select rep --</option>
                {reps.map((r) => (
                  <option key={r.rep_email} value={r.rep_email}>
                    {r.rep_name || r.rep_email} {r.salesperson_code ? `(${r.salesperson_code})` : ''}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Reason</label>
              <input
                type="text"
                value={form.reason}
                onChange={(e) => setForm({ ...form, reason: e.target.value })}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                placeholder="e.g. Strategic account carve-out"
                data-testid="rep-overrides-form-reason"
              />
            </div>
            <div className="sm:col-span-2">
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Notes</label>
              <textarea
                value={form.notes}
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                rows={2}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                data-testid="rep-overrides-form-notes"
              />
            </div>
            <div>
              <label className="text-[11px] uppercase tracking-wide text-muted-foreground">Expires (optional)</label>
              <input
                type="date"
                value={form.expires_at ? form.expires_at.slice(0, 10) : ''}
                onChange={(e) => setForm({ ...form, expires_at: e.target.value ? `${e.target.value}T23:59:59+00:00` : '' })}
                className="w-full mt-1 px-2 py-1.5 text-sm border border-border rounded bg-background"
                data-testid="rep-overrides-form-expires"
              />
            </div>
          </div>
          <div className="flex items-center justify-end gap-2">
            <button
              type="button"
              onClick={() => { setForm(EMPTY_FORM); setShowForm(false); setSubmitMsg(null); }}
              className="px-3 py-1.5 text-sm rounded-md border border-border hover:bg-muted"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={submitting}
              className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              data-testid="rep-overrides-form-submit"
            >
              {submitting ? 'Saving…' : 'Save Override'}
            </button>
          </div>
        </form>
      )}

      <div className="rounded-lg border border-border bg-card" data-testid="rep-overrides-table-card">
        <div className="flex items-center gap-3 p-3 border-b border-border">
          <div className="text-sm font-semibold">
            Active Overrides
            <span className="ml-2 text-xs text-muted-foreground">({overrides.length})</span>
          </div>
          <div className="relative ml-auto w-64">
            <Search className="h-3.5 w-3.5 text-muted-foreground absolute left-2 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Filter by customer or rep…"
              className="w-full pl-7 pr-2 py-1.5 text-xs border border-border rounded bg-background"
              data-testid="rep-overrides-search"
            />
          </div>
        </div>

        {loading && overrides.length === 0 && (
          <div className="p-6 text-sm text-muted-foreground text-center">Loading overrides…</div>
        )}
        {!loading && filtered.length === 0 && (
          <div className="p-10 text-sm text-muted-foreground text-center" data-testid="rep-overrides-empty">
            {overrides.length === 0 ? 'No active overrides. Click "Add Override" to create one.' : 'No overrides match your search.'}
          </div>
        )}

        {filtered.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] uppercase tracking-wide text-muted-foreground border-b border-border">
                  <th className="p-2">Customer</th>
                  <th className="p-2">Rep</th>
                  <th className="p-2">Reason</th>
                  <th className="p-2">Updated</th>
                  <th className="p-2">Expires</th>
                  <th className="p-2 w-12"></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((o) => (
                  <tr
                    key={o.id || o.customer_no || o.customer_name}
                    className={`border-b border-border/50 hover:bg-muted/30 ${o.expired ? 'opacity-60' : ''}`}
                    data-testid={`rep-overrides-row-${o.customer_no || o.customer_name}`}
                  >
                    <td className="p-2">
                      <div className="font-mono text-xs">{o.customer_no || '—'}</div>
                      {o.customer_name && <div className="text-xs text-muted-foreground">{o.customer_name}</div>}
                    </td>
                    <td className="p-2">
                      <div className="font-medium">{o.rep_name || '—'}</div>
                      <div className="text-xs text-muted-foreground">{o.rep_email}</div>
                      {o.salesperson_code && <div className="text-[10px] font-mono text-muted-foreground">{o.salesperson_code}</div>}
                    </td>
                    <td className="p-2 text-xs text-muted-foreground max-w-xs truncate" title={o.notes || o.reason || ''}>
                      {o.reason || <span className="italic">—</span>}
                    </td>
                    <td className="p-2 text-xs text-muted-foreground">
                      {o.updated_utc ? new Date(o.updated_utc).toLocaleDateString() : '—'}
                    </td>
                    <td className="p-2 text-xs">
                      {o.expires_at
                        ? <span className={o.expired ? 'text-red-600' : 'text-muted-foreground'}>
                            {new Date(o.expires_at).toLocaleDateString()}
                            {o.expired && ' (expired)'}
                          </span>
                        : <span className="text-muted-foreground italic">never</span>}
                    </td>
                    <td className="p-2">
                      <button
                        onClick={() => onDelete(o.customer_no)}
                        disabled={!o.customer_no}
                        className="text-red-600 hover:bg-red-500/10 rounded p-1 disabled:opacity-30"
                        title="Deactivate override"
                        data-testid={`rep-overrides-delete-${o.customer_no || o.customer_name}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
