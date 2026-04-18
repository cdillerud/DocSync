import { useEffect, useState, useCallback } from 'react';
import { Activity, AlertTriangle, TrendingUp, TrendingDown, RefreshCw, Sparkles, Package, Database, Calendar, Zap } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function Metric({ label, value, hint, color = 'text-foreground', icon: Icon }) {
  return (
    <div className="bg-card border border-border rounded-lg p-3">
      <div className="flex items-center gap-2 text-[11px] uppercase tracking-wide text-muted-foreground">
        {Icon && <Icon className="h-3 w-3" />} {label}
      </div>
      <div className={`text-2xl font-bold mt-1 ${color}`} data-testid={`metric-${label.replace(/\s+/g,'-').toLowerCase()}`}>
        {value}
      </div>
      {hint && <div className="text-[10px] text-muted-foreground mt-0.5">{hint}</div>}
    </div>
  );
}

function num(v) {
  if (v == null) return '—';
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(v);
}

function daysSince(iso) {
  if (!iso) return null;
  const ms = Date.now() - new Date(iso).getTime();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

function StatusDot({ shortage, low }) {
  if (shortage > 0) return <span className="inline-block w-2 h-2 rounded-full bg-red-500" title="Shortage" />;
  if (low > 0) return <span className="inline-block w-2 h-2 rounded-full bg-amber-500" title="Low stock" />;
  return <span className="inline-block w-2 h-2 rounded-full bg-emerald-500" title="Healthy" />;
}

export default function InventoryHealthPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inventory-ledger/health-summary`);
      setData(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetch_(); }, [fetch_]);

  if (loading && !data) return <div className="text-sm text-muted-foreground">Loading inventory health…</div>;
  if (!data) return <div className="text-sm text-red-400">Failed to load health summary.</div>;

  const t = data.totals || {};
  const xls = data.xls_activity || {};
  const autoPct = (xls.auto_apply_ratio_30d || 0) * 100;

  return (
    <div className="space-y-6" data-testid="inventory-health-page">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight flex items-center gap-2">
            <Activity className="h-5 w-5 text-emerald-400" /> Inventory Health
          </h2>
          <p className="text-sm text-muted-foreground">
            Cross-customer supply-chain overview. Derived from the inventory ledger, updated as XLS imports are approved.
          </p>
        </div>
        <button onClick={fetch_} className="p-2 rounded border border-border hover:bg-muted" title="Refresh">
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Top-line totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric label="Customers" value={t.customer_count} hint="with active ledger" icon={Package} />
        <Metric label="Distinct Items" value={num(t.total_items)} hint="across all workspaces" icon={Database} />
        <Metric label="On Hand" value={num(t.total_on_hand)} hint="total balance" icon={TrendingUp} color="text-emerald-400" />
        <Metric label="Committed" value={num(t.total_committed)} hint="open orders outflow" icon={TrendingDown} color="text-amber-400" />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Metric
          label="Shortages"
          value={t.total_shortage_buckets}
          hint="items with committed > available"
          icon={AlertTriangle}
          color={t.total_shortage_buckets > 0 ? 'text-red-400' : 'text-muted-foreground'}
        />
        <Metric
          label="Low Stock"
          value={t.total_low_buckets}
          hint="below threshold"
          icon={AlertTriangle}
          color={t.total_low_buckets > 0 ? 'text-amber-400' : 'text-muted-foreground'}
        />
        <Metric
          label="Stale Customers"
          value={t.stale_customer_count}
          hint={`no movement >${data.thresholds?.stale_days || 30}d`}
          icon={Calendar}
          color={t.stale_customer_count > 0 ? 'text-sky-400' : 'text-muted-foreground'}
        />
        <Metric
          label="Incoming Supply"
          value={num(t.total_incoming)}
          hint="planned receipts (forecasts)"
          icon={TrendingUp}
          color="text-sky-400"
        />
      </div>

      {/* XLS activity strip */}
      <div className="bg-card border border-border rounded-lg p-4" data-testid="xls-activity">
        <div className="flex items-center gap-2 mb-2">
          <Sparkles className="h-4 w-4 text-amber-400" />
          <h3 className="text-sm font-semibold">XLS Pipeline Activity (last 30 days)</h3>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
          <div>
            <div className="text-xl font-bold">{xls.staged_last_30d || 0}</div>
            <div className="text-[10px] uppercase text-muted-foreground">Staged</div>
          </div>
          <div>
            <div className="text-xl font-bold text-emerald-400">{xls.applied_last_30d || 0}</div>
            <div className="text-[10px] uppercase text-muted-foreground">Applied</div>
          </div>
          <div>
            <div className="text-xl font-bold text-violet-400 flex items-center gap-1">
              <Zap className="h-4 w-4" />{xls.auto_applied_last_30d || 0}
            </div>
            <div className="text-[10px] uppercase text-muted-foreground">Auto-Applied</div>
          </div>
          <div>
            <div className={`text-xl font-bold ${autoPct >= 40 ? 'text-emerald-400' : autoPct >= 10 ? 'text-amber-400' : 'text-muted-foreground'}`}>
              {autoPct.toFixed(0)}%
            </div>
            <div className="text-[10px] uppercase text-muted-foreground">Auto Ratio</div>
          </div>
          <div>
            <div className="text-xl font-bold">{xls.staged_last_7d || 0}</div>
            <div className="text-[10px] uppercase text-muted-foreground">Staged 7d</div>
          </div>
        </div>
      </div>

      {/* Per-customer roll-up table */}
      <div className="bg-card border border-border rounded-lg overflow-hidden">
        <div className="px-4 pt-4 pb-2">
          <h3 className="text-sm font-semibold">Customer Roll-up</h3>
          <p className="text-[11px] text-muted-foreground">Sorted: shortages first, then by outgoing commitment volume.</p>
        </div>
        {(data.per_customer || []).length === 0 ? (
          <div className="py-12 text-center text-sm text-muted-foreground">No customer balances yet. Approve some XLS imports to populate.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted-foreground border-b border-border">
                  <th className="pb-2 pl-4 pr-3">Status</th>
                  <th className="pb-2 pr-3">Customer</th>
                  <th className="pb-2 pr-3 text-right">Items</th>
                  <th className="pb-2 pr-3 text-right">On Hand</th>
                  <th className="pb-2 pr-3 text-right">Incoming</th>
                  <th className="pb-2 pr-3 text-right">Committed</th>
                  <th className="pb-2 pr-3 text-right">Shortages</th>
                  <th className="pb-2 pr-3 text-right">Low</th>
                  <th className="pb-2 pr-3">Last Move</th>
                </tr>
              </thead>
              <tbody>
                {data.per_customer.map(c => {
                  const d = daysSince(c.last_movement);
                  const staleColor = c.is_stale ? 'text-sky-400' : d != null && d <= 7 ? 'text-emerald-400' : 'text-muted-foreground';
                  return (
                    <tr key={c.customer_id} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-2.5 pl-4 pr-3"><StatusDot shortage={c.shortage_buckets} low={c.low_buckets} /></td>
                      <td className="py-2.5 pr-3">
                        <div className="text-sm font-medium">{c.customer_name}</div>
                        <div className="text-[10px] font-mono text-muted-foreground">{c.customer_code}</div>
                      </td>
                      <td className="py-2.5 pr-3 text-right font-mono text-xs">{c.total_items}</td>
                      <td className="py-2.5 pr-3 text-right font-mono text-xs">{num(c.total_on_hand)}</td>
                      <td className="py-2.5 pr-3 text-right font-mono text-xs text-sky-400">{num(c.total_incoming)}</td>
                      <td className="py-2.5 pr-3 text-right font-mono text-xs text-amber-400">{num(c.total_committed)}</td>
                      <td className={`py-2.5 pr-3 text-right font-mono text-xs ${c.shortage_buckets > 0 ? 'text-red-400 font-bold' : 'text-muted-foreground'}`}>{c.shortage_buckets || '—'}</td>
                      <td className={`py-2.5 pr-3 text-right font-mono text-xs ${c.low_buckets > 0 ? 'text-amber-400' : 'text-muted-foreground'}`}>{c.low_buckets || '—'}</td>
                      <td className={`py-2.5 pr-3 text-xs ${staleColor}`}>
                        {d == null ? '—' : d === 0 ? 'today' : `${d}d ago`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Items at risk */}
      {(data.items_at_risk || []).length > 0 && (
        <div className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-4 pt-4 pb-2">
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <AlertTriangle className="h-4 w-4 text-red-400" /> Items At Risk
            </h3>
            <p className="text-[11px] text-muted-foreground">
              Committed outflow exceeds on-hand + incoming supply — will stock out unless receipts land.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-[11px] text-muted-foreground border-b border-border">
                  <th className="pb-2 pl-4 pr-3">Customer</th>
                  <th className="pb-2 pr-3">Item</th>
                  <th className="pb-2 pr-3">Warehouse</th>
                  <th className="pb-2 pr-3 text-right">On Hand</th>
                  <th className="pb-2 pr-3 text-right">Incoming</th>
                  <th className="pb-2 pr-3 text-right">Committed</th>
                  <th className="pb-2 pr-3 text-right">Available</th>
                  <th className="pb-2 pr-3 text-right">Gap</th>
                </tr>
              </thead>
              <tbody>
                {data.items_at_risk.map((r, i) => (
                  <tr key={i} className="border-b border-border/50 hover:bg-muted/30">
                    <td className="py-2 pl-4 pr-3 text-xs">{r.customer_name}</td>
                    <td className="py-2 pr-3 font-mono text-xs">{r.item}</td>
                    <td className="py-2 pr-3 text-xs">{r.warehouse}</td>
                    <td className="py-2 pr-3 text-right font-mono text-xs">{num(r.on_hand)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-xs text-sky-400">{num(r.incoming)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-xs text-amber-400">{num(r.committed)}</td>
                    <td className={`py-2 pr-3 text-right font-mono text-xs ${r.available < 0 ? 'text-red-400 font-bold' : ''}`}>{num(r.available)}</td>
                    <td className="py-2 pr-3 text-right font-mono text-xs text-red-400 font-bold">{num(r.gap)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="text-[10px] text-muted-foreground text-right">
        Generated: {new Date(data.generated_at).toLocaleString()}
      </div>
    </div>
  );
}
