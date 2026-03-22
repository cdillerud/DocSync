import { useState, useEffect, useCallback, useRef } from 'react';
import api from '../lib/api';
import { toast } from 'sonner';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter, DialogClose } from '../components/ui/dialog';
import { ScrollArea } from '../components/ui/scroll-area';
import { Checkbox } from '../components/ui/checkbox';
import { Textarea } from '../components/ui/textarea';
import {
  Plus, Trash2, Archive, CheckCircle2, Play, Upload, Download,
  Search, ChevronRight, X, FileText, BarChart3, ClipboardList,
  Zap, Eye, Pencil, RefreshCw, AlertTriangle, ChevronDown,
  FolderSearch, Loader2
} from 'lucide-react';

const API = '/intake-benchmark';

const STATUS_COLORS = {
  draft: 'bg-slate-500/15 text-slate-600 border-slate-300',
  in_progress: 'bg-blue-500/15 text-blue-600 border-blue-300',
  complete: 'bg-emerald-500/15 text-emerald-600 border-emerald-300',
  archived: 'bg-zinc-500/15 text-zinc-500 border-zinc-300',
};

const FINAL_STATUS_OPTS = ['Usable', 'Partial', 'Failed'];
const NEEDS_REVIEW_OPTS = ['None', 'Minor', 'Major'];

// ═══════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════

export default function BakeOffPage() {
  const [activeTab, setActiveTab] = useState('runs');
  const [selectedRunId, setSelectedRunId] = useState(null);
  const [selectedRunName, setSelectedRunName] = useState('');

  const openRun = (runId, name) => {
    setSelectedRunId(runId);
    setSelectedRunName(name);
    setActiveTab('scoring');
  };

  return (
    <div data-testid="bakeoff-page" className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Intake Benchmark
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            GPI Hub vs Square 9 — side-by-side comparison workspace
          </p>
        </div>
        {selectedRunId && (
          <Badge variant="outline" className="text-xs font-mono gap-1.5 px-3 py-1">
            <ClipboardList className="w-3 h-3" />
            {selectedRunName || selectedRunId}
          </Badge>
        )}
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList data-testid="bakeoff-tabs">
          <TabsTrigger value="runs" data-testid="tab-runs">
            <ClipboardList className="w-4 h-4 mr-1.5" /> Runs
          </TabsTrigger>
          <TabsTrigger value="scoring" data-testid="tab-scoring" disabled={!selectedRunId}>
            <Pencil className="w-4 h-4 mr-1.5" /> Scoring
          </TabsTrigger>
          <TabsTrigger value="summary" data-testid="tab-summary" disabled={!selectedRunId}>
            <BarChart3 className="w-4 h-4 mr-1.5" /> Results
          </TabsTrigger>
        </TabsList>

        <TabsContent value="runs">
          <RunSetup onOpenRun={openRun} />
        </TabsContent>
        <TabsContent value="scoring">
          {selectedRunId && <DocumentScoring runId={selectedRunId} />}
        </TabsContent>
        <TabsContent value="summary">
          {selectedRunId && <ResultsSummary runId={selectedRunId} runName={selectedRunName} />}
        </TabsContent>
      </Tabs>
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// RUN SETUP
// ═══════════════════════════════════════════════════════════════

function RunSetup({ onOpenRun }) {
  const [runs, setRuns] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: '', description: '', test_date: '', source_batch_identifier: '', expected_document_count: 50 });

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get(`${API}/runs`);
      setRuns(data.runs || []);
    } catch { toast.error('Failed to load runs'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const createRun = async () => {
    try {
      await api.post(`${API}/runs`, form);
      toast.success('Run created');
      setShowCreate(false);
      setForm({ name: '', description: '', test_date: '', source_batch_identifier: '', expected_document_count: 50 });
      fetchRuns();
    } catch { toast.error('Failed to create run'); }
  };

  const archiveRun = async (id) => {
    try { await api.post(`${API}/runs/${id}/archive`); toast.success('Archived'); fetchRuns(); }
    catch { toast.error('Failed'); }
  };

  const completeRun = async (id) => {
    try { await api.post(`${API}/runs/${id}/complete`); toast.success('Completed'); fetchRuns(); }
    catch { toast.error('Failed'); }
  };

  const deleteRun = async (id) => {
    try { await api.delete(`${API}/runs/${id}`); toast.success('Deleted'); fetchRuns(); }
    catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Benchmark Runs</h2>
        <Dialog open={showCreate} onOpenChange={setShowCreate}>
          <DialogTrigger asChild>
            <Button data-testid="create-run-btn" className="gap-1.5"><Plus className="w-4 h-4" /> New Run</Button>
          </DialogTrigger>
          <DialogContent data-testid="create-run-dialog">
            <DialogHeader><DialogTitle>Create Benchmark Run</DialogTitle></DialogHeader>
            <div className="space-y-3">
              <Input placeholder="Run Name" value={form.name} onChange={e => setForm(p => ({ ...p, name: e.target.value }))} data-testid="run-name-input" />
              <Textarea placeholder="Description / Notes" value={form.description} onChange={e => setForm(p => ({ ...p, description: e.target.value }))} rows={2} />
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Test Date</label>
                  <Input type="date" value={form.test_date} onChange={e => setForm(p => ({ ...p, test_date: e.target.value }))} data-testid="run-date-input" />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Expected Doc Count</label>
                  <Input type="number" value={form.expected_document_count} onChange={e => setForm(p => ({ ...p, expected_document_count: parseInt(e.target.value) || 0 }))} />
                </div>
              </div>
              <Input placeholder="Source Batch Identifier (optional)" value={form.source_batch_identifier} onChange={e => setForm(p => ({ ...p, source_batch_identifier: e.target.value }))} />
            </div>
            <DialogFooter>
              <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
              <Button onClick={createRun} disabled={!form.name} data-testid="confirm-create-run">Create Run</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground py-8 text-center">Loading...</p>
      ) : runs.length === 0 ? (
        <Card><CardContent className="py-12 text-center text-muted-foreground">No benchmark runs yet. Create one to get started.</CardContent></Card>
      ) : (
        <div className="grid gap-3">
          {runs.map(r => (
            <Card key={r.run_id} className="hover:border-primary/30 transition-colors cursor-pointer" data-testid={`run-${r.run_id}`}>
              <CardContent className="py-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3 flex-1 min-w-0" onClick={() => onOpenRun(r.run_id, r.name)}>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold truncate">{r.name}</span>
                        <Badge variant="outline" className={`text-[10px] ${STATUS_COLORS[r.status] || ''}`}>{r.status}</Badge>
                      </div>
                      <div className="text-xs text-muted-foreground mt-0.5 flex gap-3">
                        {r.test_date && <span>{r.test_date}</span>}
                        <span>{r.actual_document_count || 0} / {r.expected_document_count || '?'} docs</span>
                        {r.description && <span className="truncate max-w-[300px]">{r.description}</span>}
                      </div>
                    </div>
                    <ChevronRight className="w-4 h-4 text-muted-foreground shrink-0" />
                  </div>
                  <div className="flex items-center gap-1 ml-3">
                    {r.status === 'in_progress' && (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); completeRun(r.run_id); }} title="Mark complete">
                        <CheckCircle2 className="w-3.5 h-3.5 text-emerald-600" />
                      </Button>
                    )}
                    {r.status !== 'archived' && (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); archiveRun(r.run_id); }} title="Archive">
                        <Archive className="w-3.5 h-3.5" />
                      </Button>
                    )}
                    {r.status === 'draft' && (
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={(e) => { e.stopPropagation(); deleteRun(r.run_id); }} title="Delete">
                        <Trash2 className="w-3.5 h-3.5 text-destructive" />
                      </Button>
                    )}
                  </div>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}


// ═══════════════════════════════════════════════════════════════
// DOCUMENT SCORING
// ═══════════════════════════════════════════════════════════════

function DocumentScoring({ runId }) {
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addForm, setAddForm] = useState({ document_id: '', file_name: '' });
  const [whyWrongTags, setWhyWrongTags] = useState([]);
  const fileInputRef = useRef(null);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const params = { search: search || undefined };
      const { data } = await api.get(`${API}/runs/${runId}/documents`, { params });
      setDocs(data.documents || []);
      setTotal(data.total || 0);
    } catch { toast.error('Failed to load documents'); }
    finally { setLoading(false); }
  }, [runId, search]);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);
  useEffect(() => {
    api.get(`${API}/why-wrong-tags`).then(r => setWhyWrongTags(r.data.tags || [])).catch(() => {});
  }, []);

  const addDocument = async () => {
    try {
      await api.post(`${API}/runs/${runId}/documents`, addForm);
      toast.success('Document added');
      setShowAdd(false);
      setAddForm({ document_id: '', file_name: '' });
      fetchDocs();
    } catch { toast.error('Failed'); }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    try {
      const { data } = await api.post(`${API}/runs/${runId}/documents/import`, formData, { headers: { 'Content-Type': 'multipart/form-data' } });
      toast.success(`Imported ${data.imported} documents`);
      fetchDocs();
    } catch { toast.error('Import failed'); }
    e.target.value = '';
  };

  const autoPopulate = async () => {
    try {
      const { data } = await api.post(`${API}/runs/${runId}/auto-populate`);
      const parts = [`Linked ${data.linked} of ${data.total} docs`];
      if (data.vendor_inferred > 0) parts.push(`${data.vendor_inferred} vendors inferred`);
      if (data.truth_seeded > 0) parts.push(`${data.truth_seeded} truth fields seeded`);
      toast.success(parts.join(' | '));
      fetchDocs();
    } catch { toast.error('Auto-populate failed'); }
  };

  const [scanning, setScanning] = useState(false);
  const scanSharePoint = async () => {
    setScanning(true);
    try {
      const { data } = await api.post(`${API}/runs/${runId}/scan-sharepoint`, {
        max_files_per_folder: 50,
        include_subfolders: true,
        auto_match_gpi: true,
        auto_route_gpi: true,
      });
      toast.success(data.message);
      fetchDocs();
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'SharePoint scan failed');
    } finally { setScanning(false); }
  };

  const deleteDoc = async (uid) => {
    try {
      await api.delete(`${API}/runs/${runId}/documents/${uid}`);
      toast.success('Deleted');
      if (selectedDoc?.doc_uid === uid) setSelectedDoc(null);
      fetchDocs();
    } catch { toast.error('Failed'); }
  };

  const scored = docs.filter(d =>
    d.gpi_final_status || d.s9_final_status
  ).length;

  return (
    <div className="space-y-4">
      {/* Header bar */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <span className="text-sm text-muted-foreground">{scored}/{total} scored</span>
          <div className="h-2 w-32 bg-muted rounded-full overflow-hidden">
            <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${total > 0 ? (scored / total) * 100 : 0}%` }} />
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input className="pl-8 h-8 w-48 text-xs" placeholder="Search docs..." value={search} onChange={e => setSearch(e.target.value)} data-testid="scoring-search" />
          </div>
          <Button variant="outline" size="sm" className="gap-1 h-8 text-xs" onClick={autoPopulate} data-testid="auto-populate-btn">
            <Zap className="w-3 h-3" /> Auto-Populate GPI
          </Button>
          <Button variant="outline" size="sm" className="gap-1 h-8 text-xs" onClick={scanSharePoint} disabled={scanning} data-testid="scan-sp-btn">
            {scanning ? <Loader2 className="w-3 h-3 animate-spin" /> : <FolderSearch className="w-3 h-3" />}
            {scanning ? 'Scanning...' : 'Scan S9 Folders'}
          </Button>
          <Button variant="outline" size="sm" className="gap-1 h-8 text-xs" onClick={() => fileInputRef.current?.click()}>
            <Upload className="w-3 h-3" /> Import CSV
          </Button>
          <input ref={fileInputRef} type="file" accept=".csv" className="hidden" onChange={handleImport} />
          <Dialog open={showAdd} onOpenChange={setShowAdd}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-1 h-8 text-xs"><Plus className="w-3 h-3" /> Add Doc</Button>
            </DialogTrigger>
            <DialogContent data-testid="add-doc-dialog">
              <DialogHeader><DialogTitle>Add Document</DialogTitle></DialogHeader>
              <div className="space-y-3">
                <Input placeholder="Document ID" value={addForm.document_id} onChange={e => setAddForm(p => ({ ...p, document_id: e.target.value }))} data-testid="add-doc-id" />
                <Input placeholder="File Name" value={addForm.file_name} onChange={e => setAddForm(p => ({ ...p, file_name: e.target.value }))} data-testid="add-doc-filename" />
              </div>
              <DialogFooter>
                <DialogClose asChild><Button variant="outline">Cancel</Button></DialogClose>
                <Button onClick={addDocument} disabled={!addForm.document_id && !addForm.file_name}>Add</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      {/* Two-panel: table + detail */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Left: Document table */}
        <div className={`${selectedDoc ? 'lg:col-span-2' : 'lg:col-span-5'}`}>
          <Card>
            <CardContent className="p-0">
              <ScrollArea className="h-[65vh]">
                <table className="w-full text-xs">
                  <thead className="bg-muted/50 sticky top-0 z-10">
                    <tr>
                      <th className="text-left px-3 py-2 font-medium">Document</th>
                      <th className="text-left px-2 py-2 font-medium">Type</th>
                      <th className="text-center px-2 py-2 font-medium">GPI</th>
                      <th className="text-center px-2 py-2 font-medium">S9</th>
                      <th className="px-2 py-2 w-8"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {docs.map(d => (
                      <tr
                        key={d.doc_uid}
                        className={`border-b border-border/30 hover:bg-muted/30 cursor-pointer transition-colors ${selectedDoc?.doc_uid === d.doc_uid ? 'bg-primary/5' : ''}`}
                        onClick={() => setSelectedDoc(d)}
                        data-testid={`doc-row-${d.doc_uid}`}
                      >
                        <td className="px-3 py-2">
                          <div className="font-medium truncate max-w-[200px]">{d.file_name || d.document_id}</div>
                          {d.vendor_truth && <div className="text-muted-foreground truncate max-w-[200px]">{d.vendor_truth}</div>}
                        </td>
                        <td className="px-2 py-2 text-muted-foreground">{d.doc_type_truth || '—'}</td>
                        <td className="px-2 py-2 text-center">
                          <StatusDot status={d.gpi_final_status} />
                        </td>
                        <td className="px-2 py-2 text-center">
                          <StatusDot status={d.s9_final_status} />
                        </td>
                        <td className="px-2 py-2">
                          <Button variant="ghost" size="icon" className="h-6 w-6" onClick={(e) => { e.stopPropagation(); deleteDoc(d.doc_uid); }}>
                            <Trash2 className="w-3 h-3 text-muted-foreground" />
                          </Button>
                        </td>
                      </tr>
                    ))}
                    {docs.length === 0 && (
                      <tr><td colSpan={5} className="text-center py-12 text-muted-foreground">No documents. Add or import to begin.</td></tr>
                    )}
                  </tbody>
                </table>
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Right: Detail panel */}
        {selectedDoc && (
          <div className="lg:col-span-3">
            <DocumentDetail
              runId={runId}
              doc={selectedDoc}
              whyWrongTags={whyWrongTags}
              onClose={() => setSelectedDoc(null)}
              onUpdate={(updated) => {
                setSelectedDoc(updated);
                setDocs(prev => prev.map(d => d.doc_uid === updated.doc_uid ? updated : d));
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}

function StatusDot({ status }) {
  if (!status) return <span className="text-muted-foreground/40">—</span>;
  const s = status.toLowerCase();
  const color = s === 'usable' ? 'bg-emerald-500' : s === 'partial' ? 'bg-amber-500' : s === 'failed' ? 'bg-red-500' : 'bg-slate-400';
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${color}`} title={status} />;
}


// ═══════════════════════════════════════════════════════════════
// DOCUMENT DETAIL DRAWER
// ═══════════════════════════════════════════════════════════════

function DocumentDetail({ runId, doc, whyWrongTags, onClose, onUpdate }) {
  const [saving, setSaving] = useState(false);
  const [edits, setEdits] = useState({});

  const edit = (field, value) => setEdits(p => ({ ...p, [field]: value }));

  const save = async () => {
    if (Object.keys(edits).length === 0) return;
    setSaving(true);
    try {
      const { data } = await api.put(`${API}/runs/${runId}/documents/${doc.doc_uid}`, edits);
      onUpdate(data);
      setEdits({});
      toast.success('Saved');
    } catch { toast.error('Save failed'); }
    finally { setSaving(false); }
  };

  const val = (field) => edits[field] !== undefined ? edits[field] : doc[field];

  return (
    <Card data-testid="doc-detail-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-semibold truncate">{doc.file_name || doc.document_id}</CardTitle>
          <div className="flex items-center gap-2">
            {Object.keys(edits).length > 0 && (
              <Button size="sm" className="h-7 text-xs gap-1" onClick={save} disabled={saving} data-testid="save-scoring-btn">
                {saving ? <RefreshCw className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
                Save
              </Button>
            )}
            <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onClose}><X className="w-4 h-4" /></Button>
          </div>
        </div>
        {doc.gpi_auto_linked && <Badge variant="outline" className="text-[10px] bg-blue-500/10 text-blue-600">Auto-linked</Badge>}
        {doc.gpi_manually_edited && <Badge variant="outline" className="text-[10px] bg-amber-500/10 text-amber-600 ml-1">Manually edited</Badge>}
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-[60vh] pr-2">
          <div className="space-y-5">
            {/* Truth Section */}
            <FieldSection title="Ground Truth" color="border-l-violet-500">
              <FieldRow label="Vendor" value={val('vendor_truth')} onChange={v => edit('vendor_truth', v)} />
              <FieldRow label="Doc Type" value={val('doc_type_truth')} onChange={v => edit('doc_type_truth', v)} />
              <FieldRow label="Amount" value={val('amount_truth')} onChange={v => edit('amount_truth', v === '' ? null : parseFloat(v))} type="number" />
              <FieldRow label="PO" value={val('po_truth')} onChange={v => edit('po_truth', v)} />
              <FieldRow label="Folder" value={val('folder_truth')} onChange={v => edit('folder_truth', v)} />
              <div>
                <label className="text-[10px] text-muted-foreground uppercase tracking-wider">Notes</label>
                <Textarea className="text-xs h-14 mt-0.5" value={val('truth_notes') || ''} onChange={e => edit('truth_notes', e.target.value)} />
              </div>
            </FieldSection>

            {/* Side-by-side: GPI vs S9 */}
            <div className="grid grid-cols-2 gap-3">
              {/* GPI */}
              <SystemSection
                prefix="gpi" title="GPI Hub" color="border-l-emerald-500"
                doc={doc} edits={edits} edit={edit} val={val}
                whyWrongTags={whyWrongTags}
              />
              {/* S9 */}
              <SystemSection
                prefix="s9" title="Square 9" color="border-l-orange-500"
                doc={doc} edits={edits} edit={edit} val={val}
                whyWrongTags={whyWrongTags}
              />
            </div>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

function FieldSection({ title, color, children }) {
  return (
    <div className={`border-l-2 ${color} pl-3 space-y-2`}>
      <h4 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{title}</h4>
      {children}
    </div>
  );
}

function FieldRow({ label, value, onChange, type = 'text' }) {
  return (
    <div className="flex items-center gap-2">
      <label className="text-[10px] text-muted-foreground w-14 shrink-0 uppercase tracking-wider">{label}</label>
      <Input className="h-7 text-xs flex-1" type={type} value={value ?? ''} onChange={e => onChange(e.target.value)} />
    </div>
  );
}

function SystemSection({ prefix, title, color, doc, edits, edit, val, whyWrongTags }) {
  const toggleTag = (tag) => {
    const field = `${prefix}_why_wrong_tags`;
    const current = val(field) || [];
    const next = current.includes(tag) ? current.filter(t => t !== tag) : [...current, tag];
    edit(field, next);
  };

  return (
    <FieldSection title={title} color={color}>
      <div className="flex items-center gap-2 mb-1">
        <Checkbox
          checked={val(`${prefix}_ingested`) === true}
          onCheckedChange={v => edit(`${prefix}_ingested`, v)}
        />
        <span className="text-[10px] text-muted-foreground">Ingested</span>
      </div>
      <FieldRow label="Type" value={val(`${prefix}_doc_type`) ?? ''} onChange={v => edit(`${prefix}_doc_type`, v)} />
      <FieldRow label="Vendor" value={val(`${prefix}_vendor`) ?? ''} onChange={v => edit(`${prefix}_vendor`, v)} />
      <FieldRow label="Amount" value={val(`${prefix}_amount`) ?? ''} onChange={v => edit(`${prefix}_amount`, v === '' ? null : parseFloat(v))} type="number" />
      <FieldRow label="PO" value={val(`${prefix}_po`) ?? ''} onChange={v => edit(`${prefix}_po`, v)} />
      <FieldRow label="Folder" value={val(`${prefix}_folder_output`) ?? ''} onChange={v => edit(`${prefix}_folder_output`, v)} />

      {/* Correctness flags */}
      <div className="mt-2 space-y-1">
        <span className="text-[10px] font-medium uppercase tracking-wider text-muted-foreground">Correctness</span>
        <div className="grid grid-cols-5 gap-1">
          {['doc_type', 'vendor', 'amount', 'po', 'folder'].map(f => {
            const field = `${prefix}_${f}_correct`;
            const v = val(field);
            return (
              <button
                key={f}
                className={`text-[9px] px-1.5 py-1 rounded border text-center transition-colors ${
                  v === true ? 'bg-emerald-500/15 border-emerald-400 text-emerald-700' :
                  v === false ? 'bg-red-500/15 border-red-400 text-red-700' :
                  'bg-muted/30 border-border text-muted-foreground'
                }`}
                onClick={() => edit(field, v === true ? false : v === false ? null : true)}
                title={`${f}: click to toggle`}
              >
                {f === 'doc_type' ? 'Type' : f === 'folder' ? 'Fldr' : f.charAt(0).toUpperCase() + f.slice(1)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Needs Review + Final Status */}
      <div className="grid grid-cols-2 gap-2 mt-2">
        <div>
          <label className="text-[10px] text-muted-foreground">Review</label>
          <Select value={val(`${prefix}_needs_review`) || ''} onValueChange={v => edit(`${prefix}_needs_review`, v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {NEEDS_REVIEW_OPTS.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <label className="text-[10px] text-muted-foreground">Status</label>
          <Select value={val(`${prefix}_final_status`) || ''} onValueChange={v => edit(`${prefix}_final_status`, v)}>
            <SelectTrigger className="h-7 text-xs"><SelectValue placeholder="—" /></SelectTrigger>
            <SelectContent>
              {FINAL_STATUS_OPTS.map(o => <SelectItem key={o} value={o}>{o}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>

      {/* Why Wrong Tags */}
      <div className="mt-2">
        <label className="text-[10px] text-muted-foreground">Why Wrong</label>
        <div className="flex flex-wrap gap-1 mt-1">
          {whyWrongTags.map(tag => {
            const active = (val(`${prefix}_why_wrong_tags`) || []).includes(tag);
            return (
              <button
                key={tag}
                className={`text-[9px] px-1.5 py-0.5 rounded-full border transition-colors ${
                  active ? 'bg-primary/15 border-primary/40 text-primary' : 'bg-muted/30 border-border text-muted-foreground'
                }`}
                onClick={() => toggleTag(tag)}
              >
                {tag}
              </button>
            );
          })}
        </div>
      </div>

      {/* Notes */}
      <Textarea
        className="text-xs h-10 mt-1"
        placeholder="Notes..."
        value={val(`${prefix}_notes`) || ''}
        onChange={e => edit(`${prefix}_notes`, e.target.value)}
      />
    </FieldSection>
  );
}


// ═══════════════════════════════════════════════════════════════
// RESULTS SUMMARY
// ═══════════════════════════════════════════════════════════════

function ResultsSummary({ runId, runName }) {
  const [metrics, setMetrics] = useState(null);
  const [breakdowns, setBreakdowns] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      setLoading(true);
      try {
        const { data } = await api.get(`${API}/runs/${runId}/metrics`);
        setMetrics(data.metrics);
        setBreakdowns(data.breakdowns);
      } catch { toast.error('Failed to load metrics'); }
      finally { setLoading(false); }
    };
    fetch();
  }, [runId]);

  const exportRun = async () => {
    try {
      const response = await api.get(`${API}/runs/${runId}/export`, { responseType: 'blob' });
      const url = window.URL.createObjectURL(new Blob([response.data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = `bakeoff_${runId}.xlsx`;
      a.click();
      window.URL.revokeObjectURL(url);
      toast.success('Export downloaded');
    } catch { toast.error('Export failed'); }
  };

  if (loading) return <p className="text-sm text-muted-foreground py-8 text-center">Loading metrics...</p>;
  if (!metrics) return <p className="text-sm text-muted-foreground py-8 text-center">No metrics available</p>;

  const gpi = metrics.gpi || {};
  const s9 = metrics.s9 || {};

  const kpiRows = [
    { label: 'Ingest Rate', gpi: gpi.ingest_rate, s9: s9.ingest_rate, unit: '%' },
    { label: 'Classification Accuracy', gpi: gpi.classification_accuracy, s9: s9.classification_accuracy, unit: '%' },
    { label: 'Vendor Accuracy', gpi: gpi.vendor_accuracy, s9: s9.vendor_accuracy, unit: '%' },
    { label: 'Amount Accuracy', gpi: gpi.amount_accuracy, s9: s9.amount_accuracy, unit: '%' },
    { label: 'PO Accuracy', gpi: gpi.po_accuracy, s9: s9.po_accuracy, unit: '%' },
    { label: 'Folder Accuracy', gpi: gpi.folder_accuracy, s9: s9.folder_accuracy, unit: '%' },
    { label: 'No-Touch Rate', gpi: gpi.no_touch_rate, s9: s9.no_touch_rate, unit: '%' },
    { label: 'Usable Output', gpi: gpi.usable_output_rate, s9: s9.usable_output_rate, unit: '%', highlight: true },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{runName || 'Results'}</h2>
          <p className="text-xs text-muted-foreground">{metrics.total} documents scored</p>
        </div>
        <Button variant="outline" size="sm" className="gap-1.5" onClick={exportRun} data-testid="export-btn">
          <Download className="w-4 h-4" /> Export Excel
        </Button>
      </div>

      {/* KPI Comparison Table */}
      <Card data-testid="kpi-comparison">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Side-by-Side Comparison</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <table className="w-full text-sm">
            <thead className="bg-muted/50">
              <tr>
                <th className="text-left px-4 py-2 font-medium">KPI</th>
                <th className="text-center px-4 py-2 font-medium text-emerald-600">GPI Hub</th>
                <th className="text-center px-4 py-2 font-medium text-orange-600">Square 9</th>
                <th className="text-center px-4 py-2 font-medium">Delta</th>
              </tr>
            </thead>
            <tbody>
              {kpiRows.map(({ label, gpi: g, s9: s, unit, highlight }) => {
                const delta = (g != null && s != null) ? (g - s).toFixed(1) : null;
                return (
                  <tr key={label} className={`border-b border-border/30 ${highlight ? 'bg-primary/5 font-semibold' : ''}`}>
                    <td className="px-4 py-2.5">{label}</td>
                    <td className="text-center px-4 py-2.5 font-mono">{g != null ? `${g}${unit}` : '—'}</td>
                    <td className="text-center px-4 py-2.5 font-mono">{s != null ? `${s}${unit}` : '—'}</td>
                    <td className="text-center px-4 py-2.5 font-mono">
                      {delta != null ? (
                        <span className={parseFloat(delta) > 0 ? 'text-emerald-600' : parseFloat(delta) < 0 ? 'text-red-600' : ''}>
                          {parseFloat(delta) > 0 ? '+' : ''}{delta}{unit}
                        </span>
                      ) : '—'}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </CardContent>
      </Card>

      {/* Breakdowns */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Why Wrong Distribution */}
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Why Wrong — GPI Hub</CardTitle></CardHeader>
          <CardContent>
            <TagDistribution data={breakdowns?.gpi_why_wrong || {}} color="emerald" />
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Why Wrong — Square 9</CardTitle></CardHeader>
          <CardContent>
            <TagDistribution data={breakdowns?.s9_why_wrong || {}} color="orange" />
          </CardContent>
        </Card>

        {/* By Doc Type */}
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Accuracy by Document Type</CardTitle></CardHeader>
          <CardContent>
            <BreakdownTable data={breakdowns?.by_doc_type || {}} type="doc_type" />
          </CardContent>
        </Card>

        {/* By Vendor */}
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-sm">Accuracy by Vendor</CardTitle></CardHeader>
          <CardContent>
            <BreakdownTable data={breakdowns?.by_vendor || {}} type="vendor" />
          </CardContent>
        </Card>
      </div>

      {/* Key Insights */}
      {breakdowns?.insights?.length > 0 && (
        <Card data-testid="key-insights">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm flex items-center gap-2"><AlertTriangle className="w-4 h-4 text-amber-500" /> Key Insights</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="space-y-1.5">
              {breakdowns.insights.map((insight, i) => (
                <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                  <ChevronRight className="w-3.5 h-3.5 mt-0.5 shrink-0 text-primary" />
                  {insight}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {/* Folder Alignment Report */}
      <FolderAlignment runId={runId} />

      {/* Auto-Post Readiness */}
      <AutoPostReadiness runId={runId} />
    </div>
  );
}

function AutoPostReadiness({ runId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      try {
        const { data: d } = await api.get(`${API}/runs/${runId}/auto-post-readiness`);
        setData(d);
      } catch { /* endpoint may not have AP invoices */ }
      finally { setLoading(false); }
    };
    fetch();
  }, [runId]);

  if (loading || !data || data.summary.ap_invoices === 0) return null;

  const s = data.summary;
  const rates = data.criteria_pass_rates;
  const blockers = data.blockers_distribution;

  const readyPct = s.auto_post_ready_pct;
  const barColor = readyPct >= 70 ? 'bg-emerald-500' : readyPct >= 40 ? 'bg-amber-500' : 'bg-red-500';

  return (
    <Card data-testid="auto-post-readiness">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Play className="w-4 h-4 text-emerald-500" /> Auto-Post Readiness — AP Invoices
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          If auto-posting were enabled today, how many AP invoices could auto-create a Purchase Invoice in BC?
        </p>
      </CardHeader>
      <CardContent>
        {/* Hero metric */}
        <div className="flex items-center gap-4 mb-4">
          <div className="text-3xl font-bold text-emerald-500">{s.auto_post_ready}</div>
          <div>
            <div className="text-sm font-medium">of {s.ap_invoices} AP invoices ready ({readyPct}%)</div>
            <div className="w-48 h-2 bg-muted/50 rounded-full overflow-hidden mt-1">
              <div className={`h-full rounded-full ${barColor}`} style={{ width: `${readyPct}%` }} />
            </div>
          </div>
        </div>

        {/* Tiers */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="bg-emerald-500/10 rounded-lg p-2.5 text-center">
            <div className="text-lg font-bold text-emerald-500">{s.auto_post_ready}</div>
            <div className="text-[10px] text-muted-foreground">Ready Now</div>
          </div>
          <div className="bg-amber-500/10 rounded-lg p-2.5 text-center">
            <div className="text-lg font-bold text-amber-500">{s.one_blocker_away}</div>
            <div className="text-[10px] text-muted-foreground">1 Blocker Away</div>
          </div>
          <div className="bg-red-500/10 rounded-lg p-2.5 text-center">
            <div className="text-lg font-bold text-red-400">{s.multiple_blockers}</div>
            <div className="text-[10px] text-muted-foreground">Multiple Blockers</div>
          </div>
        </div>

        {/* Criteria pass rates */}
        <div className="space-y-1.5 mb-4">
          <p className="text-xs font-medium text-muted-foreground mb-1">Criteria Pass Rates</p>
          {Object.entries(rates).map(([key, pct]) => (
            <div key={key} className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground w-32 truncate">{key.replace(/_/g, ' ')}</span>
              <div className="flex-1 h-3 bg-muted/50 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${pct >= 80 ? 'bg-emerald-500/70' : pct >= 50 ? 'bg-amber-500/70' : 'bg-red-400/70'}`}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="text-xs font-mono w-12 text-right">{pct}%</span>
            </div>
          ))}
        </div>

        {/* Blockers */}
        {Object.keys(blockers).length > 0 && (
          <div>
            <p className="text-xs font-medium text-muted-foreground mb-1">Top Blockers</p>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(blockers).slice(0, 8).map(([tag, cnt]) => (
                <span key={tag} className="text-[10px] bg-red-500/10 text-red-400 px-2 py-0.5 rounded-full">
                  {tag.replace(/_/g, ' ')} ({cnt})
                </span>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function FolderAlignment({ runId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetch = async () => {
      try {
        const { data: d } = await api.get(`${API}/runs/${runId}/folder-alignment`);
        setData(d);
      } catch { /* no data yet */ }
      finally { setLoading(false); }
    };
    fetch();
  }, [runId]);

  if (loading || !data) return null;

  const { summary, alignment, gpi_only_folders } = data;

  return (
    <Card data-testid="folder-alignment">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <FolderSearch className="w-4 h-4 text-blue-500" /> Folder Alignment — S9 vs GPI Hub
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {summary.matched_to_gpi}/{summary.total_s9_folders} S9 folders matched to GPI Hub
          {summary.gaps > 0 && <span className="text-amber-500 ml-1">({summary.gaps} gaps)</span>}
        </p>
      </CardHeader>
      <CardContent>
        <ScrollArea className="h-56">
          <table className="w-full text-xs">
            <thead><tr className="text-muted-foreground border-b">
              <th className="text-left py-1.5 font-medium">S9 Folder</th>
              <th className="text-center py-1.5 font-medium w-12">Docs</th>
              <th className="text-center py-1.5 font-medium w-16">Match</th>
              <th className="text-left py-1.5 font-medium">GPI Routes To</th>
              <th className="text-center py-1.5 font-medium w-16 text-emerald-600">GPI OK</th>
              <th className="text-center py-1.5 font-medium w-16 text-orange-600">S9 OK</th>
            </tr></thead>
            <tbody>
              {alignment.map((row) => (
                <tr key={row.s9_folder} className="border-b border-border/20">
                  <td className="py-1 truncate max-w-[200px]" title={row.s9_folder}>{row.s9_folder}</td>
                  <td className="text-center py-1 font-mono">{row.doc_count}</td>
                  <td className="text-center py-1">
                    {row.gpi_match === 'exact' && <span className="text-emerald-600 font-medium">Exact</span>}
                    {row.gpi_match === 'partial' && <span className="text-blue-500 font-medium">Partial</span>}
                    {row.gpi_match === 'fuzzy' && <span className="text-amber-500 font-medium">Fuzzy</span>}
                    {row.gpi_match === 'none' && <span className="text-red-500 font-medium">Gap</span>}
                  </td>
                  <td className="py-1 truncate max-w-[200px]" title={Object.keys(row.gpi_routing_destinations).join(', ')}>
                    {Object.entries(row.gpi_routing_destinations).map(([folder, cnt]) => (
                      <span key={folder} className="inline-block mr-1">
                        {folder} <span className="text-muted-foreground">({cnt})</span>
                      </span>
                    ))}
                    {Object.keys(row.gpi_routing_destinations).length === 0 && <span className="text-muted-foreground">--</span>}
                  </td>
                  <td className="text-center py-1 font-mono">{row.gpi_folder_correct}/{row.doc_count}</td>
                  <td className="text-center py-1 font-mono">{row.s9_folder_correct}/{row.doc_count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </ScrollArea>

        {gpi_only_folders.length > 0 && (
          <div className="mt-3 pt-3 border-t">
            <p className="text-xs text-muted-foreground mb-1 font-medium">GPI Hub folders not seen in S9 data:</p>
            <div className="flex flex-wrap gap-1">
              {gpi_only_folders.slice(0, 15).map(f => (
                <span key={f} className="text-[10px] bg-muted/60 px-1.5 py-0.5 rounded">{f}</span>
              ))}
              {gpi_only_folders.length > 15 && (
                <span className="text-[10px] text-muted-foreground">+{gpi_only_folders.length - 15} more</span>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TagDistribution({ data, color }) {
  const entries = Object.entries(data);
  if (entries.length === 0) return <p className="text-xs text-muted-foreground">No failure tags recorded</p>;
  const max = Math.max(...entries.map(([_, v]) => v));
  return (
    <div className="space-y-1.5">
      {entries.map(([tag, count]) => (
        <div key={tag} className="flex items-center gap-2">
          <span className="text-xs text-muted-foreground w-40 truncate shrink-0">{tag}</span>
          <div className="flex-1 h-4 bg-muted/50 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${color === 'emerald' ? 'bg-emerald-500/60' : 'bg-orange-500/60'}`}
              style={{ width: `${(count / max) * 100}%` }}
            />
          </div>
          <span className="text-xs font-mono w-6 text-right">{count}</span>
        </div>
      ))}
    </div>
  );
}

function BreakdownTable({ data, type }) {
  const entries = Object.entries(data).sort((a, b) => b[1].total - a[1].total);
  if (entries.length === 0) return <p className="text-xs text-muted-foreground">No data</p>;
  const correctField = type === 'vendor' ? 'gpi_vendor_correct' : 'gpi_correct';
  const s9Field = type === 'vendor' ? 's9_vendor_correct' : 's9_correct';
  return (
    <ScrollArea className="h-44">
      <table className="w-full text-xs">
        <thead><tr className="text-muted-foreground">
          <th className="text-left py-1 font-medium">{type === 'vendor' ? 'Vendor' : 'Doc Type'}</th>
          <th className="text-center py-1 font-medium">Total</th>
          <th className="text-center py-1 font-medium text-emerald-600">GPI</th>
          <th className="text-center py-1 font-medium text-orange-600">S9</th>
        </tr></thead>
        <tbody>
          {entries.slice(0, 20).map(([name, d]) => (
            <tr key={name} className="border-b border-border/20">
              <td className="py-1 truncate max-w-[150px]">{name}</td>
              <td className="text-center py-1">{d.total}</td>
              <td className="text-center py-1 font-mono">{d[correctField] ?? 0}</td>
              <td className="text-center py-1 font-mono">{d[s9Field] ?? 0}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ScrollArea>
  );
}
