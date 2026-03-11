import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDashboardStats, retryWorkflow, getWorkflowIntelligence, getStableVendorMetrics } from '../lib/api';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { toast } from 'sonner';
import {
  FileText, AlertCircle, CheckCircle2, RefreshCw, ArrowRight, UploadCloud, Files,
  TrendingUp, Target, Zap, Clock, Users, Truck, Database, FolderArchive, 
  BarChart3, PieChart, Activity, Layers, Network, Building2, GitBranch,
  UserX, Link2Off, ClipboardCheck, Bell, ShieldCheck
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line, PieChart as RechartsPieChart, Pie, Legend } from 'recharts';
import { Square9StageSummary } from '../components/Square9WorkflowTracker';

const STATUS_COLORS = {
  Received: 'status-received',
  Classified: 'status-classified',
  LinkedToBC: 'status-linked',
  Exception: 'status-exception',
  Completed: 'status-completed',
};

const CHART_COLORS = ['#3b82f6', '#22c55e', '#a855f7', '#f59e0b', '#ef4444', '#06b6d4', '#ec4899', '#84cc16'];
const SOURCE_COLORS = {
  document_history: '#22c55e',
  spiro_crm: '#3b82f6',
  business_central: '#a855f7',
  sharepoint_patterns: '#f59e0b',
  unknown: '#6b7280'
};

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function formatPercent(value) {
  return value !== undefined ? `${value.toFixed(1)}%` : '0%';
}

// Action Required Card - Shows the 3 actionable queues
function ActionRequiredCard({ data, onNavigate }) {
  if (!data) return null;
  
  const queues = [
    {
      key: 'needs_vendor_review',
      label: 'Needs Vendor Review',
      description: 'AP invoices with no vendor match',
      count: data.needs_vendor_review || 0,
      icon: UserX,
      color: 'text-red-500',
      bgColor: 'bg-red-500/10',
      filter: 'vendor_pending'
    },
    {
      key: 'needs_po_match',
      label: 'Needs PO Match',
      description: 'Shipping docs missing PO link',
      count: data.needs_po_match || 0,
      icon: Link2Off,
      color: 'text-amber-500',
      bgColor: 'bg-amber-500/10',
      filter: 'po_pending'
    },
    {
      key: 'needs_approval',
      label: 'Needs Approval',
      description: 'Validated, awaiting sign-off',
      count: data.needs_approval || 0,
      icon: ClipboardCheck,
      color: 'text-blue-500',
      bgColor: 'bg-blue-500/10',
      filter: 'ready_for_approval'
    }
  ];

  const totalAction = data.total_action_needed || 0;

  return (
    <Card className="border-2 border-amber-500/50 bg-gradient-to-br from-amber-500/5 to-transparent" data-testid="action-required-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Bell className="w-5 h-5 text-amber-500" />
            <CardTitle className="text-lg font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Action Required</CardTitle>
          </div>
          {totalAction > 0 && (
            <Badge variant="destructive" className="text-sm px-3 py-1">
              {totalAction} items
            </Badge>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {queues.map((queue) => (
          <div
            key={queue.key}
            className={`${queue.bgColor} rounded-lg p-4 cursor-pointer hover:ring-2 hover:ring-offset-2 hover:ring-offset-background hover:ring-${queue.color.replace('text-', '')} transition-all`}
            onClick={() => onNavigate && onNavigate(`/queue?filter=${queue.filter}`)}
            data-testid={`action-${queue.key}`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <queue.icon className={`w-5 h-5 ${queue.color}`} />
                <div>
                  <div className="font-semibold text-sm">{queue.label}</div>
                  <div className="text-xs text-muted-foreground">{queue.description}</div>
                </div>
              </div>
              <div className={`text-2xl font-black ${queue.color}`} style={{ fontFamily: 'Chivo, sans-serif' }}>
                {queue.count}
              </div>
            </div>
          </div>
        ))}
        
        {totalAction === 0 && (
          <div className="text-center py-4 text-muted-foreground">
            <CheckCircle2 className="w-8 h-8 mx-auto mb-2 text-green-500" />
            <p className="text-sm font-medium">All caught up!</p>
            <p className="text-xs">No documents need attention</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Vendor Intelligence Card Component
function VendorIntelligenceCard({ data }) {
  if (!data) return null;
  
  const sourceData = Object.entries(data.matches_by_source || {}).map(([name, info]) => ({
    name: name.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()),
    value: info.count,
    avgScore: info.avg_score
  }));

  const matchMethodData = Object.entries(data.match_methods || {}).map(([method, info]) => ({
    name: method === 'none' ? 'No Match' : method.replace('_', ' ').replace(/\b\w/g, c => c.toUpperCase()),
    value: info.count,
    avgScore: info.avg_score
  }));

  return (
    <Card className="border border-border" data-testid="vendor-intelligence-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Users className="w-4 h-4 text-blue-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Vendor Intelligence</CardTitle>
        </div>
        <CardDescription>Vendor matching across all data sources</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Key Metrics */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-muted/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-green-500">{formatPercent(data.vendor_extraction_rate)}</div>
            <div className="text-xs text-muted-foreground">Vendor Match Rate</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-blue-500">{data.total_with_vendor || 0}</div>
            <div className="text-xs text-muted-foreground">Vendors Extracted</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-purple-500">{data.cached_vendor_matches || 0}</div>
            <div className="text-xs text-muted-foreground">Cached Matches</div>
          </div>
          <div className="bg-muted/50 rounded-lg p-3">
            <div className="text-2xl font-bold text-red-500">{data.needs_vendor_review || 0}</div>
            <div className="text-xs text-muted-foreground">Needs Review</div>
          </div>
        </div>

        {/* Match Sources */}
        {sourceData.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <Network className="w-3 h-3" /> Matches by Source
            </h4>
            <div className="space-y-2">
              {sourceData.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div className="w-24 text-xs truncate">{item.name}</div>
                  <div className="flex-1">
                    <Progress value={(item.value / (data.total_with_vendor || 1)) * 100} className="h-2" />
                  </div>
                  <div className="w-16 text-xs text-right font-mono">
                    {item.value} <span className="text-muted-foreground">({item.avgScore}%)</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Match Methods */}
        {matchMethodData.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <GitBranch className="w-3 h-3" /> Match Methods
            </h4>
            <div className="flex flex-wrap gap-2">
              {matchMethodData.slice(0, 6).map((item) => (
                <Badge key={item.name} variant="secondary" className="text-xs">
                  {item.name}: {item.value}
                </Badge>
              ))}
            </div>
          </div>
        )}

        {/* Freight Detection */}
        <div className="pt-2 border-t flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Truck className="w-4 h-4 text-amber-500" />
            <span>Freight Carriers Detected</span>
          </div>
          <span className="font-bold">{data.freight_carriers_detected || 0}</span>
        </div>

        {/* Spiro Integration */}
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <span>Spiro CRM Companies</span>
          <span className="font-mono">{(data.spiro_companies_available || 0).toLocaleString()}</span>
        </div>
      </CardContent>
    </Card>
  );
}

// Validation Metrics Card Component  
function ValidationMetricsCard({ data }) {
  if (!data) return null;

  const failureData = Object.entries(data.failure_reasons || {})
    .map(([reason, count]) => ({
      name: reason.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: count
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5);

  return (
    <Card className="border border-border" data-testid="validation-metrics-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="w-4 h-4 text-green-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Validation Success</CardTitle>
        </div>
        <CardDescription>Document validation and quality metrics</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Pass Rate Gauge */}
        <div className="relative">
          <div className="flex justify-between items-center mb-2">
            <span className="text-sm font-medium">Overall Pass Rate</span>
            <span className="text-2xl font-bold text-green-500">{formatPercent(data.pass_rate)}</span>
          </div>
          <Progress value={data.pass_rate || 0} className="h-3" />
          <div className="flex justify-between text-xs text-muted-foreground mt-1">
            <span>{data.passed || 0} passed</span>
            <span>{data.failed || 0} failed</span>
          </div>
        </div>

        {/* Failure Reasons */}
        {failureData.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
              <AlertCircle className="w-3 h-3 text-red-500" /> Top Failure Reasons
            </h4>
            <div className="space-y-1.5">
              {failureData.map((item, idx) => (
                <div key={item.name} className="flex items-center gap-2 text-sm">
                  <span className="w-5 text-center text-muted-foreground">{idx + 1}.</span>
                  <span className="flex-1 truncate">{item.name}</span>
                  <Badge variant="destructive" className="text-xs">{item.value}</Badge>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Total Validated */}
        <div className="pt-2 border-t text-xs text-muted-foreground">
          Based on {data.total_validated || 0} validated documents
        </div>
      </CardContent>
    </Card>
  );
}

// Processing Metrics Card Component
function ProcessingMetricsCard({ data }) {
  if (!data) return null;

  const workflowStatusData = Object.entries(data.by_workflow_status || {})
    .filter(([status]) => status !== 'unknown' && status !== 'none')
    .map(([status, count]) => ({
      name: status.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: count
    }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 8);

  return (
    <Card className="border border-border" data-testid="processing-metrics-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Activity className="w-4 h-4 text-purple-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Processing Health</CardTitle>
        </div>
        <CardDescription>Workflow throughput and efficiency</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Key Metrics Grid */}
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-green-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-green-500">{data.completed || 0}</div>
            <div className="text-xs text-muted-foreground">Completed</div>
          </div>
          <div className="bg-red-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-red-500">{data.stuck || 0}</div>
            <div className="text-xs text-muted-foreground">Stuck/Exception</div>
          </div>
          <div className="bg-blue-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-blue-500">{data.auto_cleared || 0}</div>
            <div className="text-xs text-muted-foreground">Auto-Cleared</div>
          </div>
          <div className="bg-purple-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-purple-500">{formatPercent(data.success_rate)}</div>
            <div className="text-xs text-muted-foreground">Success Rate</div>
          </div>
        </div>

        {/* Retry Stats */}
        {data.retry_stats && data.retry_stats.docs_requiring_retry > 0 && (
          <div className="bg-amber-500/10 rounded-lg p-3">
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-medium">Retry Activity</span>
              <RefreshCw className="w-4 h-4 text-amber-500" />
            </div>
            <div className="grid grid-cols-3 gap-2 text-xs">
              <div>
                <div className="font-bold">{data.retry_stats.docs_requiring_retry}</div>
                <div className="text-muted-foreground">Docs Retried</div>
              </div>
              <div>
                <div className="font-bold">{data.retry_stats.avg_retries.toFixed(1)}</div>
                <div className="text-muted-foreground">Avg Retries</div>
              </div>
              <div>
                <div className="font-bold">{data.retry_stats.total_retries}</div>
                <div className="text-muted-foreground">Total Retries</div>
              </div>
            </div>
          </div>
        )}

        {/* Workflow Status Distribution */}
        {workflowStatusData.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2">Workflow Status Distribution</h4>
            <ResponsiveContainer width="100%" height={120}>
              <BarChart data={workflowStatusData} layout="vertical" barCategoryGap="15%">
                <XAxis type="number" hide />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={100} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '0.5rem', fontSize: '11px' }} />
                <Bar dataKey="value" fill="#a855f7" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// BC Integration Card Component
function BCIntegrationCard({ data }) {
  if (!data) return null;

  return (
    <Card className="border border-border" data-testid="bc-integration-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Building2 className="w-4 h-4 text-indigo-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Business Central</CardTitle>
        </div>
        <CardDescription>ERP integration success metrics</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <div className="text-center">
            <div className="text-2xl font-bold text-indigo-500">{data.linked_to_bc || 0}</div>
            <div className="text-xs text-muted-foreground">Linked</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-green-500">{data.posted_to_bc || 0}</div>
            <div className="text-xs text-muted-foreground">Posted</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-red-500">{data.post_failures || 0}</div>
            <div className="text-xs text-muted-foreground">Failed</div>
          </div>
        </div>
        <div>
          <div className="flex justify-between text-sm mb-1">
            <span>BC Link Rate</span>
            <span className="font-bold">{formatPercent(data.link_rate)}</span>
          </div>
          <Progress value={data.link_rate || 0} className="h-2" />
        </div>
      </CardContent>
    </Card>
  );
}

// SharePoint Card Component
function SharePointCard({ data }) {
  if (!data) return null;

  const topFolders = Object.entries(data.top_folders || {})
    .map(([folder, count]) => ({
      name: folder.split('/').pop() || folder,
      fullPath: folder,
      value: count
    }))
    .slice(0, 5);

  return (
    <Card className="border border-border" data-testid="sharepoint-card">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <FolderArchive className="w-4 h-4 text-cyan-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>SharePoint Archive</CardTitle>
        </div>
        <CardDescription>Document archival metrics</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="bg-cyan-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-cyan-500">{data.documents_archived || 0}</div>
            <div className="text-xs text-muted-foreground">Archived</div>
          </div>
          <div className="bg-cyan-500/10 rounded-lg p-3 text-center">
            <div className="text-2xl font-bold text-cyan-500">{formatPercent(data.archive_rate)}</div>
            <div className="text-xs text-muted-foreground">Archive Rate</div>
          </div>
        </div>
        
        {topFolders.length > 0 && (
          <div>
            <h4 className="text-sm font-semibold mb-2">Top Folders</h4>
            <div className="space-y-1.5">
              {topFolders.map((item, idx) => (
                <div key={item.fullPath} className="flex items-center gap-2 text-xs">
                  <span className="w-4 text-center text-muted-foreground">{idx + 1}.</span>
                  <span className="flex-1 truncate" title={item.fullPath}>{item.name}</span>
                  <span className="font-mono">{item.value}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Daily Trends Chart Component
function DailyTrendsChart({ data }) {
  if (!data || data.length === 0) return null;

  return (
    <Card className="border border-border" data-testid="daily-trends-chart">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <TrendingUp className="w-4 h-4 text-green-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Processing Trends (7 Days)</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={data}>
            <XAxis 
              dataKey="date" 
              tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} 
              axisLine={false} 
              tickLine={false}
              tickFormatter={(val) => val?.slice(5) || ''} 
            />
            <YAxis 
              tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} 
              axisLine={false} 
              tickLine={false}
              allowDecimals={false}
            />
            <Tooltip
              contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '0.5rem', fontSize: '11px' }}
            />
            <Legend verticalAlign="top" height={36} iconSize={10} />
            <Line type="monotone" dataKey="total" name="Total" stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
            <Line type="monotone" dataKey="validated" name="Validated" stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} />
            <Line type="monotone" dataKey="exceptions" name="Exceptions" stroke="#ef4444" strokeWidth={2} dot={{ r: 3 }} />
          </LineChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

// Ingestion Sources Chart Component
function IngestionSourcesChart({ data }) {
  if (!data || Object.keys(data).length === 0) return null;

  const chartData = Object.entries(data)
    .map(([source, count]) => ({
      name: source.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
      value: count
    }))
    .sort((a, b) => b.value - a.value);

  return (
    <Card className="border border-border" data-testid="ingestion-sources-chart">
      <CardHeader className="pb-2">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-amber-500" />
          <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Ingestion Sources</CardTitle>
        </div>
      </CardHeader>
      <CardContent>
        <ResponsiveContainer width="100%" height={180}>
          <RechartsPieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              innerRadius={40}
              outerRadius={70}
              paddingAngle={2}
              dataKey="value"
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              labelLine={false}
            >
              {chartData.map((entry, index) => (
                <Cell key={entry.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '0.5rem', fontSize: '11px' }} />
          </RechartsPieChart>
        </ResponsiveContainer>
      </CardContent>
    </Card>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [intelligence, setIntelligence] = useState(null);
  const [stableVendorMetrics, setStableVendorMetrics] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchStats = async () => {
    setLoading(true);
    try {
      const [statsRes, intelligenceRes, svRes] = await Promise.all([
        getDashboardStats(),
        getWorkflowIntelligence().catch(() => ({ data: null })),
        getStableVendorMetrics().catch(() => ({ data: null })),
      ]);
      setStats(statsRes.data);
      setIntelligence(intelligenceRes.data);
      setStableVendorMetrics(svRes.data);
    } catch (err) {
      toast.error('Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchStats(); }, []);

  const handleRetry = async (wfId) => {
    try {
      await retryWorkflow(wfId);
      toast.success('Workflow retry initiated');
      fetchStats();
    } catch (err) {
      toast.error('Retry failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="dashboard-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  const chartData = stats?.by_status
    ? Object.entries(stats.by_status).map(([name, value]) => ({ name, value }))
    : [];

  // Top-level metrics
  const metricCards = [
    { label: 'Total Documents', value: intelligence?.total_documents || stats?.total_documents || 0, icon: FileText, color: 'text-blue-500' },
    { label: 'Validation Rate', value: formatPercent(intelligence?.validation_metrics?.pass_rate || 0), icon: CheckCircle2, color: 'text-green-500' },
    { label: 'Vendor Match Rate', value: formatPercent(intelligence?.vendor_intelligence?.vendor_extraction_rate || 0), icon: Users, color: 'text-purple-500' },
    { label: 'Exceptions', value: intelligence?.processing_metrics?.stuck || stats?.by_status?.Exception || 0, icon: AlertCircle, color: 'text-red-500' },
  ];

  return (
    <div className="space-y-6 max-w-[1800px] mx-auto" data-testid="dashboard-page">
      {/* Demo mode banner */}
      {stats?.demo_mode && (
        <div className="bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 flex items-center gap-3" data-testid="demo-mode-banner">
          <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-200">
            <span className="font-semibold">Demo Mode Active</span> - Microsoft APIs are simulated. Configure Entra ID credentials in Settings to connect live.
          </p>
        </div>
      )}

      {/* Header with refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Workflow Intelligence Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Real-time insights into document processing automation
            {intelligence?.generated_at && (
              <span className="ml-2 text-xs">• Updated {formatDate(intelligence.generated_at)}</span>
            )}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchStats} data-testid="refresh-dashboard-btn">
          <RefreshCw className="w-4 h-4 mr-2" /> Refresh
        </Button>
      </div>

      {/* Top-level Metric Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="stats-grid">
        {metricCards.map(({ label, value, icon: Icon, color }, i) => (
          <Card key={label} className={`border border-border hover:border-primary/30 transition-colors`}>
            <CardContent className="p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
                <Icon className={`w-4 h-4 ${color}`} />
              </div>
              <p className="text-3xl font-black tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }} data-testid={`stat-${label.toLowerCase().replace(/\s+/g, '-')}`}>
                {value}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Action Required - Prominent placement */}
      {intelligence?.action_required && (intelligence.action_required.total_action_needed > 0) && (
        <ActionRequiredCard data={intelligence.action_required} onNavigate={navigate} />
      )}

      {/* Stable Vendor Auto-Ready KPIs */}
      {stableVendorMetrics && stableVendorMetrics.feature_enabled && (
        <Card className="border border-border" data-testid="stable-vendor-kpi-card">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-emerald-500" />
              <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Stable Vendor Auto-Ready</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground hover:text-foreground cursor-pointer underline underline-offset-2"
                onClick={() => navigate('/stable-vendors')} data-testid="sv-view-all-link">View All</span>
            </div>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div className="text-center" data-testid="sv-stable-count">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Stable Vendors</p>
                <p className="text-2xl font-black" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {stableVendorMetrics.stable_vendors_count}
                  <span className="text-xs font-normal text-muted-foreground ml-1">/ {stableVendorMetrics.total_vendors}</span>
                </p>
              </div>
              <div className="text-center" data-testid="sv-auto-ready-today">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Auto Ready Today</p>
                <p className="text-2xl font-black text-emerald-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {stableVendorMetrics.auto_ready_today}
                </p>
              </div>
              <div className="text-center" data-testid="sv-low-priority-today">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Low Priority Today</p>
                <p className="text-2xl font-black text-sky-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {stableVendorMetrics.low_priority_today}
                </p>
              </div>
              <div className="text-center" data-testid="sv-total-processed">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Processed Today</p>
                <p className="text-2xl font-black" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {stableVendorMetrics.total_processed_today}
                </p>
              </div>
              <div className="text-center" data-testid="sv-automation-rate">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Auto-Ready Rate</p>
                <p className="text-2xl font-black text-emerald-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {(stableVendorMetrics.stable_vendor_automation_rate * 100).toFixed(0)}%
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Main Intelligence Grid */}
      <Tabs defaultValue="overview" className="w-full">
        <TabsList className="mb-4">
          <TabsTrigger value="overview" data-testid="tab-overview">
            <BarChart3 className="w-4 h-4 mr-2" /> Overview
          </TabsTrigger>
          <TabsTrigger value="vendor" data-testid="tab-vendor">
            <Users className="w-4 h-4 mr-2" /> Vendor Intelligence
          </TabsTrigger>
          <TabsTrigger value="workflows" data-testid="tab-workflows">
            <Activity className="w-4 h-4 mr-2" /> Workflows
          </TabsTrigger>
        </TabsList>

        {/* Overview Tab */}
        <TabsContent value="overview" className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
            {/* Status Chart */}
            <Card className="md:col-span-5 border border-border" data-testid="status-chart-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Documents by Status</CardTitle>
              </CardHeader>
              <CardContent>
                {chartData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={chartData} barCategoryGap="25%">
                      <XAxis dataKey="name" tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                      <YAxis tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} allowDecimals={false} />
                      <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '0.5rem', fontSize: '11px' }} />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        {chartData.map((entry, idx) => (
                          <Cell key={entry.name} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="flex flex-col items-center justify-center h-52 text-muted-foreground">
                    <FileText className="w-10 h-10 mb-3 opacity-40" />
                    <p className="text-sm">No documents yet</p>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Daily Trends */}
            <div className="md:col-span-7">
              <DailyTrendsChart data={intelligence?.daily_trends} />
            </div>
          </div>

          {/* Second Row - Key Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <ValidationMetricsCard data={intelligence?.validation_metrics} />
            <BCIntegrationCard data={intelligence?.bc_integration} />
            <SharePointCard data={intelligence?.sharepoint_archival} />
          </div>

          {/* Quick Actions + Type Distribution */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            <Card className="border border-border" data-testid="quick-actions-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Quick Actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <Button className="w-full justify-start gap-2" onClick={() => navigate('/upload')} data-testid="quick-upload-btn">
                  <UploadCloud className="w-4 h-4" /> Upload Document
                </Button>
                <Button variant="secondary" className="w-full justify-start gap-2" onClick={() => navigate('/queue')} data-testid="quick-queue-btn">
                  <Files className="w-4 h-4" /> View Queue
                </Button>
                <Button variant="secondary" className="w-full justify-start gap-2" onClick={fetchStats} data-testid="quick-refresh-btn">
                  <RefreshCw className="w-4 h-4" /> Refresh Stats
                </Button>
              </CardContent>
            </Card>

            <IngestionSourcesChart data={intelligence?.ingestion_sources} />

            {/* Type distribution */}
            {stats?.by_type && Object.keys(stats.by_type).length > 0 && (
              <Card className="border border-border" data-testid="type-distribution-card">
                <CardHeader className="pb-2">
                  <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>By Document Type</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  {Object.entries(stats.by_type).map(([type, count]) => (
                    <div key={type} className="flex items-center justify-between text-sm">
                      <span className="text-muted-foreground">{type}</span>
                      <span className="font-mono font-semibold">{count}</span>
                    </div>
                  ))}
                </CardContent>
              </Card>
            )}
          </div>
        </TabsContent>

        {/* Vendor Intelligence Tab */}
        <TabsContent value="vendor" className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <VendorIntelligenceCard data={intelligence?.vendor_intelligence} />
            <ProcessingMetricsCard data={intelligence?.processing_metrics} />
          </div>
          
          {/* Square9 Stages */}
          <Square9StageSummary />
        </TabsContent>

        {/* Workflows Tab */}
        <TabsContent value="workflows" className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <ProcessingMetricsCard data={intelligence?.processing_metrics} />
            <ValidationMetricsCard data={intelligence?.validation_metrics} />
          </div>

          {/* Recent Workflows */}
          <Card className="border border-border" data-testid="recent-workflows-card">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Recent Workflow Runs</CardTitle>
                <Button variant="ghost" size="sm" className="text-xs" onClick={fetchStats} data-testid="refresh-workflows-btn">
                  <RefreshCw className="w-3 h-3 mr-1" /> Refresh
                </Button>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {stats?.recent_workflows?.length > 0 ? (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs uppercase tracking-wider">Workflow</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider">Status</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider">Started</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider">Steps</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stats.recent_workflows.map((wf) => (
                      <TableRow key={wf.id} className="cursor-pointer" onClick={() => wf.document_id && navigate(`/documents/${wf.document_id}`)}>
                        <TableCell className="font-mono text-xs">{wf.workflow_name}</TableCell>
                        <TableCell>
                          <Badge variant={wf.status === 'Completed' ? 'secondary' : wf.status === 'Failed' ? 'destructive' : 'default'}>
                            {wf.status}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-xs text-muted-foreground font-mono">{formatDate(wf.started_utc)}</TableCell>
                        <TableCell className="text-xs">{wf.steps?.length || 0} steps</TableCell>
                        <TableCell className="text-right">
                          {wf.status === 'Failed' && (
                            <Button
                              variant="ghost" size="sm" className="text-xs h-7"
                              onClick={(e) => { e.stopPropagation(); handleRetry(wf.id); }}
                              data-testid={`retry-workflow-${wf.id}`}
                            >
                              <RefreshCw className="w-3 h-3 mr-1" /> Retry
                            </Button>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <div className="py-12 text-center text-sm text-muted-foreground">
                  No workflow runs yet. Upload a document to get started.
                </div>
              )}
            </CardContent>
          </Card>

          {/* Failed Workflows */}
          {stats?.failed_workflows?.length > 0 && (
            <Card className="border border-destructive/30" data-testid="failed-workflows-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold text-destructive" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  <AlertCircle className="w-4 h-4 inline mr-2" />
                  Failed Workflows
                </CardTitle>
              </CardHeader>
              <CardContent className="p-0">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead className="text-xs uppercase tracking-wider">ID</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider">Error</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider">Time</TableHead>
                      <TableHead className="text-xs uppercase tracking-wider text-right">Action</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {stats.failed_workflows.map((wf) => (
                      <TableRow key={wf.id}>
                        <TableCell className="font-mono text-xs">{wf.id.slice(0, 8)}...</TableCell>
                        <TableCell className="text-xs text-destructive max-w-[300px] truncate">{wf.error || 'Unknown error'}</TableCell>
                        <TableCell className="text-xs font-mono text-muted-foreground">{formatDate(wf.started_utc)}</TableCell>
                        <TableCell className="text-right">
                          <Button variant="ghost" size="sm" className="text-xs h-7" onClick={() => handleRetry(wf.id)} data-testid={`retry-failed-${wf.id}`}>
                            <RefreshCw className="w-3 h-3 mr-1" /> Retry
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
