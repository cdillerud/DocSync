import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Loader2, Plus, PowerOff, Search, X, ShieldAlert } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function getUserEmail() {
  try {
    const raw = localStorage.getItem('gpi_user');
    if (!raw) return '';
    const u = JSON.parse(raw);
    return u.email || u.username || '';
  } catch {
    return '';
  }
}

export default function CpItemRegistryPanel() {
  const [searchParams] = useSearchParams();
  const deepLinkItem = (searchParams.get('filter_item') || '').trim().toUpperCase();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [customerFilter, setCustomerFilter] = useState('');
  const [itemFilter, setItemFilter] = useState(deepLinkItem);
  const [statusFilter, setStatusFilter] = useState(deepLinkItem ? 'all' : 'active');
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [retiring, setRetiring] = useState(null); // item_no being retired
  const [banner, setBanner] = useState(null);     // { kind: 'ok'|'err', text }
  const [form, setForm] = useState({
    item_no: '', customer_no: '', base_item_no: '', canonical_location: '', notes: '',
  });

  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (customerFilter.trim()) params.set('customer_no', customerFilter.trim());
      if (statusFilter && statusFilter !== 'all') params.set('status', statusFilter);
      params.set('limit', '500');
      const res = await fetch(`${API}/api/cp-items?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        let arr = data.items || [];
        if (itemFilter.trim()) {
          const needle = itemFilter.trim().toUpperCase();
          arr = arr.filter((it) => (it.item_no || '').includes(needle));
        }
        setItems(arr);
      } else {
        setBanner({ kind: 'err', text: `Load failed (${res.status})` });
      }
    } catch (e) {
      setBanner({ kind: 'err', text: `Load failed: ${e.message}` });
    }
    setLoading(false);
  }, [customerFilter, statusFilter, itemFilter]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchItems(); }, [fetchItems]);

  const resetForm = () => setForm({
    item_no: '', customer_no: '', base_item_no: '', canonical_location: '', notes: '',
  });

  const submitCreate = async () => {
    const required = ['item_no', 'customer_no', 'base_item_no', 'canonical_location'];
    for (const f of required) {
      if (!form[f] || !form[f].trim()) {
        setBanner({ kind: 'err', text: `Field "${f}" is required` });
        return;
      }
    }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/cp-items`, {
        method: 'POST', headers, body: JSON.stringify(form),
      });
      if (res.ok) {
        setBanner({ kind: 'ok', text: `Saved ${form.item_no.toUpperCase()}` });
        setShowCreate(false);
        resetForm();
        fetchItems();
      } else {
        const body = await res.json().catch(() => ({}));
        setBanner({
          kind: 'err',
          text: body.detail || `Create failed (${res.status})`,
        });
      }
    } catch (e) {
      setBanner({ kind: 'err', text: `Create failed: ${e.message}` });
    }
    setSaving(false);
  };

  const retireRow = async (item_no) => {
    const defaultEmail = getUserEmail();
    const actor = window.prompt(
      `Retiring ${item_no}. Enter retirement actor email (must match server-side COW_RETIREMENT_ACTOR_EMAIL):`,
      defaultEmail,
    );
    if (!actor) return;
    setRetiring(item_no);
    try {
      const res = await fetch(
        `${API}/api/cp-items/${encodeURIComponent(item_no)}/retire`,
        { method: 'POST', headers, body: JSON.stringify({ actor_email: actor }) },
      );
      if (res.ok) {
        setBanner({ kind: 'ok', text: `Retired ${item_no}` });
        fetchItems();
      } else {
        const body = await res.json().catch(() => ({}));
        setBanner({
          kind: 'err',
          text: body.detail || `Retire failed (${res.status})`,
        });
      }
    } catch (e) {
      setBanner({ kind: 'err', text: `Retire failed: ${e.message}` });
    }
    setRetiring(null);
  };

  return (
    <div data-testid="cp-items-panel" className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <ShieldAlert className="h-5 w-5 text-primary" />
            CP Item Registry
            <Badge variant="secondary" data-testid="cp-items-count">
              {items.length}
            </Badge>
          </CardTitle>
          <Button
            size="sm"
            onClick={() => { setShowCreate(true); resetForm(); }}
            data-testid="cp-items-create-btn"
          >
            <Plus className="h-4 w-4 mr-1" /> New CP Item
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {banner && (
            <div
              data-testid="cp-items-banner"
              className={`px-3 py-2 rounded text-sm flex items-center justify-between ${
                banner.kind === 'ok'
                  ? 'bg-green-500/10 text-green-600 border border-green-500/20'
                  : 'bg-red-500/10 text-red-600 border border-red-500/20'
              }`}
            >
              <span>{banner.text}</span>
              <button onClick={() => setBanner(null)} className="p-1">
                <X className="h-4 w-4" />
              </button>
            </div>
          )}

          {/* Filters */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                data-testid="cp-items-filter-customer"
                placeholder="Filter by customer_no"
                value={customerFilter}
                onChange={(e) => setCustomerFilter(e.target.value)}
                className="pl-8"
              />
            </div>
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                data-testid="cp-items-filter-item"
                placeholder="Filter by item_no"
                value={itemFilter}
                onChange={(e) => setItemFilter(e.target.value)}
                className="pl-8"
              />
            </div>
            <select
              data-testid="cp-items-filter-status"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="h-9 px-3 rounded-md border border-border bg-background text-sm"
            >
              <option value="all">All</option>
              <option value="active">Active</option>
              <option value="retired">Retired</option>
            </select>
            <Button
              size="sm"
              variant="outline"
              onClick={fetchItems}
              data-testid="cp-items-refresh-btn"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Refresh'}
            </Button>
          </div>

          {/* Table */}
          <div className="border border-border rounded-md overflow-hidden">
            <table className="w-full text-sm" data-testid="cp-items-table">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium">Item No</th>
                  <th className="px-3 py-2 font-medium">Customer</th>
                  <th className="px-3 py-2 font-medium">Base Item</th>
                  <th className="px-3 py-2 font-medium">Canonical Location</th>
                  <th className="px-3 py-2 font-medium">Status</th>
                  <th className="px-3 py-2 font-medium">Created</th>
                  <th className="px-3 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin inline mr-2" />Loading…
                  </td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={7} className="px-3 py-6 text-center text-muted-foreground" data-testid="cp-items-empty">
                    {deepLinkItem ? (
                      <div className="space-y-1" data-testid="cp-items-empty-deeplink">
                        <p>
                          Item <span className="font-mono text-foreground">{deepLinkItem}</span> is not in the CP registry.
                        </p>
                        <p className="text-xs">
                          It may need to be added, or the reference on the source document may be incorrect.
                          Clear the filter above to browse the full registry.
                        </p>
                      </div>
                    ) : (
                      "No CP items match the current filters."
                    )}
                  </td></tr>
                )}
                {!loading && items.map((it) => (
                  <tr
                    key={it.item_no}
                    data-testid={`cp-items-row-${it.item_no}`}
                    className={`border-t border-border ${
                      deepLinkItem && it.item_no === deepLinkItem
                        ? 'bg-primary/10 ring-1 ring-primary/40'
                        : ''
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-xs">{it.item_no}</td>
                    <td className="px-3 py-2">{it.customer_no}</td>
                    <td className="px-3 py-2 font-mono text-xs">{it.base_item_no}</td>
                    <td className="px-3 py-2">{it.canonical_location}</td>
                    <td className="px-3 py-2">
                      <Badge
                        variant={it.status === 'active' ? 'default' : 'secondary'}
                        data-testid={`cp-items-status-${it.item_no}`}
                      >
                        {it.status}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {(it.created_utc || '').slice(0, 10)}
                    </td>
                    <td className="px-3 py-2 text-right">
                      {it.status === 'active' && (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => retireRow(it.item_no)}
                          disabled={retiring === it.item_no}
                          data-testid={`cp-items-retire-btn-${it.item_no}`}
                        >
                          {retiring === it.item_no
                            ? <Loader2 className="h-4 w-4 animate-spin" />
                            : <><PowerOff className="h-4 w-4 mr-1" /> Retire</>}
                        </Button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            CP items can only be retired by the configured admin email
            (server env <code>COW_RETIREMENT_ACTOR_EMAIL</code>,
            default <code>items@gamerpackaging.com</code>).
          </p>
        </CardContent>
      </Card>

      {/* Create modal */}
      {showCreate && (
        <div
          data-testid="cp-items-modal"
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
        >
          <Card className="w-full max-w-md">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">New CP Item</CardTitle>
              <button onClick={() => setShowCreate(false)} className="p-1">
                <X className="h-4 w-4" />
              </button>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                ['item_no', 'Item Number (uppercased server-side)'],
                ['customer_no', 'Customer Number'],
                ['base_item_no', 'Base Item Number (billed on SO)'],
                ['canonical_location', 'Canonical Location (adjustment journal)'],
                ['notes', 'Notes (optional)'],
              ].map(([key, label]) => (
                <div key={key}>
                  <label className="text-xs text-muted-foreground block mb-1">{label}</label>
                  <Input
                    data-testid={`cp-items-modal-${key}`}
                    value={form[key]}
                    onChange={(e) => setForm({ ...form, [key]: e.target.value })}
                  />
                </div>
              ))}
              <div className="flex justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowCreate(false)}
                  data-testid="cp-items-modal-cancel"
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={submitCreate}
                  disabled={saving}
                  data-testid="cp-items-modal-submit"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Save'}
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
