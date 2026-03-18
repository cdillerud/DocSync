import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import {
  Plus, Pencil, Trash2, Search, Filter, Save, X, Loader2,
  Package, Hash, Tag, Users, ArrowUpDown, CheckCircle2, XCircle
} from 'lucide-react';
import api from '@/lib/api';

const TARGET_TYPES = [
  { value: 'item', label: 'Item' },
  { value: 'gl_account', label: 'G/L Account' },
];

function MappingFormDialog({ mapping, onSave, onCancel, saving }) {
  const isEdit = !!mapping?.id;
  const [form, setForm] = useState({
    keyword_phrase: mapping?.keyword_phrase || '',
    keywords: (mapping?.keywords || []).join(', '),
    aliases: (mapping?.aliases || []).join(', '),
    target_type: mapping?.target_type || 'item',
    target_no: mapping?.target_no || mapping?.bc_item_number || '',
    bc_item_description: mapping?.bc_item_description || '',
    customer_no: mapping?.customer_no || '',
    priority: mapping?.priority ?? 100,
    active: mapping?.active ?? true,
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    if (!form.target_no) {
      toast.error('Target number is required');
      return;
    }
    if (!form.keyword_phrase && !form.keywords.trim()) {
      toast.error('Keyword phrase or keywords are required');
      return;
    }
    onSave({
      ...form,
      keywords: form.keywords ? form.keywords.split(',').map(k => k.trim()).filter(Boolean) : [],
      aliases: form.aliases ? form.aliases.split(',').map(a => a.trim()).filter(Boolean) : [],
      priority: parseInt(form.priority) || 100,
    });
  };

  return (
    <div className="border border-border rounded-lg p-4 bg-card" data-testid="mapping-form">
      <h3 className="text-sm font-bold mb-3" style={{ fontFamily: 'Chivo, sans-serif' }}>
        {isEdit ? 'Edit Mapping Rule' : 'New Mapping Rule'}
      </h3>
      <form onSubmit={handleSubmit} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Keyword Phrase</Label>
            <Input
              className="h-8 text-xs"
              placeholder="e.g. corrugated box 12x12"
              value={form.keyword_phrase}
              onChange={e => setForm({ ...form, keyword_phrase: e.target.value })}
              data-testid="mapping-keyword-phrase"
            />
          </div>
          <div>
            <Label className="text-xs">Keywords (comma-separated)</Label>
            <Input
              className="h-8 text-xs"
              placeholder="e.g. corrugated, box, 12x12"
              value={form.keywords}
              onChange={e => setForm({ ...form, keywords: e.target.value })}
              data-testid="mapping-keywords"
            />
          </div>
        </div>

        <div>
          <Label className="text-xs">Aliases (comma-separated)</Label>
          <Input
            className="h-8 text-xs"
            placeholder="e.g. corr box, corrbox 12"
            value={form.aliases}
            onChange={e => setForm({ ...form, aliases: e.target.value })}
            data-testid="mapping-aliases"
          />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Target Type</Label>
            <Select value={form.target_type} onValueChange={v => setForm({ ...form, target_type: v })}>
              <SelectTrigger className="h-8 text-xs" data-testid="mapping-target-type">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {TARGET_TYPES.map(t => (
                  <SelectItem key={t.value} value={t.value}>{t.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div>
            <Label className="text-xs">Target No.</Label>
            <Input
              className="h-8 text-xs font-mono"
              placeholder="e.g. ITEM-001"
              value={form.target_no}
              onChange={e => setForm({ ...form, target_no: e.target.value })}
              data-testid="mapping-target-no"
              required
            />
          </div>
          <div>
            <Label className="text-xs">Description</Label>
            <Input
              className="h-8 text-xs"
              placeholder="BC item description"
              value={form.bc_item_description}
              onChange={e => setForm({ ...form, bc_item_description: e.target.value })}
              data-testid="mapping-description"
            />
          </div>
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div>
            <Label className="text-xs">Customer No. (optional)</Label>
            <Input
              className="h-8 text-xs font-mono"
              placeholder="All customers"
              value={form.customer_no}
              onChange={e => setForm({ ...form, customer_no: e.target.value })}
              data-testid="mapping-customer-no"
            />
          </div>
          <div>
            <Label className="text-xs">Priority (lower = higher)</Label>
            <Input
              className="h-8 text-xs font-mono"
              type="number"
              min={1}
              value={form.priority}
              onChange={e => setForm({ ...form, priority: e.target.value })}
              data-testid="mapping-priority"
            />
          </div>
          <div className="flex items-end gap-2 pb-0.5">
            <Label className="text-xs">Active</Label>
            <Switch
              checked={form.active}
              onCheckedChange={v => setForm({ ...form, active: v })}
              data-testid="mapping-active-toggle"
            />
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <Button type="submit" size="sm" className="h-7 text-xs" disabled={saving} data-testid="mapping-save-btn">
            {saving ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Save className="w-3 h-3 mr-1" />}
            {isEdit ? 'Update' : 'Create'}
          </Button>
          <Button type="button" variant="ghost" size="sm" className="h-7 text-xs" onClick={onCancel} data-testid="mapping-cancel-btn">
            <X className="w-3 h-3 mr-1" /> Cancel
          </Button>
        </div>
      </form>
    </div>
  );
}

export default function ItemMappingsPage() {
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState('');
  const [filterCustomer, setFilterCustomer] = useState('');
  const [showInactive, setShowInactive] = useState(false);
  const [editingMapping, setEditingMapping] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [saving, setSaving] = useState(false);
  const [deletingId, setDeletingId] = useState(null);

  const fetchMappings = useCallback(async () => {
    try {
      setLoading(true);
      const params = new URLSearchParams();
      if (filterCustomer) params.append('customer_no', filterCustomer);
      if (!showInactive) params.append('active_only', 'false');
      const res = await api.get(`/gpi-integration/item-mappings?${params.toString()}`);
      setMappings(res.data.mappings || []);
    } catch (err) {
      toast.error('Failed to load item mappings');
    } finally {
      setLoading(false);
    }
  }, [filterCustomer, showInactive]);

  useEffect(() => { fetchMappings(); }, [fetchMappings]);

  const handleSave = async (formData) => {
    setSaving(true);
    try {
      if (editingMapping?.id) {
        await api.put(`/gpi-integration/item-mappings/${editingMapping.id}`, formData);
        toast.success('Mapping updated');
      } else {
        await api.post('/gpi-integration/item-mappings', formData);
        toast.success('Mapping created');
      }
      setShowForm(false);
      setEditingMapping(null);
      fetchMappings();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this mapping rule?')) return;
    setDeletingId(id);
    try {
      await api.delete(`/gpi-integration/item-mappings/${id}`);
      toast.success('Mapping deleted');
      fetchMappings();
    } catch (err) {
      toast.error('Delete failed');
    } finally {
      setDeletingId(null);
    }
  };

  const filtered = mappings.filter(m => {
    if (searchTerm) {
      const q = searchTerm.toLowerCase();
      const match = (m.keyword_phrase || '').toLowerCase().includes(q) ||
        (m.target_no || '').toLowerCase().includes(q) ||
        (m.bc_item_description || '').toLowerCase().includes(q) ||
        (m.keywords || []).some(k => k.toLowerCase().includes(q));
      if (!match) return false;
    }
    if (!showInactive && m.active === false) return false;
    return true;
  });

  return (
    <div data-testid="item-mappings-page">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Item Mapping Rules
          </h2>
          <p className="text-xs text-muted-foreground mt-0.5">
            Configure how document line descriptions map to BC item numbers or G/L accounts
          </p>
        </div>
        <Button
          size="sm"
          className="h-8 text-xs"
          onClick={() => { setEditingMapping(null); setShowForm(true); }}
          data-testid="add-mapping-btn"
        >
          <Plus className="w-3.5 h-3.5 mr-1" /> Add Rule
        </Button>
      </div>

      {/* Form */}
      {showForm && (
        <div className="mb-4">
          <MappingFormDialog
            mapping={editingMapping}
            onSave={handleSave}
            onCancel={() => { setShowForm(false); setEditingMapping(null); }}
            saving={saving}
          />
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-xs">
          <Search className="w-3.5 h-3.5 absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="h-8 text-xs pl-8"
            placeholder="Search keyword, item, description..."
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            data-testid="mapping-search-input"
          />
        </div>
        <Input
          className="h-8 text-xs w-32 font-mono"
          placeholder="Customer No."
          value={filterCustomer}
          onChange={e => setFilterCustomer(e.target.value)}
          data-testid="mapping-filter-customer"
        />
        <div className="flex items-center gap-1.5">
          <Switch
            checked={showInactive}
            onCheckedChange={setShowInactive}
            data-testid="mapping-show-inactive"
          />
          <Label className="text-xs text-muted-foreground">Show Inactive</Label>
        </div>
        <Badge variant="outline" className="text-[10px]">
          {filtered.length} rule{filtered.length !== 1 ? 's' : ''}
        </Badge>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            {mappings.length === 0
              ? 'No item mapping rules configured yet. Click "Add Rule" to create one.'
              : 'No mappings match your filters.'}
          </CardContent>
        </Card>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="mappings-table">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-muted/50 border-b border-border">
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Keyword / Phrase</th>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Target</th>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Description</th>
                <th className="text-left px-3 py-2 font-semibold text-muted-foreground">Customer</th>
                <th className="text-center px-3 py-2 font-semibold text-muted-foreground">Priority</th>
                <th className="text-center px-3 py-2 font-semibold text-muted-foreground">Status</th>
                <th className="text-right px-3 py-2 font-semibold text-muted-foreground">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map(m => (
                <tr key={m.id} className="border-b border-border last:border-b-0 hover:bg-muted/30 transition-colors" data-testid={`mapping-row-${m.id}`}>
                  <td className="px-3 py-2.5">
                    <div className="font-medium">{m.keyword_phrase || '-'}</div>
                    {m.keywords?.length > 0 && (
                      <div className="flex flex-wrap gap-1 mt-1">
                        {m.keywords.slice(0, 4).map((k, i) => (
                          <Badge key={i} variant="outline" className="text-[9px] px-1 py-0 h-4">{k}</Badge>
                        ))}
                        {m.keywords.length > 4 && (
                          <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">+{m.keywords.length - 4}</Badge>
                        )}
                      </div>
                    )}
                    {m.aliases?.length > 0 && (
                      <div className="text-[10px] text-muted-foreground mt-0.5">
                        Aliases: {m.aliases.slice(0, 2).join(', ')}{m.aliases.length > 2 ? ` +${m.aliases.length - 2}` : ''}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <Badge variant="secondary" className="text-[9px] px-1 py-0 h-4">
                        {m.target_type === 'gl_account' ? 'G/L' : 'Item'}
                      </Badge>
                      <code className="font-mono text-[11px]">{m.target_no || m.bc_item_number}</code>
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-muted-foreground max-w-[200px] truncate">
                    {m.bc_item_description || '-'}
                  </td>
                  <td className="px-3 py-2.5">
                    {m.customer_no ? (
                      <code className="font-mono text-[11px]">{m.customer_no}</code>
                    ) : (
                      <span className="text-muted-foreground">All</span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    <span className="font-mono">{m.priority ?? 100}</span>
                  </td>
                  <td className="px-3 py-2.5 text-center">
                    {m.active !== false ? (
                      <span className="inline-flex items-center gap-0.5 text-emerald-500 text-[10px]">
                        <CheckCircle2 className="w-3 h-3" /> Active
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-0.5 text-muted-foreground text-[10px]">
                        <XCircle className="w-3 h-3" /> Inactive
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => { setEditingMapping(m); setShowForm(true); }}
                        data-testid={`edit-mapping-${m.id}`}
                      >
                        <Pencil className="w-3 h-3" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6 text-red-500 hover:text-red-600"
                        onClick={() => handleDelete(m.id)}
                        disabled={deletingId === m.id}
                        data-testid={`delete-mapping-${m.id}`}
                      >
                        {deletingId === m.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
