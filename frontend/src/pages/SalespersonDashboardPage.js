import { useState, useEffect, useCallback } from 'react';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import {
  Users, TrendingUp, Target, Zap, Clock, UserCheck, AlertTriangle,
  BarChart3, Activity, ChevronRight, RefreshCw, ArrowUpRight, ArrowDownRight, Minus
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, CartesianGrid, Legend } from 'recharts';

const CHART_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16', '#64748b', '#f97316'];

function formatDuration(seconds) {
  if (!seconds) return '--';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function TrendIndicator({ value, suffix = '%' }) {
  if (value === null || value === undefined) return <Minus className="w-3.5 h-3.5 text-muted-foreground" />;
  if (value > 0) return <span className="flex items-center gap-0.5 text-emerald-400 text-xs font-medium"><ArrowUpRight className="w-3.5 h-3.5" />{value}{suffix}</span>;
  if (value < 0) return <span className="flex items-center gap-0.5 text-red-400 text-xs font-medium"><ArrowDownRight className="w-3.5 h-3.5" />{Math.abs(value)}{suffix}</span>;
  return <Minus className="w-3.5 h-3.5 text-muted-foreground" />;
}

function MetricCard({ icon: Icon, label, value, subValue, color = 'primary' }) {
  const colorClasses = {
    primary: 'from-blue-500/10 to-blue-600/5 border-blue-500/20',
    success: 'from-emerald-500/10 to-emerald-600/5 border-emerald-500/20',
    warning: 'from-amber-500/10 to-amber-600/5 border-amber-500/20',
    danger: 'from-red-500/10 to-red-600/5 border-red-500/20',
    purple: 'from-purple-500/10 to-purple-600/5 border-purple-500/20',
  };
  const iconColors = {
    primary: 'text-blue-400',
    success: 'text-emerald-400',
    warning: 'text-amber-400',
    danger: 'text-red-400',
    purple: 'text-purple-400',
  };

  return (
    <Card className={`bg-gradient-to-br ${colorClasses[color]} border`} data-testid={`metric-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <CardContent className="p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">{label}</p>
            <p className="text-2xl font-bold tracking-tight">{value}</p>
            {subValue && <p className="text-xs text-muted-foreground mt-1">{subValue}</p>}
          </div>
          <div className={`p-2 rounded-lg bg-background/50 ${iconColors[color]}`}>
            <Icon className="w-5 h-5" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function RepRow({ rep, rank, onSelect }) {
  const successRate = rep.success_rate || 0;
  const barColor = successRate >= 80 ? 'bg-emerald-500' : successRate >= 50 ? 'bg-amber-500' : 'bg-red-500';
  const statusColor = successRate >= 80 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
    : successRate >= 50 ? 'bg-amber-500/10 text-amber-400 border-amber-500/30'
    : 'bg-red-500/10 text-red-400 border-red-500/30';

  return (
    <TableRow
      className="cursor-pointer hover:bg-accent/50 transition-colors"
      onClick={() => onSelect(rep.code)}
      data-testid={`rep-row-${rep.code}`}
    >
      <TableCell className="font-mono text-muted-foreground text-xs w-8">{rank}</TableCell>
      <TableCell>
        <div className="flex flex-col">
          <span className="font-semibold text-sm">{rep.name || rep.code}</span>
          <span className="text-xs text-muted-foreground font-mono">{rep.code}</span>
        </div>
      </TableCell>
      <TableCell className="text-center">
        <span className="text-lg font-bold">{rep.total_documents}</span>
      </TableCell>
      <TableCell className="text-center">
        <span className="font-semibold text-emerald-400">{rep.auto_created}</span>
        <span className="text-muted-foreground text-xs"> / {rep.auto_attempted}</span>
      </TableCell>
      <TableCell className="w-40">
        <div className="flex items-center gap-2">
          <div className="flex-1 h-2 rounded-full bg-muted overflow-hidden">
            <div className={`h-full rounded-full transition-all ${barColor}`} style={{ width: `${Math.min(successRate, 100)}%` }} />
          </div>
          <Badge variant="outline" className={`text-[10px] px-1.5 py-0 ${statusColor}`}>
            {successRate.toFixed(0)}%
          </Badge>
        </div>
      </TableCell>
      <TableCell className="text-center font-medium">{rep.unique_customers}</TableCell>
      <TableCell className="text-center text-sm">
        {formatDuration(rep.avg_processing_seconds)}
      </TableCell>
      <TableCell className="text-center">
        {rep.pending_review > 0 ? (
          <Badge variant="outline" className="bg-amber-500/10 text-amber-400 border-amber-500/30 text-xs">
            {rep.pending_review}
          </Badge>
        ) : (
          <span className="text-muted-foreground text-xs">--</span>
        )}
      </TableCell>
      <TableCell className="w-8">
        <ChevronRight className="w-4 h-4 text-muted-foreground" />
      </TableCell>
    </TableRow>
  );
}

function RepDetailPanel({ code, days, onClose }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    api.get(`/salesperson-dashboard/detail/${code}?days=${days}`)
      .then(res => setData(res.data))
      .catch(() => toast.error('Failed to load rep details'))
      .finally(() => setLoading(false));
  }, [code, days]);

  if (loading) return (
    <Card className="border-primary/30" data-testid="rep-detail-loading">
      <CardContent className="p-8 text-center">
        <RefreshCw className="w-6 h-6 animate-spin mx-auto text-muted-foreground" />
        <p className="text-sm text-muted-foreground mt-3">Loading details...</p>
      </CardContent>
    </Card>
  );

  if (!data) return null;

  const sp = data.salesperson || {};
  const breakdown = data.customer_breakdown || [];
  const recentDocs = data.recent_documents || [];

  return (
    <Card className="border-primary/30" data-testid="rep-detail-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-lg">{sp.name || sp.code}</CardTitle>
            <CardDescription className="font-mono text-xs">{sp.code}{sp.email ? ` — ${sp.email}` : ''}</CardDescription>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} data-testid="close-rep-detail-btn">Close</Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Customer Breakdown */}
        {breakdown.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">Customer Breakdown</h4>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
              {breakdown.slice(0, 9).map(c => (
                <div key={c.name} className="flex items-center justify-between p-2.5 rounded-lg bg-muted/30 border border-border/50">
                  <span className="text-sm font-medium truncate flex-1 mr-2">{c.name}</span>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-sm font-bold">{c.total}</span>
                    {c.auto_created > 0 && <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]">{c.auto_created} auto</Badge>}
                    {c.pending > 0 && <Badge className="bg-amber-500/20 text-amber-400 text-[10px]">{c.pending} pending</Badge>}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent Documents */}
        {recentDocs.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-3 text-muted-foreground uppercase tracking-wider">Recent Documents</h4>
            <div className="rounded-lg border overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30">
                    <TableHead className="text-xs">File</TableHead>
                    <TableHead className="text-xs">Customer</TableHead>
                    <TableHead className="text-xs">SO #</TableHead>
                    <TableHead className="text-xs">Status</TableHead>
                    <TableHead className="text-xs">Date</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {recentDocs.slice(0, 10).map(doc => (
                    <TableRow key={doc.id} className="text-sm">
                      <TableCell className="font-mono text-xs truncate max-w-[180px]">{doc.filename}</TableCell>
                      <TableCell className="text-xs truncate max-w-[120px]">{doc.customer_extracted || '--'}</TableCell>
                      <TableCell className="font-mono text-xs">{doc.bc_sales_order_number || '--'}</TableCell>
                      <TableCell>
                        {doc.auto_create_success ? (
                          <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]">Auto-Created</Badge>
                        ) : doc.review_status === 'needs_review' ? (
                          <Badge className="bg-amber-500/20 text-amber-400 text-[10px]">Needs Review</Badge>
                        ) : (
                          <Badge variant="outline" className="text-[10px]">{doc.status || doc.bc_posting_status || 'Pending'}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {doc.created_utc ? new Date(doc.created_utc).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) : '--'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {breakdown.length === 0 && recentDocs.length === 0 && (
          <div className="text-center py-8">
            <Users className="w-10 h-10 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No activity found for this rep in the last {days} days</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function SalespersonDashboardPage() {
  const [overview, setOverview] = useState(null);
  const [trend, setTrend] = useState(null);
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState('90');
  const [selectedRep, setSelectedRep] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [ovRes, trRes] = await Promise.all([
        api.get(`/salesperson-dashboard/overview?days=${days}`),
        api.get(`/salesperson-dashboard/trend?days=${days}&interval=week`),
      ]);
      setOverview(ovRes.data);
      setTrend(trRes.data);
    } catch (err) {
      toast.error('Failed to load dashboard data');
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const totals = overview?.totals || {};
  const reps = overview?.salespersons || [];
  const unassigned = overview?.unassigned;
  const trendData = trend?.data || [];

  // Chart data: top reps by volume
  const chartData = reps.slice(0, 8).map((r, i) => ({
    name: r.name?.split(' ')[0] || r.code,
    code: r.code,
    total: r.total_documents,
    auto_created: r.auto_created,
    pending: r.pending_review,
    fill: CHART_COLORS[i % CHART_COLORS.length],
  }));

  return (
    <div className="space-y-6" data-testid="salesperson-dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Rep Performance</h2>
          <p className="text-sm text-muted-foreground">Sales order automation metrics by salesperson</p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="w-[130px] h-8 text-xs" data-testid="days-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
              <SelectItem value="180">Last 6 months</SelectItem>
              <SelectItem value="365">Last year</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="outline" size="sm" onClick={fetchData} disabled={loading} data-testid="refresh-btn">
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <MetricCard
          icon={Users}
          label="Active Reps"
          value={totals.active_reps || 0}
          subValue={`${totals.days || 0}d window`}
          color="primary"
        />
        <MetricCard
          icon={Target}
          label="Total Documents"
          value={totals.total_documents || 0}
          subValue="Sales docs ingested"
          color="purple"
        />
        <MetricCard
          icon={Zap}
          label="Auto-Created"
          value={totals.total_auto_created || 0}
          subValue={`of ${totals.total_auto_attempted || 0} attempted`}
          color="success"
        />
        <MetricCard
          icon={TrendingUp}
          label="Success Rate"
          value={`${totals.overall_success_rate || 0}%`}
          subValue="Auto-creation rate"
          color={totals.overall_success_rate >= 70 ? 'success' : 'warning'}
        />
        <MetricCard
          icon={AlertTriangle}
          label="Needs Review"
          value={totals.total_pending_review || 0}
          subValue="Pending action"
          color={totals.total_pending_review > 0 ? 'danger' : 'success'}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Volume by Rep */}
        <Card data-testid="volume-chart">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-blue-400" />
              Volume by Rep
            </CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={chartData} barGap={2}>
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={30} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    formatter={(val, name) => [val, name === 'auto_created' ? 'Auto-Created' : name === 'total' ? 'Total Docs' : name]}
                  />
                  <Bar dataKey="total" radius={[4, 4, 0, 0]} name="Total Docs">
                    {chartData.map((entry, i) => <Cell key={i} fill={entry.fill} fillOpacity={0.7} />)}
                  </Bar>
                  <Bar dataKey="auto_created" radius={[4, 4, 0, 0]} fill="#22c55e" fillOpacity={0.9} name="Auto-Created" />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-muted-foreground text-sm">
                No rep data available yet
              </div>
            )}
          </CardContent>
        </Card>

        {/* Trend */}
        <Card data-testid="trend-chart">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold flex items-center gap-2">
              <Activity className="w-4 h-4 text-emerald-400" />
              Weekly Trend
            </CardTitle>
          </CardHeader>
          <CardContent>
            {trendData.length > 1 ? (
              <ResponsiveContainer width="100%" height={220}>
                <LineChart data={trendData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                  <XAxis
                    dataKey="period"
                    tick={{ fontSize: 10 }}
                    axisLine={false}
                    tickLine={false}
                    tickFormatter={v => { const d = new Date(v); return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }}
                  />
                  <YAxis tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={30} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }}
                    labelFormatter={v => { const d = new Date(v); return `Week of ${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}`; }}
                  />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="total" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} name="Total" />
                  <Line type="monotone" dataKey="auto_created" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} name="Auto-Created" />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[220px] flex items-center justify-center text-muted-foreground text-sm">
                {trendData.length === 1 ? 'Need more data points for trend' : 'No trend data available'}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Rep Detail Panel (if selected) */}
      {selectedRep && (
        <RepDetailPanel
          code={selectedRep}
          days={parseInt(days)}
          onClose={() => setSelectedRep(null)}
        />
      )}

      {/* Rep Leaderboard Table */}
      <Card data-testid="rep-leaderboard">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold flex items-center gap-2">
            <UserCheck className="w-4 h-4 text-primary" />
            Rep Leaderboard
          </CardTitle>
          <CardDescription className="text-xs">Click a row to see detailed breakdown</CardDescription>
        </CardHeader>
        <CardContent>
          {reps.length > 0 ? (
            <div className="rounded-lg border overflow-hidden">
              <Table>
                <TableHeader>
                  <TableRow className="bg-muted/30">
                    <TableHead className="text-[10px] w-8">#</TableHead>
                    <TableHead className="text-[10px]">Rep</TableHead>
                    <TableHead className="text-[10px] text-center">Docs</TableHead>
                    <TableHead className="text-[10px] text-center">Auto / Attempted</TableHead>
                    <TableHead className="text-[10px]">Success Rate</TableHead>
                    <TableHead className="text-[10px] text-center">Customers</TableHead>
                    <TableHead className="text-[10px] text-center">Avg Time</TableHead>
                    <TableHead className="text-[10px] text-center">Review</TableHead>
                    <TableHead className="text-[10px] w-8" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {reps.map((rep, i) => (
                    <RepRow
                      key={rep.code}
                      rep={rep}
                      rank={i + 1}
                      onSelect={setSelectedRep}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : (
            <div className="text-center py-12">
              <Users className="w-12 h-12 text-muted-foreground/30 mx-auto mb-4" />
              <h3 className="text-base font-semibold mb-1">No rep assignments yet</h3>
              <p className="text-sm text-muted-foreground max-w-md mx-auto">
                Salesperson assignments are made automatically when Sales Orders are created in BC.
                Once documents start flowing through the pipeline, rep metrics will appear here.
              </p>
            </div>
          )}

          {/* Unassigned bucket */}
          {unassigned && unassigned.total_documents > 0 && (
            <div className="mt-4 p-3 rounded-lg bg-amber-500/5 border border-amber-500/20">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <AlertTriangle className="w-4 h-4 text-amber-400" />
                  <span className="text-sm font-medium">Unassigned Documents</span>
                </div>
                <div className="flex items-center gap-4 text-sm">
                  <span className="text-muted-foreground">{unassigned.total_documents} docs</span>
                  <span className="text-muted-foreground">{unassigned.unique_customers} customers</span>
                  {unassigned.pending_review > 0 && (
                    <Badge className="bg-amber-500/20 text-amber-400 text-[10px]">{unassigned.pending_review} need review</Badge>
                  )}
                </div>
              </div>
              {unassigned.top_customers?.length > 0 && (
                <p className="text-xs text-muted-foreground mt-2">
                  Top customers: {unassigned.top_customers.slice(0, 5).join(', ')}
                </p>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
