import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Loader2, RefreshCw, AlertTriangle, ChevronRight, Warehouse, Truck, ClipboardList, Package, FileText, Clock, User, UserX, Activity, History, Bookmark, BookmarkCheck, Save, Star, Trash2, X } from 'lucide-react';
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

function priorityColor(score) {
  if (score >= 40) return 'text-red-600 bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800';
  if (score >= 20) return 'text-amber-600 bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800';
  return 'text-blue-600 bg-blue-50 dark:bg-blue-900/20 border-blue-200 dark:border-blue-800';
}

function priorityBadge(score) {
  if (score >= 40) return 'destructive';
  if (score >= 20) return 'secondary';
  return 'outline';
}

function timeAgo(iso) {
  if (!iso) return '';
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

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

  // Saved views state
  const [savedViews, setSavedViews] = useState([]);
  const [activeViewId, setActiveViewId] = useState(null);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [saveViewName, setSaveViewName] = useState('');
  const [saveViewNotes, setSaveViewNotes] = useState('');
  const [saveAsDefault, setSaveAsDefault] = useState(false);
  const [savingView, setSavingView] = useState(false);
  const [showViewsPanel, setShowViewsPanel] = useState(false);
  const defaultLoaded = useRef(false);

  const getCurrentFilters = () => ({
    entity_type: filterType !== 'all' ? filterType : '',
    escalation: filterEsc !== 'all' ? filterEsc : '',
    assigned_to: filterOwner.trim(),
    assignment_status: filterAsgn !== 'all' ? filterAsgn : '',
    unassigned_only: filterAsgn === 'unassigned' ? 'true' : '',
    search: search.trim(),
  });
  const getCurrentSort = () => ({ field: sortBy === 'activity' ? 'latest_activity' : 'priority_score', direction: 'desc' });

  const applyView = (view) => {
    const f = view.filters || {};
    setFilterType(f.entity_type || 'all');
    setFilterEsc(f.escalation || 'all');
    setFilterOwner(f.assigned_to || '');
    if (f.unassigned_only === 'true') {
      setFilterAsgn('unassigned');
    } else {
      setFilterAsgn(f.assignment_status || 'all');
    }
    setSearch(f.search || '');
    const s = view.sort || {};
    setSortBy(s.field === 'latest_activity' ? 'activity' : 'priority');
    setActiveViewId(view.saved_view_id);
    setShowViewsPanel(false);
  };

  // Load saved views
  const loadViews = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views?view_type=operations_queue`);
      if (res.ok) {
        const d = await res.json();
        setSavedViews(d.entries || []);
        // Auto-load default on first open
        if (!defaultLoaded.current) {
          defaultLoaded.current = true;
          const def = (d.entries || []).find(v => v.is_default);
          if (def) { applyView(def); }
        }
      }
    } catch { /* silent */ }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200', offset: '0' });
      if (filterType !== 'all') params.set('entity_type', filterType);
      if (filterEsc !== 'all') params.set('escalation', filterEsc);
      if (filterAsgn === 'unassigned') {
        params.set('unassigned_only', 'true');
      } else if (filterAsgn !== 'all') {
        params.set('assignment_status', filterAsgn);
      }
      if (filterOwner.trim()) params.set('assigned_to', filterOwner.trim());
      if (sortBy === 'activity') params.set('sort_by', 'latest_activity');
      const res = await fetch(`${API}/api/inventory-ledger/operations-queue?${params}`);
      if (res.ok) {
        const d = await res.json();
        setItems(d.items || []);
        setTotal(d.total || 0);
        setCounts({
          highPriority: d.high_priority_count || 0,
          dueSoon: d.due_soon_count || 0,
          overdue: d.overdue_count || 0,
          escalated: d.escalated_count || 0,
          unassigned: d.unassigned_count || 0,
          inProgress: d.in_progress_count || 0,
          waiting: d.waiting_count || 0,
          activityToday: d.recent_activity_today || 0,
          stale7d: d.no_recent_activity_7d || 0,
          savedViewsCount: d.saved_views_count || 0,
          defaultViewName: d.default_view_name || '',
        });
      } else { toast.error('Failed to load operations queue'); }
    } catch { toast.error('Failed to load operations queue'); }
    finally { setLoading(false); }
  }, [filterType, filterEsc, filterAsgn, filterOwner, sortBy]);

  useEffect(() => { loadViews(); }, [loadViews]);
  useEffect(() => { load(); }, [load]);

  const saveView = async () => {
    if (!saveViewName.trim()) { toast.error('View name is required'); return; }
    setSavingView(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          view_type: 'operations_queue', name: saveViewName.trim(),
          is_default: saveAsDefault, filters: getCurrentFilters(),
          sort: getCurrentSort(), notes: saveViewNotes.trim(),
        }),
      });
      if (res.ok) {
        const d = await res.json();
        toast.success(`View "${d.name}" saved`);
        setShowSaveDialog(false); setSaveViewName(''); setSaveViewNotes(''); setSaveAsDefault(false);
        setActiveViewId(d.saved_view_id);
        loadViews();
      } else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed to save view'); }
    finally { setSavingView(false); }
  };

  const toggleDefault = async (view) => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views/${view.saved_view_id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ is_default: !view.is_default }),
      });
      if (res.ok) {
        toast.success(view.is_default ? 'Default removed' : `"${view.name}" set as default`);
        loadViews(); load();
      }
    } catch { toast.error('Failed to update'); }
  };

  const deleteView = async (view) => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views/${view.saved_view_id}`, { method: 'DELETE' });
      if (res.ok) {
        toast.success(`View "${view.name}" deleted`);
        if (activeViewId === view.saved_view_id) setActiveViewId(null);
        loadViews(); load();
      }
    } catch { toast.error('Failed to delete'); }
  };

  const overwriteView = async (view) => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/saved-views/${view.saved_view_id}`, {
        method: 'PATCH', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ filters: getCurrentFilters(), sort: getCurrentSort() }),
      });
      if (res.ok) { toast.success(`View "${view.name}" updated with current filters`); loadViews(); }
    } catch { toast.error('Failed to update'); }
  };

  const activeView = savedViews.find(v => v.saved_view_id === activeViewId);

  const filtered = search.trim()
    ? items.filter(i => i.entity_id.toLowerCase().includes(search.toLowerCase()) || i.action_required.some(a => a.toLowerCase().includes(search.toLowerCase())) || (i.current_owner || '').toLowerCase().includes(search.toLowerCase()))
    : items;

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5" data-testid="operations-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }} data-testid="ops-queue-title">Operations Queue</h1>
          <div className="flex items-center gap-2 mt-0.5">
            <p className="text-sm text-muted-foreground">Items requiring operational attention</p>
            {activeView && (
              <Badge variant="secondary" className="text-[9px] gap-1" data-testid="active-view-badge">
                <Bookmark className="w-3 h-3" />{activeView.name}
                {activeView.is_default && <Star className="w-2.5 h-2.5 fill-amber-400 text-amber-400" />}
              </Badge>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          <div className="relative">
            <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={() => setShowViewsPanel(!showViewsPanel)} data-testid="saved-views-btn">
              <Bookmark className="w-3.5 h-3.5" />
              Views {savedViews.length > 0 && <Badge variant="secondary" className="text-[8px] h-4 px-1">{savedViews.length}</Badge>}
            </Button>

            {/* Views Panel */}
            {showViewsPanel && (
              <div className="absolute right-0 top-10 z-50 bg-background border border-border rounded-lg shadow-xl w-72 p-3 space-y-2" data-testid="saved-views-panel">
                <div className="flex items-center justify-between">
                  <p className="text-xs font-bold">Saved Views</p>
                  <Button variant="ghost" size="sm" className="h-5 w-5 p-0" onClick={() => setShowViewsPanel(false)}><X className="w-3 h-3" /></Button>
                </div>
                {savedViews.length === 0 ? (
                  <p className="text-[10px] text-muted-foreground text-center py-3 italic">No saved views yet</p>
                ) : (
                  <div className="space-y-1 max-h-[240px] overflow-y-auto" data-testid="saved-views-list">
                    {savedViews.map(v => (
                      <div key={v.saved_view_id} className={`flex items-center gap-2 px-2 py-1.5 rounded hover:bg-muted/40 transition-colors group ${activeViewId === v.saved_view_id ? 'bg-muted/50 ring-1 ring-primary/20' : ''}`} data-testid={`saved-view-${v.saved_view_id}`}>
                        <button className="flex-1 text-left min-w-0" onClick={() => applyView(v)} data-testid={`apply-view-${v.saved_view_id}`}>
                          <div className="flex items-center gap-1">
                            <span className="text-[10px] font-medium truncate">{v.name}</span>
                            {v.is_default && <Star className="w-2.5 h-2.5 fill-amber-400 text-amber-400 shrink-0" />}
                          </div>
                          {v.notes && <p className="text-[8px] text-muted-foreground truncate">{v.notes}</p>}
                        </button>
                        <div className="flex gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0" title={v.is_default ? 'Remove default' : 'Set as default'} onClick={(e) => { e.stopPropagation(); toggleDefault(v); }} data-testid={`default-view-${v.saved_view_id}`}>
                            <Star className={`w-3 h-3 ${v.is_default ? 'fill-amber-400 text-amber-400' : 'text-muted-foreground'}`} />
                          </Button>
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0" title="Update with current filters" onClick={(e) => { e.stopPropagation(); overwriteView(v); }} data-testid={`overwrite-view-${v.saved_view_id}`}>
                            <Save className="w-3 h-3 text-muted-foreground" />
                          </Button>
                          <Button variant="ghost" size="sm" className="h-5 w-5 p-0 text-red-500 hover:text-red-600" title="Delete view" onClick={(e) => { e.stopPropagation(); deleteView(v); }} data-testid={`delete-view-${v.saved_view_id}`}>
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                <Button size="sm" className="h-7 text-[10px] w-full" onClick={() => { setShowViewsPanel(false); setShowSaveDialog(true); setSaveViewName(''); setSaveViewNotes(''); setSaveAsDefault(false); }} data-testid="new-view-from-panel-btn">
                  <Save className="w-3 h-3 mr-1" /> Save Current Filters as View
                </Button>
              </div>
            )}
          </div>

          <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5" onClick={() => { setShowSaveDialog(true); setSaveViewName(''); setSaveViewNotes(''); setSaveAsDefault(false); }} data-testid="save-view-btn">
            <Save className="w-3.5 h-3.5" /> Save View
          </Button>
          <Button variant="outline" size="sm" className="h-8 text-xs" onClick={load} disabled={loading} data-testid="ops-queue-refresh">
            {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
            Refresh
          </Button>
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
              <label className="flex items-center gap-2 text-xs cursor-pointer" data-testid="save-view-default-toggle">
                <input type="checkbox" checked={saveAsDefault} onChange={e => setSaveAsDefault(e.target.checked)} className="rounded border-border" />
                Set as default view (auto-loads on open)
              </label>
              <div className="text-[9px] text-muted-foreground bg-muted/40 rounded p-2 space-y-0.5">
                <p className="font-medium">Current filters:</p>
                {filterType !== 'all' && <p>Type: {filterType}</p>}
                {filterEsc !== 'all' && <p>Escalation: {filterEsc}</p>}
                {filterAsgn !== 'all' && <p>Assignment: {filterAsgn}</p>}
                {filterOwner && <p>Owner: {filterOwner}</p>}
                {search && <p>Search: {search}</p>}
                <p>Sort: {sortBy === 'activity' ? 'Latest Activity' : 'Priority'}</p>
                {filterType === 'all' && filterEsc === 'all' && filterAsgn === 'all' && !filterOwner && !search && <p className="italic">No filters applied</p>}
              </div>
            </div>
            <div className="flex gap-2 justify-end">
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setShowSaveDialog(false)}>Cancel</Button>
              <Button size="sm" className="h-7 text-[10px]" disabled={savingView || !saveViewName.trim()} onClick={saveView} data-testid="confirm-save-view-btn">
                {savingView ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />} Save
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Summary Strip */}
      <div className="flex gap-3 text-sm flex-wrap" data-testid="ops-queue-summary">
        <div className="flex items-center gap-2 border border-border rounded-lg px-3 py-2">
          <ClipboardList className="w-4 h-4 text-muted-foreground" />
          <div><p className="text-xs text-muted-foreground">Total Queue</p><p className="text-lg font-bold font-mono" data-testid="ops-queue-total">{total}</p></div>
        </div>
        <div className="flex items-center gap-2 border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-4 h-4 text-red-500" />
          <div><p className="text-xs text-red-600 dark:text-red-400">High Priority</p><p className="text-lg font-bold font-mono text-red-600" data-testid="ops-queue-high-priority">{counts.highPriority}</p></div>
        </div>
        <div className="flex items-center gap-2 border border-orange-200 dark:border-orange-800 bg-orange-50 dark:bg-orange-900/20 rounded-lg px-3 py-2">
          <UserX className="w-4 h-4 text-orange-600" />
          <div><p className="text-xs text-orange-600">Unassigned</p><p className="text-lg font-bold font-mono text-orange-600" data-testid="ops-queue-unassigned">{counts.unassigned}</p></div>
        </div>
        <div className="flex items-center gap-2 border border-indigo-200 dark:border-indigo-800 bg-indigo-50 dark:bg-indigo-900/20 rounded-lg px-3 py-2">
          <User className="w-4 h-4 text-indigo-600" />
          <div><p className="text-xs text-indigo-600">In Progress</p><p className="text-lg font-bold font-mono text-indigo-600" data-testid="ops-queue-in-progress">{counts.inProgress}</p></div>
        </div>
        <div className="flex items-center gap-2 border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 rounded-lg px-3 py-2">
          <Activity className="w-4 h-4 text-green-600" />
          <div><p className="text-xs text-green-600">Activity Today</p><p className="text-lg font-bold font-mono text-green-600" data-testid="ops-queue-activity-today">{counts.activityToday}</p></div>
        </div>
        <div className="flex items-center gap-2 border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/20 rounded-lg px-3 py-2">
          <History className="w-4 h-4 text-slate-500" />
          <div><p className="text-xs text-slate-500">Stale (&gt;7d)</p><p className="text-lg font-bold font-mono text-slate-500" data-testid="ops-queue-stale-7d">{counts.stale7d}</p></div>
        </div>
        {counts.savedViewsCount > 0 && (
          <div className="flex items-center gap-2 border border-violet-200 dark:border-violet-800 bg-violet-50 dark:bg-violet-900/20 rounded-lg px-3 py-2">
            <Bookmark className="w-4 h-4 text-violet-600" />
            <div>
              <p className="text-xs text-violet-600">{counts.defaultViewName ? counts.defaultViewName : 'Saved Views'}</p>
              <p className="text-lg font-bold font-mono text-violet-600" data-testid="ops-queue-saved-views-count">{counts.savedViewsCount}</p>
            </div>
          </div>
        )}
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center flex-wrap" data-testid="ops-queue-filters">
        <Select value={filterType} onValueChange={v => { setFilterType(v); setActiveViewId(null); }}>
          <SelectTrigger className="h-8 w-[140px] text-xs" data-testid="ops-queue-type-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="sales_order">Sales Orders</SelectItem>
            <SelectItem value="po_draft">PO Drafts</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filterEsc} onValueChange={v => { setFilterEsc(v); setActiveViewId(null); }}>
          <SelectTrigger className="h-8 w-[140px] text-xs" data-testid="ops-queue-esc-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Escalations</SelectItem>
            <SelectItem value="due_soon">Due Soon</SelectItem>
            <SelectItem value="overdue">Overdue</SelectItem>
            <SelectItem value="escalated">Escalated</SelectItem>
            <SelectItem value="on_track">On Track</SelectItem>
          </SelectContent>
        </Select>
        <Select value={filterAsgn} onValueChange={v => { setFilterAsgn(v); setActiveViewId(null); }}>
          <SelectTrigger className="h-8 w-[150px] text-xs" data-testid="ops-queue-asgn-filter"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Assignments</SelectItem>
            <SelectItem value="unassigned">Unassigned</SelectItem>
            <SelectItem value="assigned">Assigned</SelectItem>
            <SelectItem value="in_progress">In Progress</SelectItem>
            <SelectItem value="waiting">Waiting</SelectItem>
            <SelectItem value="completed">Completed</SelectItem>
          </SelectContent>
        </Select>
        <Select value={sortBy} onValueChange={v => { setSortBy(v); setActiveViewId(null); }}>
          <SelectTrigger className="h-8 w-[150px] text-xs" data-testid="ops-queue-sort"><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="priority">Sort: Priority</SelectItem>
            <SelectItem value="activity">Sort: Latest Activity</SelectItem>
          </SelectContent>
        </Select>
        <Input className="h-8 text-xs w-[150px]" placeholder="Filter by owner..." value={filterOwner} onChange={e => { setFilterOwner(e.target.value); setActiveViewId(null); }} onKeyDown={e => e.key === 'Enter' && load()} data-testid="ops-queue-owner-filter" />
        <Input className="h-8 text-xs max-w-[200px]" placeholder="Search ID / action / owner..." value={search} onChange={e => setSearch(e.target.value)} data-testid="ops-queue-search" />
        <span className="text-xs text-muted-foreground ml-auto">{filtered.length} items</span>
      </div>

      {/* Queue Table */}
      {loading && items.length === 0 ? (
        <div className="flex justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" /></div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground" data-testid="ops-queue-empty">
          <ClipboardList className="w-10 h-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm font-medium">No items in queue</p>
          <p className="text-xs mt-1">All operations are up to date</p>
        </div>
      ) : (
        <div className="border border-border rounded-lg overflow-hidden" data-testid="ops-queue-table">
          <table className="w-full text-xs">
            <thead className="bg-muted/40 text-muted-foreground">
              <tr>
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
                const isUnassignedHighPri = !item.current_owner && item.priority_score >= 40;
                const asgnStyle = ASGN_BADGE[item.assignment_status] || ASGN_BADGE.unassigned;
                return (
                  <tr
                    key={`${item.entity_type}-${item.entity_id}`}
                    className={`border-t border-border/30 hover:bg-muted/20 cursor-pointer transition-colors ${isUnassignedHighPri ? 'bg-orange-50/60 dark:bg-orange-900/15 border-l-2 border-l-orange-400' : item.escalation_status === 'overdue' ? 'bg-red-50/50 dark:bg-red-900/10' : item.escalation_status === 'escalated' ? 'bg-red-100/60 dark:bg-red-900/20' : item.escalation_status === 'due_soon' ? 'bg-amber-50/40 dark:bg-amber-900/10' : ''}`}
                    onClick={() => setSelectedItem(item)}
                    data-testid={`ops-queue-row-${i}`}
                  >
                    <td className="p-2.5">
                      <Badge variant="outline" className="text-[9px] gap-1">
                        {item.entity_type === 'sales_order' ? <Package className="w-3 h-3" /> : <ClipboardList className="w-3 h-3" />}
                        {item.entity_type === 'sales_order' ? 'SO' : 'PO Draft'}
                      </Badge>
                    </td>
                    <td className="p-2.5 font-mono font-bold" data-testid={`ops-queue-id-${i}`}>{item.entity_id}</td>
                    <td className="p-2.5 text-center">
                      <Badge variant={priorityBadge(item.priority_score)} className={`text-[9px] font-mono font-bold ${priorityColor(item.priority_score)} border`} data-testid={`ops-queue-priority-${i}`}>
                        {item.priority_score}
                      </Badge>
                    </td>
                    <td className="p-2.5" data-testid={`ops-queue-owner-${i}`}>
                      {item.current_owner ? (
                        <span className="text-[10px] font-medium flex items-center gap-1"><User className="w-3 h-3 text-indigo-500" />{item.current_owner}</span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground flex items-center gap-1 italic"><UserX className="w-3 h-3 text-orange-400" />Unassigned</span>
                      )}
                    </td>
                    <td className="p-2.5 text-center">
                      <Badge className={`text-[8px] ${asgnStyle.cls}`} variant={asgnStyle.variant} data-testid={`ops-queue-asgn-${i}`}>{asgnStyle.label}</Badge>
                    </td>
                    <td className="p-2.5 text-[10px] font-medium" data-testid={`ops-queue-next-${i}`}>{item.next_action}</td>
                    <td className="p-2.5 text-center">
                      {item.escalation_status && (() => {
                        const es = ESC_BADGE[item.escalation_status] || ESC_BADGE.on_track;
                        return <Badge className={`text-[8px] ${es.cls}`} variant={es.variant} data-testid={`ops-queue-esc-${i}`}>{es.label}</Badge>;
                      })()}
                    </td>
                    <td className="p-2.5 text-[10px] text-muted-foreground" data-testid={`ops-queue-activity-${i}`}>
                      {item.latest_activity_at ? (
                        <span className="flex items-center gap-1"><Activity className="w-3 h-3" />{timeAgo(item.latest_activity_at)}</span>
                      ) : (
                        <span className="italic">No activity</span>
                      )}
                    </td>
                    <td className="p-2.5"><ChevronRight className="w-3.5 h-3.5 text-muted-foreground" /></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Selected Item Detail */}
      {selectedItem && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center" onClick={() => setSelectedItem(null)} data-testid="ops-queue-detail-overlay">
          <div className="bg-background border border-border rounded-lg p-5 max-w-md w-full shadow-xl space-y-3" onClick={e => e.stopPropagation()} data-testid="ops-queue-detail-panel">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                {selectedItem.entity_type === 'sales_order' ? 'Sales Order' : 'PO Draft'}: {selectedItem.entity_id}
              </h3>
              <Badge variant={priorityBadge(selectedItem.priority_score)} className={`text-[9px] font-mono font-bold ${priorityColor(selectedItem.priority_score)} border`}>
                Score: {selectedItem.priority_score}
              </Badge>
            </div>
            <div className="space-y-1.5 text-xs">
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Type:</span>
                <Badge variant="secondary" className="text-[9px] gap-1">
                  {selectedItem.order_type === 'drop_ship' ? <Truck className="w-3 h-3" /> : <Warehouse className="w-3 h-3" />}
                  {selectedItem.order_type === 'drop_ship' ? 'Drop-Ship' : selectedItem.order_type === 'warehouse_supply' ? 'WH Supply' : 'Warehouse'}
                </Badge>
              </div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Owner:</span>
                {selectedItem.current_owner ? (
                  <span className="font-medium flex items-center gap-1"><User className="w-3 h-3 text-indigo-500" />{selectedItem.current_owner}</span>
                ) : (
                  <span className="text-muted-foreground italic flex items-center gap-1"><UserX className="w-3 h-3 text-orange-400" />Unassigned</span>
                )}
              </div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Assignment:</span>
                {(() => { const s = ASGN_BADGE[selectedItem.assignment_status] || ASGN_BADGE.unassigned; return <Badge className={`text-[9px] ${s.cls}`} variant={s.variant}>{s.label}</Badge>; })()}
              </div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Last Activity:</span>
                <span>{selectedItem.latest_activity_at ? `${timeAgo(selectedItem.latest_activity_at)} (${selectedItem.latest_activity_type})` : 'None'}</span>
              </div>
              <div className="flex gap-2"><span className="text-muted-foreground w-24">Checklist:</span>
                <Badge variant={selectedItem.checklist_complete ? 'default' : 'secondary'} className="text-[9px]">{selectedItem.checklist_complete ? 'Complete' : 'Incomplete'}</Badge>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Actions Required</p>
              <div className="space-y-1">
                {selectedItem.action_required.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs"><AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" /><span>{a}</span></div>
                ))}
              </div>
            </div>
            <div className="flex gap-2 pt-1">
              <a href="/inventory-ledger" className="flex-1">
                <Button size="sm" className="h-7 text-[10px] w-full" data-testid="ops-queue-open-workflow"><FileText className="w-3 h-3 mr-1" /> Open in Inventory Ledger</Button>
              </a>
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setSelectedItem(null)} data-testid="ops-queue-close-detail">Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
