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
  RotateCcw, FileText,
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
  const [search, setSearch] = useState('');

  const cid = customer?.id;

  const refresh = useCallback(async () => {
    if (!cid) return;
    setLoading(true);
    try {
      const [sumRes, balRes, movRes, incRes] = await Promise.all([
        fetch(`${API}/api/inventory-ledger/customers/${cid}/summary`),
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
          </TabsList>
          <div className="flex gap-2">
            {tab === 'balances' && (
              <div className="relative w-48">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                <Input placeholder="Filter items..." value={search} onChange={e => setSearch(e.target.value)} className="pl-8 h-8 text-xs" data-testid="inv-balance-search" />
              </div>
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
          <BalanceTable balances={filteredBalances} loading={loading} />
        </TabsContent>
        <TabsContent value="movements">
          <MovementTable movements={movements} total={movementTotal} />
        </TabsContent>
        <TabsContent value="incoming">
          <IncomingTable records={incoming} customerId={cid} onUpdate={refresh} />
        </TabsContent>
      </Tabs>

      {/* Movement Form Dialog */}
      {showMovementForm && (
        <MovementFormDialog open={showMovementForm} customerId={cid} onClose={() => setShowMovementForm(false)} onCreated={() => { setShowMovementForm(false); refresh(); }} />
      )}
      {showIncomingForm && (
        <IncomingFormDialog open={showIncomingForm} customerId={cid} onClose={() => setShowIncomingForm(false)} onCreated={() => { setShowIncomingForm(false); refresh(); }} />
      )}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* SUMMARY STRIP                                                    */
/* ════════════════════════════════════════════════════════════════ */

function SummaryStrip({ summary }) {
  const cards = [
    { label: 'Items Tracked', value: summary.total_items, icon: Package, color: 'text-blue-500' },
    { label: 'On Hand', value: summary.total_on_hand, icon: Box, color: 'text-emerald-500' },
    { label: 'Incoming', value: summary.total_incoming, icon: Truck, color: 'text-sky-500' },
    { label: 'Committed', value: summary.total_committed, icon: ClipboardList, color: 'text-amber-500' },
    { label: 'Shortages', value: summary.shortage_count, icon: TrendingDown, color: summary.shortage_count > 0 ? 'text-red-500' : 'text-muted-foreground' },
  ];
  return (
    <div className="grid grid-cols-2 sm:grid-cols-5 gap-3" data-testid="inv-summary-strip">
      {cards.map(c => {
        const Icon = c.icon;
        return (
          <div key={c.label} className="bg-muted/30 border border-border rounded-md p-3 flex items-center gap-3">
            <Icon className={`w-5 h-5 ${c.color} shrink-0`} />
            <div>
              <p className="text-lg font-bold leading-tight">{typeof c.value === 'number' ? c.value.toLocaleString() : c.value}</p>
              <p className="text-[10px] text-muted-foreground">{c.label}</p>
            </div>
          </div>
        );
      })}
    </div>
  );
}

/* ════════════════════════════════════════════════════════════════ */
/* BALANCE TABLE                                                    */
/* ════════════════════════════════════════════════════════════════ */

function BalanceTable({ balances, loading }) {
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
            </tr>
          </thead>
          <tbody>
            {balances.map((b, i) => {
              const oc = OWNERSHIP_COLORS[b.ownership_type] || OWNERSHIP_COLORS.unknown;
              return (
                <tr key={i} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-balance-row-${i}`}>
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

const STATUS_COLORS = { expected: 'bg-sky-100 text-sky-700', in_transit: 'bg-amber-100 text-amber-700', received: 'bg-emerald-100 text-emerald-700', cancelled: 'bg-gray-100 text-gray-500' };

function IncomingTable({ records, customerId, onUpdate }) {
  const updateStatus = async (id, status) => {
    try {
      await fetch(`${API}/api/inventory-ledger/customers/${customerId}/incoming/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status }) });
      toast.success(`Status updated to ${status}`);
      onUpdate();
    } catch { toast.error('Update failed'); }
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
              <th className="text-right py-2 px-3 font-medium">Action</th>
            </tr>
          </thead>
          <tbody>
            {records.map(r => (
              <tr key={r.id} className="border-b border-border/50 hover:bg-muted/20" data-testid={`inv-incoming-${r.id}`}>
                <td className="py-1.5 px-3 font-mono font-medium">{r.item}</td>
                <td className="py-1.5 px-3 font-mono">{r.warehouse}</td>
                <td className="py-1.5 px-3 text-right font-mono font-bold">{r.incoming_qty.toLocaleString()}</td>
                <td className="py-1.5 px-3">{r.unit_of_measure}</td>
                <td className="py-1.5 px-3">{r.eta || '-'}</td>
                <td className="py-1.5 px-3 font-mono">{r.source_reference || '-'}</td>
                <td className="py-1.5 px-3"><Badge variant="secondary" className={`text-[9px] ${STATUS_COLORS[r.status] || ''}`}>{r.status}</Badge></td>
                <td className="py-1.5 px-3 text-right">
                  {r.status === 'expected' && <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5" onClick={() => updateStatus(r.id, 'in_transit')}>In Transit</Button>}
                  {r.status === 'in_transit' && <Button variant="outline" size="sm" className="h-5 text-[9px] px-1.5" onClick={() => updateStatus(r.id, 'received')}>Received</Button>}
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
/* MOVEMENT FORM DIALOG                                             */
/* ════════════════════════════════════════════════════════════════ */

function MovementFormDialog({ open, customerId, onClose, onCreated }) {
  const [form, setForm] = useState({ item: '', item_description: '', warehouse: 'MAIN', ownership_type: 'customer_owned', movement_type: 'receipt', quantity_delta: '', unit_of_measure: 'cases', source_type: 'manual_entry', reference_type: '', reference_id: '', notes: '' });
  const [saving, setSaving] = useState(false);

  const update = (k, v) => setForm(prev => ({ ...prev, [k]: v }));

  const submit = async () => {
    if (!form.item || !form.quantity_delta) { toast.error('Item and quantity are required'); return; }
    setSaving(true);
    try {
      const payload = { ...form, quantity_delta: parseFloat(form.quantity_delta) };
      const res = await fetch(`${API}/api/inventory-ledger/customers/${customerId}/movements`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
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
        <DialogHeader><DialogTitle className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>New Movement Entry</DialogTitle></DialogHeader>
        <div className="space-y-3 max-h-[60vh] overflow-y-auto pr-1">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Movement Type</Label>
              <Select value={form.movement_type} onValueChange={v => update('movement_type', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{MOVEMENT_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{t.replace(/_/g, ' ')}</SelectItem>)}</SelectContent>
              </Select>
            </div>
            <div>
              <Label className="text-xs">Source Type</Label>
              <Select value={form.source_type} onValueChange={v => update('source_type', v)}>
                <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
                <SelectContent>{SOURCE_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{t.replace(/_/g, ' ')}</SelectItem>)}</SelectContent>
              </Select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Item / SKU</Label>
              <Input className="h-8 text-xs" value={form.item} onChange={e => update('item', e.target.value)} placeholder="SPAM-12OZ" data-testid="inv-mov-item" />
            </div>
            <div>
              <Label className="text-xs">Description</Label>
              <Input className="h-8 text-xs" value={form.item_description} onChange={e => update('item_description', e.target.value)} placeholder="SPAM Classic 12oz" />
            </div>
          </div>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <Label className="text-xs">Quantity</Label>
              <Input type="number" className="h-8 text-xs font-mono" value={form.quantity_delta} onChange={e => update('quantity_delta', e.target.value)} placeholder="+100 or -50" data-testid="inv-mov-qty" />
              <p className="text-[9px] text-muted-foreground mt-0.5">Positive = in, Negative = out</p>
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
            <Label className="text-xs">Ownership</Label>
            <Select value={form.ownership_type} onValueChange={v => update('ownership_type', v)}>
              <SelectTrigger className="h-8 text-xs"><SelectValue /></SelectTrigger>
              <SelectContent>{OWNERSHIP_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{OWNERSHIP_LABELS[t]}</SelectItem>)}</SelectContent>
            </Select>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Reference Type</Label>
              <Input className="h-8 text-xs" value={form.reference_type} onChange={e => update('reference_type', e.target.value)} placeholder="sales_order" />
            </div>
            <div>
              <Label className="text-xs">Reference ID</Label>
              <Input className="h-8 text-xs" value={form.reference_id} onChange={e => update('reference_id', e.target.value)} placeholder="SO-107040" />
            </div>
          </div>
          <div>
            <Label className="text-xs">Notes</Label>
            <Textarea className="text-xs min-h-[50px]" value={form.notes} onChange={e => update('notes', e.target.value)} />
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
