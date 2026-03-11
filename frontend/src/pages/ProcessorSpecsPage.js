import { useState, useEffect, useCallback } from 'react';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import {
  Cpu, Plus, FileCode, Copy, Check, Trash2, RefreshCw, Sparkles, ArrowRight, FileText, Code, Wand2,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const STATUS_STYLES = {
  draft:       { label: 'Draft',       cls: 'bg-gray-500/20 text-gray-400 border-gray-600' },
  ready:       { label: 'Ready',       cls: 'bg-blue-500/20 text-blue-400 border-blue-600' },
  approved:    { label: 'Approved',    cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-700' },
  implemented: { label: 'Implemented', cls: 'bg-purple-500/20 text-purple-400 border-purple-600' },
  rejected:    { label: 'Rejected',    cls: 'bg-red-500/20 text-red-400 border-red-700' },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.draft;
  return <Badge data-testid={`spec-status-${status}`} className={`text-[10px] font-semibold border ${s.cls}`}>{s.label}</Badge>;
}

function CopyButton({ text, label }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    toast.success(`${label} copied to clipboard`);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <Button variant="ghost" size="sm" onClick={handleCopy} data-testid={`copy-${label.toLowerCase().replace(/\s/g, '-')}-btn`}>
      {copied ? <Check className="w-3 h-3 mr-1" /> : <Copy className="w-3 h-3 mr-1" />}
      {copied ? 'Copied' : `Copy ${label}`}
    </Button>
  );
}

// ─── Create/Edit Spec Dialog ──────────────────────────────────
function SpecForm({ spec, onSave, onCancel }) {
  const [form, setForm] = useState({
    processor_name: spec?.processor_name || '',
    doc_type: spec?.doc_type || '',
    description: spec?.description || '',
    layout_family_id: spec?.layout_family_id || '',
    notes: spec?.notes || '',
    keywords: (spec?.detection_patterns?.keywords || []).join(', '),
    vendor_patterns: (spec?.detection_patterns?.vendor_patterns || []).join(', '),
    vendor_hints: (spec?.vendor_hints || []).join(', '),
    field_mappings_text: JSON.stringify(spec?.field_mappings || [], null, 2),
    reference_hints_text: JSON.stringify(spec?.reference_hints || [], null, 2),
  });
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!form.processor_name) { toast.error('Processor name is required'); return; }
    setSaving(true);
    try {
      let field_mappings = [];
      let reference_hints = [];
      try { field_mappings = JSON.parse(form.field_mappings_text); } catch { toast.error('Invalid field mappings JSON'); setSaving(false); return; }
      try { reference_hints = JSON.parse(form.reference_hints_text); } catch { toast.error('Invalid reference hints JSON'); setSaving(false); return; }

      const body = {
        processor_name: form.processor_name,
        doc_type: form.doc_type,
        description: form.description,
        layout_family_id: form.layout_family_id,
        notes: form.notes,
        detection_patterns: {
          keywords: form.keywords.split(',').map(s => s.trim()).filter(Boolean),
          vendor_patterns: form.vendor_patterns.split(',').map(s => s.trim()).filter(Boolean),
          layout_hints: [],
        },
        vendor_hints: form.vendor_hints.split(',').map(s => s.trim()).filter(Boolean),
        field_mappings,
        reference_hints,
      };

      const url = spec?.spec_id
        ? `${API}/api/processor-specs/${spec.spec_id}`
        : `${API}/api/processor-specs/create`;
      const method = spec?.spec_id ? 'PUT' : 'POST';

      const res = await fetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      if (!res.ok) throw new Error(await res.text());
      toast.success(spec?.spec_id ? 'Spec updated' : 'Spec created');
      onSave();
    } catch (e) {
      toast.error(`Save failed: ${e.message}`);
    } finally {
      setSaving(false);
    }
  };

  const set = (key, val) => setForm(f => ({ ...f, [key]: val }));

  return (
    <div className="space-y-4 p-1">
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Processor Name</label>
          <Input data-testid="spec-name-input" value={form.processor_name} onChange={e => set('processor_name', e.target.value)} placeholder="e.g. PackingSlipProcessor" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Document Type</label>
          <Input data-testid="spec-doctype-input" value={form.doc_type} onChange={e => set('doc_type', e.target.value)} placeholder="e.g. PACKING_SLIP" />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Description</label>
        <Textarea data-testid="spec-description-input" value={form.description} onChange={e => set('description', e.target.value)} rows={2} placeholder="What does this processor do?" />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Layout Family ID</label>
          <Input value={form.layout_family_id} onChange={e => set('layout_family_id', e.target.value)} placeholder="Optional" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Vendor Hints (comma-separated)</label>
          <Input value={form.vendor_hints} onChange={e => set('vendor_hints', e.target.value)} placeholder="UPS, FedEx, DHL" />
        </div>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Detection Keywords (comma-separated)</label>
          <Input value={form.keywords} onChange={e => set('keywords', e.target.value)} placeholder="PACKING SLIP, SHIP TO" />
        </div>
        <div>
          <label className="text-xs text-muted-foreground mb-1 block">Vendor Patterns (comma-separated)</label>
          <Input value={form.vendor_patterns} onChange={e => set('vendor_patterns', e.target.value)} placeholder="Pattern1, Pattern2" />
        </div>
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Field Mappings (JSON array)</label>
        <Textarea data-testid="spec-fields-input" value={form.field_mappings_text} onChange={e => set('field_mappings_text', e.target.value)} rows={4} className="font-mono text-xs" />
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Reference Hints (JSON array)</label>
        <Textarea data-testid="spec-refs-input" value={form.reference_hints_text} onChange={e => set('reference_hints_text', e.target.value)} rows={3} className="font-mono text-xs" />
      </div>
      <div>
        <label className="text-xs text-muted-foreground mb-1 block">Notes</label>
        <Textarea value={form.notes} onChange={e => set('notes', e.target.value)} rows={2} />
      </div>
      <div className="flex gap-2 justify-end pt-2">
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
        <Button onClick={handleSave} disabled={saving} data-testid="save-spec-btn">
          {saving ? 'Saving...' : (spec?.spec_id ? 'Update Spec' : 'Create Spec')}
        </Button>
      </div>
    </div>
  );
}

// ─── Spec Detail Panel ────────────────────────────────────────
function SpecDetailPanel({ spec, onClose, onRefresh }) {
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [activeTab, setActiveTab] = useState('brief');
  const [detail, setDetail] = useState(spec);

  useEffect(() => { setDetail(spec); setActiveTab('brief'); setEditing(false); }, [spec]);

  const generateOutputs = async () => {
    setGenerating(true);
    try {
      const res = await fetch(`${API}/api/processor-specs/${detail.spec_id}/generate`, { method: 'POST' });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setDetail(d => ({ ...d, generated_brief: data.brief, generated_json_spec: data.json_spec, generated_prompt: data.prompt, spec_status: 'ready' }));
      toast.success('Outputs generated');
      onRefresh();
    } catch (e) {
      toast.error(`Generate failed: ${e.message}`);
    } finally {
      setGenerating(false);
    }
  };

  const setStatus = async (status) => {
    try {
      const res = await fetch(`${API}/api/processor-specs/${detail.spec_id}/set-status`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }),
      });
      if (!res.ok) throw new Error(await res.text());
      const updated = await res.json();
      setDetail(updated);
      toast.success(`Status changed to ${status}`);
      onRefresh();
    } catch (e) {
      toast.error(`Status change failed: ${e.message}`);
    }
  };

  if (!detail) return null;
  if (editing) {
    return <SpecForm spec={detail} onSave={() => { setEditing(false); onRefresh(); onClose(); }} onCancel={() => setEditing(false)} />;
  }

  const tabs = [
    { id: 'brief', label: 'Brief', icon: FileText },
    { id: 'json', label: 'JSON Spec', icon: Code },
    { id: 'prompt', label: 'Prompt', icon: Wand2 },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold">{detail.processor_name}</h3>
          <p className="text-xs text-muted-foreground">{detail.doc_type} | {detail.spec_id}</p>
        </div>
        <StatusBadge status={detail.spec_status} />
      </div>

      {detail.description && <p className="text-sm text-muted-foreground">{detail.description}</p>}

      <div className="flex gap-2 flex-wrap">
        <Button size="sm" variant="outline" onClick={() => setEditing(true)} data-testid="edit-spec-btn">Edit</Button>
        <Button size="sm" onClick={generateOutputs} disabled={generating} data-testid="generate-outputs-btn">
          <Sparkles className="w-3 h-3 mr-1" />{generating ? 'Generating...' : 'Generate Outputs'}
        </Button>
        {detail.spec_status === 'ready' && (
          <Button size="sm" variant="default" onClick={() => setStatus('approved')} data-testid="approve-spec-btn">
            <Check className="w-3 h-3 mr-1" />Approve
          </Button>
        )}
        {detail.spec_status === 'approved' && (
          <Button size="sm" variant="default" onClick={() => setStatus('implemented')} data-testid="mark-implemented-btn">
            <ArrowRight className="w-3 h-3 mr-1" />Mark Implemented
          </Button>
        )}
        {detail.spec_status !== 'rejected' && (
          <Button size="sm" variant="destructive" onClick={() => setStatus('rejected')} data-testid="reject-spec-btn">Reject</Button>
        )}
      </div>

      {/* Output tabs */}
      <div className="flex gap-1 border-b border-border">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id)}
            className={`flex items-center gap-1 px-3 py-2 text-xs font-medium transition-colors border-b-2 ${
              activeTab === t.id ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'
            }`}
            data-testid={`tab-${t.id}`}
          >
            <t.icon className="w-3 h-3" />{t.label}
          </button>
        ))}
      </div>

      <div className="min-h-[200px]">
        {activeTab === 'brief' && (
          <div className="space-y-2">
            {detail.generated_brief ? (
              <>
                <div className="flex justify-end"><CopyButton text={detail.generated_brief} label="Brief" /></div>
                <pre className="text-xs font-mono whitespace-pre-wrap bg-muted/30 rounded p-3 border border-border max-h-[400px] overflow-y-auto" data-testid="brief-content">{detail.generated_brief}</pre>
              </>
            ) : (
              <p className="text-sm text-muted-foreground italic">No brief generated yet. Click "Generate Outputs" to create one.</p>
            )}
          </div>
        )}
        {activeTab === 'json' && (
          <div className="space-y-2">
            {detail.generated_json_spec && Object.keys(detail.generated_json_spec).length > 0 ? (
              <>
                <div className="flex justify-end"><CopyButton text={JSON.stringify(detail.generated_json_spec, null, 2)} label="JSON" /></div>
                <pre className="text-xs font-mono whitespace-pre-wrap bg-muted/30 rounded p-3 border border-border max-h-[400px] overflow-y-auto" data-testid="json-content">{JSON.stringify(detail.generated_json_spec, null, 2)}</pre>
              </>
            ) : (
              <p className="text-sm text-muted-foreground italic">No JSON spec generated yet.</p>
            )}
          </div>
        )}
        {activeTab === 'prompt' && (
          <div className="space-y-2">
            {detail.generated_prompt ? (
              <>
                <div className="flex justify-end"><CopyButton text={detail.generated_prompt} label="Prompt" /></div>
                <pre className="text-xs font-mono whitespace-pre-wrap bg-muted/30 rounded p-3 border border-border max-h-[400px] overflow-y-auto" data-testid="prompt-content">{detail.generated_prompt}</pre>
              </>
            ) : (
              <p className="text-sm text-muted-foreground italic">No implementation prompt generated yet.</p>
            )}
          </div>
        )}
      </div>

      {/* Meta info */}
      <div className="text-xs text-muted-foreground space-y-1 border-t border-border pt-3">
        {detail.vendor_hints?.length > 0 && <p>Vendors: {detail.vendor_hints.join(', ')}</p>}
        {detail.field_mappings?.length > 0 && <p>Fields: {detail.field_mappings.map(f => f.field_name).join(', ')}</p>}
        <p>Created: {new Date(detail.created_at).toLocaleString()}</p>
        <p>Updated: {new Date(detail.updated_at).toLocaleString()}</p>
      </div>
    </div>
  );
}

// ─── Main Page ────────────────────────────────────────────────
export default function ProcessorSpecsPage() {
  const [specs, setSpecs] = useState([]);
  const [stats, setStats] = useState({ total: 0, by_status: {} });
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [selectedSpec, setSelectedSpec] = useState(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = statusFilter !== 'all' ? `?status=${statusFilter}` : '';
      const [specRes, statsRes] = await Promise.all([
        fetch(`${API}/api/processor-specs/list${params}`),
        fetch(`${API}/api/processor-specs/stats`),
      ]);
      const specData = await specRes.json();
      const statsData = await statsRes.json();
      setSpecs(specData.specs || []);
      setStats(statsData);
    } catch (e) {
      toast.error(`Failed to load specs: ${e.message}`);
    } finally {
      setLoading(false);
    }
  }, [statusFilter]);

  useEffect(() => { load(); }, [load]);

  const handleDelete = async (specId) => {
    if (!window.confirm('Delete this spec?')) return;
    try {
      await fetch(`${API}/api/processor-specs/${specId}`, { method: 'DELETE' });
      toast.success('Spec deleted');
      load();
      if (selectedSpec?.spec_id === specId) { setSheetOpen(false); setSelectedSpec(null); }
    } catch (e) {
      toast.error(`Delete failed: ${e.message}`);
    }
  };

  const filtered = specs.filter(s =>
    !search || s.processor_name.toLowerCase().includes(search.toLowerCase()) || s.doc_type?.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="space-y-6" data-testid="processor-specs-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" data-testid="page-title">Processor Specs</h1>
          <p className="text-sm text-muted-foreground mt-1">Generate implementation specifications for document processors</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} data-testid="refresh-specs-btn"><RefreshCw className="w-3 h-3 mr-1" />Refresh</Button>
          <Button size="sm" onClick={() => setCreating(true)} data-testid="create-spec-btn"><Plus className="w-3 h-3 mr-1" />New Spec</Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {['draft', 'ready', 'approved', 'implemented', 'rejected'].map(s => (
          <Card key={s} className="cursor-pointer hover:border-primary/50 transition-colors" onClick={() => setStatusFilter(statusFilter === s ? 'all' : s)}>
            <CardContent className="p-3">
              <div className="flex items-center justify-between">
                <span className="text-xs text-muted-foreground capitalize">{s}</span>
                <StatusBadge status={s} />
              </div>
              <p className="text-xl font-bold mt-1" data-testid={`count-${s}`}>{stats.by_status?.[s] || 0}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <div className="relative flex-1 max-w-xs">
          <Input
            placeholder="Search specs..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            data-testid="search-specs-input"
          />
        </div>
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[140px]" data-testid="status-filter">
            <SelectValue placeholder="All statuses" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All</SelectItem>
            <SelectItem value="draft">Draft</SelectItem>
            <SelectItem value="ready">Ready</SelectItem>
            <SelectItem value="approved">Approved</SelectItem>
            <SelectItem value="implemented">Implemented</SelectItem>
            <SelectItem value="rejected">Rejected</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Doc Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Fields</TableHead>
                <TableHead>Created</TableHead>
                <TableHead className="w-[80px]">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">Loading...</TableCell></TableRow>
              ) : filtered.length === 0 ? (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground">No specs found. Create one to get started.</TableCell></TableRow>
              ) : filtered.map(s => (
                <TableRow
                  key={s.spec_id}
                  className="cursor-pointer hover:bg-muted/30"
                  onClick={() => { setSelectedSpec(s); setSheetOpen(true); }}
                  data-testid={`spec-row-${s.spec_id}`}
                >
                  <TableCell className="font-medium">
                    <div className="flex items-center gap-2">
                      <Cpu className="w-4 h-4 text-muted-foreground" />
                      {s.processor_name}
                    </div>
                  </TableCell>
                  <TableCell><Badge variant="outline" className="text-[10px]">{s.doc_type || '-'}</Badge></TableCell>
                  <TableCell><StatusBadge status={s.spec_status} /></TableCell>
                  <TableCell className="text-xs text-muted-foreground">{s.field_mappings?.length || 0} fields</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{new Date(s.created_at).toLocaleDateString()}</TableCell>
                  <TableCell>
                    <Button variant="ghost" size="sm" onClick={e => { e.stopPropagation(); handleDelete(s.spec_id); }} data-testid={`delete-spec-${s.spec_id}`}>
                      <Trash2 className="w-3 h-3 text-red-400" />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Detail Sheet */}
      <Sheet open={sheetOpen && !!selectedSpec} onOpenChange={setSheetOpen}>
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <FileCode className="w-4 h-4" />Processor Spec Detail
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4">
            <SpecDetailPanel
              spec={selectedSpec}
              onClose={() => setSheetOpen(false)}
              onRefresh={load}
            />
          </div>
        </SheetContent>
      </Sheet>

      {/* Create Sheet */}
      <Sheet open={creating} onOpenChange={setCreating}>
        <SheetContent className="sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              <Plus className="w-4 h-4" />Create Processor Spec
            </SheetTitle>
          </SheetHeader>
          <div className="mt-4">
            <SpecForm spec={null} onSave={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
