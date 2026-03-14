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
  RotateCcw, FileText, Download, Settings, Pencil, Upload,
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
  const [historyItem, setHistoryItem] = useState(null);

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
          <BalanceTable balances={filteredBalances} loading={loading} onItemClick={(item) => setHistoryItem({ item, customerId: cid })} />
        </TabsContent>
        <TabsContent value="movements">
          <MovementTable movements={movements} total={movementTotal} />
        </TabsContent>
        <TabsContent value="incoming">
          <IncomingTable records={incoming} customerId={cid} onUpdate={refresh} />
        </TabsContent>
        <TabsContent value="reorder">
          <ReorderPanel customerId={cid} onSupplyCreated={refresh} />
        </TabsContent>
        <TabsContent value="settings">
          <ItemSettingsPanel customerId={cid} />
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
      {/* Item History Modal */}
      {historyItem && (
        <ItemHistoryModal
          item={historyItem.item}
          customerId={historyItem.customerId}
          onClose={() => setHistoryItem(null)}
        />
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* REORDER RECOMMENDATIONS                                          */
/* ════════════════════════════════════════════════════════════════ */

function ReorderPanel({ customerId, onSupplyCreated }) {
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
                  <span className="font-mono font-medium">{r.item}</span>
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
