import { useState, useEffect } from 'react';
import { 
  Card, CardContent, CardHeader, CardTitle, CardDescription 
} from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { 
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue 
} from '../components/ui/select';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { toast } from 'sonner';
import {
  Package, Truck, AlertTriangle, ShoppingCart, Anchor,
  RefreshCw, Users, Building2, ClipboardList, TrendingDown,
  ChevronRight, Search, Filter, Mail, FileText, Eye
} from 'lucide-react';
import { Input } from '../components/ui/input';

const API = process.env.REACT_APP_BACKEND_URL;

export default function SalesDashboardPage() {
  const [loading, setLoading] = useState(true);
  const [customers, setCustomers] = useState([]);
  const [selectedCustomer, setSelectedCustomer] = useState(null);
  const [selectedWarehouse, setSelectedWarehouse] = useState('all');
  const [warehouses, setWarehouses] = useState([]);
  const [dashboardData, setDashboardData] = useState(null);
  const [inventorySearch, setInventorySearch] = useState('');
  const [orderSearch, setOrderSearch] = useState('');
  const [activeTab, setActiveTab] = useState('inventory');
  
  // Email Documents state
  const [emailDocs, setEmailDocs] = useState({ total: 0, documents: [] });
  const [emailDocsLoading, setEmailDocsLoading] = useState(false);
  const [docTypeStats, setDocTypeStats] = useState([]);
  const [docTypeFilter, setDocTypeFilter] = useState('all');

  // Load customers and warehouses on mount
  useEffect(() => {
    const loadInitialData = async () => {
      try {
        const [custRes, whRes] = await Promise.all([
          fetch(`${API}/api/sales/customers`).then(r => r.json()),
          fetch(`${API}/api/sales/warehouses`).then(r => r.json())
        ]);
        setCustomers(custRes);
        setWarehouses(whRes);
        // Auto-select first customer
        if (custRes.length > 0) {
          setSelectedCustomer(custRes[0].customer_id);
        }
      } catch (err) {
        toast.error('Failed to load customers');
      } finally {
        setLoading(false);
      }
    };
    loadInitialData();
  }, []);

  // Load dashboard when customer changes
  useEffect(() => {
    if (!selectedCustomer) return;
    
    const loadDashboard = async () => {
      setLoading(true);
      try {
        const whParam = selectedWarehouse !== 'all' ? `&warehouse=${selectedWarehouse}` : '';
        const res = await fetch(`${API}/api/sales/customers/${selectedCustomer}/dashboard?days=30${whParam}`);
        const data = await res.json();
        setDashboardData(data);
      } catch (err) {
        toast.error('Failed to load dashboard');
      } finally {
        setLoading(false);
      }
    };
    loadDashboard();
  }, [selectedCustomer, selectedWarehouse]);

  // Load email documents when tab changes to 'documents'
  useEffect(() => {
    if (activeTab !== 'documents') return;
    loadEmailDocuments();
  }, [activeTab, docTypeFilter]);

  const loadEmailDocuments = async () => {
    setEmailDocsLoading(true);
    try {
      const typeParam = docTypeFilter !== 'all' ? `&document_type=${docTypeFilter}` : '';
      const [docsRes, statsRes] = await Promise.all([
        fetch(`${API}/api/sales/documents?limit=50${typeParam}`).then(r => r.json()),
        fetch(`${API}/api/sales/documents/stats/by-type?days=30`).then(r => r.json())
      ]);
      setEmailDocs(docsRes);
      setDocTypeStats(statsRes.by_type || []);
    } catch (err) {
      toast.error('Failed to load email documents');
    } finally {
      setEmailDocsLoading(false);
    }
  };

  const formatNumber = (num) => {
    if (num === null || num === undefined) return '0';
    return num.toLocaleString();
  };

  const formatDate = (dateStr) => {
    if (!dateStr) return '-';
    const d = new Date(dateStr);
    return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  };

  // Filter inventory by search
  const filteredInventory = dashboardData?.inventory_positions?.filter(inv => {
    if (!inventorySearch) return true;
    const search = inventorySearch.toLowerCase();
    return (
      inv.item_no?.toLowerCase().includes(search) ||
      inv.item_description?.toLowerCase().includes(search) ||
      inv.customer_sku?.toLowerCase().includes(search)
    );
  }) || [];

  // Filter orders by search
  const filteredOrders = dashboardData?.open_orders?.filter(order => {
    if (!orderSearch) return true;
    const search = orderSearch.toLowerCase();
    return (
      order.customer_po_no?.toLowerCase().includes(search) ||
      order.order_id?.toLowerCase().includes(search)
    );
  }) || [];

  if (loading && !dashboardData) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="sales-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6" data-testid="sales-dashboard-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <ShoppingCart className="w-6 h-6 text-primary" />
            Sales Inventory & Orders
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Phase 0 - BC Disconnected (Read-Only)
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={selectedCustomer || ''} onValueChange={setSelectedCustomer}>
            <SelectTrigger className="w-48" data-testid="customer-select">
              <SelectValue placeholder="Select Customer" />
            </SelectTrigger>
            <SelectContent>
              {customers.map(c => (
                <SelectItem key={c.customer_id} value={c.customer_id}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={selectedWarehouse} onValueChange={setSelectedWarehouse}>
            <SelectTrigger className="w-40" data-testid="warehouse-select">
              <SelectValue placeholder="Warehouse" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Warehouses</SelectItem>
              {warehouses.map(w => (
                <SelectItem key={w.warehouse_id} value={w.warehouse_id}>
                  {w.code}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="secondary" onClick={() => setSelectedCustomer(selectedCustomer)} data-testid="refresh-btn">
            <RefreshCw className="w-4 h-4" />
          </Button>
        </div>
      </div>

      {/* Customer Info Bar */}
      {dashboardData && (
        <Card className="border border-primary/30 bg-primary/5">
          <CardContent className="p-4">
            <div className="flex flex-wrap items-center gap-6">
              <div className="flex items-center gap-2">
                <Building2 className="w-5 h-5 text-primary" />
                <span className="font-semibold text-lg">{dashboardData.customer_name}</span>
              </div>
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Users className="w-4 h-4" />
                <span>{dashboardData.account_manager || 'No Manager Assigned'}</span>
              </div>
              <Badge variant="outline" className="bg-amber-100 text-amber-800 border-amber-300">
                BC: Not Connected
              </Badge>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Tabs for different views */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="grid w-full grid-cols-2 lg:w-96">
          <TabsTrigger value="inventory" className="flex items-center gap-2">
            <Package className="w-4 h-4" />
            Inventory & Orders
          </TabsTrigger>
          <TabsTrigger value="documents" className="flex items-center gap-2">
            <Mail className="w-4 h-4" />
            Email Documents
            {emailDocs.total > 0 && (
              <Badge variant="secondary" className="ml-1 text-xs">{emailDocs.total}</Badge>
            )}
          </TabsTrigger>
        </TabsList>

        {/* Inventory & Orders Tab */}
        <TabsContent value="inventory" className="space-y-6 mt-6">

      {/* Summary Cards */}
      {dashboardData && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4" data-testid="summary-cards">
          <Card className="border border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <Package className="w-5 h-5 text-emerald-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{formatNumber(dashboardData.summary.on_hand)}</p>
                  <p className="text-xs text-muted-foreground">On Hand</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                  <Package className="w-5 h-5 text-blue-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{formatNumber(dashboardData.summary.available)}</p>
                  <p className="text-xs text-muted-foreground">Available</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                  <ClipboardList className="w-5 h-5 text-amber-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{formatNumber(dashboardData.summary.allocated)}</p>
                  <p className="text-xs text-muted-foreground">Open Orders</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-cyan-100 dark:bg-cyan-900/30 flex items-center justify-center">
                  <Anchor className="w-5 h-5 text-cyan-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{formatNumber(dashboardData.summary.on_water)}</p>
                  <p className="text-xs text-muted-foreground">On Water</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border border-border">
            <CardContent className="p-4">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                  <Truck className="w-5 h-5 text-purple-600" />
                </div>
                <div>
                  <p className="text-2xl font-bold">{formatNumber(dashboardData.summary.on_order)}</p>
                  <p className="text-xs text-muted-foreground">On Order</p>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Alerts Panel */}
      {dashboardData?.alerts && dashboardData.alerts.length > 0 && (
        <Card className="border-2 border-amber-500/50 bg-amber-50/30 dark:bg-amber-900/10" data-testid="alerts-panel">
          <CardHeader className="pb-2">
            <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
              <AlertTriangle className="w-5 h-5 text-amber-600" />
              Alerts ({dashboardData.alerts.length})
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {dashboardData.alerts.map((alert, idx) => (
                <div 
                  key={idx} 
                  className={`p-3 rounded-lg flex items-center gap-3 ${
                    alert.severity === 'critical' 
                      ? 'bg-red-100 dark:bg-red-900/20 border border-red-200' 
                      : 'bg-amber-100 dark:bg-amber-900/20 border border-amber-200'
                  }`}
                >
                  {alert.alert_type === 'low_stock' && <Package className="w-4 h-4 text-amber-600" />}
                  {alert.alert_type === 'at_risk_order' && <Truck className="w-4 h-4 text-red-600" />}
                  {alert.alert_type === 'lost_business' && <TrendingDown className="w-4 h-4 text-amber-600" />}
                  <span className="text-sm flex-1">{alert.message}</span>
                  <Badge variant={alert.severity === 'critical' ? 'destructive' : 'secondary'} className="text-xs">
                    {alert.severity}
                  </Badge>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Inventory Grid */}
      {dashboardData && (
        <Card className="border border-border" data-testid="inventory-grid">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Package className="w-5 h-5 text-emerald-600" />
                Inventory Positions
              </CardTitle>
              <div className="relative w-64">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search items..."
                  value={inventorySearch}
                  onChange={(e) => setInventorySearch(e.target.value)}
                  className="pl-9"
                  data-testid="inventory-search"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Item No</th>
                    <th className="pb-2 font-medium">Customer SKU</th>
                    <th className="pb-2 font-medium">Description</th>
                    <th className="pb-2 font-medium">Warehouse</th>
                    <th className="pb-2 font-medium text-right">On Hand</th>
                    <th className="pb-2 font-medium text-right">Allocated</th>
                    <th className="pb-2 font-medium text-right">Available</th>
                    <th className="pb-2 font-medium text-right">On Water</th>
                    <th className="pb-2 font-medium text-right">On Order</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredInventory.map((inv, idx) => (
                    <tr key={inv.inventory_id || idx} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-3 font-mono text-xs">{inv.item_no}</td>
                      <td className="py-3 text-xs">{inv.customer_sku || '-'}</td>
                      <td className="py-3 text-xs max-w-[200px] truncate">{inv.item_description}</td>
                      <td className="py-3">
                        <Badge variant="outline" className="text-xs">{inv.warehouse_code}</Badge>
                      </td>
                      <td className="py-3 text-right font-mono">{formatNumber(inv.qty_on_hand)}</td>
                      <td className="py-3 text-right font-mono text-amber-600">{formatNumber(inv.qty_allocated)}</td>
                      <td className="py-3 text-right font-mono text-emerald-600 font-medium">{formatNumber(inv.qty_available)}</td>
                      <td className="py-3 text-right font-mono text-cyan-600">{formatNumber(inv.qty_on_water)}</td>
                      <td className="py-3 text-right font-mono text-purple-600">{formatNumber(inv.qty_on_order)}</td>
                    </tr>
                  ))}
                  {filteredInventory.length === 0 && (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-muted-foreground">
                        No inventory positions found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Open Orders Grid */}
      {dashboardData && (
        <Card className="border border-border" data-testid="orders-grid">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <ClipboardList className="w-5 h-5 text-amber-600" />
                Open Orders ({dashboardData.open_orders?.length || 0})
              </CardTitle>
              <div className="relative w-64">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
                <Input
                  placeholder="Search orders..."
                  value={orderSearch}
                  onChange={(e) => setOrderSearch(e.target.value)}
                  className="pl-9"
                  data-testid="order-search"
                />
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Customer PO</th>
                    <th className="pb-2 font-medium">Hub Order ID</th>
                    <th className="pb-2 font-medium">Order Date</th>
                    <th className="pb-2 font-medium">Requested Ship</th>
                    <th className="pb-2 font-medium">Status</th>
                    <th className="pb-2 font-medium text-right">Total Qty</th>
                    <th className="pb-2 font-medium text-right">Lines</th>
                    <th className="pb-2 font-medium">Source</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredOrders.map((order, idx) => (
                    <tr key={order.order_id || idx} className="border-b border-border/50 hover:bg-muted/30 cursor-pointer">
                      <td className="py-3 font-medium">{order.customer_po_no}</td>
                      <td className="py-3 font-mono text-xs text-muted-foreground">{order.order_id}</td>
                      <td className="py-3 text-xs">{order.order_date}</td>
                      <td className="py-3 text-xs">{order.requested_ship_date || '-'}</td>
                      <td className="py-3">
                        <Badge 
                          variant={
                            order.status === 'released' ? 'default' :
                            order.status === 'shipped' ? 'secondary' :
                            order.status === 'in_draft' ? 'outline' :
                            'secondary'
                          }
                          className={
                            order.status === 'released' ? 'bg-emerald-100 text-emerald-800 border-emerald-200' :
                            order.status === 'planned' ? 'bg-blue-100 text-blue-800 border-blue-200' :
                            ''
                          }
                        >
                          {order.status}
                        </Badge>
                      </td>
                      <td className="py-3 text-right font-mono">{formatNumber(order.total_qty)}</td>
                      <td className="py-3 text-right">{order.line_count}</td>
                      <td className="py-3">
                        <Badge variant="outline" className="text-xs">{order.source}</Badge>
                      </td>
                    </tr>
                  ))}
                  {filteredOrders.length === 0 && (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-muted-foreground">
                        No open orders found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Phase 0 Notice */}
      <Card className="border border-dashed border-muted-foreground/30 bg-muted/20">
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0">
              <Filter className="w-4 h-4 text-primary" />
            </div>
            <div>
              <p className="font-medium text-sm">Phase 0 - Feasibility Build</p>
              <p className="text-xs text-muted-foreground mt-1">
                This is a read-only view using seed data. Business Central integration is disabled.
                BC fields (bc_customer_no, bc_sales_order_no) are placeholders for Phase 1.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
