import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Loader2, RefreshCw, AlertTriangle, ChevronRight, Warehouse, Truck, ClipboardList, Package, FileText, Clock, User, UserX, Activity, History, Bookmark, BookmarkCheck, Save, Star, Trash2, X, CheckSquare, Square, Users, Calendar, ShieldCheck, ArrowUpCircle } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

const ESC_BADGE = {
  on_track: { variant: 'outline', label: 'On Track', cls: '' },
  due_soon: { variant: 'secondary', label: 'Due Soon', cls: 'bg-amber-500 text-white' },
  overdue: { variant: 'destructive', label: 'Overdue', cls: '' },
  escalated: { variant: 'destructive', label: 'Escalated', cls: 'bg-red-700' },
};
const ASGN_BADGE = {
  assigned: { variant: 'secondary', label: 'Assigned', cls: 'bg-blue-500 text-white' },
  in_progress: { variant: 'secondary', label: 'In Progress', cls: 'bg-indigo-500 text-white' },
  waiting: { variant: 'secondary', label: 'Waiting', cls: 'bg-amber-500 text-white' },
  completed: { variant: 'default', label: 'Completed', cls: 'bg-green-600 text-white' },
  unassigned: { variant: 'outline', label: 'Unassigned', cls: 'border-dashed text-muted-foreground' },
};
function priorityColor(s) { if (s >= 40) return 'text-red-600 bg-red-50 dark:bg-red-900/20 border-red-200'; if (s >= 20) return 'text-amber-600 bg-amber-50 dark:bg-amber-900/20 border-amber-200'; return 'text-blue-600 bg-blue-50 dark:bg-blue-900/20 border-blue-200'; }
function priorityBadge(s) { if (s >= 40) return 'destructive'; if (s >= 20) return 'secondary'; return 'outline'; }
function timeAgo(iso) { if (!iso) return ''; const d = Date.now() - new Date(iso).getTime(); const m = Math.floor(d/60000); if (m<1) return 'just now'; if (m<60) return `${m}m ago`; const h = Math.floor(m/60); if (h<24) return `${h}h ago`; return `${Math.floor(h/24)}d ago`; }

export default function OperationsQueuePage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState('all');
  const [filterEsc, setFilterEsc] = useState('all');
  const [filterOwner, setFilterOwner] = useState('');
  const [filterAsgn, setFilterAsgn] = useState('all');
  const [sortBy, setSortBy] = useState('priority');
  const [search, setSearch] = useState('');
  const [selectedItem, setSelectedItem] = useState(null);

  // Selection & bulk
  const [selected, setSelected] = useState(new Set());
  const [bulkAction, setBulkAction] = useState(null);
  const [bulkPayload, setBulkPayload] = useState({});
  const [bulkRunning, setBulkRunning] = useState(false);
  const [bulkResult, setBulkResult] = useState(null);
  const [bulkTemplates, setBulkTemplates] = useState([]);

  // Saved views
  const [savedViews, setSavedViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveViewName, setSaveViewName] = useState('');
  const [saveViewNotes, setSaveViewNotes] = useState('');
  const [saveAsDefault, setSaveAsDefault] = useState(false);
  const [savingView, setSavingView] = useState(false);
  const [showViewsPanel, setShowViewsPanel] = useState(false);
  const defaultLoaded = useRef(false);

  const getCurrentFilters = () => ({ entity_type: filterType !== 'all' ? filterType : '', escalation: filterEsc !== 'all' ? filterEsc : '', assigned_to: filterOwner.trim(), assignment_status: filterAsgn !== 'all' ? filterAsgn : '', unassigned_only: filterAsgn === 'unassigned' ? 'true' : '', search: search.trim() });
  const getCurrentSort = () => ({ field: sortBy === 'activity' ? 'latest_activity' : 'priority_score', direction: 'desc' });

  const applyView = (view) => {
    const f = view.filters || {};
    setFilterType(f.entity_type || 'all'); setFilterEsc(f.escalation || 'all'); setFilterOwner(f.assigned_to || '');
    setFilterAsgn(f.unassigned_only === 'true' ? 'unassigned' : (f.assignment_status || 'all'));
    setSearch(f.search || ''); setSortBy((view.sort || {}).field === 'latest_activity' ? 'activity' : 'priority');
    setActiveViewId(view.saved_view_id); setShowViewsPanel(false);
  };

  const loadViews = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views?view_type=operations_queue`);
      if (res.ok) { const d = await res.json(); setSavedViews(d.entries || []); if (!defaultLoaded.current) { defaultLoaded.current = true; const def = (d.entries || []).find(v => v.is_default); if (def) applyView(def); } }
    } catch {}
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200', offset: '0' });
      if (filterType !== 'all') params.set('entity_type', filterType);
      if (filterEsc !== 'all') params.set('escalation', filterEsc);
      if (filterAsgn === 'unassigned') params.set('unassigned_only', 'true');
      else if (filterAsgn !== 'all') params.set('assignment_status', filterAsgn);
      if (filterOwner.trim()) params.set('assigned_to', filterOwner.trim());
      if (sortBy === 'activity') params.set('sort_by', 'latest_activity');
      const res = await fetch(`${API}/api/inventory-ledger/operations-queue?${params}`);
      if (res.ok) {
        const d = await res.json();
        setItems(d.items || []); setTotal(d.total || 0);
        setCounts({ highPriority: d.high_priority_count||0, dueSoon: d.due_soon_count||0, overdue: d.overdue_count||0, escalated: d.escalated_count||0, unassigned: d.unassigned_count||0, inProgress: d.in_progress_count||0, waiting: d.waiting_count||0, activityToday: d.recent_activity_today||0, stale7d: d.no_recent_activity_7d||0, savedViewsCount: d.saved_views_count||0, defaultViewName: d.default_view_name||'' });
      }
    } catch { toast.error('Failed to load queue'); }
    finally { setLoading(false); }
  }, [filterType, filterEsc, filterAsgn, filterOwner, sortBy]);

  useEffect(() => { loadViews(); }, [loadViews]);
  useEffect(() => { load(); }, [load]);

  // Saved views CRUD
  const saveView = async () => { if (!saveViewName.trim()) return; setSavingView(true); try { const res = await fetch(`${API}/api/inventory-ledger/saved-views`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ view_type: 'operations_queue', name: saveViewName.trim(), is_default: saveAsDefault, filters: getCurrentFilters(), sort: getCurrentSort(), notes: saveViewNotes.trim() }) }); if (res.ok) { const d = await res.json(); toast.success(`View "${d.name}" saved`); setShowSaveDialog(false); setActiveViewId(d.saved_view_id); loadViews(); } } catch {} finally { setSavingView(false); } };
  const toggleDefault = async (v) => { try { await fetch(`${API}/api/inventory-ledger/saved-views/${v.saved_view_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_default: !v.is_default }) }); toast.success(v.is_default ? 'Default removed' : `"${v.name}" set as default`); loadViews(); load(); } catch {} };
  const deleteView = async (v) => { try { await fetch(`${API}/api/inventory-ledger/saved-views/${v.saved_view_id}`, { method: 'DELETE' }); toast.success(`Deleted "${v.name}"`); if (activeViewId === v.saved_view_id) setActiveViewId(null); loadViews(); load(); } catch {} };
  const overwriteView = async (v) => { try { await fetch(`${API}/api/inventory-ledger/saved-views/${v.saved_view_id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ filters: getCurrentFilters(), sort: getCurrentSort() }) }); toast.success(`Updated "${v.name}"`); loadViews(); } catch {} };

  // Selection helpers
  const filtered = search.trim() ? items.filter(i => i.entity_id.toLowerCase().includes(search.toLowerCase()) || (i.current_owner||'').toLowerCase().includes(search.toLowerCase()) || i.action_required.some(a => a.toLowerCase().includes(search.toLowerCase()))) : items;
  const toggleSelect = (key) => setSelected(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  const toggleSelectAll = () => { if (selected.size === filtered.length) { setSelected(new Set()); } else { setSelected(new Set(filtered.map(i => `${i.entity_type}::${i.entity_id}`))); } };
  const selectedItems = filtered.filter(i => selected.has(`${i.entity_type}::${i.entity_id}`));
  const selectedSoIds = selectedItems.filter(i => i.entity_type === 'sales_order').map(i => i.entity_id);
  const selectedPoIds = selectedItems.filter(i => i.entity_type === 'po_draft').map(i => i.entity_id);

  // Bulk action execution
  const runBulkAction = async () => {
    setBulkRunning(true); setBulkResult(null);
    try {
      const allResults = [];
      // Run for each entity type that has selected items
      for (const [eType, ids] of [['sales_order', selectedSoIds], ['po_draft', selectedPoIds]]) {
        if (ids.length === 0) continue;
        const res = await fetch(`${API}/api/inventory-ledger/operations-queue/bulk-action`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ entity_type: eType, entity_ids: ids, action: bulkAction, payload: bulkPayload }),
        });
        if (res.ok) { const d = await res.json(); allResults.push(...(d.results || [])); }
        else { ids.forEach(id => allResults.push({ entity_id: id, status: 'failed', message: 'Request failed' })); }
      }
      const ok = allResults.filter(r => r.status === 'success').length;
      const fail = allResults.filter(r => r.status === 'failed').length;
      setBulkResult({ results: allResults, succeeded: ok, failed: fail });
      if (ok > 0) toast.success(`${ok} item(s) updated successfully`);
      if (fail > 0) toast.error(`${fail} item(s) failed`);
      if (fail === 0) setSelected(new Set());
      setBulkAction(null); setBulkPayload({});
      load();
    } catch { toast.error('Bulk action failed'); }
    finally { setBulkRunning(false); }
  };

  const activeView = savedViews.find(v => v.saved_view_id === activeViewId);

  const loadBulkTemplates = async () => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/templates?is_active=true`);
      if (res.ok) { const d = await res.json(); setBulkTemplates(d.entries || []); }
    } catch {}
  };

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5" data-testid="operations-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }} data-testid="ops-queue-title">Operations Queue</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-sm text-muted-foreground">Items requiring operational attention</p>
            {activeView && <Badge variant="secondary" className="text-[9px] gap-1" data-testid="active-view-badge"><Bookmark className="w-3 h-3" />{activeView.name}{activeView.is_default && <Star className="w-2.5 h-2.5 fill-amber-400 text-amber-400" />}</Badge>}
          </div>
        </div>
        <div className="flex gap-2">
          {/* Views button */}
          <div className="relative">
            <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={() => setShowViewsPanel(!showViewsPanel)} data-testid="saved-views-btn">
              <Bookmark className="w-3.5 h-3.5" /> Views {savedViews.length > 0 && <Badge variant="secondary" className="text-[8px] h-4 px-1">{savedViews.length}</Badge>}
            </Button>
            {showViewsPanel && (
              <div className="absolute right-0 top-10 z-50 bg-background border border-border rounded-lg shadow-xl w-72 p-3 space-y-2" data-testid="saved-views-panel">
                <div className="flex items-center justify-between"><p className="text-xs font-bold">Saved Views</p><Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => setShowViewsPanel(false)}><X className="w-3 h-3" /></Button></div>
                {savedViews.length === 0 ? <p className="text-[10px] text-muted-foreground text-center py-3 italic">No saved views yet</p> : (
                  <div className="space-y-1 max-h-[240px] overflow-y-auto" data-testid="saved-views-list">
                    {savedViews.map(v => (
                      <div key={v.saved_view_id} className={`flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/40 group ${activeViewId === v.saved_view_id ? 'bg-muted/50 ring-1 ring-primary/20' : ''}`} data-testid={`saved-view-${v.saved_view_id}`}>
                        <button className="flex-1 text-left min-w-0" onClick={() => applyView(v)} data-testid={`apply-view-${v.saved_view_id}`}>
                          <div className="flex items-center gap-1"><span className="text-[10px] font-medium truncate">{v.name}</span>{v.is_default && <Star className="w-2.5 h-2.5 fill-amber-400 text-amber-400 shrink-0" />}</div>
                          {v.notes && <p className="text-[8px] text-muted-foreground truncate">{v.notes}</p>}
                        </button>
                        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 shrink-0">
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={e => { e.stopPropagation(); toggleDefault(v); }} data-testid={`default-view-${v.saved_view_id}`}><Star className={`w-3 h-3 ${v.is_default ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground'}`} /></Button>
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={e => { e.stopPropagation(); overwriteView(v); }} data-testid={`overwrite-view-${v.saved_view_id}`}><Save className="w-3 h-3 text-muted-foreground" /></Button>
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0 text-red-500" onClick={e => { e.stopPropagation(); deleteView(v); }} data-testid={`delete-view-${v.saved_view_id}`}><Trash2 className="w-3 h-3" /></Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <Button size="sm" className="h-7 text-[10px] w-full" onClick={() => { setShowViewsPanel(false); setShowSaveDialog(true); }} data-testid="new-view-from-panel-btn"><Save className="w-3 h-3 mr-1" /> Save Current Filters</Button>
              </div>
            )}
          </div>
          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={() => { setShowSaveDialog(true); setSaveViewName(''); setSaveViewNotes(''); setSaveAsDefault(false); }} data-testid="save-view-btn"><Save className="w-3.5 h-3.5" /> Save View</Button>
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={load} disabled={loading} data-testid="ops-queue-refresh">{loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}Refresh</Button>
        </div>
      </div>

      {/* Save View Dialog */}
      {showSaveDialog && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setShowSaveDialog(false)} data-testid="save-view-dialog">
          <div className="bg-background border border-border rounded-lg p-5 max-w-sm w-full shadow-xl space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold flex items-center gap-2"><BookmarkCheck className="w-4 h-4" /> Save Current View</h3>
            <div className="space-y-2">
              <Input className="h-8 text-xs" placeholder="View name..." value={saveViewName} onChange={e => setSaveViewName(e.target.value)} data-testid="save-view-name-input" autoFocus />
              <Input className="h-8 text-xs" placeholder="Notes (optional)..." value={saveViewNotes} onChange={e => setSaveViewNotes(e.target.value)} data-testid="save-view-notes-input" />
              <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="save-view-default-toggle"><input type="checkbox" checked={saveAsDefault} onChange={e => setSaveAsDefault(e.target.checked)} className="rounded" /> Set as default</label>
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setShowSaveDialog(false)}>Cancel</Button>
              <Button size="sm" className="h-7 text-[10px]" disabled={savingView || !saveViewName.trim()} onClick={saveView} data-testid="confirm-save-view-btn">{savingView ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />} Save</Button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Action Toolbar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 bg-primary/5 border border-primary/20 rounded-lg px-4 py-2.5 animate-in slide-in-from-top-2" data-testid="bulk-action-toolbar">
          <Badge variant="secondary" className="text-xs font-mono" data-testid="bulk-selected-count">{selected.size} selected</Badge>
          <div className="flex gap-1.5 flex-wrap">
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" onClick={() => { setBulkAction('assign_owner'); setBulkPayload({}); }} data-testid="bulk-assign-btn"><Users className="w-3 h-3" /> Assign Owner</Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" onClick={() => { setBulkAction('update_assignment_status'); setBulkPayload({}); }} data-testid="bulk-status-btn"><ArrowUpCircle className="w-3 h-3" /> Update Status</Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" onClick={() => { setBulkAction('set_due_date'); setBulkPayload({}); }} data-testid="bulk-duedate-btn"><Calendar className="w-3 h-3" /> Set Due Date</Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" onClick={() => { setBulkAction('set_escalation_status'); setBulkPayload({}); }} data-testid="bulk-escalation-btn"><AlertTriangle className="w-3 h-3" /> Set Escalation</Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1" onClick={() => { setBulkAction('request_approval'); setBulkPayload({}); }} data-testid="bulk-approval-btn"><ShieldCheck className="w-3 h-3" /> Request Approval</Button>
            <Button size="sm" variant="outline" className="h-7 text-[10px] gap-1 border-violet-300 text-violet-700" onClick={() => { setBulkAction('apply_template'); setBulkPayload({}); loadBulkTemplates(); }} data-testid="bulk-template-btn"><FileText className="w-3 h-3" /> Apply Template</Button>
          </div>
          <Button size="sm" variant="ghost" className="h-7 text-[10px] ml-auto" onClick={() => setSelected(new Set())} data-testid="bulk-clear-btn"><X className="w-3 h-3 mr-1" /> Clear</Button>
        </div>
      )}

      {/* Bulk Action Dialog */}
      {bulkAction && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setBulkAction(null)} data-testid="bulk-action-dialog">
          <div className="bg-background border border-border rounded-lg p-5 max-w-sm w-full shadow-xl space-y-3" onClick={e => e.stopPropagation()}>
            <h3 className="text-sm font-bold capitalize" data-testid="bulk-action-title">{bulkAction.replace(/_/g, ' ')} — {selected.size} items</h3>
            <div className="space-y-2">
              {bulkAction === 'assign_owner' && (
                <Input className="h-8 text-xs" placeholder="Assign to..." value={bulkPayload.assigned_to || ''} onChange={e => setBulkPayload({ ...bulkPayload, assigned_to: e.target.value })} data-testid="bulk-owner-input" autoFocus />
              )}
              {bulkAction === 'update_assignment_status' && (
                <Select value={bulkPayload.assignment_status || ''} onValueChange={v => setBulkPayload({ ...bulkPayload, assignment_status: v })}>
                  <SelectTrigger className="h-8 text-xs" data-testid="bulk-asgn-status-select"><SelectValue placeholder="Select status..." /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="assigned">Assigned</SelectItem>
                    <SelectItem value="in_progress">In Progress</SelectItem>
                    <SelectItem value="waiting">Waiting</SelectItem>
                    <SelectItem value="completed">Completed</SelectItem>
                  </SelectContent>
                </Select>
              )}
              {bulkAction === 'set_due_date' && (
                <Input type="date" className="h-8 text-xs" value={bulkPayload.due_date_local || ''} onChange={e => setBulkPayload({ ...bulkPayload, due_date_local: e.target.value, due_date: e.target.value ? `${e.target.value}T00:00:00Z` : '' })} data-testid="bulk-duedate-input" />
              )}
              {bulkAction === 'set_escalation_status' && (
                <Select value={bulkPayload.escalation_status || ''} onValueChange={v => setBulkPayload({ ...bulkPayload, escalation_status: v })}>
                  <SelectTrigger className="h-8 text-xs" data-testid="bulk-esc-status-select"><SelectValue placeholder="Select escalation..." /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="on_track">On Track</SelectItem>
                    <SelectItem value="due_soon">Due Soon</SelectItem>
                    <SelectItem value="overdue">Overdue</SelectItem>
                    <SelectItem value="escalated">Escalated</SelectItem>
                  </SelectContent>
                </Select>
              )}
              {bulkAction === 'request_approval' && (
                <Select value={bulkPayload.approval_type || 'manager_review'} onValueChange={v => setBulkPayload({ ...bulkPayload, approval_type: v })}>
                  <SelectTrigger className="h-8 text-xs" data-testid="bulk-approval-type-select"><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="manager_review">Manager Review</SelectItem>
                    <SelectItem value="finance_review">Finance Review</SelectItem>
                    <SelectItem value="logistics_review">Logistics Review</SelectItem>
                  </SelectContent>
                </Select>
              )}
              {bulkAction === 'apply_template' && (
                <div className="space-y-1">
                  {bulkTemplates.length === 0 ? (
                    <p className="text-[10px] text-muted-foreground italic">No active templates available</p>
                  ) : (
                    <Select value={bulkPayload.template_id || ''} onValueChange={v => setBulkPayload({ ...bulkPayload, template_id: v })}>
                      <SelectTrigger className="h-8 text-xs" data-testid="bulk-template-select"><SelectValue placeholder="Select template..." /></SelectTrigger>
                      <SelectContent>
                        {bulkTemplates.map(t => (
                          <SelectItem key={t.template_id} value={t.template_id}>{t.name} ({t.entity_type === 'sales_order' ? 'SO' : 'PO'})</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                </div>
              )}
              <Input className="h-8 text-xs" placeholder="Notes (optional)..." value={bulkPayload.notes || ''} onChange={e => setBulkPayload({ ...bulkPayload, notes: e.target.value })} data-testid="bulk-notes-input" />
            </div>
            <div className="text-[9px] text-muted-foreground">
              {selectedSoIds.length > 0 && <p>{selectedSoIds.length} Sales Order(s)</p>}
              {selectedPoIds.length > 0 && <p>{selectedPoIds.length} PO Draft(s)</p>}
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setBulkAction(null)}>Cancel</Button>
              <Button size="sm" className="h-7 text-[10px]" disabled={bulkRunning || (bulkAction === 'assign_owner' && !bulkPayload.assigned_to?.trim()) || (bulkAction === 'update_assignment_status' && !bulkPayload.assignment_status) || (bulkAction === 'set_due_date' && !bulkPayload.due_date) || (bulkAction === 'set_escalation_status' && !bulkPayload.escalation_status) || (bulkAction === 'apply_template' && !bulkPayload.template_id)} onClick={runBulkAction} data-testid="bulk-confirm-btn">
                {bulkRunning ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <CheckSquare className="w-3 h-3 mr-1" />} Apply to {selected.size} items
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Bulk Result Summary */}
      {bulkResult && (
        <div className="border border-border rounded-lg p-3 bg-muted/20 space-y-2" data-testid="bulk-result-summary">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold">Bulk Action Result</p>
            <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => setBulkResult(null)}><X className="w-3 h-3" /></Button>
          </div>
          <div className="flex gap-3 text-xs">
            <Badge variant="default" className="bg-green-600" data-testid="bulk-result-success">{bulkResult.succeeded} succeeded</Badge>
            {bulkResult.failed > 0 && <Badge variant="destructive" data-testid="bulk-result-failed">{bulkResult.failed} failed</Badge>}
          </div>
          {bulkResult.failed > 0 && (
            <div className="text-[9px] space-y-0.5 max-h-[100px] overflow-y-auto">
              {bulkResult.results.filter(r => r.status === 'failed').map((r, i) => (
                <p key={i} className="text-red-600">{r.entity_id}: {r.message}</p>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Summary Strip */}
      <div className="flex gap-3 text-sm flex-wrap" data-testid="ops-queue-summary">
        <div className="flex items-center gap-2 border border-border rounded-lg px-3 py-2"><ClipboardList className="w-4 h-4 text-muted-foreground" /><div><p className="text-xs text-muted-foreground">Total Queue</p><p className="text-lg font-bold font-mono" data-testid="ops-queue-total">{total}</p></div></div>
        <div className="flex items-center gap-2 border border-red-200 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2"><AlertTriangle className="w-4 h-4 text-red-500" /><div><p className="text-xs text-red-600">High Priority</p><p className="text-lg font-bold font-mono text-red-600" data-testid="ops-queue-high-priority">{counts.highPriority}</p></div></div>
        <div className="flex items-center gap-2 border border-orange-200 bg-orange-50 dark:bg-orange-900/20 rounded-lg px-3 py-2"><UserX className="w-4 h-4 text-orange-600" /><div><p className="text-xs text-orange-600">Unassigned</p><p className="text-lg font-bold font-mono text-orange-600" data-testid="ops-queue-unassigned">{counts.unassigned}</p></div></div>
        <div className="flex items-center gap-2 border border-indigo-200 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg px-3 py-2"><User className="w-4 h-4 text-indigo-600" /><div><p className="text-xs text-indigo-600">In Progress</p><p className="text-lg font-bold font-mono text-indigo-600" data-testid="ops-queue-in-progress">{counts.inProgress}</p></div></div>
        <div className="flex items-center gap-2 border border-green-200 bg-green-50 dark:bg-green-900/20 rounded-lg px-3 py-2"><Activity className="w-4 h-4 text-green-600" /><div><p className="text-xs text-green-600">Activity Today</p><p className="text-lg font-bold font-mono text-green-600" data-testid="ops-queue-activity-today">{counts.activityToday}</p></div></div>
        <div className="flex items-center gap-2 border border-slate-200 bg-slate-50 dark:bg-slate-900/20 rounded-lg px-3 py-2"><History className="w-4 h-4 text-slate-500" /><div><p className="text-xs text-slate-500">Stale (&gt;7d)</p><p className="text-lg font-bold font-mono text-slate-500" data-testid="ops-queue-stale-7d">{counts.stale7d}</p></div></div>
        {counts.savedViewsCount > 0 && <div className="flex items-center gap-2 border border-violet-200 bg-violet-50 dark:bg-violet-900/20 rounded-lg px-3 py-2"><Bookmark className="w-4 h-4 text-violet-600" /><div><p className="text-xs text-violet-600">{counts.defaultViewName || 'Saved Views'}</p><p className="text-lg font-bold font-mono text-violet-600" data-testid="ops-queue-saved-views-count">{counts.savedViewsCount}</p></div></div>}
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap" data-testid="ops-queue-filters">
        <Select value={filterType} onValueChange={v => { setFilterType(v); setActiveViewId(null); }}><SelectTrigger className="h-8 w-[140px] text-xs" data-testid="ops-queue-type-filter"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All Types</SelectItem><SelectItem value="sales_order">Sales Orders</SelectItem><SelectItem value="po_draft">PO Drafts</SelectItem></SelectContent></Select>
        <Select value={filterEsc} onValueChange={v => { setFilterEsc(v); setActiveViewId(null); }}><SelectTrigger className="h-8 w-[140px] text-xs" data-testid="ops-queue-esc-filter"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All Escalations</SelectItem><SelectItem value="due_soon">Due Soon</SelectItem><SelectItem value="overdue">Overdue</SelectItem><SelectItem value="escalated">Escalated</SelectItem><SelectItem value="on_track">On Track</SelectItem></SelectContent></Select>
        <Select value={filterAsgn} onValueChange={v => { setFilterAsgn(v); setActiveViewId(null); }}><SelectTrigger className="h-8 w-[150px] text-xs" data-testid="ops-queue-asgn-filter"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">All Assignments</SelectItem><SelectItem value="unassigned">Unassigned</SelectItem><SelectItem value="assigned">Assigned</SelectItem><SelectItem value="in_progress">In Progress</SelectItem><SelectItem value="waiting">Waiting</SelectItem><SelectItem value="completed">Completed</SelectItem></SelectContent></Select>
        <Select value={sortBy} onValueChange={v => { setSortBy(v); setActiveViewId(null); }}><SelectTrigger className="h-8 w-[150px] text-xs" data-testid="ops-queue-sort"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="priority">Sort: Priority</SelectItem><SelectItem value="activity">Sort: Latest Activity</SelectItem></SelectContent></Select>
        <Input className="h-8 text-xs w-[150px]" placeholder="Filter by owner..." value={filterOwner} onChange={e => { setFilterOwner(e.target.value); setActiveViewId(null); }} onKeyDown={e => e.key === 'Enter' && load()} data-testid="ops-queue-owner-filter" />
        <Input className="h-8 text-xs max-w-[200px]" placeholder="Search..." value={search} onChange={e => setSearch(e.target.value)} data-testid="ops-queue-search" />
        <span className="text-xs text-muted-foreground ml-auto">{filtered.length} items</span>
      </div>

      {/* Queue Table */}
      {loading && items.length === 0 ? (
        <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground" data-testid="ops-queue-empty"><ClipboardList className="w-10 h-10 mx-auto mb-3 opacity-30" /><p className="text-sm font-medium">No items in queue</p></div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ops-queue-table">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
                <th className="p-2.5 w-8">
                  <button onClick={toggleSelectAll} className="flex items-center justify-center" data-testid="select-all-checkbox">
                    {selected.size === filtered.length && filtered.length > 0 ? <CheckSquare className="w-4 h-4 text-primary" /> : <Square className="w-4 h-4" />}
                  </button>
                </th>
                <th className="p-2.5 text-left font-medium">Type</th>
                <th className="p-2.5 text-left font-medium">ID</th>
                <th className="p-2.5 text-center font-medium">Priority</th>
                <th className="p-2.5 text-left font-medium">Owner</th>
                <th className="p-2.5 text-center font-medium">Status</th>
                <th className="p-2.5 text-left font-medium">Next Action</th>
                <th className="p-2.5 text-center font-medium">Escalation</th>
                <th className="p-2.5 text-left font-medium">Last Activity</th>
                <th className="p-2.5 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, i) => {
                const key = `${item.entity_type}::${item.entity_id}`;
                const isSelected = selected.has(key);
                const isUnassignedHighPri = !item.current_owner && item.priority_score >= 40;
                const asgnStyle = ASGN_BADGE[item.assignment_status] || ASGN_BADGE.unassigned;
                return (
                  <tr key={key} className={`border-t border-border/30 hover:bg-muted/20 cursor-pointer transition-colors ${isSelected ? 'bg-primary/5 ring-1 ring-primary/10' : ''} ${isUnassignedHighPri ? 'bg-orange-50/60 dark:bg-orange-900/15 border-l-2 border-l-orange-400' : item.escalation_status === 'overdue' ? 'bg-red-50/50' : item.escalation_status === 'escalated' ? 'bg-red-100/60' : item.escalation_status === 'due_soon' ? 'bg-amber-50/40' : ''}`} data-testid={`ops-queue-row-${i}`}>
                    <td className="p-2.5" onClick={e => { e.stopPropagation(); toggleSelect(key); }}>
                      <div className="flex items-center justify-center" data-testid={`row-checkbox-${i}`}>
                        {isSelected ? <CheckSquare className="w-4 h-4 text-primary" /> : <Square className="w-4 h-4 text-muted-foreground" />}
                      </div>
                    </td>
                    <td className="p-2.5" onClick={() => setSelectedItem(item)}><Badge variant="outline" className="text-[9px] gap-1">{item.entity_type === 'sales_order' ? <Package className="w-3 h-3" /> : <ClipboardList className="w-3 h-3" />}{item.entity_type === 'sales_order' ? 'SO' : 'PO'}</Badge></td>
                    <td className="p-2.5 font-mono font-bold" onClick={() => setSelectedItem(item)} data-testid={`ops-queue-id-${i}`}>{item.entity_id}</td>
                    <td className="p-2.5 text-center" onClick={() => setSelectedItem(item)}><Badge variant={priorityBadge(item.priority_score)} className={`text-[9px] font-mono font-bold ${priorityColor(item.priority_score)} border`} data-testid={`ops-queue-priority-${i}`}>{item.priority_score}</Badge></td>
                    <td className="p-2.5" onClick={() => setSelectedItem(item)} data-testid={`ops-queue-owner-${i}`}>{item.current_owner ? <span className="text-[10px] font-medium flex items-center gap-1"><User className="w-3 h-3 text-indigo-500" />{item.current_owner}</span> : <span className="text-[10px] text-muted-foreground flex items-center gap-1 italic"><UserX className="w-3 h-3 text-orange-400" />Unassigned</span>}</td>
                    <td className="p-2.5 text-center" onClick={() => setSelectedItem(item)}><Badge className={`text-[8px] ${asgnStyle.cls}`} variant={asgnStyle.variant} data-testid={`ops-queue-asgn-${i}`}>{asgnStyle.label}</Badge></td>
                    <td className="p-2.5 text-[10px] font-medium" onClick={() => setSelectedItem(item)} data-testid={`ops-queue-next-${i}`}>{item.next_action}</td>
                    <td className="p-2.5 text-center" onClick={() => setSelectedItem(item)}>{item.escalation_status && (() => { const es = ESC_BADGE[item.escalation_status] || ESC_BADGE.on_track; return <Badge className={`text-[8px] ${es.cls}`} variant={es.variant} data-testid={`ops-queue-esc-${i}`}>{es.label}</Badge>; })()}</td>
                    <td className="p-2.5 text-[10px] text-muted-foreground" onClick={() => setSelectedItem(item)} data-testid={`ops-queue-activity-${i}`}>{item.latest_activity_at ? <span className="flex items-center gap-1"><Activity className="w-3 h-3" />{timeAgo(item.latest_activity_at)}</span> : <span className="italic">No activity</span>}</td>
                    <td className="p-2.5" onClick={() => setSelectedItem(item)}><ChevronRight className="w-3.5 h-3.5 text-muted-foreground" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail Panel */}
      {selectedItem && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setSelectedItem(null)} data-testid="ops-queue-detail-overlay">
          <div className="bg-background border border-border rounded-lg p-5 max-w-md w-full shadow-xl space-y-3" onClick={e => e.stopPropagation()} data-testid="ops-queue-detail-panel">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold">{selectedItem.entity_type === 'sales_order' ? 'Sales Order' : 'PO Draft'}: {selectedItem.entity_id}</h3>
              <Badge variant={priorityBadge(selectedItem.priority_score)} className={`text-[9px] font-mono font-bold ${priorityColor(selectedItem.priority_score)} border`}>Score: {selectedItem.priority_score}</Badge>
            </div>
            <div className="space-y-1.5 text-xs">
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Owner:</span>{selectedItem.current_owner ? <span className="font-medium flex items-center gap-1"><User className="w-3 h-3 text-indigo-500" />{selectedItem.current_owner}</span> : <span className="text-muted-foreground italic">Unassigned</span>}</div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Assignment:</span>{(() => { const s = ASGN_BADGE[selectedItem.assignment_status] || ASGN_BADGE.unassigned; return <Badge className={`text-[9px] ${s.cls}`} variant={s.variant}>{s.label}</Badge>; })()}</div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Last Activity:</span><span>{selectedItem.latest_activity_at ? `${timeAgo(selectedItem.latest_activity_at)} (${selectedItem.latest_activity_type})` : 'None'}</span></div>
            </div>
            <div className="space-y-1"><p className="text-[10px] font-medium text-muted-foreground uppercase">Actions Required</p>{selectedItem.action_required.map((a, i) => <div key={i} className="flex items-center gap-2 text-xs"><AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" /><span>{a}</span></div>)}</div>
            <div className="flex gap-2 pt-1">
              <a href="/inventory-ledger" className="flex-1"><Button size="sm" className="h-7 text-[10px] w-full" data-testid="ops-queue-open-workflow"><FileText className="w-3 h-3 mr-1" /> Open</Button></a>
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setSelectedItem(null)} data-testid="ops-queue-close-detail">Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
