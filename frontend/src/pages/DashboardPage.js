import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { getDashboardStats, retryWorkflow } from '../lib/api';
import api from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { toast } from 'sonner';
import {
  FileText, Link, AlertCircle, CheckCircle2, RefreshCw, ArrowRight, UploadCloud, Files,
  TrendingUp, Target, Zap, Clock
} from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell, LineChart, Line } from 'recharts';

const STATUS_COLORS = {
  Received: 'status-received',
  Classified: 'status-classified',
  LinkedToBC: 'status-linked',
  Exception: 'status-exception',
  Completed: 'status-completed',
};

const CHART_COLORS = ['#3b82f6', '#a855f7', '#22c55e', '#ef4444', '#6b7280'];

function StatusBadge({ status }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STATUS_COLORS[status] || ''}`}>
      {status}
    </span>
  );
}

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function DashboardPage() {
  const [stats, setStats] = useState(null);
  const [extractionQuality, setExtractionQuality] = useState(null);
  const [dailyTrends, setDailyTrends] = useState([]);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const fetchStats = async () => {
    try {
      const res = await getDashboardStats();
      setStats(res.data);
      
      // Fetch extraction quality metrics
      try {
        const qualityRes = await api.get('/metrics/extraction-quality?days=7');
        setExtractionQuality(qualityRes.data);
      } catch (e) {
        console.log('Extraction quality API not available');
      }
      
      // Fetch daily trends
      try {
        const trendsRes = await api.get('/metrics/daily?days=7');
        setDailyTrends(trendsRes.data?.daily || []);
      } catch (e) {
        console.log('Daily trends API not available');
      }
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

  const metricCards = [
    { label: 'Total Documents', value: stats?.total_documents || 0, icon: FileText, color: 'text-blue-500' },
    { label: 'Linked to BC', value: stats?.by_status?.LinkedToBC || 0, icon: Link, color: 'text-emerald-500' },
    { label: 'Exceptions', value: stats?.by_status?.Exception || 0, icon: AlertCircle, color: 'text-red-500' },
    { label: 'Completed', value: stats?.by_status?.Completed || 0, icon: CheckCircle2, color: 'text-gray-500' },
  ];

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto" data-testid="dashboard-page">
      {/* Demo mode banner */}
      {stats?.demo_mode && (
        <div className="bg-amber-50 dark:bg-amber-950/50 border border-amber-200 dark:border-amber-800 rounded-lg px-4 py-3 flex items-center gap-3" data-testid="demo-mode-banner">
          <AlertCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 shrink-0" />
          <p className="text-sm text-amber-800 dark:text-amber-200">
            <span className="font-semibold">Demo Mode Active</span> - Microsoft APIs are simulated. Configure Entra ID credentials in Settings to connect live.
          </p>
        </div>
      )}

      {/* Metric cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="stats-grid">
        {metricCards.map(({ label, value, icon: Icon, color }, i) => (
          <Card key={label} className={`border border-border hover:border-primary/30 transition-colors animate-fade-in-up animate-delay-${i}00`}>
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

      {/* Chart + Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-12 gap-6">
        <Card className="md:col-span-8 border border-border" data-testid="status-chart-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>Documents by Status</CardTitle>
          </CardHeader>
          <CardContent>
            {chartData.length > 0 ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData} barCategoryGap="25%">
                  <XAxis dataKey="name" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} />
                  <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} allowDecimals={false} />
                  <Tooltip
                    contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: '0.5rem', fontSize: '12px' }}
                    labelStyle={{ fontWeight: 600 }}
                  />
                  <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                    {chartData.map((entry, idx) => (
                      <Cell key={entry.name} fill={CHART_COLORS[idx % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex flex-col items-center justify-center h-64 text-muted-foreground">
                <FileText className="w-10 h-10 mb-3 opacity-40" />
                <p className="text-sm">No documents yet</p>
                <Button variant="ghost" className="mt-2 text-primary" onClick={() => navigate('/upload')} data-testid="upload-first-doc-btn">
                  Upload your first document <ArrowRight className="w-4 h-4 ml-1" />
                </Button>
              </div>
            )}
          </CardContent>
        </Card>

        <div className="md:col-span-4 space-y-4">
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
    </div>
  );
}
