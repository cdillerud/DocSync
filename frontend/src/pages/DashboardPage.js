import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDashboardStats, retryWorkflow, getWorkflowIntelligence, getStableVendorMetrics, getDailyIngestion, bulkApproveAndFile } from '../lib/api';
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
  UserX, Link2Off, ClipboardCheck, Bell, ShieldCheck, Route,
  Gauge, ShieldAlert, Eye, Ban, HelpCircle, Calendar, Inbox, Mail, Archive, Loader2
} from 'lucide-react';
import AutomationMetricsCard from '../components/AutomationMetricsCard';
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
  const [processing, setProcessing] = useState(false);
  const [result, setResult] = useState(null);
  
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
      filter: 'vendor_pending',
      bulkCategory: 'needs_vendor_review',
    },
    {
      key: 'needs_po_match',
      label: 'Needs PO Match',
      description: 'Shipping docs missing PO link',
      count: data.needs_po_match || 0,
      icon: Link2Off,
      color: 'text-amber-500',
      bgColor: 'bg-amber-500/10',
      filter: 'po_pending',
      bulkCategory: null,
    },
    {
      key: 'needs_approval',
      label: 'Needs Approval',
      description: 'Validated, awaiting sign-off',
      count: data.needs_approval || 0,
      icon: ClipboardCheck,
      color: 'text-blue-500',
      bgColor: 'bg-blue-500/10',
      filter: 'ready_for_approval',
      bulkCategory: 'needs_approval',
    }
  ];

  const totalAction = data.total_action_needed || 0;

  const handleBulkApprove = async (category, count) => {
    if (!window.confirm(`Approve & file ${count} documents? They'll be routed to SharePoint and cleared.`)) return;
    setProcessing(true);
    setResult(null);
    try {
      const res = await bulkApproveAndFile(category, 500);
      const d = res.data || res;
      setResult(d);
      toast.success(d.message || `Filed ${d.filed} documents`);
      // Refresh the page after a short delay
      setTimeout(() => window.location.reload(), 1500);
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Bulk approve failed');
    }
    setProcessing(false);
  };

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
            onClick={() => onNavigate && onNavigate(`/documents?filter=${queue.filter}`)}
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
              <div className="flex items-center gap-3">
                {queue.bulkCategory && queue.count > 0 && (
                  <Button
                    size="sm"
                    variant="outline"
                    className="h-7 text-xs"
                    disabled={processing}
                    onClick={(e) => { e.stopPropagation(); handleBulkApprove(queue.bulkCategory, queue.count); }}
                    data-testid={`bulk-approve-${queue.key}`}
                  >
                    {processing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Archive className="w-3 h-3 mr-1" />}
                    Approve & File All
                  </Button>
                )}
                <div className={`text-2xl font-black ${queue.color}`} style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {queue.count}
                </div>
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
        {/* Accurate Vendor KPIs */}
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-emerald-500/10 rounded-lg p-2.5 text-center" data-testid="vendor-auto-resolve-rate">
            <div className="text-2xl font-black text-emerald-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {formatPercent(data.vendor_auto_resolve_rate)}
            </div>
            <div className="text-[10px] text-muted-foreground">Auto-Resolve Rate</div>
            <div className="text-[9px] text-muted-foreground">{data.vendor_auto_resolved_total || 0} / {data.vendor_applicable_total || 0}</div>
          </div>
          <div className="bg-blue-500/10 rounded-lg p-2.5 text-center" data-testid="vendor-final-resolve-rate">
            <div className="text-2xl font-black text-blue-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {formatPercent(data.vendor_final_resolved_rate)}
            </div>
            <div className="text-[10px] text-muted-foreground">Final Resolved Rate</div>
            <div className="text-[9px] text-muted-foreground">{data.vendor_final_resolved_total || 0} / {data.vendor_applicable_total || 0}</div>
          </div>
          <div className="bg-amber-500/10 rounded-lg p-2.5 text-center" data-testid="vendor-needs-review">
            <div className="text-2xl font-black text-amber-500" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {data.vendor_needs_review_total || 0}
            </div>
            <div className="text-[10px] text-muted-foreground">Needs Review</div>
          </div>
        </div>

        {/* Method breakdown */}
        {data.vendor_by_method && Object.keys(data.vendor_by_method).length > 0 && (
          <div>
            <h4 className="text-xs font-semibold mb-1.5">Resolution by Method</h4>
            <div className="space-y-1">
              {Object.entries(data.vendor_by_method).sort((a,b) => b[1]-a[1]).slice(0, 6).map(([method, count]) => {
                const total = data.vendor_applicable_total || 1;
                const pct = ((count / total) * 100).toFixed(0);
                const isAutoMethod = ['bc_exact_match','alias_match','fuzzy_match','bc_search','exact_name'].includes(method);
                const isCandidate = method === 'fuzzy_candidate';
                return (
                  <div key={method} className="flex items-center gap-2 text-xs" data-testid={`vendor-method-${method}`}>
                    <span className="w-[100px] truncate text-muted-foreground">{method.replace(/_/g, ' ')}</span>
                    <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${isAutoMethod ? 'bg-emerald-500' : isCandidate ? 'bg-amber-500' : 'bg-muted-foreground'}`}
                        style={{ width: `${Math.max(2, parseFloat(pct))}%` }} />
                    </div>
                    <span className="w-[50px] text-right">{count} ({pct}%)</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
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

        {/* Freight Detection */}
        <div className="pt-2 border-t flex items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <Truck className="w-4 h-4 text-amber-500" />
            <span>Freight Carriers Detected</span>
          </div>
          <span className="font-bold">{data.freight_carriers_detected || 0}</span>
        </div>

        {/* Alias Learning Metrics */}
        {data.alias_metrics && data.alias_metrics.total_aliases > 0 && (
          <div className="pt-2 border-t space-y-2" data-testid="alias-metrics-section">
            <h4 className="text-sm font-semibold flex items-center gap-2">
              <Link2Off className="w-3 h-3 text-cyan-500" /> Alias Learning
            </h4>
            <div className="grid grid-cols-3 gap-2">
              <div className="bg-cyan-500/10 rounded-lg p-2 text-center">
                <div className="text-lg font-bold text-cyan-500">{data.alias_metrics.total_aliases}</div>
                <div className="text-[10px] text-muted-foreground">Total Aliases</div>
              </div>
              <div className="bg-emerald-500/10 rounded-lg p-2 text-center">
                <div className="text-lg font-bold text-emerald-500">{data.alias_metrics.auto_learned || 0}</div>
                <div className="text-[10px] text-muted-foreground">Auto-Learned</div>
              </div>
              <div className="bg-purple-500/10 rounded-lg p-2 text-center">
                <div className="text-lg font-bold text-purple-500">{data.alias_metrics.alias_matched_docs || 0}</div>
                <div className="text-[10px] text-muted-foreground">Alias Matches</div>
              </div>
            </div>
            {data.alias_metrics.top_aliases && data.alias_metrics.top_aliases.length > 0 && (
              <div className="space-y-1">
                <div className="text-xs text-muted-foreground">Top Learned Aliases</div>
                {data.alias_metrics.top_aliases.slice(0, 3).map((a, i) => (
                  <div key={i} className="flex items-center justify-between text-xs">
                    <span className="truncate max-w-[60%] text-muted-foreground">{a.normalized_alias || a.alias}</span>
                    <span className="font-mono text-cyan-500">{a.usage_count}x → {a.vendor_name}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

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

const API_OPS = process.env.REACT_APP_BACKEND_URL;

function OperationsQueueSummaryCard() {
  const [data, setData] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API_OPS}/api/inventory-ledger/operations-queue?limit=5`);
        if (res.ok) setData(await res.json());
      } catch { /* silent */ }
    })();
  }, []);

  if (!data || data.total === 0) return null;

  return (
    <Card className="border border-border" data-testid="ops-queue-dashboard-card">
      <CardContent className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-blue-500" />
            <span className="text-sm font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Operations Queue</span>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <span className="text-xs text-muted-foreground">Total</span>
              <p className="text-xl font-bold font-mono" data-testid="ops-dash-total">{data.total}</p>
            </div>
            <div className="text-right">
              <span className="text-xs text-red-500">High Priority</span>
              <p className="text-xl font-bold font-mono text-red-600" data-testid="ops-dash-high">{data.high_priority_count}</p>
            </div>
            {(data.due_soon_count > 0 || data.overdue_count > 0 || data.escalated_count > 0) && (
              <>
                {data.due_soon_count > 0 && (
                  <div className="text-right">
                    <span className="text-xs text-amber-500">Due Soon</span>
                    <p className="text-xl font-bold font-mono text-amber-600" data-testid="ops-dash-due-soon">{data.due_soon_count}</p>
                  </div>
                )}
                {data.overdue_count > 0 && (
                  <div className="text-right">
                    <span className="text-xs text-red-600">Overdue</span>
                    <p className="text-xl font-bold font-mono text-red-600" data-testid="ops-dash-overdue">{data.overdue_count}</p>
                  </div>
                )}
                {data.escalated_count > 0 && (
                  <div className="text-right">
                    <span className="text-xs text-red-700">Escalated</span>
                    <p className="text-xl font-bold font-mono text-red-700" data-testid="ops-dash-escalated">{data.escalated_count}</p>
                  </div>
                )}
              </>
            )}
            <Button variant="outline" size="sm" className="text-xs h-7" onClick={() => navigate('/operations-queue')} data-testid="ops-dash-view-all">
              View All <ArrowRight className="w-3 h-3 ml-1" />
            </Button>
          </div>
        </div>
        {data.items.length > 0 && (
          <div className="space-y-1.5">
            {data.items.slice(0, 3).map((item, i) => (
              <div key={`${item.entity_type}-${item.entity_id}`} className="flex items-center gap-2 text-xs p-1.5 rounded bg-muted/20" data-testid={`ops-dash-item-${i}`}>
                <Badge variant={item.priority_score >= 40 ? 'destructive' : item.priority_score >= 20 ? 'secondary' : 'outline'} className="text-[9px] font-mono w-8 justify-center">{item.priority_score}</Badge>
                <span className="font-mono font-bold truncate w-[140px]">{item.entity_id}</span>
                <Badge variant="outline" className="text-[8px]">{item.entity_type === 'sales_order' ? 'SO' : 'PO'}</Badge>
                <span className="text-muted-foreground truncate flex-1">{item.next_action}</span>
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Document Routing Summary Card (Auto-Clear Gate)
function RoutingSummaryCard({ statsRouting, intelligenceRouting }) {
  // Merge data: prefer intelligence routing (more detailed), fall back to stats
  const routing = intelligenceRouting || {};
  const counts = routing.counts || statsRouting || {};

  const autoProcess = counts.auto_process || { count: 0, avg_score: 0 };
  const review = counts.review || { count: 0, avg_score: 0 };
  const blocked = counts.blocked || { count: 0, avg_score: 0 };
  const unrouted = counts.unrouted || { count: 0, avg_score: 0 };

  // Normalize: counts may be plain numbers (from stats) or objects (from intelligence)
  const ap = typeof autoProcess === 'number' ? { count: autoProcess, avg_score: 0 } : autoProcess;
  const rv = typeof review === 'number' ? { count: review, avg_score: 0 } : review;
  const bl = typeof blocked === 'number' ? { count: blocked, avg_score: 0 } : blocked;
  const un = typeof unrouted === 'number' ? { count: unrouted, avg_score: 0 } : unrouted;

  const totalRouted = ap.count + rv.count + bl.count;
  if (totalRouted === 0 && un.count === 0) return null;

  const segments = [
    { key: 'auto_process', label: 'Auto Process', count: ap.count, avgScore: ap.avg_score, color: 'text-emerald-500', bg: 'bg-emerald-500/10', barColor: 'bg-emerald-500' },
    { key: 'review', label: 'Needs Review', count: rv.count, avgScore: rv.avg_score, color: 'text-amber-500', bg: 'bg-amber-500/10', barColor: 'bg-amber-500' },
    { key: 'blocked', label: 'Blocked', count: bl.count, avgScore: bl.avg_score, color: 'text-red-500', bg: 'bg-red-500/10', barColor: 'bg-red-500' },
  ];

  return (
    <Card className="border-2 border-emerald-500/30 bg-gradient-to-br from-emerald-500/5 to-transparent" data-testid="routing-summary-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Route className="w-5 h-5 text-emerald-500" />
            <CardTitle className="text-lg font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Routing</CardTitle>
          </div>
          {totalRouted > 0 && (
            <Badge variant="secondary" className="text-sm px-3 py-1" data-testid="routing-total-badge">
              {totalRouted} routed
            </Badge>
          )}
        </div>
        <CardDescription>Auto-Clear Gate classification</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Counts grid */}
        <div className="grid grid-cols-3 gap-3">
          {segments.map((seg) => (
            <div key={seg.key} className={`${seg.bg} rounded-lg p-3 text-center`} data-testid={`routing-${seg.key}`}>
              <div className={`text-2xl font-black ${seg.color}`} style={{ fontFamily: 'Chivo, sans-serif' }}>
                {seg.count}
              </div>
              <div className="text-xs text-muted-foreground">{seg.label}</div>
              {seg.avgScore > 0 && (
                <div className="text-[10px] text-muted-foreground mt-1">avg {seg.avgScore}</div>
              )}
            </div>
          ))}
        </div>

        {/* Progress bar */}
        {totalRouted > 0 && (
          <div>
            <div className="flex items-center gap-1 h-3 rounded-full overflow-hidden bg-muted/30">
              {segments.map((seg) => {
                const pct = (seg.count / totalRouted) * 100;
                if (pct === 0) return null;
                return (
                  <div
                    key={seg.key}
                    className={`${seg.barColor} h-full transition-all`}
                    style={{ width: `${pct}%` }}
                    title={`${seg.label}: ${seg.count} (${pct.toFixed(0)}%)`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              {segments.filter(s => s.count > 0).map((seg) => (
                <span key={seg.key} className={seg.color}>
                  {seg.label} {((seg.count / totalRouted) * 100).toFixed(0)}%
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Unrouted notice */}
        {un.count > 0 && (
          <div className="text-xs text-muted-foreground pt-1 border-t">
            {un.count} document{un.count !== 1 ? 's' : ''} not yet routed
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Document Readiness Summary Card
function ReadinessSummaryCard({ data }) {
  if (!data) return null;

  const byStatus = data.by_status || {};
  const confidence = data.confidence_by_status || {};
  const total = Object.values(byStatus).reduce((a, b) => a + b, 0);
  if (total === 0 && (data.no_readiness_data || 0) === 0) return null;

  const statuses = [
    { key: 'ready_auto_draft', label: 'Auto Draft', icon: Zap, color: 'text-emerald-500', bg: 'bg-emerald-500/10', barColor: 'bg-emerald-500' },
    { key: 'ready_auto_link', label: 'Auto Link', icon: Link2Off, color: 'text-blue-500', bg: 'bg-blue-500/10', barColor: 'bg-blue-500' },
    { key: 'needs_review', label: 'Needs Review', icon: Eye, color: 'text-amber-500', bg: 'bg-amber-500/10', barColor: 'bg-amber-500' },
    { key: 'blocked', label: 'Blocked', icon: Ban, color: 'text-red-500', bg: 'bg-red-500/10', barColor: 'bg-red-500' },
    { key: 'ambiguous', label: 'Ambiguous', icon: HelpCircle, color: 'text-purple-500', bg: 'bg-purple-500/10', barColor: 'bg-purple-500' },
  ];

  const topBlockers = (data.top_blocking_reasons || []).slice(0, 4);
  const topWarnings = (data.top_warning_reasons || []).slice(0, 4);

  return (
    <Card className="border-2 border-sky-500/30 bg-gradient-to-br from-sky-500/5 to-transparent" data-testid="readiness-summary-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Gauge className="w-5 h-5 text-sky-500" />
            <CardTitle className="text-lg font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Readiness</CardTitle>
          </div>
          {total > 0 && (
            <Badge variant="secondary" className="text-sm px-3 py-1" data-testid="readiness-total-badge">
              {total} evaluated
            </Badge>
          )}
        </div>
        <CardDescription>Readiness engine assessment — can documents be auto-processed?</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Status counts grid */}
        <div className="grid grid-cols-5 gap-2">
          {statuses.map((s) => {
            const count = byStatus[s.key] || 0;
            const conf = confidence[s.key];
            return (
              <div key={s.key} className={`${s.bg} rounded-lg p-2.5 text-center`} data-testid={`readiness-${s.key}`}>
                <s.icon className={`w-4 h-4 mx-auto mb-1 ${s.color}`} />
                <div className={`text-xl font-black ${s.color}`} style={{ fontFamily: 'Chivo, sans-serif' }}>
                  {count}
                </div>
                <div className="text-[10px] text-muted-foreground leading-tight">{s.label}</div>
                {conf !== undefined && (
                  <div className="text-[9px] text-muted-foreground mt-0.5">{(conf * 100).toFixed(0)}% conf</div>
                )}
              </div>
            );
          })}
        </div>

        {/* Progress bar */}
        {total > 0 && (
          <div>
            <div className="flex items-center gap-0.5 h-2.5 rounded-full overflow-hidden bg-muted/30">
              {statuses.map((s) => {
                const count = byStatus[s.key] || 0;
                const pct = (count / total) * 100;
                if (pct === 0) return null;
                return (
                  <div
                    key={s.key}
                    className={`${s.barColor} h-full transition-all`}
                    style={{ width: `${pct}%` }}
                    title={`${s.label}: ${count} (${pct.toFixed(0)}%)`}
                  />
                );
              })}
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              {statuses.filter(s => (byStatus[s.key] || 0) > 0).map((s) => (
                <span key={s.key} className={s.color}>
                  {s.label} {(((byStatus[s.key] || 0) / total) * 100).toFixed(0)}%
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Top blockers & warnings */}
        <div className="grid grid-cols-2 gap-3">
          {topBlockers.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1.5 flex items-center gap-1">
                <ShieldAlert className="w-3 h-3 text-red-500" /> Top Blockers
              </h4>
              <div className="space-y-1">
                {topBlockers.map((b) => (
                  <div key={b.reason} className="flex items-center justify-between text-xs">
                    <span className="truncate text-muted-foreground">{b.reason.replace(/_/g, ' ')}</span>
                    <Badge variant="destructive" className="text-[10px] h-4 px-1.5">{b.count}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
          {topWarnings.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1.5 flex items-center gap-1">
                <AlertCircle className="w-3 h-3 text-amber-500" /> Top Warnings
              </h4>
              <div className="space-y-1">
                {topWarnings.map((w) => (
                  <div key={w.reason} className="flex items-center justify-between text-xs">
                    <span className="truncate text-muted-foreground">{w.reason.replace(/_/g, ' ')}</span>
                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{w.count}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Unscored docs notice */}
        {(data.no_readiness_data || 0) > 0 && (
          <div className="text-xs text-muted-foreground pt-1 border-t">
            {data.no_readiness_data} document{data.no_readiness_data !== 1 ? 's' : ''} not yet evaluated
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Daily Ingestion Card ────────────────────────────────────
function DailyIngestionCard({ data, date, onDateChange }) {
  if (!data) return null;

  const SOURCE_COLORS = {
    email: '#6366f1', email_poll: '#8b5cf6', backfill: '#94a3b8',
    manual_upload: '#10b981', unknown: '#64748b',
  };

  const hourData = Array.from({ length: 24 }, (_, i) => {
    const found = (data.by_hour || []).find(h => h.hour === i);
    return { hour: `${i.toString().padStart(2, '0')}:00`, count: found?.count || 0 };
  });

  const typeData = Object.entries(data.by_type || {}).slice(0, 8).map(([name, value]) => ({ name, value }));
  const sourceData = Object.entries(data.by_source || {}).map(([name, value]) => ({
    name, value, fill: SOURCE_COLORS[name] || '#64748b',
  }));

  return (
    <Card className="border border-border" data-testid="daily-ingestion-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Inbox className="w-5 h-5 text-indigo-500" />
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Daily Ingestion
            </CardTitle>
            <Badge className="text-xs bg-indigo-500/20 text-indigo-400 border-indigo-700">
              {data.total} docs
            </Badge>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="sm" className="text-xs h-7 px-2"
              onClick={() => {
                const d = new Date(date); d.setDate(d.getDate() - 1);
                onDateChange(d.toISOString().split('T')[0]);
              }} data-testid="prev-day-btn">
              &larr;
            </Button>
            <input type="date" value={date}
              onChange={e => onDateChange(e.target.value)}
              className="text-xs h-7 px-2 bg-muted/40 border border-border rounded-md font-mono"
              data-testid="ingestion-date-picker" />
            <Button variant="ghost" size="sm" className="text-xs h-7 px-2"
              onClick={() => {
                const d = new Date(date); d.setDate(d.getDate() + 1);
                const today = new Date().toISOString().split('T')[0];
                const next = d.toISOString().split('T')[0];
                if (next <= today) onDateChange(next);
              }} data-testid="next-day-btn">
              &rarr;
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Summary KPIs */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {sourceData.map(s => (
            <div key={s.name} className="bg-muted/30 rounded-md p-2.5 text-center">
              <p className="text-xl font-black font-mono" style={{ color: s.fill }}>{s.value}</p>
              <p className="text-[10px] text-muted-foreground uppercase">{s.name.replace(/_/g, ' ')}</p>
            </div>
          ))}
        </div>

        {/* Hourly activity chart */}
        {data.total > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Hourly Activity</p>
            <div className="h-[100px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={hourData} margin={{ top: 0, right: 0, left: 0, bottom: 0 }}>
                  <XAxis dataKey="hour" tick={{ fontSize: 9 }} interval={2} />
                  <YAxis hide />
                  <Tooltip contentStyle={{ fontSize: 11, background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))' }} />
                  <Bar dataKey="count" fill="#6366f1" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* By Document Type */}
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">By Document Type</p>
            <div className="space-y-1">
              {typeData.map(t => (
                <div key={t.name} className="flex items-center justify-between text-xs px-2 py-1 bg-muted/20 rounded">
                  <span className="text-muted-foreground truncate max-w-[150px]">{t.name.replace(/_/g, ' ')}</span>
                  <span className="font-mono font-bold">{t.value}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Top Senders */}
          {data.top_senders?.length > 0 && (
            <div>
              <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">Top Senders</p>
              <div className="space-y-1">
                {data.top_senders.slice(0, 8).map(s => (
                  <div key={s.sender} className="flex items-center justify-between text-xs px-2 py-1 bg-muted/20 rounded">
                    <span className="text-muted-foreground truncate max-w-[180px] flex items-center gap-1">
                      <Mail className="w-3 h-3 shrink-0" />{s.sender}
                    </span>
                    <span className="font-mono font-bold">{s.count}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Recent Documents */}
        {data.recent_documents?.length > 0 && (
          <div>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-2">
              Recent Documents ({data.recent_documents.length})
            </p>
            <div className="max-h-[250px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-[10px]">File</TableHead>
                    <TableHead className="text-[10px]">Type</TableHead>
                    <TableHead className="text-[10px]">Source</TableHead>
                    <TableHead className="text-[10px]">Vendor</TableHead>
                    <TableHead className="text-[10px]">Status</TableHead>
                    <TableHead className="text-[10px]">Time</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.recent_documents.map((doc, i) => (
                    <TableRow key={doc.id || i} className="text-xs">
                      <TableCell className="py-1.5">
                        <span className="truncate max-w-[180px] block font-medium">{doc.file_name || '-'}</span>
                      </TableCell>
                      <TableCell className="py-1.5">
                        <Badge variant="outline" className="text-[9px]">{(doc.document_type || '?').replace(/_/g, ' ')}</Badge>
                      </TableCell>
                      <TableCell className="py-1.5 text-muted-foreground">{doc.source || '-'}</TableCell>
                      <TableCell className="py-1.5 text-muted-foreground truncate max-w-[120px]">
                        {doc.vendor_canonical || doc.matched_vendor_name || '-'}
                      </TableCell>
                      <TableCell className="py-1.5">
                        <Badge variant="outline" className="text-[9px]">{doc.status || doc.workflow_status || '-'}</Badge>
                      </TableCell>
                      <TableCell className="py-1.5 font-mono text-muted-foreground">
                        {doc.created_utc ? doc.created_utc.substring(11, 16) : '-'}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
        )}

        {data.total === 0 && (
          <div className="text-center py-6 text-muted-foreground">
            <Calendar className="w-8 h-8 mx-auto mb-2 opacity-40" />
            <p className="text-sm">No documents ingested on this day</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}


export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [intelligence, setIntelligence] = useState(null);
  const [stableVendorMetrics, setStableVendorMetrics] = useState(null);
  const [dailyIngestion, setDailyIngestion] = useState(null);
  const [ingestionDate, setIngestionDate] = useState(() => {
    const d = new Date(); return d.toISOString().split('T')[0];
  });
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchStats = async () => {
    setLoading(true);
    try {
      const [statsRes, intelligenceRes, svRes, diRes] = await Promise.all([
        getDashboardStats(),
        getWorkflowIntelligence().catch(() => ({ data: null })),
        getStableVendorMetrics().catch(() => ({ data: null })),
        getDailyIngestion(ingestionDate).catch(() => ({ data: null })),
      ]);
      setStats(statsRes.data);
      setIntelligence(intelligenceRes.data);
      setStableVendorMetrics(svRes.data);
      setDailyIngestion(diRes.data);
    } catch (err) {
      toast.error('Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  };

  const fetchIngestion = useCallback(async (date) => {
    try {
      const res = await getDailyIngestion(date);
      setDailyIngestion(res.data);
    } catch {}
  }, []);

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
    { label: 'Vendor Auto-Resolve', value: formatPercent(intelligence?.vendor_intelligence?.vendor_auto_resolve_rate || 0), icon: Users, color: 'text-purple-500' },
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

      {/* Operations Queue Summary */}
      <OperationsQueueSummaryCard />

      {/* Document Routing Summary (Auto-Clear Gate) */}
      <RoutingSummaryCard
        statsRouting={stats?.routing_summary}
        intelligenceRouting={intelligence?.routing_summary}
      />

      {/* Document Readiness Summary */}
      <ReadinessSummaryCard data={intelligence?.readiness_summary} />

      {/* Automation Intelligence Metrics */}
      <AutomationMetricsCard />

      {/* Stable Vendor Auto-Ready KPIs */}
      {stableVendorMetrics && stableVendorMetrics.feature_enabled && (
        <Card className="border border-border" data-testid="stable-vendor-kpi-card">
          <CardHeader className="pb-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="w-5 h-5 text-emerald-500" />
              <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Stable Vendor Auto-Ready</CardTitle>
              <span className="ml-auto text-xs text-muted-foreground hover:text-foreground cursor-pointer underline underline-offset-2"
                onClick={() => navigate('/vendors?tab=stable')} data-testid="sv-view-all-link">View All</span>
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

      {/* Daily Ingestion */}
      <DailyIngestionCard
        data={dailyIngestion}
        date={ingestionDate}
        onDateChange={(d) => { setIngestionDate(d); fetchIngestion(d); }}
      />

      {/* Main Intelligence Grid - continued */}
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
                <Button className="w-full justify-start gap-2" onClick={() => navigate('/documents?tab=upload')} data-testid="quick-upload-btn">
                  <UploadCloud className="w-4 h-4" /> Upload Document
                </Button>
                <Button variant="secondary" className="w-full justify-start gap-2" onClick={() => navigate('/documents')} data-testid="quick-queue-btn">
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
