import { useState, useEffect, useCallback } from 'react';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Loader2, RefreshCw, AlertTriangle, ChevronRight, Warehouse, Truck, ClipboardList, Package, FileText } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

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

export default function OperationsQueuePage() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [highPriority, setHighPriority] = useState(0);
  const [loading, setLoading] = useState(false);
  const [filterType, setFilterType] = useState('all');
  const [search, setSearch] = useState('');
  // Dialog state for opening SO/PO workflows
  const [selectedItem, setSelectedItem] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200', offset: '0' });
      if (filterType !== 'all') params.set('entity_type', filterType);
      const res = await fetch(`${API}/api/inventory-ledger/operations-queue?${params}`);
      if (res.ok) {
        const d = await res.json();
        setItems(d.items || []);
        setTotal(d.total || 0);
        setHighPriority(d.high_priority_count || 0);
      } else {
        toast.error('Failed to load operations queue');
      }
    } catch { toast.error('Failed to load operations queue'); }
    finally { setLoading(false); }
  }, [filterType]);

  useEffect(() => { load(); }, [load]);

  const filtered = search.trim()
    ? items.filter(i => i.entity_id.toLowerCase().includes(search.toLowerCase()) || i.action_required.some(a => a.toLowerCase().includes(search.toLowerCase())))
    : items;

  return (
    <div className="p-6 max-w-[1400px] mx-auto space-y-5" data-testid="operations-queue-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }} data-testid="ops-queue-title">Operations Queue</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Items requiring operational attention across Sales Orders and PO Drafts</p>
        </div>
        <Button variant="outline" size="sm" className="h-8 text-xs" onClick={load} disabled={loading} data-testid="ops-queue-refresh">
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1.5" /> : <RefreshCw className="w-3.5 h-3.5 mr-1.5" />}
          Refresh
        </Button>
      </div>

      {/* Summary Strip */}
      <div className="flex gap-4 text-sm" data-testid="ops-queue-summary">
        <div className="flex items-center gap-2 border border-border rounded-lg px-4 py-2.5">
          <ClipboardList className="w-4 h-4 text-muted-foreground" />
          <div>
            <p className="text-xs text-muted-foreground">Total Queue</p>
            <p className="text-lg font-bold font-mono" data-testid="ops-queue-total">{total}</p>
          </div>
        </div>
        <div className="flex items-center gap-2 border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-900/20 rounded-lg px-4 py-2.5">
          <AlertTriangle className="w-4 h-4 text-red-500" />
          <div>
            <p className="text-xs text-red-600 dark:text-red-400">High Priority</p>
            <p className="text-lg font-bold font-mono text-red-600" data-testid="ops-queue-high-priority">{highPriority}</p>
          </div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex gap-3 items-center" data-testid="ops-queue-filters">
        <Select value={filterType} onValueChange={setFilterType}>
          <SelectTrigger className="h-8 w-[160px] text-xs" data-testid="ops-queue-type-filter">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="sales_order">Sales Orders</SelectItem>
            <SelectItem value="po_draft">PO Drafts</SelectItem>
          </SelectContent>
        </Select>
        <Input className="h-8 text-xs max-w-[250px]" placeholder="Search by ID or action..." value={search} onChange={e => setSearch(e.target.value)} data-testid="ops-queue-search" />
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
                <th className="p-2.5 text-left font-medium">Order Type</th>
                <th className="p-2.5 text-center font-medium">Priority</th>
                <th className="p-2.5 text-left font-medium">Action Required</th>
                <th className="p-2.5 text-left font-medium">Next Action</th>
                <th className="p-2.5 text-left font-medium">Approval</th>
                <th className="p-2.5 text-right font-medium">Created</th>
                <th className="p-2.5 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((item, i) => (
                <tr
                  key={`${item.entity_type}-${item.entity_id}`}
                  className="border-t border-border/30 hover:bg-muted/20 cursor-pointer transition-colors"
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
                  <td className="p-2.5">
                    <Badge variant="secondary" className="text-[9px] gap-1">
                      {item.order_type === 'drop_ship' ? <Truck className="w-3 h-3" /> : <Warehouse className="w-3 h-3" />}
                      {item.order_type === 'drop_ship' ? 'Drop-Ship' : item.order_type === 'warehouse_supply' ? 'WH Supply' : 'Warehouse'}
                    </Badge>
                  </td>
                  <td className="p-2.5 text-center">
                    <Badge variant={priorityBadge(item.priority_score)} className={`text-[9px] font-mono font-bold ${priorityColor(item.priority_score)} border`} data-testid={`ops-queue-priority-${i}`}>
                      {item.priority_score}
                    </Badge>
                  </td>
                  <td className="p-2.5 max-w-[280px]">
                    <div className="flex flex-wrap gap-1">
                      {item.action_required.slice(0, 3).map((a, j) => (
                        <span key={j} className="text-[9px] px-1.5 py-0.5 bg-muted/60 rounded">{a}</span>
                      ))}
                      {item.action_required.length > 3 && <span className="text-[9px] text-muted-foreground">+{item.action_required.length - 3}</span>}
                    </div>
                  </td>
                  <td className="p-2.5 text-[10px] font-medium" data-testid={`ops-queue-next-${i}`}>{item.next_action}</td>
                  <td className="p-2.5">
                    <Badge
                      variant={item.approval_status === 'approved' ? 'default' : item.approval_status === 'pending' ? 'secondary' : item.approval_status === 'rejected' ? 'destructive' : 'outline'}
                      className={`text-[8px] ${item.approval_status === 'approved' ? 'bg-green-600' : item.approval_status === 'pending' ? 'bg-amber-500 text-white' : ''}`}
                      data-testid={`ops-queue-approval-${i}`}
                    >
                      {item.approval_status}
                    </Badge>
                  </td>
                  <td className="p-2.5 text-right text-muted-foreground text-[10px] font-mono">{(item.created_at || '').slice(0, 10)}</td>
                  <td className="p-2.5"><ChevronRight className="w-3.5 h-3.5 text-muted-foreground" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Selected Item Detail - Navigate to Inventory Ledger */}
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
              <div className="flex gap-2">
                <span className="text-muted-foreground w-24">Type:</span>
                <Badge variant="secondary" className="text-[9px] gap-1">
                  {selectedItem.order_type === 'drop_ship' ? <Truck className="w-3 h-3" /> : <Warehouse className="w-3 h-3" />}
                  {selectedItem.order_type === 'drop_ship' ? 'Drop-Ship' : selectedItem.order_type === 'warehouse_supply' ? 'WH Supply' : 'Warehouse'}
                </Badge>
              </div>
              <div className="flex gap-2">
                <span className="text-muted-foreground w-24">Approval:</span>
                <Badge variant={selectedItem.approval_status === 'approved' ? 'default' : 'secondary'} className={`text-[9px] ${selectedItem.approval_status === 'approved' ? 'bg-green-600' : selectedItem.approval_status === 'pending' ? 'bg-amber-500 text-white' : ''}`}>
                  {selectedItem.approval_status}
                </Badge>
              </div>
              {selectedItem.vendor_name && (
                <div className="flex gap-2">
                  <span className="text-muted-foreground w-24">Vendor:</span>
                  <span>{selectedItem.vendor_name}</span>
                </div>
              )}
              <div className="flex gap-2">
                <span className="text-muted-foreground w-24">Checklist:</span>
                <Badge variant={selectedItem.checklist_complete ? 'default' : 'secondary'} className="text-[9px]">{selectedItem.checklist_complete ? 'Complete' : 'Incomplete'}</Badge>
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Actions Required</p>
              <div className="space-y-1">
                {selectedItem.action_required.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs">
                    <AlertTriangle className="w-3 h-3 text-amber-500 shrink-0" />
                    <span>{a}</span>
                  </div>
                ))}
              </div>
            </div>
            <div className="flex gap-2 pt-1">
              <a href="/inventory-ledger" className="flex-1">
                <Button size="sm" className="h-7 text-[10px] w-full" data-testid="ops-queue-open-workflow">
                  <FileText className="w-3 h-3 mr-1" /> Open in Inventory Ledger
                </Button>
              </a>
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => setSelectedItem(null)} data-testid="ops-queue-close-detail">Close</Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
