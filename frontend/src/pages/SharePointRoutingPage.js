import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { toast } from 'sonner';
import {
  FolderTree, FolderOpen, ChevronRight, ChevronDown, Plus, Trash2,
  TestTube, Users, RefreshCw, ArrowRight, Check
} from 'lucide-react';
import api from '../lib/api';

function FolderNode({ node, depth, expanded, toggle }) {
  const open = expanded.has(node.key);
  const kids = node.children || [];
  const pad = depth * 20 + 8;
  return (
    <div>
      <div
        className="flex items-center gap-2 py-1.5 px-2 rounded-md hover:bg-accent/50 cursor-pointer"
        style={{ paddingLeft: pad + 'px' }}
        onClick={() => kids.length > 0 && toggle(node.key)}
        data-testid={'folder-' + node.key}
      >
        {kids.length > 0 ? (
          open ? <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" /> : <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
        ) : <span className="w-3.5 shrink-0" />}
        <FolderOpen className={'w-4 h-4 shrink-0 ' + (depth === 0 ? 'text-amber-500' : depth === 1 ? 'text-blue-500' : 'text-muted-foreground')} />
        <span className="text-sm font-medium truncate">{node.path}</span>
        {node.dynamic && <Badge variant="outline" className="text-[10px] px-1.5 py-0 ml-1">{node.dynamic === 'by_year' ? 'By Year' : 'By Order'}</Badge>}
        {node.doc_types && node.doc_types.length > 0 && (
          <div className="ml-auto flex gap-1">
            {node.doc_types.slice(0, 2).map(t => <Badge key={t} variant="secondary" className="text-[10px] px-1.5 py-0">{t}</Badge>)}
            {node.doc_types.length > 2 && <Badge variant="secondary" className="text-[10px] px-1.5 py-0">+{node.doc_types.length - 2}</Badge>}
          </div>
        )}
      </div>
      {open && kids.map(c => <FolderNode key={c.key} node={c} depth={depth + 1} expanded={expanded} toggle={toggle} />)}
    </div>
  );
}

export default function SharePointRoutingPage() {
  const [tab, setTab] = useState('tree');
  const [tree, setTree] = useState([]);
  const [rules, setRules] = useState([]);
  const [mappings, setMappings] = useState([]);
  const [processors, setProcessors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(new Set());
  const [testForm, setTestForm] = useState({ doc_type: 'AP_Invoice', vendor: '', order_number: '', is_international: false, description: '', is_approved: false, has_freight_issue: false });
  const [testResult, setTestResult] = useState(null);
  const [testLoading, setTestLoading] = useState(false);
  const [dlgMapping, setDlgMapping] = useState(false);
  const [newMap, setNewMap] = useState({ vendor_pattern: '', folder_target: '', vendor_category: 'general' });
  const [dlgProc, setDlgProc] = useState(false);
  const [newProc, setNewProc] = useState({ folder_path: '', processor_name: '' });

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [t, m, p] = await Promise.all([
        api.get('/sharepoint-routing/folder-tree'),
        api.get('/sharepoint-routing/vendor-mappings'),
        api.get('/sharepoint-routing/processor-assignments'),
      ]);
      setTree(t.data.tree || []);
      setRules(t.data.rules || []);
      setMappings(m.data.mappings || []);
      setProcessors(p.data.assignments || []);
      setExpanded(new Set((t.data.tree || []).map(n => n.key)));
    } catch (e) { toast.error('Failed to load data'); }
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const toggle = (key) => {
    setExpanded(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  const expandAll = () => {
    const all = new Set();
    const walk = (nodes) => { for (const n of nodes) { all.add(n.key); if (n.children) walk(n.children); } };
    walk(tree);
    setExpanded(all);
  };

  const runTest = async () => {
    setTestLoading(true);
    try {
      const r = await api.post('/sharepoint-routing/suggest-folder', testForm);
      setTestResult(r.data);
    } catch (e) { toast.error('Test failed'); }
    setTestLoading(false);
  };

  const addMapping = async () => {
    if (!newMap.vendor_pattern || !newMap.folder_target) { toast.error('Fill all fields'); return; }
    try {
      await api.post('/sharepoint-routing/vendor-mappings', newMap);
      toast.success('Added'); setDlgMapping(false); setNewMap({ vendor_pattern: '', folder_target: '', vendor_category: 'general' }); load();
    } catch (e) { toast.error(e.response?.data?.detail || 'Failed'); }
  };

  const delMapping = async (p) => {
    try { await api.delete('/sharepoint-routing/vendor-mappings/' + encodeURIComponent(p)); toast.success('Deleted'); load(); } catch (e) { toast.error('Failed'); }
  };

  const addProc = async () => {
    if (!newProc.folder_path || !newProc.processor_name) { toast.error('Fill all fields'); return; }
    try {
      await api.post('/sharepoint-routing/processor-assignments', newProc);
      toast.success('Added'); setDlgProc(false); setNewProc({ folder_path: '', processor_name: '' }); load();
    } catch (e) { toast.error('Failed'); }
  };

  const delProc = async (fp, pn) => {
    try { await api.delete('/sharepoint-routing/processor-assignments?folder_path=' + encodeURIComponent(fp) + '&processor_name=' + encodeURIComponent(pn)); toast.success('Removed'); load(); } catch (e) { toast.error('Failed'); }
  };

  const reseed = async () => {
    try { await api.post('/sharepoint-routing/seed-defaults'); toast.success('Defaults re-seeded'); load(); } catch (e) { toast.error('Failed'); }
  };

  if (loading) return <div className="flex items-center justify-center h-64"><RefreshCw className="w-6 h-6 animate-spin text-muted-foreground" /></div>;

  const docTypes = ['AP_Invoice', 'Sales_Order', 'Shipping_Document', 'Freight_Document', 'Order_Confirmation', 'Remittance', 'Return_Request', 'Quality_Issue', 'Inspection_Form', 'Unknown_Document'];

  return (
    <div className="space-y-6" data-testid="sharepoint-routing-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" data-testid="page-title">SharePoint Folder Routing</h1>
          <p className="text-sm text-muted-foreground mt-1">Manage how documents are routed to SharePoint folders.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} data-testid="refresh-btn"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Refresh</Button>
          <Button variant="outline" size="sm" onClick={reseed} data-testid="reseed-btn"><RefreshCw className="w-3.5 h-3.5 mr-1.5" />Re-seed</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[['Folder Rules', rules.length], ['Vendor Mappings', mappings.length], ['Processors', processors.length], ['Top-Level', tree.length]].map(([label, val]) => (
          <Card key={label}><CardContent className="pt-4 pb-3 px-4"><div className="text-2xl font-bold">{val}</div><p className="text-xs text-muted-foreground">{label}</p></CardContent></Card>
        ))}
      </div>

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="tree"><FolderTree className="w-3.5 h-3.5 mr-1.5" />Folder Tree</TabsTrigger>
          <TabsTrigger value="vendors"><Users className="w-3.5 h-3.5 mr-1.5" />Vendor Mappings</TabsTrigger>
          <TabsTrigger value="procs"><Users className="w-3.5 h-3.5 mr-1.5" />Processors</TabsTrigger>
          <TabsTrigger value="test"><TestTube className="w-3.5 h-3.5 mr-1.5" />Test Routing</TabsTrigger>
        </TabsList>

        <TabsContent value="tree">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div><CardTitle className="text-base">SharePoint Folder Structure</CardTitle><CardDescription>Based on Temp Folder Structure 9.15.25</CardDescription></div>
                <div className="flex gap-2">
                  <Button variant="ghost" size="sm" onClick={expandAll}>Expand All</Button>
                  <Button variant="ghost" size="sm" onClick={() => setExpanded(new Set())}>Collapse All</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="border rounded-lg p-2 bg-card max-h-[600px] overflow-y-auto" data-testid="folder-tree">
                {tree.map(n => <FolderNode key={n.key} node={n} depth={0} expanded={expanded} toggle={toggle} />)}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="vendors">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div><CardTitle className="text-base">Vendor-to-Folder Mappings</CardTitle><CardDescription>Map vendor names to folder targets</CardDescription></div>
                <Button size="sm" onClick={() => setDlgMapping(true)} data-testid="add-mapping-btn"><Plus className="w-3.5 h-3.5 mr-1.5" />Add</Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="border rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead><tr className="border-b bg-muted/50"><th className="text-left px-4 py-2 font-medium">Pattern</th><th className="text-left px-4 py-2 font-medium">Target</th><th className="text-left px-4 py-2 font-medium">Category</th><th className="w-16 px-4 py-2"></th></tr></thead>
                  <tbody>
                    {mappings.map((m, i) => (
                      <tr key={i} className="border-b last:border-0 hover:bg-accent/30">
                        <td className="px-4 py-2 font-mono text-xs">{m.vendor_pattern}</td>
                        <td className="px-4 py-2"><Badge variant="outline">{m.folder_target}</Badge></td>
                        <td className="px-4 py-2"><Badge variant={m.vendor_category === 'freight' ? 'destructive' : 'secondary'} className="text-[10px]">{m.vendor_category}</Badge></td>
                        <td className="px-4 py-2"><Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => delMapping(m.vendor_pattern)}><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="procs">
          <Card>
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <div><CardTitle className="text-base">Processor Assignments</CardTitle><CardDescription>Who processes documents in which folders</CardDescription></div>
                <Button size="sm" onClick={() => setDlgProc(true)} data-testid="add-processor-btn"><Plus className="w-3.5 h-3.5 mr-1.5" />Add</Button>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                {processors.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-3 border rounded-lg bg-card">
                    <div>
                      <div className="flex items-center gap-2"><Users className="w-4 h-4 text-primary" /><span className="font-medium text-sm">{p.processor_name}</span></div>
                      <p className="text-xs text-muted-foreground mt-1 truncate max-w-[200px]">{p.folder_path}</p>
                    </div>
                    <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => delProc(p.folder_path, p.processor_name)}><Trash2 className="w-3.5 h-3.5 text-destructive" /></Button>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="test">
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <Card>
              <CardHeader className="pb-3"><CardTitle className="text-base">Test Document Routing</CardTitle><CardDescription>Simulate where a document would be filed</CardDescription></CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Document Type</label>
                  <Select value={testForm.doc_type} onValueChange={v => setTestForm(p => ({ ...p, doc_type: v }))}>
                    <SelectTrigger data-testid="test-doc-type"><SelectValue /></SelectTrigger>
                    <SelectContent>{docTypes.map(t => <SelectItem key={t} value={t}>{t}</SelectItem>)}</SelectContent>
                  </Select>
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Vendor</label>
                  <Input placeholder="e.g., Ball, Canpack..." value={testForm.vendor} onChange={e => setTestForm(p => ({ ...p, vendor: e.target.value }))} data-testid="test-vendor" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Order Number</label>
                  <Input placeholder="e.g., PO-12345" value={testForm.order_number} onChange={e => setTestForm(p => ({ ...p, order_number: e.target.value }))} data-testid="test-order" />
                </div>
                <div className="space-y-2">
                  <label className="text-xs font-medium text-muted-foreground">Description</label>
                  <Input placeholder="e.g., dunnage, tooling..." value={testForm.description} onChange={e => setTestForm(p => ({ ...p, description: e.target.value }))} data-testid="test-description" />
                </div>
                <div className="flex flex-wrap gap-4">
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={testForm.is_international} onChange={e => setTestForm(p => ({ ...p, is_international: e.target.checked }))} />International</label>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={testForm.is_approved} onChange={e => setTestForm(p => ({ ...p, is_approved: e.target.checked }))} />Approved</label>
                  <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={testForm.has_freight_issue} onChange={e => setTestForm(p => ({ ...p, has_freight_issue: e.target.checked }))} />Freight Issue</label>
                </div>
                <Button onClick={runTest} disabled={testLoading} className="w-full" data-testid="test-routing-btn">
                  {testLoading ? <RefreshCw className="w-4 h-4 mr-2 animate-spin" /> : <TestTube className="w-4 h-4 mr-2" />}Test Routing
                </Button>
              </CardContent>
            </Card>
            <Card>
              <CardHeader className="pb-3"><CardTitle className="text-base">Result</CardTitle></CardHeader>
              <CardContent>
                {testResult ? (
                  <div className="space-y-4">
                    <div className="flex items-center gap-3 p-4 bg-primary/5 border border-primary/20 rounded-lg">
                      <FolderOpen className="w-8 h-8 text-primary shrink-0" />
                      <div>
                        <p className="text-xs text-muted-foreground mb-0.5">Suggested Folder</p>
                        <p className="font-mono text-sm font-bold" data-testid="result-folder">{testResult.suggested_folder}</p>
                      </div>
                    </div>
                    <div className="p-3 bg-muted/50 rounded-lg">
                      <p className="text-xs text-muted-foreground mb-1">Reason</p>
                      <p className="text-sm" data-testid="result-reason">{testResult.reason}</p>
                    </div>
                    <div className="p-3 bg-muted/50 rounded-lg">
                      <p className="text-xs text-muted-foreground mb-2">Path</p>
                      <div className="flex items-center flex-wrap gap-1">
                        {testResult.suggested_folder.split('/').map((part, i, arr) => (
                          <span key={i} className="flex items-center gap-1">
                            <Badge variant={i === arr.length - 1 ? 'default' : 'outline'} className="text-xs">{part}</Badge>
                            {i < arr.length - 1 && <ArrowRight className="w-3 h-3 text-muted-foreground" />}
                          </span>
                        ))}
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="flex flex-col items-center justify-center h-48 text-muted-foreground">
                    <TestTube className="w-8 h-8 mb-2" /><p className="text-sm">Run a test to see the result</p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={dlgMapping} onOpenChange={setDlgMapping}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Vendor Mapping</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2"><label className="text-xs font-medium">Pattern (lowercase)</label><Input placeholder="e.g., crown cork" value={newMap.vendor_pattern} onChange={e => setNewMap(p => ({ ...p, vendor_pattern: e.target.value.toLowerCase() }))} /></div>
            <div className="space-y-2"><label className="text-xs font-medium">Folder Target</label><Input placeholder="e.g., Ball, Canpack" value={newMap.folder_target} onChange={e => setNewMap(p => ({ ...p, folder_target: e.target.value }))} /></div>
            <div className="space-y-2">
              <label className="text-xs font-medium">Category</label>
              <Select value={newMap.vendor_category} onValueChange={v => setNewMap(p => ({ ...p, vendor_category: v }))}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent><SelectItem value="general">General</SelectItem><SelectItem value="freight">Freight</SelectItem><SelectItem value="dunnage">Dunnage</SelectItem></SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter><Button variant="ghost" onClick={() => setDlgMapping(false)}>Cancel</Button><Button onClick={addMapping}><Check className="w-3.5 h-3.5 mr-1.5" />Save</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={dlgProc} onOpenChange={setDlgProc}>
        <DialogContent>
          <DialogHeader><DialogTitle>Add Processor Assignment</DialogTitle></DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2"><label className="text-xs font-medium">Folder Path</label><Input placeholder="e.g., S&H Invoices Approved Documents/Andy to Process" value={newProc.folder_path} onChange={e => setNewProc(p => ({ ...p, folder_path: e.target.value }))} /></div>
            <div className="space-y-2"><label className="text-xs font-medium">Processor Name</label><Input placeholder="e.g., Andy, Ellie" value={newProc.processor_name} onChange={e => setNewProc(p => ({ ...p, processor_name: e.target.value }))} /></div>
          </div>
          <DialogFooter><Button variant="ghost" onClick={() => setDlgProc(false)}>Cancel</Button><Button onClick={addProc}><Check className="w-3.5 h-3.5 mr-1.5" />Save</Button></DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
