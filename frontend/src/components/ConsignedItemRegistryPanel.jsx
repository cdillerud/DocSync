import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { Loader2, Plus, PackageCheck, PackageX, Search, X, ShieldAlert } from 'lucide-react';

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

const STATE_LABEL = {
  consigned_in: 'Consigned In',
  consumed: 'Consumed',
  returned: 'Returned',
};

const STATE_VARIANT = {
  consigned_in: 'default',
  consumed: 'secondary',
  returned: 'outline',
};

export default function ConsignedItemRegistryPanel() {
  const [searchParams] = useSearchParams();
  const deepLinkItem = (searchParams.get('filter_item') || '').trim().toUpperCase();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [vendorFilter, setVendorFilter] = useState('');
  const [itemFilter, setItemFilter] = useState(deepLinkItem);
  const [stateFilter, setStateFilter] = useState(deepLinkItem ? 'all' : 'consigned_in');
  const [showCreate, setShowCreate] = useState(false);
  const [saving, setSaving] = useState(false);
  const [transitioning, setTransitioning] = useState(null); // item_no
  const [banner, setBanner] = useState(null);
  const [form, setForm] = useState({
    item_no: '', vendor_no: '', physical_location: '', notes: '',
  });

  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchItems = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (vendorFilter.trim()) params.set('vendor_no', vendorFilter.trim());
      if (stateFilter && stateFilter !== 'all') params.set('state', stateFilter);
      params.set('limit', '500');
      const res = await fetch(`${API}/api/consigned-items?${params}`, { headers });
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
  }, [vendorFilter, stateFilter, itemFilter]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchItems(); }, [fetchItems]);

  const resetForm = () => setForm({
    item_no: '', vendor_no: '', physical_location: '', notes: '',
  });

  const submitCreate = async () => {
    for (const f of ['item_no', 'vendor_no', 'physical_location']) {
      if (!form[f] || !form[f].trim()) {
        setBanner({ kind: 'err', text: `Field "${f}" is required` });
        return;
      }
    }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/consigned-items`, {
        method: 'POST', headers, body: JSON.stringify(form),
      });
      if (res.ok) {
        setBanner({ kind: 'ok', text: `Saved ${form.item_no.toUpperCase()}` });
        setShowCreate(false);
        resetForm();
        fetchItems();
      } else {
        const body = await res.json().catch(() => ({}));
        setBanner({ kind: 'err', text: body.detail || `Create failed (${res.status})` });
      }
    } catch (e) {
      setBanner({ kind: 'err', text: `Create failed: ${e.message}` });
    }
    setSaving(false);
  };

  const transitionRow = async (item_no, new_state) => {
    const defaultEmail = getUserEmail();
    const actor = window.prompt(
      `Transition ${item_no} → ${new_state}. Actor email (must match CONSIGNMENT_STATE_ACTOR_EMAIL):`,
      defaultEmail,
    );
    if (!actor) return;
    const evidence_id = window.prompt(
      `Evidence document ID for this transition (required):`,
      '',
    );
    if (!evidence_id) {
      setBanner({ kind: 'err', text: 'evidence_id is required for every transition.' });
      return;
    }
    setTransitioning(item_no);
    try {
      const res = await fetch(
        `${API}/api/consigned-items/${encodeURIComponent(item_no)}/transition`,
        {
          method: 'POST', headers,
          body: JSON.stringify({ new_state, actor_email: actor, evidence_id }),
        },
      );
      if (res.ok) {
        setBanner({ kind: 'ok', text: `${item_no} → ${new_state}` });
        fetchItems();
      } else {
        const body = await res.json().catch(() => ({}));
        setBanner({ kind: 'err', text: body.detail || `Transition failed (${res.status})` });
      }
    } catch (e) {
      setBanner({ kind: 'err', text: `Transition failed: ${e.message}` });
    }
    setTransitioning(null);
  };

  return (
    <div data-testid="consigned-items-panel" className="space-y-4">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="flex items-center gap-2 text-lg">
            <ShieldAlert className="h-5 w-5 text-primary" />
            Vendor Consignment Registry
            <Badge variant="secondary" data-testid="consigned-items-count">
              {items.length}
            </Badge>
          </CardTitle>
          <Button
            size="sm"
            onClick={() => { setShowCreate(true); resetForm(); }}
            data-testid="consigned-items-create-btn"
          >
            <Plus className="h-4 w-4 mr-1" /> New Consigned Item
          </Button>
        </CardHeader>
        <CardContent className="space-y-3">
          {banner && (
            <div
              data-testid="consigned-items-banner"
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

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                data-testid="consigned-items-filter-vendor"
                placeholder="Filter by vendor_no"
                value={vendorFilter}
                onChange={(e) => setVendorFilter(e.target.value)}
                className="pl-8"
              />
            </div>
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                data-testid="consigned-items-filter-item"
                placeholder="Filter by item_no"
                value={itemFilter}
                onChange={(e) => setItemFilter(e.target.value)}
                className="pl-8"
              />
            </div>
            <select
              data-testid="consigned-items-filter-state"
              value={stateFilter}
              onChange={(e) => setStateFilter(e.target.value)}
              className="h-9 px-3 rounded-md border border-border bg-background text-sm"
            >
              <option value="all">All</option>
              <option value="consigned_in">Consigned In</option>
              <option value="consumed">Consumed</option>
              <option value="returned">Returned</option>
            </select>
            <Button
              size="sm"
              variant="outline"
              onClick={fetchItems}
              data-testid="consigned-items-refresh-btn"
            >
              {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : 'Refresh'}
            </Button>
          </div>

          <div className="border border-border rounded-md overflow-hidden">
            <table className="w-full text-sm" data-testid="consigned-items-table">
              <thead className="bg-muted/50">
                <tr className="text-left">
                  <th className="px-3 py-2 font-medium">Item No</th>
                  <th className="px-3 py-2 font-medium">Vendor</th>
                  <th className="px-3 py-2 font-medium">Physical Location</th>
                  <th className="px-3 py-2 font-medium">State</th>
                  <th className="px-3 py-2 font-medium">Changed</th>
                  <th className="px-3 py-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {loading && (
                  <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground">
                    <Loader2 className="h-4 w-4 animate-spin inline mr-2" />Loading…
                  </td></tr>
                )}
                {!loading && items.length === 0 && (
                  <tr><td colSpan={6} className="px-3 py-6 text-center text-muted-foreground" data-testid="consigned-items-empty">
                    No consigned items match the current filters.
                  </td></tr>
                )}
                {!loading && items.map((it) => (
                  <tr
                    key={it.item_no}
                    data-testid={`consigned-items-row-${it.item_no}`}
                    className={`border-t border-border ${
                      deepLinkItem && it.item_no === deepLinkItem
                        ? 'bg-primary/10 ring-1 ring-primary/40'
                        : ''
                    }`}
                  >
                    <td className="px-3 py-2 font-mono text-xs">{it.item_no}</td>
                    <td className="px-3 py-2">{it.vendor_no}</td>
                    <td className="px-3 py-2">{it.physical_location}</td>
                    <td className="px-3 py-2">
                      <Badge
                        variant={STATE_VARIANT[it.state] || 'outline'}
                        data-testid={`consigned-items-state-${it.item_no}`}
                      >
                        {STATE_LABEL[it.state] || it.state}
                      </Badge>
                    </td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {(it.state_changed_at || it.updated_utc || '').slice(0, 10)}
                    </td>
                    <td className="px-3 py-2 text-right space-x-1">
                      {it.state === 'consigned_in' && (
                        <>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => transitionRow(it.item_no, 'consumed')}
                            disabled={transitioning === it.item_no}
                            data-testid={`consigned-items-consume-btn-${it.item_no}`}
                          >
                            {transitioning === it.item_no
                              ? <Loader2 className="h-4 w-4 animate-spin" />
                              : <><PackageCheck className="h-4 w-4 mr-1" /> Consume</>}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => transitionRow(it.item_no, 'returned')}
                            disabled={transitioning === it.item_no}
                            data-testid={`consigned-items-return-btn-${it.item_no}`}
                          >
                            <PackageX className="h-4 w-4 mr-1" /> Return
                          </Button>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="text-xs text-muted-foreground">
            State transitions require the configured admin email
            (server env <code>CONSIGNMENT_STATE_ACTOR_EMAIL</code>,
            default <code>items@gamerpackaging.com</code>) and an evidence
            document ID. Terminal states <code>consumed</code> and
            <code>returned</code> cannot be reopened.
          </p>
        </CardContent>
      </Card>

      {showCreate && (
        <div
          data-testid="consigned-items-modal"
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
        >
          <Card className="w-full max-w-md">
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle className="text-base">New Consigned Item</CardTitle>
              <button onClick={() => setShowCreate(false)} className="p-1">
                <X className="h-4 w-4" />
              </button>
            </CardHeader>
            <CardContent className="space-y-3">
              {[
                ['item_no', 'Item Number (uppercased server-side)'],
                ['vendor_no', 'Vendor (Consignor) Number'],
                ['physical_location', 'Physical Location (warehouse holding the stock)'],
                ['notes', 'Notes (optional)'],
              ].map(([key, label]) => (
                <div key={key}>
                  <label className="text-xs text-muted-foreground block mb-1">{label}</label>
                  <Input
                    data-testid={`consigned-items-modal-${key}`}
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
                  data-testid="consigned-items-modal-cancel"
                >
                  Cancel
                </Button>
                <Button
                  size="sm"
                  onClick={submitCreate}
                  disabled={saving}
                  data-testid="consigned-items-modal-submit"
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
