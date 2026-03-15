import { useState, useEffect, useCallback } from 'react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Loader2, Plus, Pencil, Save, X, FileText, User, Calendar, ShieldCheck, ToggleLeft, ToggleRight } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

export default function TemplatesPage() {
  const [templates, setTemplates] = useState([]);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState('all');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (filterType !== 'all') params.set('entity_type', filterType);
      const res = await fetch(`${API}/api/inventory-ledger/templates?${params}`);
      if (res.ok) { const d = await res.json(); setTemplates(d.entries || []); }
    } catch { toast.error('Failed to load templates'); }
    finally { setLoading(false); }
  }, [filterType]);

  useEffect(() => { load(); }, [load]);

  const resetForm = () => ({ name: '', entity_type: 'sales_order', applies_to_order_type: '', description: '', default_assignment_to: '', default_due_days: 0, default_escalation_status: '', auto_request_approval: false, notes: '', is_active: true });

  const openCreate = () => { setForm(resetForm()); setEditing(null); setShowForm(true); };
  const openEdit = (t) => { setForm({ ...t }); setEditing(t.template_id); setShowForm(true); };

  const saveTemplate = async () => {
    if (!form.name?.trim()) { toast.error('Name is required'); return; }
    setSaving(true);
    try {
      const url = editing ? `${API}/api/inventory-ledger/templates/${editing}` : `${API}/api/inventory-ledger/templates`;
      const method = editing ? 'PATCH' : 'POST';
      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(form) });
      if (res.ok) { toast.success(editing ? 'Template updated' : 'Template created'); setShowForm(false); load(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed to save'); }
    finally { setSaving(false); }
  };

  const toggleActive = async (t) => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/templates/${t.template_id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_active: !t.is_active }),
      });
      if (res.ok) { toast.success(t.is_active ? 'Template deactivated' : 'Template activated'); load(); }
    } catch { toast.error('Failed'); }
  };

  return (
    <div className="p-6 max-w-[1200px] mx-auto space-y-5" data-testid="templates-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }} data-testid="templates-title">Operational Templates</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Reusable workflow setups for Sales Orders and PO Drafts</p>
        </div>
        <Button size="sm" className="h-8 text-xs gap-1.5" onClick={openCreate} data-testid="create-template-btn"><Plus className="w-3.5 h-3.5" /> New Template</Button>
      </div>

      <div className="flex gap-3 items-center">
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="h-8 w-[160px] text-xs" data-testid="template-type-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="sales_order">Sales Orders</SelectItem>
            <SelectItem value="po_draft">PO Drafts</SelectItem>
          </SelectContent>
        </Select>
        <span className="text-xs text-muted-foreground">{templates.length} templates</span>
      </div>

      {/* Template Form Dialog */}
      {showForm && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setShowForm(false)} data-testid="template-form-dialog">
          <div className="bg-background border border-border rounded-lg p-5 max-w-md w-full shadow-xl space-y-3 max-h-[85vh] overflow-y-auto" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold">{editing ? 'Edit Template' : 'Create Template'}</h3>
            <div className="space-y-2">
              <Input className="h-8 text-xs" placeholder="Template name..." value={form.name || ''} onChange={e => setForm({ ...form, name: e.target.value })} data-testid="template-name-input" autoFocus />
              <Select value={form.entity_type || 'sales_order'} onValueChange={v => setForm({ ...form, entity_type: v })}>
                <SelectTrigger className="h-8 text-xs" data-testid="template-entity-type"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="sales_order">Sales Order</SelectItem><SelectItem value="po_draft">PO Draft</SelectItem></SelectContent>
              </Select>
              {form.entity_type === 'sales_order' && (
                <Select value={form.applies_to_order_type || 'any'} onValueChange={v => setForm({ ...form, applies_to_order_type: v === 'any' ? '' : v })}>
                  <SelectTrigger className="h-8 text-xs" data-testid="template-order-type"><SelectValue /></SelectTrigger>
                  <SelectContent><SelectItem value="any">Any Order Type</SelectItem><SelectItem value="warehouse">Warehouse</SelectItem><SelectItem value="drop_ship">Drop-Ship</SelectItem></SelectContent>
                </Select>
              )}
              <Input className="h-8 text-xs" placeholder="Description..." value={form.description || ''} onChange={e => setForm({ ...form, description: e.target.value })} data-testid="template-description-input" />
              <div className="flex gap-2">
                <Input className="h-8 text-xs flex-1" placeholder="Default assign to..." value={form.default_assignment_to || ''} onChange={e => setForm({ ...form, default_assignment_to: e.target.value })} data-testid="template-assign-input" />
                <Input type="number" className="h-8 text-xs w-24" placeholder="Due days" value={form.default_due_days || ''} onChange={e => setForm({ ...form, default_due_days: parseInt(e.target.value) || 0 })} data-testid="template-due-days-input" />
              </div>
              <Select value={form.default_escalation_status || 'none'} onValueChange={v => setForm({ ...form, default_escalation_status: v === 'none' ? '' : v })}>
                <SelectTrigger className="h-8 text-xs" data-testid="template-esc-status"><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="none">No Escalation Status</SelectItem><SelectItem value="on_track">On Track</SelectItem><SelectItem value="due_soon">Due Soon</SelectItem><SelectItem value="overdue">Overdue</SelectItem><SelectItem value="escalated">Escalated</SelectItem></SelectContent>
              </Select>
              <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="template-approval-toggle">
                <input type="checkbox" checked={form.auto_request_approval || false} onChange={e => setForm({ ...form, auto_request_approval: e.target.checked })} className="rounded" />
                Auto-request approval on apply
              </label>
              <Input className="h-8 text-xs" placeholder="Notes..." value={form.notes || ''} onChange={e => setForm({ ...form, notes: e.target.value })} data-testid="template-notes-input" />
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setShowForm(false)}>Cancel</Button>
              <Button size="sm" className="h-7 text-[10px]" disabled={saving || !form.name?.trim()} onClick={saveTemplate} data-testid="template-save-btn">
                {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />} {editing ? 'Update' : 'Create'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Templates List */}
      {loading ? (
        <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : templates.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground" data-testid="templates-empty">
          <FileText className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No templates yet</p>
          <p className="text-xs mt-1">Create your first operational template</p>
        </div>
      ) : (
        <div className="grid gap-3" data-testid="templates-list">
          {templates.map((t, i) => (
            <div key={t.template_id} className={`border border-border rounded-lg p-4 hover:bg-muted/20 transition-colors ${!t.is_active ? 'opacity-50' : ''}`} data-testid={`template-card-${i}`}>
              <div className="flex items-start justify-between">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-bold truncate" data-testid={`template-name-${i}`}>{t.name}</h3>
                    <Badge variant="outline" className="text-[8px] shrink-0">{t.entity_type === 'sales_order' ? 'SO' : 'PO Draft'}</Badge>
                    {t.applies_to_order_type && <Badge variant="secondary" className="text-[8px] shrink-0">{t.applies_to_order_type === 'drop_ship' ? 'Drop-Ship' : 'Warehouse'}</Badge>}
                    {!t.is_active && <Badge variant="destructive" className="text-[8px]">Inactive</Badge>}
                  </div>
                  {t.description && <p className="text-[10px] text-muted-foreground mt-0.5">{t.description}</p>}
                  <div className="flex gap-3 mt-2 text-[10px] text-muted-foreground flex-wrap">
                    {t.default_assignment_to && <span className="flex items-center gap-1"><User className="w-3 h-3" /> {t.default_assignment_to}</span>}
                    {t.default_due_days > 0 && <span className="flex items-center gap-1"><Calendar className="w-3 h-3" /> +{t.default_due_days} days</span>}
                    {t.auto_request_approval && <span className="flex items-center gap-1"><ShieldCheck className="w-3 h-3" /> Auto-approval</span>}
                  </div>
                </div>
                <div className="flex gap-1 shrink-0 ml-2">
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => toggleActive(t)} data-testid={`template-toggle-${i}`}>
                    {t.is_active ? <ToggleRight className="w-4 h-4 text-green-600" /> : <ToggleLeft className="w-4 h-4 text-muted-foreground" />}
                  </Button>
                  <Button variant="ghost" size="sm" className="h-7 w-7 p-0" onClick={() => openEdit(t)} data-testid={`template-edit-${i}`}>
                    <Pencil className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
