import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Input } from './ui/input';
import { ScrollArea } from './ui/scroll-area';
import {
  Users, Plus, Edit2, Power, PowerOff, Loader2, Search,
  ChevronDown, ChevronUp, Save, X, Clock, AlertTriangle
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const TYPE_LABELS = {
  rep_assignment: 'Rep Assignment',
  ship_to_exception: 'Ship-To Exception',
  item_uom_exception: 'Item/UOM Exception',
  draft_preference: 'Draft Preference',
  business_note: 'Business Note',
};

export default function RepOverridesPanel() {
  const [overrides, setOverrides] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showInactive, setShowInactive] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [expanded, setExpanded] = useState(null);
  const [editing, setEditing] = useState(null); // override id being edited
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({});

  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const headers = { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' };

  const fetchOverrides = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (!showInactive) params.set('active_only', 'true');
      const res = await fetch(`${API}/api/sales-dashboard/rep-overrides?${params}`, { headers });
      if (res.ok) {
        const data = await res.json();
        setOverrides(data.overrides || []);
      }
    } catch { /* ignore */ }
    setLoading(false);
  }, [showInactive]);

  useEffect(() => { fetchOverrides(); }, [fetchOverrides]);

  const filtered = overrides.filter(o => {
    if (!searchTerm) return true;
    const s = searchTerm.toLowerCase();
    return (o.customer_name || '').toLowerCase().includes(s)
      || (o.customer_no || '').toLowerCase().includes(s)
      || (o.rep_name || '').toLowerCase().includes(s)
      || (o.rep_email || '').toLowerCase().includes(s);
  });

  const handleSave = async () => {
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/sales-dashboard/rep-overrides`, {
        method: 'POST', headers,
        body: JSON.stringify({
          customer_no: form.customer_no || '',
          customer_name: form.customer_name || '',
          rep_email: form.rep_email || '',
          rep_name: form.rep_name || '',
          salesperson_code: form.salesperson_code || '',
          override_type: form.override_type || 'rep_assignment',
          reason: form.reason || '',
          notes: form.notes || '',
          expires_at: form.expires_at || null,
        }),
      });
      if (res.ok) {
        setCreating(false);
        setEditing(null);
        setForm({});
        await fetchOverrides();
      }
    } catch { /* ignore */ }
    setSaving(false);
  };

  const handleDisable = async (customer_no) => {
    try {
      await fetch(`${API}/api/sales-dashboard/rep-overrides/${customer_no}`, { method: 'DELETE', headers });
      await fetchOverrides();
    } catch { /* ignore */ }
  };

  const startEdit = (o) => {
    setEditing(o.id);
    setForm({ ...o });
    setCreating(false);
    setExpanded(o.id);
  };

  const startCreate = () => {
    setCreating(true);
    setEditing(null);
    setForm({ override_type: 'rep_assignment' });
  };

  const activeCount = overrides.filter(o => o.active && !o.expired).length;
  const expiredCount = overrides.filter(o => o.expired).length;

  return (
    <Card data-testid="rep-overrides-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-base flex items-center gap-2">
            <Users className="w-4 h-4 text-muted-foreground" />
            Rep Overrides
            <Badge variant="outline" className="text-[10px]">{activeCount} active</Badge>
            {expiredCount > 0 && <Badge variant="outline" className="text-[10px] text-amber-600 border-amber-300">{expiredCount} expired</Badge>}
          </CardTitle>
          <div className="flex items-center gap-2">
            <label className="flex items-center gap-1.5 text-[10px] text-muted-foreground cursor-pointer">
              <input type="checkbox" checked={showInactive} onChange={e => setShowInactive(e.target.checked)} className="w-3 h-3" />
              Show inactive
            </label>
            <Button size="sm" variant="outline" className="h-7 text-xs" onClick={startCreate} data-testid="create-override-btn">
              <Plus className="w-3 h-3 mr-1" />New
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        {/* Search */}
        <div className="flex items-center gap-2 mb-3">
          <Search className="w-3.5 h-3.5 text-muted-foreground" />
          <Input value={searchTerm} onChange={e => setSearchTerm(e.target.value)}
            placeholder="Search customer, rep..." className="h-7 text-xs" data-testid="override-search" />
        </div>

        {/* Create form */}
        {creating && (
          <div className="border rounded-md p-3 mb-3 bg-muted/10 space-y-2" data-testid="create-form">
            <p className="text-xs font-semibold">New Override</p>
            <div className="grid grid-cols-2 gap-2">
              <Input placeholder="Customer No" value={form.customer_no || ''} onChange={e => setForm(p => ({...p, customer_no: e.target.value}))} className="h-7 text-xs" />
              <Input placeholder="Customer Name" value={form.customer_name || ''} onChange={e => setForm(p => ({...p, customer_name: e.target.value}))} className="h-7 text-xs" />
              <Input placeholder="Rep Email *" value={form.rep_email || ''} onChange={e => setForm(p => ({...p, rep_email: e.target.value}))} className="h-7 text-xs" />
              <Input placeholder="Rep Name" value={form.rep_name || ''} onChange={e => setForm(p => ({...p, rep_name: e.target.value}))} className="h-7 text-xs" />
              <Input placeholder="Salesperson Code" value={form.salesperson_code || ''} onChange={e => setForm(p => ({...p, salesperson_code: e.target.value}))} className="h-7 text-xs" />
              <select value={form.override_type || 'rep_assignment'} onChange={e => setForm(p => ({...p, override_type: e.target.value}))}
                className="h-7 text-xs border rounded px-2 bg-background">
                {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </div>
            <Input placeholder="Reason" value={form.reason || ''} onChange={e => setForm(p => ({...p, reason: e.target.value}))} className="h-7 text-xs" />
            <Input placeholder="Notes" value={form.notes || ''} onChange={e => setForm(p => ({...p, notes: e.target.value}))} className="h-7 text-xs" />
            <Input type="date" placeholder="Expires (optional)" value={form.expires_at || ''} onChange={e => setForm(p => ({...p, expires_at: e.target.value ? e.target.value + 'T23:59:59Z' : null}))} className="h-7 text-xs w-40" />
            <div className="flex gap-2">
              <Button size="sm" className="h-6 text-[10px]" onClick={handleSave} disabled={saving || !form.rep_email} data-testid="save-override-btn">
                {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}Save
              </Button>
              <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={() => { setCreating(false); setForm({}); }}>
                <X className="w-3 h-3 mr-1" />Cancel
              </Button>
            </div>
          </div>
        )}

        {loading && <div className="flex justify-center py-6"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>}

        {!loading && filtered.length === 0 && (
          <p className="text-center py-6 text-sm text-muted-foreground">No overrides found.</p>
        )}

        {!loading && filtered.length > 0 && (
          <ScrollArea className="max-h-[400px]">
            <div className="space-y-1" data-testid="overrides-list">
              {filtered.map(o => {
                const isExp = expanded === o.id;
                const isEdit = editing === o.id;
                return (
                  <div key={o.id} className={`border rounded-md ${!o.active ? 'opacity-50' : o.expired ? 'border-amber-300' : 'border-border/40'}`} data-testid={`override-${o.id}`}>
                    <div className="flex items-center gap-2 py-2 px-3 cursor-pointer hover:bg-muted/30" onClick={() => setExpanded(isExp ? null : o.id)}>
                      <span className="font-mono text-xs font-semibold w-16 shrink-0 text-blue-600">{o.customer_no || '—'}</span>
                      <span className="text-xs flex-1 truncate">{o.customer_name || '—'}</span>
                      <span className="text-xs text-muted-foreground w-28 truncate">{o.rep_name || o.rep_email}</span>
                      <Badge variant="outline" className="text-[9px] w-14 justify-center">{TYPE_LABELS[o.override_type] || o.override_type || 'Rep'}</Badge>
                      {o.expired && <AlertTriangle className="w-3 h-3 text-amber-500" title="Expired" />}
                      {!o.active && <PowerOff className="w-3 h-3 text-red-400" title="Inactive" />}
                      {isExp ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                    </div>

                    {isExp && !isEdit && (
                      <div className="px-3 pb-3 pt-1 border-t border-border/30 space-y-1.5 bg-muted/10 text-[11px]">
                        <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
                          <div><span className="text-muted-foreground">Rep:</span> {o.rep_name} &lt;{o.rep_email}&gt;</div>
                          <div><span className="text-muted-foreground">Code:</span> {o.salesperson_code || '—'}</div>
                          <div><span className="text-muted-foreground">Type:</span> {TYPE_LABELS[o.override_type] || o.override_type || 'rep_assignment'}</div>
                          <div><span className="text-muted-foreground">Active:</span> {o.active ? 'Yes' : 'No'}{o.expired ? ' (expired)' : ''}</div>
                          {o.reason && <div className="col-span-2"><span className="text-muted-foreground">Reason:</span> {o.reason}</div>}
                          {o.notes && <div className="col-span-2"><span className="text-muted-foreground">Notes:</span> {o.notes}</div>}
                          {o.expires_at && <div><span className="text-muted-foreground">Expires:</span> {new Date(o.expires_at).toLocaleDateString()}</div>}
                          <div><span className="text-muted-foreground">Created:</span> {o.created_utc ? new Date(o.created_utc).toLocaleDateString() : '—'}</div>
                          <div><span className="text-muted-foreground">Updated:</span> {o.updated_utc ? new Date(o.updated_utc).toLocaleDateString() : '—'}</div>
                        </div>
                        <div className="flex gap-2 pt-1">
                          <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => startEdit(o)} data-testid={`edit-${o.id}`}>
                            <Edit2 className="w-3 h-3 mr-1" />Edit
                          </Button>
                          {o.active ? (
                            <Button size="sm" variant="outline" className="h-6 text-[10px] text-red-600 border-red-300" onClick={() => handleDisable(o.customer_no)} data-testid={`disable-${o.id}`}>
                              <PowerOff className="w-3 h-3 mr-1" />Disable
                            </Button>
                          ) : (
                            <Badge variant="outline" className="text-[9px] text-muted-foreground">Inactive</Badge>
                          )}
                        </div>
                      </div>
                    )}

                    {isExp && isEdit && (
                      <div className="px-3 pb-3 pt-1 border-t border-border/30 space-y-2 bg-blue-500/5">
                        <div className="grid grid-cols-2 gap-2">
                          <Input placeholder="Customer No" value={form.customer_no || ''} onChange={e => setForm(p => ({...p, customer_no: e.target.value}))} className="h-7 text-xs" />
                          <Input placeholder="Customer Name" value={form.customer_name || ''} onChange={e => setForm(p => ({...p, customer_name: e.target.value}))} className="h-7 text-xs" />
                          <Input placeholder="Rep Email" value={form.rep_email || ''} onChange={e => setForm(p => ({...p, rep_email: e.target.value}))} className="h-7 text-xs" />
                          <Input placeholder="Rep Name" value={form.rep_name || ''} onChange={e => setForm(p => ({...p, rep_name: e.target.value}))} className="h-7 text-xs" />
                          <Input placeholder="Salesperson Code" value={form.salesperson_code || ''} onChange={e => setForm(p => ({...p, salesperson_code: e.target.value}))} className="h-7 text-xs" />
                          <select value={form.override_type || 'rep_assignment'} onChange={e => setForm(p => ({...p, override_type: e.target.value}))} className="h-7 text-xs border rounded px-2 bg-background">
                            {Object.entries(TYPE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                          </select>
                        </div>
                        <Input placeholder="Reason" value={form.reason || ''} onChange={e => setForm(p => ({...p, reason: e.target.value}))} className="h-7 text-xs" />
                        <Input placeholder="Notes" value={form.notes || ''} onChange={e => setForm(p => ({...p, notes: e.target.value}))} className="h-7 text-xs" />
                        <div className="flex gap-2">
                          <Button size="sm" className="h-6 text-[10px]" onClick={handleSave} disabled={saving} data-testid="save-edit-btn">
                            {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}Save
                          </Button>
                          <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={() => { setEditing(null); setForm({}); }}>Cancel</Button>
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
