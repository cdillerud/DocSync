import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Progress } from './ui/progress';
import { Link2, Truck, FileText, RefreshCw, Package, Users, AlertTriangle } from 'lucide-react';
import { PieChart as RechartsPieChart, Pie, Cell, ResponsiveContainer, Tooltip, Legend } from 'recharts';

const COLORS = {
  po: '#3b82f6',
  shipment: '#22c55e',
  unresolved: '#64748b',
  invalid: '#ef4444',
  noExtracted: '#f59e0b',
};

function BCResolutionWidget() {
  const [metrics, setMetrics] = useState(null);
  const [topCustomers, setTopCustomers] = useState([]);
  const [loading, setLoading] = useState(true);

  const fetchMetrics = useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.get('/po-resolution/metrics');
      setMetrics(res.data);

      // Fetch top customers from resolved shipment docs
      const docsRes = await api.get('/documents', {
        params: { limit: 200, doc_types: 'Shipping_Document,Warehouse_Receipt,Freight_Document' }
      });
      const docs = docsRes.data?.documents || docsRes.data || [];
      const customerCounts = {};
      docs.forEach(d => {
        const cust = d.po_resolution?.bc_customer_name;
        if (cust && d.po_resolution?.status === 'resolved_shipment') {
          customerCounts[cust] = (customerCounts[cust] || 0) + 1;
        }
      });
      const sorted = Object.entries(customerCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([name, count]) => ({ name, count }));
      setTopCustomers(sorted);
    } catch (err) {
      console.error('Failed to fetch PO resolution metrics:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchMetrics(); }, [fetchMetrics]);

  if (loading || !metrics) {
    return (
      <Card className="border border-border" data-testid="bc-resolution-widget">
        <CardContent className="flex items-center justify-center h-48">
          <RefreshCw className="w-5 h-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const { po_resolution: poRes, bc_link: bcLink, total_shipping_docs: total } = metrics;
  const resolvedPO = poRes?.resolved_po || 0;
  const resolvedShipment = poRes?.resolved_shipment || 0;
  const resolvedTotal = poRes?.resolved || 0;
  const notFound = poRes?.not_found || 0;
  const missReasons = metrics.unresolved_by_miss_reason || {};

  const pieData = [
    { name: 'Purchase Orders', value: resolvedPO, color: COLORS.po },
    { name: 'Sales Shipments', value: resolvedShipment, color: COLORS.shipment },
    { name: 'Unresolved', value: notFound, color: COLORS.unresolved },
  ].filter(d => d.value > 0);

  const resolutionRate = poRes?.rate || 0;
  const bcLinkRate = bcLink?.rate_total || 0;

  return (
    <Card className="border border-border col-span-full" data-testid="bc-resolution-widget">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Link2 className="w-4 h-4 text-blue-500" />
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              BC Document Resolution
            </CardTitle>
          </div>
          <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={fetchMetrics} data-testid="refresh-resolution-btn">
            <RefreshCw className="w-3 h-3 mr-1" /> Refresh
          </Button>
        </div>
        <CardDescription>{total} shipping/freight documents analyzed</CardDescription>
      </CardHeader>
      <CardContent>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          {/* Left: Pie Chart */}
          <div className="flex flex-col items-center" data-testid="resolution-pie-chart">
            <ResponsiveContainer width="100%" height={180}>
              <RechartsPieChart>
                <Pie
                  data={pieData}
                  cx="50%" cy="50%"
                  innerRadius={45} outerRadius={72}
                  paddingAngle={2}
                  dataKey="value"
                  stroke="hsl(var(--card))"
                  strokeWidth={2}
                >
                  {pieData.map((entry, idx) => (
                    <Cell key={entry.name} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip
                  contentStyle={{
                    background: 'hsl(var(--card))',
                    border: '1px solid hsl(var(--border))',
                    borderRadius: '0.5rem',
                    fontSize: '11px'
                  }}
                  formatter={(value, name) => [`${value} docs`, name]}
                />
              </RechartsPieChart>
            </ResponsiveContainer>
            <div className="flex gap-4 text-xs mt-1">
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full" style={{ background: COLORS.po }} />
                PO ({resolvedPO})
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full" style={{ background: COLORS.shipment }} />
                Shipment ({resolvedShipment})
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2 h-2 rounded-full" style={{ background: COLORS.unresolved }} />
                Unresolved ({notFound})
              </span>
            </div>
          </div>

          {/* Middle: Key Metrics */}
          <div className="space-y-4" data-testid="resolution-metrics">
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-muted-foreground">Resolution Rate</span>
                <span className="font-bold font-mono">{resolutionRate.toFixed(1)}%</span>
              </div>
              <Progress value={resolutionRate} className="h-2" />
            </div>
            <div>
              <div className="flex justify-between text-sm mb-1">
                <span className="text-muted-foreground">BC Link Rate</span>
                <span className="font-bold font-mono">{bcLinkRate.toFixed(1)}%</span>
              </div>
              <Progress value={bcLinkRate} className="h-2" />
            </div>
            <div className="grid grid-cols-2 gap-2 pt-1">
              <div className="bg-blue-500/10 rounded-lg p-2 text-center">
                <Package className="w-3.5 h-3.5 mx-auto text-blue-500 mb-0.5" />
                <div className="text-lg font-bold text-blue-500">{resolvedPO}</div>
                <div className="text-[10px] text-muted-foreground">PO Matches</div>
              </div>
              <div className="bg-green-500/10 rounded-lg p-2 text-center">
                <Truck className="w-3.5 h-3.5 mx-auto text-green-500 mb-0.5" />
                <div className="text-lg font-bold text-green-500">{resolvedShipment}</div>
                <div className="text-[10px] text-muted-foreground">Shipment Matches</div>
              </div>
            </div>
            {Object.keys(missReasons).length > 0 && (
              <div className="space-y-1 pt-1">
                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Miss Taxonomy</div>
                {Object.entries(missReasons).sort((a, b) => b[1] - a[1]).slice(0, 4).map(([reason, count]) => (
                  <div key={reason} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground flex items-center gap-1">
                      <AlertTriangle className="w-3 h-3" />
                      {reason.replace(/_/g, ' ')}
                    </span>
                    <Badge variant="outline" className="text-[10px] h-5">{count}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Right: Top Customers */}
          <div data-testid="resolution-customers">
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
              <Users className="w-3 h-3 inline mr-1" />
              Top Linked Customers
            </div>
            {topCustomers.length > 0 ? (
              <div className="space-y-2">
                {topCustomers.map((c, i) => (
                  <div key={c.name} className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground truncate max-w-[180px]" title={c.name}>
                      {c.name}
                    </span>
                    <Badge variant="secondary" className="text-[10px] h-5 font-mono">{c.count}</Badge>
                  </div>
                ))}
              </div>
            ) : (
              <div className="py-6 text-center text-xs text-muted-foreground">
                <FileText className="w-6 h-6 mx-auto mb-1 opacity-40" />
                No shipment links yet
              </div>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default BCResolutionWidget;
