import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Textarea } from '../components/ui/textarea';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from '../components/ui/dialog';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { toast } from 'sonner';
import {
  Warehouse, Loader2, Plus, Package, TrendingDown, TrendingUp,
  AlertTriangle, RefreshCw, Search, ArrowLeftRight, History,
  ChevronRight, ChevronLeft, Box, Truck, ClipboardList,
  RotateCcw, FileText, Download, Settings, Pencil, Upload, ShieldCheck, Zap,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const OWNERSHIP_LABELS = { customer_owned: 'Customer', gamer_reserved: 'Gamer Reserved', mixed: 'Mixed', unknown: 'Unknown' };
const OWNERSHIP_COLORS = { customer_owned: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300', gamer_reserved: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300', mixed: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300', unknown: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400' };
const MOVEMENT_TYPES = ['opening_balance', 'receipt', 'order_commitment', 'order_release', 'manual_adjustment', 'transfer', 'writeoff', 'correction'];
const SOURCE_TYPES = ['manual_entry', 'spreadsheet_import', 'sales_order_commitment', 'sales_order_release', 'receipt', 'correction'];
const OWNERSHIP_TYPES = ['customer_owned', 'gamer_reserved', 'mixed', 'unknown'];

export default function InventoryLedgerPage() {
  const [customers, setCustomers] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [loading, setLoading] = useState(true);
  const [showCreateCustomer, setShowCreateCustomer] = useState(false);

  const fetchCustomers = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers`);
      const data = await res.json();
      setCustomers(data);
    } catch { toast.error('Failed to load customers'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchCustomers(); }, [fetchCustomers]);

  const selected = customers.find(c => c.id === selectedId);

  if (loading) return <div className="flex items-center justify-center py-20"><Loader2 className="w-6 h-6 animate-spin" /></div>;

  return (
    <div className="max-w-[1400px] mx-auto space-y-6" data-testid="inventory-ledger-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Warehouse className="w-5 h-5 text-primary" /> Customer Inventory Ledger
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">Customer-specific warehouse inventory, commitments, and supply tracking</p>
        </div>
      </div>

      {!selectedId ? (
        <CustomerSelector customers={customers} onSelect={setSelectedId} onCreateNew={() => setShowCreateCustomer(true)} />
      ) : (
        <div className="space-y-1">
          <Button variant="ghost" size="sm" className="h-7 text-xs mb-2" onClick={() => setSelectedId(null)} data-testid="inv-back-btn">
            <ChevronLeft className="w-3 h-3 mr-1" /> All Customers
          </Button>
          <CustomerWorkspace customer={selected} onBack={() => setSelectedId(null)} />
        </div>
      )}

      {showCreateCustomer && (
        <CreateCustomerDialog
          open={showCreateCustomer}
          onClose={() => setShowCreateCustomer(false)}
          onCreated={(c) => { setCustomers(prev => [...prev, c]); setSelectedId(c.id); setShowCreateCustomer(false); }}
        />
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* CUSTOMER SELECTOR                                                */
/* ════════════════════════════════════════════════════════════════ */

function CustomerSelector({ customers, onSelect, onCreateNew }) {
  return (
    <div data-testid="inv-customer-selector">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {customers.map(c => (
          <Card key={c.id} className="cursor-pointer hover:shadow-md transition-shadow border border-border" onClick={() => onSelect(c.id)} data-testid={`inv-customer-${c.code}`}>
            <CardContent className="p-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="font-bold text-sm">{c.name}</p>
                  <p className="text-xs text-muted-foreground font-mono">{c.code}</p>
                </div>
                <ChevronRight className="w-4 h-4 text-muted-foreground" />
              </div>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant="outline" className="text-[9px]">{c.negative_balance_policy === 'block_commitment' ? 'Block on Short' : 'Warn Only'}</Badge>
              </div>
            </CardContent>
          </Card>
        ))}
        <Card className="cursor-pointer hover:shadow-md transition-shadow border border-dashed border-muted-foreground/30" onClick={onCreateNew} data-testid="inv-create-customer-btn">
          <CardContent className="p-4 flex items-center justify-center gap-2 text-muted-foreground">
            <Plus className="w-4 h-4" /> <span className="text-sm">New Customer Workspace</span>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* CUSTOMER WORKSPACE                                               */
/* ════════════════════════════════════════════════════════════════ */

function CustomerWorkspace({ customer }) {
  const [summary, setSummary] = useState(null);
  const [balances, setBalances] = useState([]);
  const [movements, setMovements] = useState([]);
  const [movementTotal, setMovementTotal] = useState(0);
  const [incoming, setIncoming] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('balances');
  const [showMovementForm, setShowMovementForm] = useState(false);
  const [showIncomingForm, setShowIncomingForm] = useState(false);
  const [showImportForm, setShowImportForm] = useState(false);
  const [search, setSearch] = useState('');
  const [detailItem, setDetailItem] = useState(null);
  const [historyItem, setHistoryItem] = useState(null);
  const [viewDraftId, setViewDraftId] = useState(null);

  const cid = customer?.id;

  const refresh = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      const [sumRes, balRes, movRes, incRes] = await Promise.all([
        fetch(`${API}/api/inventory-ledger/dashboard-summary?customer_id=${cid}`),
        fetch(`${API}/api/inventory-ledger/customers/${cid}/balances`),
        fetch(`${API}/api/inventory-ledger/customers/${cid}/movements?limit=200`),
        fetch(`${API}/api/inventory-ledger/customers/${cid}/incoming`),
      ]);
      const [sumData, balData, movData, incData] = await Promise.all([sumRes.json(), balRes.json(), movRes.json(), incRes.json()]);
      setSummary(sumData);
      setBalances(balData.balances || []);
      setMovements(movData.movements || []);
      setMovementTotal(movData.total || 0);
      setIncoming(incData || []);
    } catch { toast.error('Failed to load data'); }
    finally { setLoading(false); }
  }, [cid]);

  useEffect(() => { refresh(); }, [refresh]);

  if (!customer) return null;

  const filteredBalances = search
    ? balances.filter(b => b.item.toLowerCase().includes(search.toLowerCase()) || b.item_description.toLowerCase().includes(search.toLowerCase()) || b.warehouse.toLowerCase().includes(search.toLowerCase()))
    : balances;

  return (
    <div className="space-y-5" data-testid="inv-workspace">
      {/* Workspace Header */}
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>{customer.name}</h3>
          <p className="text-xs text-muted-foreground font-mono">{customer.code} &middot; {customer.negative_balance_policy === 'block_commitment' ? 'Block on Short' : 'Warn Only'}</p>
        </div>
        <Button variant="outline" size="sm" onClick={refresh} disabled={loading} data-testid="inv-refresh-btn">
          <RefreshCw className={`w-4 h-4 mr-1 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Summary Strip */}
      {summary && <SummaryStrip summary={summary} />}

      {/* Tabs */}
      <Tabs value={tab} onValueChange={setTab}>
        <div className="flex items-center justify-between">
          <TabsList>
            <TabsTrigger value="balances" data-testid="inv-tab-balances"><Box className="w-3.5 h-3.5 mr-1" /> Balances</TabsTrigger>
            <TabsTrigger value="movements" data-testid="inv-tab-movements"><History className="w-3.5 h-3.5 mr-1" /> Movements</TabsTrigger>
            <TabsTrigger value="incoming" data-testid="inv-tab-incoming"><Truck className="w-3.5 h-3.5 mr-1" /> Incoming</TabsTrigger>
            <TabsTrigger value="reorder" data-testid="inv-tab-reorder"><AlertTriangle className="w-3.5 h-3.5 mr-1" /> Reorder</TabsTrigger>
            <TabsTrigger value="settings" data-testid="inv-tab-settings"><Settings className="w-3.5 h-3.5 mr-1" /> Item Settings</TabsTrigger>
            <TabsTrigger value="exceptions" data-testid="inv-tab-exceptions"><AlertTriangle className="w-3.5 h-3.5 mr-1" /> Exceptions</TabsTrigger>
            <TabsTrigger value="demand" data-testid="inv-tab-demand"><TrendingDown className="w-3.5 h-3.5 mr-1" /> Demand</TabsTrigger>
            <TabsTrigger value="coverage" data-testid="inv-tab-coverage"><ShieldCheck className="w-3.5 h-3.5 mr-1" /> Supply Coverage</TabsTrigger>
            <TabsTrigger value="action-center" data-testid="inv-tab-action-center"><Zap className="w-3.5 h-3.5 mr-1" /> Action Center</TabsTrigger>
            <TabsTrigger value="po-drafts" data-testid="inv-tab-po-drafts"><FileText className="w-3.5 h-3.5 mr-1" /> PO Drafts</TabsTrigger>
          </TabsList>
          <div className="flex gap-2">
            {tab === 'balances' && (
              <div className="relative w-48">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <Input placeholder="Filter items..." value={search} onChange={e => setSearch(e.target.value)} className="pl-8 h-8 text-xs" data-testid="inv-balance-search" />
              </div>
            )}
            {tab === 'balances' && (
              <Button variant="outline" size="sm" className="h-8 text-xs"
                onClick={() => { window.open(`${API}/api/inventory-ledger/export?customer_id=${cid}${search ? '&item=' + encodeURIComponent(search) : ''}`, '_blank'); }}
                data-testid="inv-export-csv-btn">
                <Download className="w-3.5 h-3.5 mr-1" /> Export CSV
              </Button>
            )}
            {tab === 'balances' && (
              <Button variant="outline" size="sm" className="h-8 text-xs"
                onClick={() => setShowImportForm(true)}
                data-testid="inv-import-csv-btn">
                <Upload className="w-3.5 h-3.5 mr-1" /> Import CSV
              </Button>
            )}
            {tab === 'balances' && (
              <Button variant="outline" size="sm" className="h-8 text-xs"
                onClick={() => { window.open(`${API}/api/inventory-ledger/snapshot/export?customer_id=${cid}&include_reorders=true${search ? '&item=' + encodeURIComponent(search) : ''}`, '_blank'); }}
                data-testid="inv-export-snapshot-btn">
                <FileText className="w-3.5 h-3.5 mr-1" /> Export Snapshot
              </Button>
            )}
            {tab === 'movements' && (
              <Button size="sm" className="h-8 text-xs" onClick={() => setShowMovementForm(true)} data-testid="inv-new-movement-btn">
                <Plus className="w-3.5 h-3.5 mr-1" /> New Movement
              </Button>
            )}
            {tab === 'incoming' && (
              <Button size="sm" className="h-8 text-xs" onClick={() => setShowIncomingForm(true)} data-testid="inv-new-incoming-btn">
                <Plus className="w-3.5 h-3.5 mr-1" /> Add Incoming
              </Button>
            )}
          </div>
        </div>

        <TabsContent value="balances">
          <BalanceTable balances={filteredBalances} loading={loading} onItemClick={(item) => setDetailItem({ item, customerId: cid })} />
        </TabsContent>
        <TabsContent value="movements">
          <MovementTable movements={movements} total={movementTotal} />
        </TabsContent>
        <TabsContent value="incoming">
          <IncomingTable records={incoming} customerId={cid} onUpdate={refresh} />
        </TabsContent>
        <TabsContent value="reorder">
          <ReorderPanel customerId={cid} onSupplyCreated={refresh} onItemClick={(item) => setDetailItem({ item, customerId: cid })} />
        </TabsContent>
        <TabsContent value="settings">
          <ItemSettingsPanel customerId={cid} />
        </TabsContent>
        <TabsContent value="exceptions">
          <ExceptionsPanel customerId={cid} onHistoryClick={(item) => setDetailItem({ item, customerId: cid })} onSupplyCreated={refresh} />
        </TabsContent>
        <TabsContent value="demand">
          <DemandPanel customerId={cid} onItemClick={(item) => setDetailItem({ item, customerId: cid })} onSupplyCreated={refresh} />
        </TabsContent>
        <TabsContent value="coverage">
          <SupplyCoveragePanel customerId={cid} onItemClick={(item) => setDetailItem({ item, customerId: cid })} onSupplyCreated={refresh} />
        </TabsContent>
        <TabsContent value="action-center">
          <ActionCenterPanel customerId={cid} onItemClick={(item) => setDetailItem({ item, customerId: cid })} onSupplyCreated={refresh} onHistoryClick={(item) => { setDetailItem(null); setHistoryItem({ item, customerId: cid }); }} onViewDraft={(id) => setViewDraftId(id)} />
        </TabsContent>
        <TabsContent value="po-drafts">
          <PODraftsPanel customerId={cid} onViewDraft={(id) => setViewDraftId(id)} />
        </TabsContent>
      </Tabs>

      {/* Movement Form Dialog */}
      {showMovementForm && (
        <MovementFormDialog open={showMovementForm} customerId={cid} onClose={() => setShowMovementForm(false)} onCreated={() => { setShowMovementForm(false); refresh(); }} />
      )}
      {showIncomingForm && (
        <IncomingFormDialog open={showIncomingForm} customerId={cid} onClose={() => setShowIncomingForm(false)} onCreated={() => { setShowIncomingForm(false); refresh(); }} />
      )}
      {showImportForm && (
        <ImportCSVDialog open={showImportForm} customerId={cid} onClose={() => setShowImportForm(false)} onImported={() => { setShowImportForm(false); refresh(); }} />
      )}
      {/* Item Detail Drawer */}
      {detailItem && (
        <ItemDetailDrawer
          item={detailItem.item}
          customerId={detailItem.customerId}
          onClose={() => setDetailItem(null)}
          onOpenFullHistory={(item) => { setDetailItem(null); setHistoryItem({ item, customerId: cid }); }}
          onRefresh={refresh}
          onViewDraft={(id) => { setDetailItem(null); setViewDraftId(id); }}
        />
      )}
      {/* Item History Modal */}
      {historyItem && (
        <ItemHistoryModal
          item={historyItem.item}
          customerId={historyItem.customerId}
          onClose={() => setHistoryItem(null)}
        />
      )}
      {/* PO Draft Detail Drawer */}
      {viewDraftId && (
        <PODraftDetailDrawer draftId={viewDraftId} onClose={() => setViewDraftId(null)} onSupplyCreated={refresh} />
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* REORDER RECOMMENDATIONS                                          */
/* ════════════════════════════════════════════════════════════════ */

function ReorderPanel({ customerId, onSupplyCreated, onItemClick }) {
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(null);

  const fetchRecs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/reorder-recommendations?customer_id=${customerId}`);
      const data = await res.json();
      setRecs(data.recommendations || []);
    } catch { toast.error('Failed to load recommendations'); }
    finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { fetchRecs(); }, [fetchRecs]);

  const createSupply = async (rec) => {
    setCreating(rec.item);
    try {
      // Need an SO reference — use "REORDER-<item>" as a generic reference
      // This endpoint requires an existing order_commitment, so we use the incoming supply endpoint directly
      const payload = {
        item: rec.item,
        item_description: rec.item_description,
        warehouse: rec.warehouse,
        ownership_type: rec.ownership_type,
        incoming_qty: rec.recommended_qty,
        unit_of_measure: rec.unit_of_measure,
        source_reference: `REORDER-${rec.item}`,
        status: 'planned',
      };
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (res.ok) {
        toast.success(`Incoming supply created for ${rec.item} (${rec.recommended_qty} ${rec.unit_of_measure})`);
        onSupplyCreated();
        fetchRecs();
      } else {
        const d = await res.json();
        toast.error(d.detail || 'Failed to create supply');
      }
    } catch { toast.error('Failed to create supply'); }
    finally { setCreating(null); }
  };

  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;
  if (!recs.length) return (
    <div className="py-10 text-center text-muted-foreground" data-testid="inv-reorder-empty">
      <Package className="w-8 h-8 mx-auto mb-2 opacity-30" />
      <p className="text-sm font-medium">No reorder recommendations</p>
      <p className="text-xs mt-1">All items have healthy inventory levels.</p>
    </div>
  );

  return (
    <Card className="border border-border" data-testid="inv-reorder-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <AlertTriangle className="w-3.5 h-3.5 inline mr-1 text-amber-500" />
            {recs.length} item{recs.length !== 1 ? 's' : ''} need replenishment
          </CardTitle>
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={fetchRecs}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Item</th>
              <th className="text-right py-2 px-3 font-medium">On Hand</th>
              <th className="text-right py-2 px-3 font-medium">Incoming</th>
              <th className="text-right py-2 px-3 font-medium">Committed</th>
              <th className="text-right py-2 px-3 font-medium">Available</th>
              <th className="text-center py-2 px-3 font-medium">Status</th>
              <th className="text-right py-2 px-3 font-medium">Threshold</th>
              <th className="text-right py-2 px-3 font-medium">Buffer</th>
              <th className="text-right py-2 px-3 font-medium">Recommended Qty</th>
              <th className="text-right py-2 px-3 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {recs.map((r, i) => (
              <tr key={i} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-reorder-row-${i}`}>
                <td className="py-1.5 px-3">
                  <span className="font-mono font-medium cursor-pointer hover:underline text-blue-600" onClick={() => onItemClick?.(r.item)} data-testid={`inv-reorder-item-${i}`}>{r.item}</span>
                  {r.item_description && <span className="text-[10px] text-muted-foreground block truncate max-w-[180px]">{r.item_description}</span>}
                </td>
                <td className="py-1.5 px-3 text-right font-mono">{r.on_hand.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-right font-mono">{r.incoming > 0 ? <span className="text-sky-600">+{r.incoming.toLocaleString()}</span> : '-'}</td>
                <td className="py-1.5 px-3 text-right font-mono">{r.committed > 0 ? <span className="text-amber-600">-{r.committed.toLocaleString()}</span> : '-'}</td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${r.available < 0 ? 'text-red-600' : ''}`}>{r.available.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-center">
                  <Badge variant={r.status === 'SHORT' ? 'destructive' : 'outline'} className={`text-[9px] ${r.status === 'LOW' ? 'border-amber-300 text-amber-600' : ''}`}>
                    {r.status}
                  </Badge>
                </td>
                <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{r.reorder_threshold ?? 0}</td>
                <td className="py-1.5 px-3 text-right font-mono text-muted-foreground">{r.safety_buffer ?? 10}</td>
                <td className="py-1.5 px-3 text-right font-mono font-bold text-emerald-600">{r.recommended_qty.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-right">
                  <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5"
                    disabled={creating === r.item}
                    onClick={() => createSupply(r)}
                    data-testid={`inv-reorder-create-${i}`}>
                    {creating === r.item ? <Loader2 className="w-3 h-3 animate-spin" /> : <Plus className="w-3 h-3 mr-0.5" />}
                    Supply
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* ITEM SETTINGS PANEL                                              */
/* ════════════════════════════════════════════════════════════════ */

function ItemSettingsPanel({ customerId }) {
  const [settings, setSettings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editRow, setEditRow] = useState(null); // {item, reorder_threshold, safety_buffer, notes}
  const [saving, setSaving] = useState(false);

  const fetchSettings = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-items/settings?customer_id=${customerId}`);
      const data = await res.json();
      setSettings(data.settings || []);
    } catch { toast.error('Failed to load settings'); }
    finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { fetchSettings(); }, [fetchSettings]);

  const saveRow = async () => {
    if (!editRow?.item) return;
    if (editRow.reorder_threshold < 0 || editRow.safety_buffer < 0) {
      toast.error('Threshold and buffer must not be negative');
      return;
    }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/inventory-items/settings`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_id: customerId, ...editRow }),
      });
      if (res.ok) {
        toast.success(`Settings saved for ${editRow.item}`);
        setEditRow(null);
        fetchSettings();
      } else {
        const d = await res.json();
        toast.error(d.detail || 'Save failed');
      }
    } catch { toast.error('Save failed'); }
    finally { setSaving(false); }
  };

  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;

  return (
    <div className="space-y-3" data-testid="inv-settings-panel">
      {/* Add/Edit Form */}
      <Card className="border border-border">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            {editRow ? `Edit: ${editRow.item}` : 'Add Item Settings'}
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-4 gap-3">
            <div>
              <Label className="text-xs">Item</Label>
              <Input className="h-8 text-xs font-mono" value={editRow?.item || ''} disabled={!!editRow?.existing}
                onChange={e => setEditRow(prev => ({ ...prev, item: e.target.value }))}
                placeholder="PET-32" data-testid="inv-settings-item" />
            </div>
            <div>
              <Label className="text-xs">Reorder Threshold</Label>
              <Input type="number" className="h-8 text-xs font-mono" value={editRow?.reorder_threshold ?? ''}
                onChange={e => setEditRow(prev => ({ ...prev, reorder_threshold: parseFloat(e.target.value) || 0 }))}
                placeholder="100" data-testid="inv-settings-threshold" />
            </div>
            <div>
              <Label className="text-xs">Safety Buffer</Label>
              <Input type="number" className="h-8 text-xs font-mono" value={editRow?.safety_buffer ?? ''}
                onChange={e => setEditRow(prev => ({ ...prev, safety_buffer: parseFloat(e.target.value) || 0 }))}
                placeholder="25" data-testid="inv-settings-buffer" />
            </div>
            <div>
              <Label className="text-xs">Notes</Label>
              <Input className="h-8 text-xs" value={editRow?.notes || ''}
                onChange={e => setEditRow(prev => ({ ...prev, notes: e.target.value }))}
                placeholder="Core stock item" data-testid="inv-settings-notes" />
            </div>
          </div>
          <div className="flex gap-2 mt-3">
            <Button size="sm" className="h-7 text-xs" onClick={saveRow} disabled={saving || !editRow?.item} data-testid="inv-settings-save">
              {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Plus className="w-3 h-3 mr-1" />}
              {editRow?.existing ? 'Update' : 'Save'} Settings
            </Button>
            {editRow && (
              <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setEditRow(null)}>Cancel</Button>
            )}
            {!editRow && (
              <Button variant="outline" size="sm" className="h-7 text-xs" onClick={() => setEditRow({ item: '', reorder_threshold: 100, safety_buffer: 25, notes: '' })}>
                <Plus className="w-3 h-3 mr-1" /> New
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Settings Table */}
      {settings.length > 0 && (
        <Card className="border border-border" data-testid="inv-settings-table">
          <CardContent className="p-0 overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
                  <th className="text-left py-2 px-3 font-medium">Item</th>
                  <th className="text-right py-2 px-3 font-medium">Reorder Threshold</th>
                  <th className="text-right py-2 px-3 font-medium">Safety Buffer</th>
                  <th className="text-left py-2 px-3 font-medium">Notes</th>
                  <th className="text-left py-2 px-3 font-medium">Updated</th>
                  <th className="w-8"></th>
                </tr>
              </thead>
              <tbody>
                {settings.map((s, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-settings-row-${i}`}>
                    <td className="py-1.5 px-3 font-mono font-medium">{s.item}</td>
                    <td className="py-1.5 px-3 text-right font-mono">{s.reorder_threshold}</td>
                    <td className="py-1.5 px-3 text-right font-mono">{s.safety_buffer}</td>
                    <td className="py-1.5 px-3 text-muted-foreground truncate max-w-[200px]">{s.notes || '-'}</td>
                    <td className="py-1.5 px-3 text-muted-foreground font-mono">{s.updated_at ? new Date(s.updated_at).toLocaleDateString() : '-'}</td>
                    <td className="py-1.5 px-1">
                      <Button variant="ghost" size="sm" className="h-5 w-5 p-0"
                        onClick={() => setEditRow({ ...s, existing: true })}
                        data-testid={`inv-settings-edit-${i}`}>
                        <Pencil className="w-3 h-3" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* EXCEPTIONS PANEL                                                  */
/* ════════════════════════════════════════════════════════════════ */

const EXC_BADGES = {
  short: { label: 'SHORT', cls: 'bg-red-500/10 text-red-600 border-red-500/20' },
  low: { label: 'LOW', cls: 'bg-amber-500/10 text-amber-600 border-amber-500/20' },
  reorder: { label: 'REORDER', cls: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  no_incoming: { label: 'NO INCOMING', cls: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
};

function ExceptionsPanel({ customerId, onHistoryClick, onSupplyCreated }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ customer_id: customerId });
      if (filter) q.set('exception_type', filter);
      const res = await fetch(`${API}/api/inventory-ledger/exceptions?${q}`);
      setData(await res.json());
    } catch { toast.error('Failed to load exceptions'); }
    finally { setLoading(false); }
  }, [customerId, filter]);

  useEffect(() => { load(); }, [load]);

  const createSupply = async (item) => {
    setCreating(item);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_no: item, quantity: 0, source_reference: `EXCEPTION-${item}`, notes: 'Created from exceptions view' }),
      });
      if (res.ok) { toast.success(`Incoming supply created for ${item}`); onSupplyCreated?.(); load(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setCreating(null); }
  };

  const summary = data?.exception_summary || {};
  const exceptions = data?.exceptions || [];
  const cards = [
    { key: 'short', label: 'SHORT', count: summary.short_count || 0, color: 'text-red-500 border-red-500/30' },
    { key: 'low', label: 'LOW', count: summary.low_count || 0, color: 'text-amber-500 border-amber-500/30' },
    { key: 'reorder', label: 'Reorder', count: summary.reorder_count || 0, color: 'text-orange-500 border-orange-500/30' },
    { key: 'no_incoming', label: 'No Incoming', count: summary.no_incoming_count || 0, color: 'text-violet-500 border-violet-500/30' },
  ];

  return (
    <div className="space-y-4" data-testid="inv-exceptions-panel">
      {/* Exception Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3" data-testid="inv-exception-summary">
        {cards.map(c => (
          <button key={c.key}
            onClick={() => setFilter(f => f === c.key ? '' : c.key)}
            className={`border rounded-md p-3 text-left transition-all ${filter === c.key ? 'ring-2 ring-primary bg-muted/50' : 'bg-muted/20 hover:bg-muted/40'}`}
            data-testid={`inv-exc-card-${c.key}`}>
            <p className={`text-2xl font-bold ${c.color}`}>{c.count}</p>
            <p className="text-[10px] text-muted-foreground">{c.label}{filter === c.key ? ' (active)' : ''}</p>
          </button>
        ))}
      </div>

      {/* Exception Table */}
      <Card className="border-border/50">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-10"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
          ) : exceptions.length === 0 ? (
            <div className="text-center py-10 text-sm text-muted-foreground" data-testid="inv-exceptions-empty">No exceptions found{filter ? ` for "${filter}"` : ''}.</div>
          ) : (
            <table className="w-full text-xs" data-testid="inv-exceptions-table">
              <thead className="border-b border-border/50 bg-muted/30">
                <tr>
                  <th className="p-2 text-left font-medium">Item</th>
                  <th className="p-2 text-left font-medium">Warehouse</th>
                  <th className="p-2 text-right font-medium">On Hand</th>
                  <th className="p-2 text-right font-medium">Incoming</th>
                  <th className="p-2 text-right font-medium">Committed</th>
                  <th className="p-2 text-right font-medium">Available</th>
                  <th className="p-2 text-left font-medium">Exceptions</th>
                  <th className="p-2 text-right font-medium">Rec. Qty</th>
                  <th className="p-2 text-center font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {exceptions.map((e, i) => (
                  <tr key={i} className="border-b border-border/20 hover:bg-muted/20" data-testid={`inv-exc-row-${i}`}>
                    <td className="p-2 font-mono cursor-pointer hover:underline text-blue-600" onClick={() => onHistoryClick?.(e.item)} data-testid={`inv-exc-item-${i}`}>{e.item}</td>
                    <td className="p-2 text-muted-foreground">{e.warehouse || '—'}</td>
                    <td className="p-2 text-right">{e.on_hand?.toLocaleString()}</td>
                    <td className="p-2 text-right">{e.incoming?.toLocaleString()}</td>
                    <td className="p-2 text-right">{e.committed?.toLocaleString()}</td>
                    <td className={`p-2 text-right font-bold ${e.available < 0 ? 'text-red-500' : ''}`}>{e.available?.toLocaleString()}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {e.exception_types?.map(t => (
                          <span key={t} className={`text-[9px] px-1.5 py-0.5 rounded border font-medium ${EXC_BADGES[t]?.cls || ''}`}>
                            {EXC_BADGES[t]?.label || t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="p-2 text-right font-bold">{e.recommended_qty != null ? e.recommended_qty.toLocaleString() : '—'}</td>
                    <td className="p-2 text-center">
                      <div className="flex justify-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onHistoryClick?.(e.item)} title="View history"
                          data-testid={`inv-exc-history-${i}`}>
                          <History className="w-3 h-3" />
                        </Button>
                        {(e.exception_types?.includes('short') || e.exception_types?.includes('no_incoming')) && (
                          <Button variant="ghost" size="icon" className="h-6 w-6" disabled={creating === e.item}
                            onClick={() => createSupply(e.item)} title="Create incoming supply"
                            data-testid={`inv-exc-supply-${i}`}>
                            {creating === e.item ? <Loader2 className="w-3 h-3 animate-spin" /> : <Truck className="w-3 h-3" />}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* DEMAND PANEL                                                      */
/* ════════════════════════════════════════════════════════════════ */

function DemandPanel({ customerId, onItemClick, onSupplyCreated }) {
  const [signals, setSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/demand-signals?customer_id=${customerId}`);
      const data = await res.json();
      setSignals(data.demand_signals || []);
    } catch { toast.error('Failed to load demand signals'); }
    finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  const createSupply = async (item) => {
    setCreating(item);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_no: item, quantity: 0, source_reference: `DEMAND-${item}`, notes: 'Created from demand view' }),
      });
      if (res.ok) { toast.success(`Incoming supply created for ${item}`); onSupplyCreated?.(); load(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setCreating(null); }
  };

  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;
  if (!signals.length) return (
    <div className="py-10 text-center text-muted-foreground" data-testid="inv-demand-empty">
      <Package className="w-8 h-8 mx-auto mb-2 opacity-30" />
      <p className="text-sm font-medium">No demand signals</p>
      <p className="text-xs mt-1">No open order commitments found.</p>
    </div>
  );

  return (
    <Card className="border border-border" data-testid="inv-demand-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <TrendingDown className="w-3.5 h-3.5 inline mr-1 text-blue-500" />
            {signals.length} item{signals.length !== 1 ? 's' : ''} with open demand
          </CardTitle>
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={load}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs" data-testid="inv-demand-table">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Item</th>
              <th className="text-right py-2 px-3 font-medium">Open Order Qty</th>
              <th className="text-right py-2 px-3 font-medium">On Hand</th>
              <th className="text-right py-2 px-3 font-medium">Incoming</th>
              <th className="text-right py-2 px-3 font-medium">Available</th>
              <th className="text-right py-2 px-3 font-medium">Demand Gap</th>
              <th className="text-center py-2 px-3 font-medium">Status</th>
              <th className="text-right py-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {signals.map((s, i) => (
              <tr key={i} className={`border-b border-border/50 hover:bg-muted/20 ${s.demand_gap > 0 ? 'bg-red-500/5' : ''}`} data-testid={`inv-demand-row-${i}`}>
                <td className="py-1.5 px-3">
                  <span className="font-mono font-medium cursor-pointer hover:underline text-blue-600" onClick={() => onItemClick?.(s.item)} data-testid={`inv-demand-item-${i}`}>{s.item}</span>
                  {s.item_description && <span className="text-[10px] text-muted-foreground block truncate max-w-[180px]">{s.item_description}</span>}
                </td>
                <td className="py-1.5 px-3 text-right font-mono font-bold text-blue-600">{s.total_open_order_qty?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-right font-mono">{s.on_hand?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-right font-mono">{s.incoming > 0 ? <span className="text-sky-600">+{s.incoming?.toLocaleString()}</span> : '—'}</td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${s.available < 0 ? 'text-red-600' : ''}`}>{s.available?.toLocaleString()}</td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${s.demand_gap > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{s.demand_gap > 0 ? '+' : ''}{s.demand_gap?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-center">
                  <Badge variant={s.status === 'SHORT' ? 'destructive' : 'outline'} className={`text-[9px] ${s.status === 'LOW' ? 'border-amber-300 text-amber-600' : ''}`}>
                    {s.status}
                  </Badge>
                </td>
                <td className="py-1.5 px-3 text-right">
                  <div className="flex justify-end gap-1">
                    {s.demand_gap > 0 && (
                      <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5"
                        disabled={creating === s.item}
                        onClick={() => createSupply(s.item)}
                        data-testid={`inv-demand-supply-${i}`}>
                        {creating === s.item ? <Loader2 className="w-3 h-3 animate-spin" /> : <Truck className="w-3 h-3 mr-0.5" />}
                        Supply
                      </Button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* ACTION CENTER PANEL                                               */
/* ════════════════════════════════════════════════════════════════ */

const ACTION_BADGES = {
  shortage: { label: 'SHORTAGE', cls: 'bg-red-500/10 text-red-600 border-red-500/20' },
  coverage_risk: { label: 'COVERAGE RISK', cls: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
  demand_gap: { label: 'DEMAND GAP', cls: 'bg-amber-500/10 text-amber-600 border-amber-500/20' },
  reorder: { label: 'REORDER', cls: 'bg-blue-500/10 text-blue-600 border-blue-500/20' },
  no_incoming: { label: 'NO INCOMING', cls: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
};

function ActionCenterPanel({ customerId, onItemClick, onSupplyCreated, onHistoryClick, onViewDraft }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState('');
  const [creating, setCreating] = useState(null);
  const [selected, setSelected] = useState(new Set());
  const [drafting, setDrafting] = useState(false);
  const [draftResult, setDraftResult] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const q = new URLSearchParams({ customer_id: customerId });
      if (filter) q.set('action_type', filter);
      const res = await fetch(`${API}/api/inventory-ledger/action-center?${q}`);
      setData(await res.json());
    } catch { toast.error('Failed to load action center'); }
    finally { setLoading(false); }
  }, [customerId, filter]);

  useEffect(() => { load(); }, [load]);

  const createSupply = async (item) => {
    setCreating(item);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_no: item, quantity: 0, source_reference: `ACTION-${item}`, notes: 'Created from action center' }),
      });
      if (res.ok) { toast.success(`Incoming supply created for ${item}`); onSupplyCreated?.(); load(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setCreating(null); }
  };

  // Derived data from response
  const summary = data?.action_summary || {};
  const actions = data?.actions || [];
  
  // Items eligible for PO draft (reorder, coverage_risk, or shortage action types)
  const eligibleForPO = actions.filter(a => a.action_types?.some(t => ['reorder', 'coverage_risk', 'shortage'].includes(t)));
  const selectedEligible = [...selected].filter(item => eligibleForPO.some(a => a.item === item));

  const generatePO = async () => {
    if (!selectedEligible.length) { toast.error('Select items to generate PO draft'); return; }
    setDrafting(true);
    setDraftResult(null);
    try {
      const items = selectedEligible.map(item => {
        const a = actions.find(x => x.item === item);
        return { item, recommended_qty: a?.recommended_qty || Math.abs(a?.available || 0) + 10, source: 'action_center' };
      });
      const res = await fetch(`${API}/api/inventory-ledger/generate-po-draft`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ customer_id: customerId, items }),
      });
      const respData = await res.json();
      if (res.ok) {
        setDraftResult(respData);
        setSelected(new Set());
        toast.success(`PO Draft ${respData.po_draft_id} created with ${respData.total_lines} line(s)`);
      } else {
        toast.error(respData.detail || 'Failed to generate PO draft');
      }
    } catch { toast.error('Failed to generate PO draft'); }
    finally { setDrafting(false); }
  };

  const toggleSelect = (item) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(item) ? next.delete(item) : next.add(item);
      return next;
    });
  };

  const toggleAll = () => {
    if (selected.size === eligibleForPO.length) setSelected(new Set());
    else setSelected(new Set(eligibleForPO.map(a => a.item)));
  };

  const cards = [
    { key: 'shortage', label: 'Shortages', count: summary.shortage_count || 0, color: 'text-red-500 border-red-500/30' },
    { key: 'coverage_risk', label: 'Coverage Risk', count: summary.coverage_risk_count || 0, color: 'text-orange-500 border-orange-500/30' },
    { key: 'demand_gap', label: 'Demand Gaps', count: summary.demand_gap_count || 0, color: 'text-amber-500 border-amber-500/30' },
    { key: 'reorder', label: 'Reorder', count: summary.reorder_count || 0, color: 'text-blue-500 border-blue-500/30' },
    { key: 'no_incoming', label: 'No Incoming', count: summary.no_incoming_count || 0, color: 'text-violet-500 border-violet-500/30' },
  ];

  return (
    <div className="space-y-4" data-testid="inv-action-center-panel">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-5 gap-3" data-testid="inv-action-summary">
        {cards.map(c => (
          <button key={c.key}
            onClick={() => setFilter(f => f === c.key ? '' : c.key)}
            className={`border rounded-md p-3 text-left transition-all ${filter === c.key ? 'ring-2 ring-primary bg-muted/50' : 'bg-muted/20 hover:bg-muted/40'}`}
            data-testid={`inv-action-card-${c.key}`}>
            <p className={`text-2xl font-bold ${c.color}`}>{c.count}</p>
            <p className="text-[10px] text-muted-foreground">{c.label}{filter === c.key ? ' (active)' : ''}</p>
          </button>
        ))}
      </div>
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">{summary.total_action_items || 0} total action items</p>
        <div className="flex gap-2">
          {selectedEligible.length > 0 && (
            <Button size="sm" className="h-6 text-[10px]" onClick={generatePO} disabled={drafting} data-testid="inv-generate-po-btn">
              {drafting ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <FileText className="w-3 h-3 mr-1" />}
              Generate PO Draft ({selectedEligible.length})
            </Button>
          )}
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={load}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </div>

      {/* PO Draft Result */}
      {draftResult && (
        <div className="border border-emerald-500/30 bg-emerald-500/5 rounded-md p-3 space-y-1" data-testid="inv-po-draft-result">
          <div className="flex items-center justify-between">
            <p className="text-xs font-bold text-emerald-600">PO Draft Generated</p>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" className="h-5 text-[10px]" onClick={() => onViewDraft?.(draftResult.po_draft_id)} data-testid="inv-po-draft-view">View Draft</Button>
              <Button variant="ghost" size="sm" className="h-5 text-[10px]" onClick={() => setDraftResult(null)}>Dismiss</Button>
            </div>
          </div>
          <p className="text-xs">Draft ID: <span className="font-mono font-bold" data-testid="inv-po-draft-id">{draftResult.po_draft_id}</span></p>
          <p className="text-xs">Lines: {draftResult.total_lines} | Total Qty: {draftResult.total_qty?.toLocaleString()}</p>
          <div className="text-[10px] text-muted-foreground">
            {draftResult.lines?.map((l, i) => (
              <span key={i} className="mr-3">{l.item}: {l.qty}</span>
            ))}
          </div>
        </div>
      )}

      {/* Action Table */}
      <Card className="border-border/50">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-10"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
          ) : actions.length === 0 ? (
            <div className="text-center py-10 text-sm text-muted-foreground" data-testid="inv-action-center-empty">No action items found{filter ? ` for "${filter}"` : ''}.</div>
          ) : (
            <table className="w-full text-xs" data-testid="inv-action-center-table">
              <thead className="border-b border-border/50 bg-muted/30">
                <tr>
                  <th className="p-2 text-center w-8">
                    <input type="checkbox" className="rounded" checked={selected.size > 0 && selected.size === eligibleForPO.length} onChange={toggleAll} data-testid="inv-action-select-all" />
                  </th>
                  <th className="p-2 text-left font-medium">Item</th>
                  <th className="p-2 text-right font-medium">On Hand</th>
                  <th className="p-2 text-right font-medium">Incoming</th>
                  <th className="p-2 text-right font-medium">Committed</th>
                  <th className="p-2 text-right font-medium">Available</th>
                  <th className="p-2 text-left font-medium">Actions Needed</th>
                  <th className="p-2 text-right font-medium">Rec. Qty</th>
                  <th className="p-2 text-center font-medium">Priority</th>
                  <th className="p-2 text-center font-medium">Ops</th>
                </tr>
              </thead>
              <tbody>
                {actions.map((a, i) => (
                  <tr key={i} className={`border-b border-border/20 hover:bg-muted/20 ${a.action_types?.includes('shortage') ? 'bg-red-500/5' : a.action_types?.includes('coverage_risk') ? 'bg-orange-500/5' : ''}`} data-testid={`inv-action-row-${i}`}>
                    <td className="p-2 text-center">
                      {eligibleForPO.some(e => e.item === a.item) && (
                        <input type="checkbox" className="rounded" checked={selected.has(a.item)} onChange={() => toggleSelect(a.item)} data-testid={`inv-action-select-${i}`} />
                      )}
                    </td>
                    <td className="p-2">
                      <span className="font-mono font-medium cursor-pointer hover:underline text-blue-600" onClick={() => onItemClick?.(a.item)} data-testid={`inv-action-item-${i}`}>{a.item}</span>
                      {a.item_description && <span className="text-[10px] text-muted-foreground block truncate max-w-[150px]">{a.item_description}</span>}
                    </td>
                    <td className="p-2 text-right font-mono">{a.on_hand?.toLocaleString()}</td>
                    <td className="p-2 text-right font-mono">{a.incoming > 0 ? <span className="text-sky-600">+{a.incoming?.toLocaleString()}</span> : '—'}</td>
                    <td className="p-2 text-right font-mono">{a.committed > 0 ? a.committed?.toLocaleString() : '—'}</td>
                    <td className={`p-2 text-right font-mono font-bold ${a.available < 0 ? 'text-red-500' : ''}`}>{a.available?.toLocaleString()}</td>
                    <td className="p-2">
                      <div className="flex flex-wrap gap-1">
                        {a.action_types?.map(t => (
                          <span key={t} className={`text-[9px] px-1.5 py-0.5 rounded border font-medium ${ACTION_BADGES[t]?.cls || ''}`}>
                            {ACTION_BADGES[t]?.label || t}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className="p-2 text-right font-bold">{a.recommended_qty != null ? a.recommended_qty.toLocaleString() : '—'}</td>
                    <td className="p-2 text-center">
                      <span className={`text-[10px] font-bold ${a.priority_score >= 50 ? 'text-red-600' : a.priority_score >= 30 ? 'text-orange-600' : 'text-amber-600'}`} data-testid={`inv-action-priority-${i}`}>
                        {a.priority_score}
                      </span>
                    </td>
                    <td className="p-2 text-center">
                      <div className="flex justify-center gap-1">
                        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={() => onHistoryClick?.(a.item)} title="Full history"
                          data-testid={`inv-action-history-${i}`}>
                          <History className="w-3 h-3" />
                        </Button>
                        {(a.action_types?.includes('shortage') || a.action_types?.includes('coverage_risk') || a.action_types?.includes('reorder')) && (
                          <Button variant="ghost" size="icon" className="h-6 w-6" disabled={creating === a.item}
                            onClick={() => createSupply(a.item)} title="Create incoming supply"
                            data-testid={`inv-action-supply-${i}`}>
                            {creating === a.item ? <Loader2 className="w-3 h-3 animate-spin" /> : <Truck className="w-3 h-3" />}
                          </Button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* SUPPLY COVERAGE PANEL                                             */
/* ════════════════════════════════════════════════════════════════ */

function SupplyCoveragePanel({ customerId, onItemClick, onSupplyCreated }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/supply-coverage?customer_id=${customerId}`);
      const data = await res.json();
      setRows(data.coverage || []);
    } catch { toast.error('Failed to load supply coverage'); }
    finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  const createSupply = async (item) => {
    setCreating(item);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_no: item, quantity: 0, source_reference: `COVERAGE-${item}`, notes: 'Created from supply coverage view' }),
      });
      if (res.ok) { toast.success(`Incoming supply created for ${item}`); onSupplyCreated?.(); load(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setCreating(null); }
  };

  const atRiskCount = rows.filter(r => r.coverage_status === 'at_risk').length;

  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;
  if (!rows.length) return (
    <div className="py-10 text-center text-muted-foreground" data-testid="inv-coverage-empty">
      <ShieldCheck className="w-8 h-8 mx-auto mb-2 opacity-30" />
      <p className="text-sm font-medium">No committed demand</p>
      <p className="text-xs mt-1">No open order commitments to evaluate coverage for.</p>
    </div>
  );

  return (
    <Card className="border border-border" data-testid="inv-coverage-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <ShieldCheck className="w-3.5 h-3.5 inline mr-1 text-blue-500" />
            {rows.length} item{rows.length !== 1 ? 's' : ''} with committed demand
            {atRiskCount > 0 && <span className="ml-2 text-red-500 font-bold">{atRiskCount} at risk</span>}
          </CardTitle>
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={load}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs" data-testid="inv-coverage-table">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Item</th>
              <th className="text-right py-2 px-3 font-medium">On Hand</th>
              <th className="text-right py-2 px-3 font-medium">Incoming</th>
              <th className="text-right py-2 px-3 font-medium">Committed</th>
              <th className="text-right py-2 px-3 font-medium">Available</th>
              <th className="text-right py-2 px-3 font-medium">Coverage</th>
              <th className="text-center py-2 px-3 font-medium">Coverage Status</th>
              <th className="text-right py-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={`border-b border-border/50 hover:bg-muted/20 ${r.coverage_status === 'at_risk' ? 'bg-red-500/5' : ''}`} data-testid={`inv-coverage-row-${i}`}>
                <td className="py-1.5 px-3">
                  <span className="font-mono font-medium cursor-pointer hover:underline text-blue-600" onClick={() => onItemClick?.(r.item)} data-testid={`inv-coverage-item-${i}`}>{r.item}</span>
                  {r.item_description && <span className="text-[10px] text-muted-foreground block truncate max-w-[180px]">{r.item_description}</span>}
                </td>
                <td className="py-1.5 px-3 text-right font-mono">{r.on_hand?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-right font-mono">{r.incoming > 0 ? <span className="text-sky-600">+{r.incoming?.toLocaleString()}</span> : '—'}</td>
                <td className="py-1.5 px-3 text-right font-mono text-amber-600">{r.committed?.toLocaleString()}</td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${r.available < 0 ? 'text-red-600' : ''}`}>{r.available?.toLocaleString()}</td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${r.coverage < 0 ? 'text-red-600' : 'text-emerald-600'}`}>{r.coverage?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-center">
                  <Badge variant={r.coverage_status === 'at_risk' ? 'destructive' : 'outline'} className={`text-[9px] ${r.coverage_status === 'covered' ? 'border-emerald-300 text-emerald-600' : ''}`} data-testid={`inv-coverage-status-${i}`}>
                    {r.coverage_status === 'at_risk' ? 'AT RISK' : 'COVERED'}
                  </Badge>
                </td>
                <td className="py-1.5 px-3 text-right">
                  {r.coverage_status === 'at_risk' && (
                    <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5"
                      disabled={creating === r.item}
                      onClick={() => createSupply(r.item)}
                      data-testid={`inv-coverage-supply-${i}`}>
                      {creating === r.item ? <Loader2 className="w-3 h-3 animate-spin" /> : <Truck className="w-3 h-3 mr-0.5" />}
                      Supply
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* PO DRAFTS PANEL                                                   */
/* ════════════════════════════════════════════════════════════════ */

function PODraftsPanel({ customerId, onViewDraft }) {
  const [drafts, setDrafts] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/po-drafts?customer_id=${customerId}`);
      const data = await res.json();
      setDrafts(data.drafts || []);
    } catch { toast.error('Failed to load PO drafts'); }
    finally { setLoading(false); }
  }, [customerId]);

  useEffect(() => { load(); }, [load]);

  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;
  if (!drafts.length) return (
    <div className="py-10 text-center text-muted-foreground" data-testid="inv-po-drafts-empty">
      <FileText className="w-8 h-8 mx-auto mb-2 opacity-30" />
      <p className="text-sm font-medium">No PO Drafts</p>
      <p className="text-xs mt-1">Generate PO drafts from the Action Center tab.</p>
    </div>
  );

  return (
    <Card className="border border-border" data-testid="inv-po-drafts-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <FileText className="w-3.5 h-3.5 inline mr-1 text-blue-500" /> {drafts.length} PO Draft{drafts.length !== 1 ? 's' : ''}
          </CardTitle>
          <Button variant="ghost" size="sm" className="h-6 text-[10px]" onClick={load}>
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs" data-testid="inv-po-drafts-table">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Draft ID</th>
              <th className="text-left py-2 px-3 font-medium">Created</th>
              <th className="text-center py-2 px-3 font-medium">Status</th>
              <th className="text-right py-2 px-3 font-medium">Lines</th>
              <th className="text-right py-2 px-3 font-medium">Total Qty</th>
              <th className="text-left py-2 px-3 font-medium">Items</th>
              <th className="text-center py-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {drafts.map((d, i) => (
              <tr key={i} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-po-draft-row-${i}`}>
                <td className="py-1.5 px-3">
                  <span className="font-mono font-medium cursor-pointer hover:underline text-blue-600" onClick={() => onViewDraft?.(d.po_draft_id)} data-testid={`inv-po-draft-id-${i}`}>{d.po_draft_id}</span>
                </td>
                <td className="py-1.5 px-3 text-muted-foreground">{d.created_at ? new Date(d.created_at).toLocaleString() : '—'}</td>
                <td className="py-1.5 px-3 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <Badge variant={d.status === 'draft' ? 'outline' : d.status === 'sent' ? 'default' : 'secondary'} className="text-[9px]">{d.status}</Badge>
                    {d.incoming_supply_created && <Badge className="text-[8px] bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" data-testid={`inv-po-draft-supply-badge-${i}`}><Truck className="w-2.5 h-2.5 mr-0.5" />Supply</Badge>}
                  </div>
                </td>
                <td className="py-1.5 px-3 text-right font-bold">{d.total_lines}</td>
                <td className="py-1.5 px-3 text-right font-mono">{d.total_qty?.toLocaleString()}</td>
                <td className="py-1.5 px-3 text-muted-foreground text-[10px] truncate max-w-[200px]">{d.lines?.map(l => l.item).join(', ')}</td>
                <td className="py-1.5 px-3 text-center">
                  <Button variant="ghost" size="sm" className="h-5 text-[10px] px-2" onClick={() => onViewDraft?.(d.po_draft_id)} data-testid={`inv-po-draft-view-${i}`}>
                    View
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* PO DRAFT DETAIL DRAWER                                            */
/* ════════════════════════════════════════════════════════════════ */

function PODraftDetailDrawer({ draftId, onClose, onSupplyCreated }) {
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updating, setUpdating] = useState(false);
  const [converting, setConverting] = useState(false);
  const [conversionResult, setConversionResult] = useState(null);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/inventory-ledger/po-drafts/${draftId}`);
        if (res.ok) setDraft(await res.json());
        else toast.error('Draft not found');
      } catch { toast.error('Failed to load draft'); }
      finally { setLoading(false); }
    })();
  }, [draftId]);

  const updateStatus = async (newStatus) => {
    setUpdating(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/po-drafts/${draftId}/status?status=${newStatus}`, { method: 'PATCH' });
      if (res.ok) {
        setDraft(prev => prev ? { ...prev, status: newStatus } : prev);
        toast.success(`Draft marked as ${newStatus}`);
      } else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setUpdating(false); }
  };

  const createIncomingSupply = async () => {
    setConverting(true);
    setConversionResult(null);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/po-drafts/${draftId}/create-incoming-supply`, { method: 'POST' });
      const data = await res.json();
      if (res.ok) {
        setConversionResult(data);
        setDraft(prev => prev ? { ...prev, incoming_supply_created: true, incoming_supply_created_at: new Date().toISOString(), incoming_supply_ids: data.created_supply_ids } : prev);
        toast.success(`Created ${data.rows_created} incoming supply record(s)`);
        onSupplyCreated?.();
      } else {
        toast.error(data.detail || 'Conversion failed');
      }
    } catch { toast.error('Failed to create incoming supply'); }
    finally { setConverting(false); }
  };

  const supplyAlreadyCreated = draft?.incoming_supply_created;
  const canConvert = draft && !supplyAlreadyCreated && draft.status !== 'archived' && draft.lines?.length > 0;

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="inv-po-draft-detail">
        <DialogHeader>
          <DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <FileText className="w-4 h-4 inline mr-1.5" /> PO Draft
          </DialogTitle>
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" /></div>
        ) : !draft ? (
          <p className="text-sm text-muted-foreground py-4">Draft not found.</p>
        ) : (
          <div className="space-y-4">
            {/* Header */}
            <div className="grid grid-cols-2 gap-3" data-testid="inv-po-draft-header">
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">Draft ID</p>
                <p className="text-xs font-mono font-bold" data-testid="inv-po-draft-detail-id">{draft.po_draft_id}</p>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">Status</p>
                <div className="flex items-center gap-1.5">
                  <Badge variant={draft.status === 'draft' ? 'outline' : draft.status === 'sent' ? 'default' : 'secondary'} className="text-[9px]" data-testid="inv-po-draft-detail-status">{draft.status}</Badge>
                  {supplyAlreadyCreated && (
                    <Badge className="text-[9px] bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300" data-testid="inv-po-draft-supply-created-badge">
                      <Truck className="w-2.5 h-2.5 mr-0.5" /> Supply Created
                    </Badge>
                  )}
                </div>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">Created</p>
                <p className="text-xs">{draft.created_at ? new Date(draft.created_at).toLocaleString() : '—'}</p>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] text-muted-foreground">Customer</p>
                <p className="text-xs">{draft.customer_name || draft.customer_id}</p>
              </div>
            </div>

            {/* Supply Created Info */}
            {supplyAlreadyCreated && (
              <div className="border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-900/20 rounded p-2.5 text-xs space-y-1" data-testid="inv-po-draft-supply-info">
                <p className="font-medium text-green-700 dark:text-green-300"><ShieldCheck className="w-3 h-3 inline mr-1" />Incoming supply has been created from this draft</p>
                {draft.incoming_supply_created_at && <p className="text-[10px] text-green-600 dark:text-green-400">Converted: {new Date(draft.incoming_supply_created_at).toLocaleString()}</p>}
                {draft.incoming_supply_ids?.length > 0 && <p className="text-[10px] text-green-600 dark:text-green-400">{draft.incoming_supply_ids.length} supply record(s) created</p>}
              </div>
            )}

            {/* Conversion Result */}
            {conversionResult && (
              <div className="border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-900/20 rounded p-2.5 text-xs space-y-1.5" data-testid="inv-po-draft-conversion-result">
                <p className="font-medium text-blue-700 dark:text-blue-300">Conversion Complete</p>
                <div className="flex gap-3">
                  <span>Processed: <strong>{conversionResult.rows_processed}</strong></span>
                  <span>Created: <strong className="text-green-600">{conversionResult.rows_created}</strong></span>
                  {conversionResult.rows_skipped > 0 && <span>Skipped: <strong className="text-amber-600">{conversionResult.rows_skipped}</strong></span>}
                </div>
                {conversionResult.messages?.map((m, i) => (
                  <div key={i} className="flex items-center gap-2 text-[10px]">
                    <span className="font-mono font-bold">{m.item}</span>
                    <Badge variant={m.status === 'created' ? 'default' : 'secondary'} className="text-[8px]">{m.status}</Badge>
                    {m.qty && <span>qty: {m.qty}</span>}
                    {m.reason && <span className="text-muted-foreground">{m.reason}</span>}
                  </div>
                ))}
              </div>
            )}

            {/* Summary */}
            <div className="flex gap-4 text-xs border border-border rounded p-2.5">
              <div>Lines: <span className="font-bold">{draft.total_lines}</span></div>
              <div>Total Qty: <span className="font-bold">{draft.total_qty?.toLocaleString()}</span></div>
              <div>Source: <span className="font-bold">{draft.source}</span></div>
            </div>

            {/* Lines */}
            <div>
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-1.5">Draft Lines</p>
              <div className="border border-border rounded overflow-hidden">
                <table className="w-full text-[10px]" data-testid="inv-po-draft-lines">
                  <thead className="bg-muted/30">
                    <tr>
                      <th className="p-1.5 text-left font-medium">#</th>
                      <th className="p-1.5 text-left font-medium">Item</th>
                      <th className="p-1.5 text-right font-medium">Qty</th>
                      <th className="p-1.5 text-left font-medium">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {draft.lines?.map((line, i) => (
                      <tr key={i} className="border-t border-border/20" data-testid={`inv-po-draft-line-${i}`}>
                        <td className="p-1.5 text-muted-foreground">{i + 1}</td>
                        <td className="p-1.5 font-mono font-bold">{line.item}</td>
                        <td className="p-1.5 text-right font-mono">{line.qty?.toLocaleString()}</td>
                        <td className="p-1.5 text-muted-foreground">{line.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Actions */}
            <div className="flex flex-wrap gap-2 pt-1" data-testid="inv-po-draft-actions">
              {canConvert && (
                <Button size="sm" className="h-7 text-[10px] bg-green-600 hover:bg-green-700 text-white"
                  disabled={converting}
                  onClick={createIncomingSupply}
                  data-testid="inv-po-draft-create-supply">
                  {converting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Truck className="w-3 h-3 mr-1" />}
                  Create Incoming Supply
                </Button>
              )}
              <Button variant="outline" size="sm" className="h-7 text-[10px]"
                onClick={() => window.open(`${API}/api/inventory-ledger/po-drafts/${draftId}/export`, '_blank')}
                data-testid="inv-po-draft-export">
                <Download className="w-3 h-3 mr-1" /> Export JSON
              </Button>
              {draft.status === 'draft' && (
                <Button size="sm" className="h-7 text-[10px]" disabled={updating} onClick={() => updateStatus('sent')} data-testid="inv-po-draft-mark-sent">
                  Mark as Sent
                </Button>
              )}
              {draft.status !== 'archived' && (
                <Button variant="ghost" size="sm" className="h-7 text-[10px]" disabled={updating} onClick={() => updateStatus('archived')} data-testid="inv-po-draft-archive">
                  Archive
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* ITEM DETAIL DRAWER                                                */
/* ════════════════════════════════════════════════════════════════ */

function ItemDetailDrawer({ item, customerId, onClose, onOpenFullHistory, onRefresh, onViewDraft }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API}/api/inventory-ledger/item-detail?customer_id=${customerId}&item=${encodeURIComponent(item)}`);
        if (res.ok) setDetail(await res.json());
        else toast.error('Item not found');
      } catch { toast.error('Failed to load item detail'); }
      finally { setLoading(false); }
    })();
  }, [customerId, item]);

  const createSupply = async () => {
    setCreating(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_no: item, quantity: detail?.reorder?.recommended_qty || 0, source_reference: `DETAIL-${item}`, notes: 'Created from item detail' }),
      });
      if (res.ok) { toast.success(`Incoming supply created for ${item}`); onRefresh?.(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch { toast.error('Failed'); }
    finally { setCreating(false); }
  };

  const bal = detail?.balance || {};
  const settings = detail?.settings;
  const reorder = detail?.reorder || {};
  const exc = detail?.exceptions || {};
  const history = detail?.history_preview || [];
  const excBadges = [
    exc.short && { label: 'SHORT', cls: 'bg-red-500/10 text-red-600 border-red-500/20' },
    exc.low && { label: 'LOW', cls: 'bg-amber-500/10 text-amber-600 border-amber-500/20' },
    exc.reorder && { label: 'REORDER', cls: 'bg-orange-500/10 text-orange-600 border-orange-500/20' },
    exc.no_incoming && { label: 'NO INCOMING', cls: 'bg-violet-500/10 text-violet-600 border-violet-500/20' },
  ].filter(Boolean);

  return (
    <Dialog open={true} onOpenChange={onClose}>
      <DialogContent className="max-w-lg max-h-[85vh] overflow-y-auto" data-testid="inv-item-detail-drawer">
        <DialogHeader>
          <DialogTitle className="text-sm font-bold font-mono" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Package className="w-4 h-4 inline mr-1.5" /> {item}
          </DialogTitle>
          {bal.item_description && <p className="text-xs text-muted-foreground">{bal.item_description}</p>}
        </DialogHeader>

        {loading ? (
          <div className="flex items-center justify-center py-10"><Loader2 className="w-5 h-5 animate-spin" /></div>
        ) : !detail ? (
          <p className="text-sm text-muted-foreground py-4">Item not found.</p>
        ) : (
          <div className="space-y-4">
            {/* Balance Strip */}
            <div className="grid grid-cols-5 gap-2" data-testid="inv-detail-balance">
              {[
                { label: 'On Hand', value: bal.on_hand, color: '' },
                { label: 'Incoming', value: bal.incoming, color: 'text-sky-600' },
                { label: 'Committed', value: bal.committed, color: 'text-amber-600' },
                { label: 'Available', value: bal.available, color: bal.available < 0 ? 'text-red-600' : 'text-emerald-600' },
                { label: 'Status', value: bal.status, color: bal.status === 'SHORT' ? 'text-red-600' : bal.status === 'LOW' ? 'text-amber-600' : 'text-emerald-600' },
              ].map(c => (
                <div key={c.label} className="bg-muted/30 border border-border rounded p-2 text-center">
                  <p className={`text-sm font-bold ${c.color}`}>{typeof c.value === 'number' ? c.value.toLocaleString() : c.value}</p>
                  <p className="text-[9px] text-muted-foreground">{c.label}</p>
                </div>
              ))}
            </div>

            {/* Exception Badges */}
            {excBadges.length > 0 && (
              <div className="flex gap-1.5" data-testid="inv-detail-exceptions">
                {excBadges.map(b => (
                  <span key={b.label} className={`text-[10px] px-2 py-0.5 rounded border font-medium ${b.cls}`}>{b.label}</span>
                ))}
              </div>
            )}

            {/* Reorder Settings & Recommendation */}
            <div className="grid grid-cols-2 gap-3">
              <div className="border border-border rounded p-2.5 space-y-1" data-testid="inv-detail-settings">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Reorder Settings</p>
                {settings ? (
                  <>
                    <p className="text-xs">Threshold: <span className="font-bold">{settings.reorder_threshold}</span></p>
                    <p className="text-xs">Buffer: <span className="font-bold">{settings.safety_buffer}</span></p>
                    {settings.notes && <p className="text-[10px] text-muted-foreground italic">{settings.notes}</p>}
                  </>
                ) : (
                  <p className="text-xs text-muted-foreground">Using defaults (threshold: 0, buffer: 10)</p>
                )}
              </div>
              <div className="border border-border rounded p-2.5 space-y-1" data-testid="inv-detail-reorder">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Reorder Status</p>
                {reorder.is_reorder_recommended ? (
                  <>
                    <p className="text-xs text-orange-600 font-bold">Reorder Recommended</p>
                    <p className="text-xs">Qty: <span className="font-bold text-emerald-600">{reorder.recommended_qty?.toLocaleString()}</span></p>
                  </>
                ) : (
                  <p className="text-xs text-emerald-600 font-medium">Stock levels OK</p>
                )}
              </div>
            </div>

            {/* Demand Signal */}
            {detail.demand && (
              <div className="border border-border rounded p-2.5 space-y-1" data-testid="inv-detail-demand">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Demand Signal</p>
                <div className="flex gap-4 text-xs">
                  <div>Open Orders: <span className="font-bold text-blue-600">{detail.demand.total_open_order_qty?.toLocaleString()}</span></div>
                  <div>Demand Gap: <span className={`font-bold ${detail.demand.demand_gap > 0 ? 'text-red-600' : 'text-emerald-600'}`}>{detail.demand.demand_gap > 0 ? '+' : ''}{detail.demand.demand_gap?.toLocaleString()}</span></div>
                </div>
              </div>
            )}

            {/* Supply Coverage */}
            {detail.supply_coverage && (
              <div className="border border-border rounded p-2.5 space-y-1" data-testid="inv-detail-coverage">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Supply Coverage</p>
                <div className="flex gap-4 text-xs items-center">
                  <div>Coverage: <span className={`font-bold ${detail.supply_coverage.coverage < 0 ? 'text-red-600' : 'text-emerald-600'}`}>{detail.supply_coverage.coverage?.toLocaleString()}</span></div>
                  <Badge variant={detail.supply_coverage.coverage_status === 'at_risk' ? 'destructive' : 'outline'}
                    className={`text-[9px] ${detail.supply_coverage.coverage_status === 'covered' ? 'border-emerald-300 text-emerald-600' : ''}`}>
                    {detail.supply_coverage.coverage_status === 'at_risk' ? 'AT RISK' : 'COVERED'}
                  </Badge>
                </div>
              </div>
            )}

            {/* Action Summary */}
            {detail.action_summary && (
              <div className="border border-border rounded p-2.5 space-y-1" data-testid="inv-detail-action-summary">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Action Summary</p>
                <div className="flex items-center gap-2">
                  <div className="flex flex-wrap gap-1">
                    {detail.action_summary.action_types?.map(t => (
                      <span key={t} className={`text-[9px] px-1.5 py-0.5 rounded border font-medium ${ACTION_BADGES[t]?.cls || 'bg-muted text-muted-foreground'}`}>
                        {ACTION_BADGES[t]?.label || t}
                      </span>
                    ))}
                  </div>
                  <span className="text-[10px] text-muted-foreground">Priority: <span className="font-bold">{detail.action_summary.priority_score}</span></span>
                </div>
              </div>
            )}

            {/* Last PO Draft */}
            {detail.last_po_draft && (
              <div className="border border-border rounded p-2.5 space-y-1 cursor-pointer hover:bg-muted/30" onClick={() => onViewDraft?.(detail.last_po_draft.po_draft_id)} data-testid="inv-detail-po-draft">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Last PO Draft</p>
                <div className="flex gap-3 text-xs items-center">
                  <span className="font-mono font-bold text-blue-600 hover:underline">{detail.last_po_draft.po_draft_id}</span>
                  <Badge variant="outline" className="text-[9px]">{detail.last_po_draft.status}</Badge>
                  <span className="text-muted-foreground text-[10px]">{detail.last_po_draft.created_at ? new Date(detail.last_po_draft.created_at).toLocaleDateString() : ''}</span>
                </div>
              </div>
            )}

            {/* Recent History */}
            <div data-testid="inv-detail-history">
              <div className="flex items-center justify-between mb-1.5">
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">Recent Movements ({detail.history_total} total)</p>
                <Button variant="link" size="sm" className="h-5 text-[10px] p-0" onClick={() => onOpenFullHistory?.(item)} data-testid="inv-detail-full-history">
                  View Full History
                </Button>
              </div>
              {history.length === 0 ? (
                <p className="text-xs text-muted-foreground py-2">No movements recorded.</p>
              ) : (
                <div className="border border-border rounded overflow-hidden">
                  <table className="w-full text-[10px]">
                    <thead className="bg-muted/30">
                      <tr>
                        <th className="p-1.5 text-left font-medium">Type</th>
                        <th className="p-1.5 text-right font-medium">Qty</th>
                        <th className="p-1.5 text-left font-medium">Reference</th>
                        <th className="p-1.5 text-left font-medium">Date</th>
                      </tr>
                    </thead>
                    <tbody>
                      {history.map((m, i) => (
                        <tr key={i} className="border-t border-border/20" data-testid={`inv-detail-mov-${i}`}>
                          <td className="p-1.5 capitalize">{m.movement_type?.replace(/_/g, ' ')}</td>
                          <td className={`p-1.5 text-right font-mono font-bold ${m.quantity_delta > 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                            {m.quantity_delta > 0 ? '+' : ''}{m.quantity_delta}
                          </td>
                          <td className="p-1.5 text-muted-foreground truncate max-w-[120px]">{m.reference_id || '—'}</td>
                          <td className="p-1.5 text-muted-foreground">{m.created_at ? new Date(m.created_at).toLocaleDateString() : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Actions */}
            <div className="flex gap-2 pt-1" data-testid="inv-detail-actions">
              <Button variant="outline" size="sm" className="h-7 text-[10px]" onClick={() => onOpenFullHistory?.(item)} data-testid="inv-detail-action-history">
                <History className="w-3 h-3 mr-1" /> Full History
              </Button>
              {reorder.is_reorder_recommended && (
                <Button variant="outline" size="sm" className="h-7 text-[10px]" disabled={creating} onClick={createSupply} data-testid="inv-detail-action-supply">
                  {creating ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Truck className="w-3 h-3 mr-1" />} Create Supply
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* SUMMARY STRIP                                                    */
/* ════════════════════════════════════════════════════════════════ */

function SummaryStrip({ summary }) {
  const cards = [
    { label: 'Total Items', value: summary.total_items, icon: Package, color: 'text-blue-500' },
    { label: 'OK', value: summary.items_ok, icon: TrendingUp, color: 'text-emerald-500' },
    { label: 'LOW', value: summary.items_low, icon: AlertTriangle, color: summary.items_low > 0 ? 'text-amber-500' : 'text-muted-foreground' },
    { label: 'SHORT', value: summary.items_short, icon: TrendingDown, color: summary.items_short > 0 ? 'text-red-500' : 'text-muted-foreground' },
    { label: 'Incoming', value: summary.total_incoming, icon: Truck, color: 'text-sky-500' },
    { label: 'Committed', value: summary.total_committed, icon: ClipboardList, color: 'text-amber-500' },
    { label: 'Available', value: summary.total_available, icon: Box, color: 'text-emerald-500' },
    { label: 'Reorders Needed', value: summary.total_reorder_recommendations, icon: RotateCcw, color: summary.total_reorder_recommendations > 0 ? 'text-orange-500' : 'text-muted-foreground' },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3" data-testid="inv-dashboard-summary">
      {cards.map(c => {
        const Icon = c.icon;
        return (
          <div key={c.label} className="bg-muted/30 border border-border rounded-md p-3 flex items-center gap-3" data-testid={`inv-summary-${c.label.toLowerCase().replace(/\s+/g, '-')}`}>
            <Icon className={`w-5 h-5 ${c.color} shrink-0`} />
            <div>
              <p className="text-lg font-bold leading-tight">{typeof c.value === 'number' ? c.value.toLocaleString() : (c.value ?? 0)}</p>
              <p className="text-[10px] text-muted-foreground">{c.label}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* ITEM HISTORY MODAL                                               */
/* ════════════════════════════════════════════════════════════════ */

function ItemHistoryModal({ item, customerId, onClose }) {
  const [summary, setSummary] = useState(null);
  const [history, setHistory] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [typeFilter, setTypeFilter] = useState('');
  const [refFilter, setRefFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const pageSize = 50;

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ customer_id: customerId, item, limit: String(pageSize), offset: String(offset) });
      if (typeFilter) params.set('movement_type', typeFilter);
      if (refFilter) params.set('reference', refFilter);

      const [sumRes, histRes] = await Promise.all([
        fetch(`${API}/api/inventory-ledger/history/summary?customer_id=${customerId}&item=${encodeURIComponent(item)}`),
        fetch(`${API}/api/inventory-ledger/history?${params}`),
      ]);
      const [sumData, histData] = await Promise.all([sumRes.json(), histRes.json()]);
      setSummary(sumData);
      setHistory(histData.movements || []);
      setTotal(histData.total || 0);
    } catch { toast.error('Failed to load history'); }
    finally { setLoading(false); }
  }, [customerId, item, typeFilter, refFilter, offset]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const bal = summary?.current_balances || {};
  const typeTotals = summary?.movement_type_totals || {};

  return (
    <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-hidden flex flex-col" data-testid="item-history-modal">
        <DialogHeader>
          <DialogTitle className="text-sm font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <span className="font-mono">{item}</span> — Movement History
          </DialogTitle>
        </DialogHeader>

        {/* Balance Summary Strip */}
        <div className="grid grid-cols-4 gap-2 mb-3" data-testid="item-history-summary">
          {[
            { label: 'On Hand', value: bal.on_hand, color: 'text-foreground' },
            { label: 'Incoming', value: bal.incoming, color: 'text-sky-600 dark:text-sky-400' },
            { label: 'Committed', value: bal.committed, color: 'text-amber-600 dark:text-amber-400' },
            { label: 'Available', value: bal.available, color: bal.available < 0 ? 'text-red-600' : 'text-emerald-600 dark:text-emerald-400' },
          ].map(s => (
            <div key={s.label} className="bg-muted/40 rounded-md p-2.5 text-center border border-border/50">
              <div className={`text-lg font-bold font-mono ${s.color}`}>{(s.value ?? 0).toLocaleString()}</div>
              <div className="text-[9px] text-muted-foreground uppercase tracking-wider">{s.label}</div>
            </div>
          ))}
        </div>

        {/* Type Breakdown */}
        <div className="flex flex-wrap gap-1.5 mb-3" data-testid="item-history-type-breakdown">
          {Object.entries(typeTotals).map(([mt, data]) => (
            <Badge key={mt} variant="outline" className={`text-[9px] cursor-pointer ${typeFilter === mt ? 'ring-1 ring-primary' : ''} ${MOVE_COLORS[mt] || ''}`}
              onClick={() => { setTypeFilter(typeFilter === mt ? '' : mt); setOffset(0); }}>
              {mt.replace(/_/g, ' ')} ({data.count})
            </Badge>
          ))}
          {typeFilter && (
            <Button variant="ghost" size="sm" className="h-5 text-[9px] px-1.5" onClick={() => { setTypeFilter(''); setOffset(0); }}>
              Clear filter
            </Button>
          )}
        </div>

        {/* Reference Filter */}
        <div className="flex gap-2 mb-3">
          <div className="relative flex-1">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input placeholder="Filter by reference..." value={refFilter}
              onChange={e => { setRefFilter(e.target.value); setOffset(0); }}
              className="pl-8 h-7 text-xs" data-testid="item-history-ref-filter" />
          </div>
        </div>

        {/* Movement List */}
        <div className="flex-1 overflow-y-auto border border-border rounded-md" data-testid="item-history-list">
          {loading ? (
            <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>
          ) : !history.length ? (
            <div className="py-10 text-center text-muted-foreground text-sm">No movements match filters.</div>
          ) : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted/80 backdrop-blur-sm">
                <tr className="border-b border-border text-[10px] text-muted-foreground uppercase tracking-wider">
                  <th className="text-left py-2 px-2.5 font-medium">Type</th>
                  <th className="text-right py-2 px-2.5 font-medium">Effect</th>
                  <th className="text-left py-2 px-2.5 font-medium">Reference</th>
                  <th className="text-left py-2 px-2.5 font-medium">Source</th>
                  <th className="text-left py-2 px-2.5 font-medium">Notes</th>
                  <th className="text-left py-2 px-2.5 font-medium">Timestamp</th>
                </tr>
              </thead>
              <tbody>
                {history.map((m, i) => {
                  const effect = m.display_effect ?? m.quantity_delta;
                  const isPos = effect > 0;
                  return (
                    <tr key={m.id || i} className="border-b border-border/30 hover:bg-muted/10" data-testid={`item-history-row-${i}`}>
                      <td className="py-1.5 px-2.5">
                        <Badge variant="secondary" className={`text-[8px] ${MOVE_COLORS[m.movement_type] || ''}`}>
                          {m.movement_type?.replace(/_/g, ' ')}
                        </Badge>
                      </td>
                      <td className={`py-1.5 px-2.5 text-right font-mono font-bold ${isPos ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>
                        {isPos ? '+' : ''}{effect.toLocaleString()}
                      </td>
                      <td className="py-1.5 px-2.5 font-mono text-muted-foreground">{m.reference_id || '-'}</td>
                      <td className="py-1.5 px-2.5 text-muted-foreground">{m.source_type?.replace(/_/g, ' ') || '-'}</td>
                      <td className="py-1.5 px-2.5 text-muted-foreground truncate max-w-[180px]" title={m.notes}>{m.notes || '-'}</td>
                      <td className="py-1.5 px-2.5 text-muted-foreground font-mono">{m.created_at ? new Date(m.created_at).toLocaleString() : '-'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Pagination */}
        {total > pageSize && (
          <div className="flex items-center justify-between pt-2">
            <span className="text-[10px] text-muted-foreground">
              Showing {offset + 1}–{Math.min(offset + pageSize, total)} of {total}
            </span>
            <div className="flex gap-1">
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2" disabled={offset === 0}
                onClick={() => setOffset(Math.max(0, offset - pageSize))}>
                <ChevronLeft className="w-3 h-3" /> Prev
              </Button>
              <Button variant="outline" size="sm" className="h-6 text-[10px] px-2" disabled={offset + pageSize >= total}
                onClick={() => setOffset(offset + pageSize)}>
                Next <ChevronRight className="w-3 h-3" />
              </Button>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function BalanceTable({ balances, loading, onItemClick }) {
  if (loading) return <div className="py-10 text-center"><Loader2 className="w-5 h-5 animate-spin mx-auto" /></div>;
  if (!balances.length) return <div className="py-10 text-center text-muted-foreground text-sm">No inventory data. Add movements to get started.</div>;

  return (
    <Card className="border border-border" data-testid="inv-balance-table">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2.5 px-3 font-medium">Item</th>
              <th className="text-left py-2.5 px-3 font-medium">Warehouse</th>
              <th className="text-left py-2.5 px-3 font-medium">Ownership</th>
              <th className="text-right py-2.5 px-3 font-medium">On Hand</th>
              <th className="text-right py-2.5 px-3 font-medium">Incoming</th>
              <th className="text-right py-2.5 px-3 font-medium">Committed</th>
              <th className="text-right py-2.5 px-3 font-medium">Available</th>
              <th className="text-left py-2.5 px-3 font-medium">UOM</th>
              <th className="text-center py-2.5 px-3 font-medium">Status</th>
              <th className="w-8"></th>
            </tr>
          </thead>
          <tbody>
            {balances.map((b, i) => {
              const oc = OWNERSHIP_COLORS[b.ownership_type] || OWNERSHIP_COLORS.unknown;
              return (
                <tr key={i} className="border-b border-border/50 hover:bg-muted/20 group" data-testid={`inv-balance-row-${i}`}>
                  <td className="py-2 px-3">
                    <span className="font-mono text-xs font-medium">{b.item}</span>
                    {b.item_description && <span className="text-[10px] text-muted-foreground block truncate max-w-[200px]">{b.item_description}</span>}
                  </td>
                  <td className="py-2 px-3 text-xs font-mono">{b.warehouse}</td>
                  <td className="py-2 px-3"><Badge variant="secondary" className={`text-[9px] ${oc}`}>{OWNERSHIP_LABELS[b.ownership_type] || b.ownership_type}</Badge></td>
                  <td className="py-2 px-3 text-right font-mono text-xs font-medium">{b.on_hand.toLocaleString()}</td>
                  <td className="py-2 px-3 text-right font-mono text-xs">{b.incoming > 0 ? <span className="text-sky-600 dark:text-sky-400">+{b.incoming.toLocaleString()}</span> : '-'}</td>
                  <td className="py-2 px-3 text-right font-mono text-xs">{b.committed > 0 ? <span className="text-amber-600 dark:text-amber-400">-{b.committed.toLocaleString()}</span> : '-'}</td>
                  <td className={`py-2 px-3 text-right font-mono text-xs font-bold ${b.is_short ? 'text-red-600 dark:text-red-400' : b.is_low ? 'text-amber-600 dark:text-amber-400' : ''}`}>{b.available.toLocaleString()}</td>
                  <td className="py-2 px-3 text-xs text-muted-foreground">{b.unit_of_measure}</td>
                  <td className="py-2 px-3 text-center">
                    {b.is_short ? <Badge variant="destructive" className="text-[9px]">SHORT</Badge>
                      : b.is_low ? <Badge variant="outline" className="text-[9px] border-amber-300 text-amber-600">LOW</Badge>
                      : <Badge variant="outline" className="text-[9px] border-emerald-300 text-emerald-600">OK</Badge>}
                  </td>
                  <td className="py-2 px-1">
                    <Button variant="ghost" size="sm"
                      className="h-6 w-6 p-0 opacity-40 group-hover:opacity-100 transition-opacity"
                      onClick={() => onItemClick?.(b.item)}
                      title="View movement history"
                      data-testid={`inv-history-btn-${i}`}>
                      <ClipboardList className="w-3.5 h-3.5" />
                    </Button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* MOVEMENT TABLE                                                   */
/* ════════════════════════════════════════════════════════════════ */

const MOVE_COLORS = {
  opening_balance: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  receipt: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  order_commitment: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  order_release: 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  manual_adjustment: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  transfer: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300',
  writeoff: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  correction: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
};

function MovementTable({ movements, total }) {
  if (!movements.length) return <div className="py-10 text-center text-muted-foreground text-sm">No movements recorded yet.</div>;
  return (
    <Card className="border border-border" data-testid="inv-movement-table">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Time</th>
              <th className="text-left py-2 px-3 font-medium">Type</th>
              <th className="text-left py-2 px-3 font-medium">Item</th>
              <th className="text-left py-2 px-3 font-medium">Warehouse</th>
              <th className="text-left py-2 px-3 font-medium">Ownership</th>
              <th className="text-right py-2 px-3 font-medium">Qty Delta</th>
              <th className="text-left py-2 px-3 font-medium">UOM</th>
              <th className="text-left py-2 px-3 font-medium">Source</th>
              <th className="text-left py-2 px-3 font-medium">Reference</th>
              <th className="text-left py-2 px-3 font-medium">Notes</th>
            </tr>
          </thead>
          <tbody>
            {movements.map(m => (
              <tr key={m.id} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-movement-${m.id}`}>
                <td className="py-1.5 px-3 text-muted-foreground whitespace-nowrap">{new Date(m.created_at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })}</td>
                <td className="py-1.5 px-3"><Badge variant="secondary" className={`text-[9px] ${MOVE_COLORS[m.movement_type] || ''}`}>{m.movement_type.replace(/_/g, ' ')}</Badge></td>
                <td className="py-1.5 px-3 font-mono font-medium">{m.item}</td>
                <td className="py-1.5 px-3 font-mono">{m.warehouse}</td>
                <td className="py-1.5 px-3"><Badge variant="outline" className="text-[8px]">{OWNERSHIP_LABELS[m.ownership_type] || m.ownership_type}</Badge></td>
                <td className={`py-1.5 px-3 text-right font-mono font-bold ${m.quantity_delta >= 0 ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}`}>{m.quantity_delta >= 0 ? '+' : ''}{m.quantity_delta.toLocaleString()}</td>
                <td className="py-1.5 px-3">{m.unit_of_measure}</td>
                <td className="py-1.5 px-3 text-muted-foreground">{m.source_type?.replace(/_/g, ' ')}</td>
                <td className="py-1.5 px-3">{m.reference_id ? <span className="font-mono">{m.reference_type}: {m.reference_id}</span> : '-'}</td>
                <td className="py-1.5 px-3 text-muted-foreground truncate max-w-[150px]" title={m.notes}>{m.notes || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {total > movements.length && (
          <div className="border-t px-3 py-1.5 text-[10px] text-muted-foreground">Showing {movements.length} of {total}</div>
        )}
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* INCOMING SUPPLY TABLE                                            */
/* ════════════════════════════════════════════════════════════════ */

const STATUS_COLORS = { planned: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300', ordered: 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300', expected: 'bg-sky-100 text-sky-700', in_transit: 'bg-amber-100 text-amber-700', received: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300', cancelled: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-500' };

function IncomingTable({ records, customerId, onUpdate }) {
  const [transitioning, setTransitioning] = useState(null);

  const transitionStatus = async (supplyId, newStatus) => {
    setTransitioning(supplyId);
    try {
      const res = await fetch(`${API}/api/incoming-supply/${supplyId}/status`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus }),
      });
      if (res.ok) {
        const data = await res.json();
        toast.success(`Status updated to ${newStatus}`);
        if (data.receipt_movement_id) {
          toast.success('Receipt movement created');
        }
        onUpdate();
      } else if (res.status === 409) {
        toast.error('Already received — duplicate receipt prevented');
      } else {
        const d = await res.json();
        toast.error(d.detail || 'Update failed');
      }
    } catch { toast.error('Status update failed'); }
    finally { setTransitioning(null); }
  };

  if (!records.length) return <div className="py-10 text-center text-muted-foreground text-sm">No incoming supply records.</div>;
  return (
    <Card className="border border-border" data-testid="inv-incoming-table">
      <CardContent className="p-0 overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-muted/40 text-[10px] text-muted-foreground uppercase tracking-wider">
              <th className="text-left py-2 px-3 font-medium">Item</th>
              <th className="text-left py-2 px-3 font-medium">Warehouse</th>
              <th className="text-right py-2 px-3 font-medium">Qty</th>
              <th className="text-left py-2 px-3 font-medium">UOM</th>
              <th className="text-left py-2 px-3 font-medium">ETA</th>
              <th className="text-left py-2 px-3 font-medium">Source</th>
              <th className="text-left py-2 px-3 font-medium">Status</th>
              <th className="text-right py-2 px-3 font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {records.map(r => {
              const isBusy = transitioning === r.id;
              return (
                <tr key={r.id} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-incoming-${r.id}`}>
                  <td className="py-1.5 px-3 font-mono font-medium">{r.item}</td>
                  <td className="py-1.5 px-3 font-mono">{r.warehouse}</td>
                  <td className="py-1.5 px-3 text-right font-mono font-bold">{r.incoming_qty.toLocaleString()}</td>
                  <td className="py-1.5 px-3">{r.unit_of_measure}</td>
                  <td className="py-1.5 px-3">{r.eta || '-'}</td>
                  <td className="py-1.5 px-3 font-mono">{r.source_reference || '-'}</td>
                  <td className="py-1.5 px-3">
                    <Badge variant="secondary" className={`text-[9px] ${STATUS_COLORS[r.status] || ''}`} data-testid={`inv-incoming-status-${r.id}`}>
                      {r.status}
                    </Badge>
                  </td>
                  <td className="py-1.5 px-3 text-right">
                    <div className="flex items-center justify-end gap-1">
                      {r.status === 'planned' && (
                        <>
                          <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5" disabled={isBusy}
                            onClick={() => transitionStatus(r.id, 'ordered')} data-testid={`inv-incoming-ordered-${r.id}`}>
                            {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Ordered'}
                          </Button>
                          <Button variant="ghost" size="sm" className="h-5 text-[9px] px-1.5 text-red-500 hover:text-red-700" disabled={isBusy}
                            onClick={() => transitionStatus(r.id, 'cancelled')} data-testid={`inv-incoming-cancel-${r.id}`}>
                            Cancel
                          </Button>
                        </>
                      )}
                      {r.status === 'ordered' && (
                        <>
                          <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5 border-emerald-300 text-emerald-700 hover:bg-emerald-50" disabled={isBusy}
                            onClick={() => transitionStatus(r.id, 'received')} data-testid={`inv-incoming-received-${r.id}`}>
                            {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Received'}
                          </Button>
                          <Button variant="ghost" size="sm" className="h-5 text-[9px] px-1.5 text-red-500 hover:text-red-700" disabled={isBusy}
                            onClick={() => transitionStatus(r.id, 'cancelled')} data-testid={`inv-incoming-cancel-${r.id}`}>
                            Cancel
                          </Button>
                        </>
                      )}
                      {r.status === 'expected' && (
                        <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5" disabled={isBusy}
                          onClick={() => transitionStatus(r.id, 'ordered')} data-testid={`inv-incoming-ordered-${r.id}`}>
                          Ordered
                        </Button>
                      )}
                      {r.status === 'in_transit' && (
                        <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5 border-emerald-300 text-emerald-700 hover:bg-emerald-50" disabled={isBusy}
                          onClick={() => transitionStatus(r.id, 'received')} data-testid={`inv-incoming-received-${r.id}`}>
                          Received
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* MOVEMENT FORM DIALOG                                             */
/* ════════════════════════════════════════════════════════════════ */

const MANUAL_MOVEMENT_TYPES = ['opening_balance', 'manual_adjustment', 'transfer', 'writeoff', 'correction'];

function MovementFormDialog({ open, customerId, onClose, onCreated }) {
  const [form, setForm] = useState({ item: '', item_description: '', warehouse: 'MAIN', ownership_type: 'customer_owned', movement_type: 'manual_adjustment', quantity_delta: '', unit_of_measure: 'cases', reference_id: '', notes: '' });
  const [saving, setSaving] = useState(false);

  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = async () => {
    if (!form.item || !form.quantity_delta) { toast.error('Item and quantity are required'); return; }
    const qty = parseFloat(form.quantity_delta);
    if (isNaN(qty) || qty === 0) { toast.error('Quantity must be a non-zero number'); return; }
    if (form.movement_type === 'writeoff' && qty > 0) { toast.error('Writeoff must be negative'); return; }

    setSaving(true);
    const idempotencyKey = `${customerId}_${form.item}_${form.movement_type}_${qty}_${Date.now()}`;
    try {
      const payload = {
        customer_id: customerId,
        movement_type: form.movement_type,
        item: form.item,
        qty,
        item_description: form.item_description,
        warehouse: form.warehouse,
        ownership_type: form.ownership_type,
        unit_of_measure: form.unit_of_measure,
        reference: form.reference_id,
        notes: form.notes,
        idempotency_key: idempotencyKey,
      };
      const res = await fetch(`${API}/api/inventory-ledger/movements`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      const data = await res.json();
      if (res.ok && data.success) {
        toast.success('Movement recorded');
        if (data.warning) toast.warning(data.warning);
        onCreated();
      } else {
        toast.error(data.detail || 'Failed to create movement');
      }
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg" data-testid="inv-movement-dialog">
        <DialogHeader><DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>New Manual Movement</DialogTitle></DialogHeader>
        <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Movement Type</Label>
              <Select value={form.movement_type} onValueChange={v => update('movement_type', v)}>
                <SelectTrigger className="h-8 text-xs" data-testid="inv-mov-type"><SelectValue /></SelectTrigger>
                <SelectContent>{MANUAL_MOVEMENT_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{t.replace(/_/g, ' ')}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Ownership</Label>
              <Select value={form.ownership_type} onValueChange={v => update('ownership_type', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{OWNERSHIP_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{OWNERSHIP_LABELS[t]}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Item / SKU</Label>
              <Input className="h-8 text-xs" value={form.item} onChange={e => update('item', e.target.value)} placeholder="PET-32" data-testid="inv-mov-item" />
            </div>
            <div>
              <Label className="text-xs">Description</Label>
              <Input className="h-8 text-xs" value={form.item_description} onChange={e => update('item_description', e.target.value)} placeholder="PET 32oz Container" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-xs">Quantity</Label>
              <Input type="number" className="h-8 text-xs font-mono" value={form.quantity_delta} onChange={e => update('quantity_delta', e.target.value)} placeholder="+100 or -50" data-testid="inv-mov-qty" />
              <p className="text-[9px] text-muted-foreground mt-0.5">
                {form.movement_type === 'writeoff' ? 'Must be negative' : 'Positive = in, Negative = out'}
              </p>
            </div>
            <div>
              <Label className="text-xs">UOM</Label>
              <Input className="h-8 text-xs" value={form.unit_of_measure} onChange={e => update('unit_of_measure', e.target.value)} />
            </div>
            <div>
              <Label className="text-xs">Warehouse</Label>
              <Input className="h-8 text-xs" value={form.warehouse} onChange={e => update('warehouse', e.target.value)} />
            </div>
          </div>
          <div>
            <Label className="text-xs">Reference</Label>
            <Input className="h-8 text-xs" value={form.reference_id} onChange={e => update('reference_id', e.target.value)} placeholder="Cycle Count 2026-03-13" data-testid="inv-mov-ref" />
          </div>
          <div>
            <Label className="text-xs">Notes</Label>
            <Textarea className="text-xs min-h-[50px]" value={form.notes} onChange={e => update('notes', e.target.value)} data-testid="inv-mov-notes" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={submit} disabled={saving} data-testid="inv-mov-submit">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Plus className="w-3.5 h-3.5 mr-1" />} Record Movement
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* INCOMING SUPPLY FORM DIALOG                                      */
/* ════════════════════════════════════════════════════════════════ */

function IncomingFormDialog({ open, customerId, onClose, onCreated }) {
  const [form, setForm] = useState({ item: '', item_description: '', warehouse: 'MAIN', ownership_type: 'customer_owned', incoming_qty: '', unit_of_measure: 'cases', eta: '', source_reference: '', notes: '' });
  const [saving, setSaving] = useState(false);
  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = async () => {
    if (!form.item || !form.incoming_qty) { toast.error('Item and quantity are required'); return; }
    setSaving(true);
    try {
      const payload = { ...form, incoming_qty: parseFloat(form.incoming_qty) };
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      if (res.ok) { toast.success('Incoming supply added'); onCreated(); }
      else { const d = await res.json(); toast.error(d.detail || 'Failed'); }
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-md" data-testid="inv-incoming-dialog">
        <DialogHeader><DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Add Incoming Supply</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <div><Label className="text-xs">Item / SKU</Label><Input className="h-8 text-xs" value={form.item} onChange={e => update('item', e.target.value)} data-testid="inv-inc-item" /></div>
            <div><Label className="text-xs">Description</Label><Input className="h-8 text-xs" value={form.item_description} onChange={e => update('item_description', e.target.value)} /></div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div><Label className="text-xs">Quantity</Label><Input type="number" className="h-8 text-xs font-mono" value={form.incoming_qty} onChange={e => update('incoming_qty', e.target.value)} data-testid="inv-inc-qty" /></div>
            <div><Label className="text-xs">UOM</Label><Input className="h-8 text-xs" value={form.unit_of_measure} onChange={e => update('unit_of_measure', e.target.value)} /></div>
            <div><Label className="text-xs">Warehouse</Label><Input className="h-8 text-xs" value={form.warehouse} onChange={e => update('warehouse', e.target.value)} /></div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div><Label className="text-xs">ETA</Label><Input type="date" className="h-8 text-xs" value={form.eta} onChange={e => update('eta', e.target.value)} /></div>
            <div><Label className="text-xs">Source Reference</Label><Input className="h-8 text-xs" value={form.source_reference} onChange={e => update('source_reference', e.target.value)} placeholder="PO-5010" /></div>
          </div>
          <div>
            <Label className="text-xs">Ownership</Label>
            <Select value={form.ownership_type} onValueChange={v => update('ownership_type', v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{OWNERSHIP_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{OWNERSHIP_LABELS[t]}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div><Label className="text-xs">Notes</Label><Textarea className="text-xs min-h-[40px]" value={form.notes} onChange={e => update('notes', e.target.value)} /></div>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={submit} disabled={saving} data-testid="inv-inc-submit">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Plus className="w-3.5 h-3.5 mr-1" />} Add Incoming
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* IMPORT CSV DIALOG                                                 */
/* ════════════════════════════════════════════════════════════════ */

function ImportCSVDialog({ open, customerId, onClose, onImported }) {
  const [mode, setMode] = useState('opening_balance');
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  const submit = async () => {
    if (!file) { toast.error('Select a CSV file'); return; }
    setUploading(true);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      formData.append('customer_id', customerId);
      formData.append('import_mode', mode);
      const res = await fetch(`${API}/api/inventory-ledger/import`, { method: 'POST', body: formData });
      const data = await res.json();
      if (res.status === 409) {
        toast.error(data.detail || 'Duplicate import detected');
        setResult({ ...data, duplicate: true });
      } else if (res.ok) {
        setResult(data);
        if (data.rows_imported > 0) {
          toast.success(`Imported ${data.rows_imported} row${data.rows_imported !== 1 ? 's' : ''}`);
        }
        if (data.rows_failed > 0) {
          toast.warning(`${data.rows_failed} row${data.rows_failed !== 1 ? 's' : ''} failed`);
        }
      } else {
        toast.error(data.detail || 'Import failed');
        setResult({ rows_processed: 0, rows_imported: 0, rows_failed: 0, errors: [{ row: 0, error: data.detail }] });
      }
    } catch { toast.error('Import failed'); }
    finally { setUploading(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-md" data-testid="inv-import-dialog">
        <DialogHeader>
          <DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Upload className="w-4 h-4 inline mr-1.5" /> Import CSV
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <Label className="text-xs">Import Mode</Label>
            <Select value={mode} onValueChange={setMode} disabled={!!result}>
              <SelectTrigger className="h-8 text-xs" data-testid="inv-import-mode"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="opening_balance" className="text-xs">Opening Balance</SelectItem>
                <SelectItem value="manual_adjustment" className="text-xs">Manual Adjustment</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-[10px] text-muted-foreground mt-1">
              {mode === 'opening_balance' ? 'Set initial balances for items. Duplicates will be rejected.' : 'Adjust existing inventory levels up or down.'}
            </p>
          </div>
          <div>
            <Label className="text-xs">CSV File</Label>
            <Input type="file" accept=".csv" className="h-8 text-xs cursor-pointer" disabled={!!result}
              onChange={e => setFile(e.target.files?.[0] || null)} data-testid="inv-import-file" />
            <p className="text-[10px] text-muted-foreground mt-1">
              Required columns: <span className="font-mono">item, qty</span>. Optional: <span className="font-mono">warehouse, ownership_type, uom, reference, notes, item_description</span>
            </p>
          </div>

          {/* Import Results */}
          {result && (
            <div className="border border-border rounded-md p-3 space-y-2" data-testid="inv-import-result">
              {result.duplicate ? (
                <p className="text-xs text-red-500 font-medium">Duplicate import — this file has already been processed.</p>
              ) : (
                <>
                  <div className="flex gap-4 text-xs">
                    <div><span className="text-muted-foreground">Processed:</span> <span className="font-bold" data-testid="inv-import-processed">{result.rows_processed}</span></div>
                    <div><span className="text-muted-foreground">Imported:</span> <span className="font-bold text-emerald-600" data-testid="inv-import-imported">{result.rows_imported}</span></div>
                    <div><span className="text-muted-foreground">Failed:</span> <span className={`font-bold ${result.rows_failed > 0 ? 'text-red-600' : ''}`} data-testid="inv-import-failed">{result.rows_failed}</span></div>
                  </div>
                  {result.errors?.length > 0 && (
                    <div className="max-h-32 overflow-y-auto border-t border-border/50 pt-2 space-y-1" data-testid="inv-import-errors">
                      {result.errors.map((e, i) => (
                        <p key={i} className="text-[10px] text-red-500">
                          Row {e.row}{e.item ? ` (${e.item})` : ''}: {e.error}
                        </p>
                      ))}
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
        <DialogFooter>
          {result ? (
            <Button size="sm" onClick={() => { if (result.rows_imported > 0) onImported(); else onClose(); }} data-testid="inv-import-done">
              {result.rows_imported > 0 ? 'Done & Refresh' : 'Close'}
            </Button>
          ) : (
            <>
              <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
              <Button size="sm" onClick={submit} disabled={uploading || !file} data-testid="inv-import-submit">
                {uploading ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Upload className="w-3.5 h-3.5 mr-1" />} Import
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* CREATE CUSTOMER DIALOG                                           */
/* ════════════════════════════════════════════════════════════════ */

function CreateCustomerDialog({ open, onClose, onCreated }) {
  const [name, setName] = useState('');
  const [code, setCode] = useState('');
  const [policy, setPolicy] = useState('warn_only');
  const [saving, setSaving] = useState(false);

  const submit = async () => {
    if (!name || !code) { toast.error('Name and code are required'); return; }
    setSaving(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/customers`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, code, negative_balance_policy: policy }) });
      const data = await res.json();
      if (res.ok && data.id) { toast.success(`Workspace created: ${data.name}`); onCreated(data); }
      else { toast.error(data.detail || 'Failed'); }
    } catch (e) { toast.error(e.message); }
    finally { setSaving(false); }
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-sm" data-testid="inv-create-customer-dialog">
        <DialogHeader><DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>New Customer Workspace</DialogTitle></DialogHeader>
        <div className="space-y-3">
          <div><Label className="text-xs">Customer Name</Label><Input className="h-8 text-xs" value={name} onChange={e => setName(e.target.value)} placeholder="Hormel Foods" data-testid="inv-cust-name" /></div>
          <div><Label className="text-xs">Code</Label><Input className="h-8 text-xs font-mono uppercase" value={code} onChange={e => setCode(e.target.value)} placeholder="HORMEL" data-testid="inv-cust-code" /></div>
          <div>
            <Label className="text-xs">Negative Balance Policy</Label>
            <Select value={policy} onValueChange={setPolicy}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="warn_only" className="text-xs">Warn Only</SelectItem>
                <SelectItem value="block_commitment" className="text-xs">Block Commitment</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
          <Button size="sm" onClick={submit} disabled={saving} data-testid="inv-cust-submit">Create</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
