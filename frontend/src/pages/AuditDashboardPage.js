import { useState, useEffect } from 'react';
import { 
  Card, CardContent, CardHeader, CardTitle, CardDescription 
} from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs';
import { 
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue 
} from '../components/ui/select';
import { toast } from 'sonner';
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, LineChart, Line, Legend
} from 'recharts';
import {
  TrendingUp, TrendingDown, AlertTriangle, CheckCircle2, Clock, 
  RefreshCw, Users, FileText, Zap, Shield, BarChart3
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const COLORS = ['#10b981', '#f59e0b', '#ef4444', '#6366f1', '#8b5cf6', '#06b6d4'];

export default function AuditDashboardPage() {
  const [loading, setLoading] = useState(true);
  const [days, setDays] = useState('30');
  const [metrics, setMetrics] = useState(null);
  const [vendorFriction, setVendorFriction] = useState(null);
  const [aliasImpact, setAliasImpact] = useState(null);
  const [resolutionTime, setResolutionTime] = useState(null);
  const [dailyMetrics, setDailyMetrics] = useState(null);

  const fetchAllMetrics = async () => {
    setLoading(true);
    try {
      const [metricsRes, vendorRes, aliasRes, timeRes, dailyRes] = await Promise.all([
        fetch(`${API}/api/metrics/automation?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/vendors?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/alias-impact`).then(r => r.json()),
        fetch(`${API}/api/metrics/resolution-time?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/daily?days=14`).then(r => r.json())
      ]);
      setMetrics(metricsRes);
      setVendorFriction(vendorRes);
      setAliasImpact(aliasRes);
      setResolutionTime(timeRes);
      setDailyMetrics(dailyRes);
    } catch (err) {
      toast.error('Failed to load metrics');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchAllMetrics(); }, [days]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="audit-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  // Prepare chart data
  const statusData = metrics ? [
    { name: 'Auto-Linked', value: metrics.status_distribution.counts.LinkedToBC, color: '#10b981' },
    { name: 'Needs Review', value: metrics.status_distribution.counts.NeedsReview, color: '#f59e0b' },
    { name: 'Stored in SP', value: metrics.status_distribution.counts.StoredInSP, color: '#06b6d4' },
    { name: 'Classified', value: metrics.status_distribution.counts.Classified, color: '#6366f1' },
    { name: 'Exception', value: metrics.status_distribution.counts.Exception, color: '#ef4444' },
  ].filter(d => d.value > 0) : [];

  const confidenceData = metrics ? [
    { range: '90-100%', count: metrics.confidence_distribution['0.90-1.00'] },
    { range: '80-90%', count: metrics.confidence_distribution['0.80-0.90'] },
    { range: '70-80%', count: metrics.confidence_distribution['0.70-0.80'] },
    { range: '<70%', count: metrics.confidence_distribution.below_0.70 },
  ] : [];

  const matchMethodData = aliasImpact ? Object.entries(aliasImpact.match_method_distribution).map(([method, count]) => ({
    method: method.replace('_', ' ').replace(/\b\w/g, l => l.toUpperCase()),
    count,
    percentage: aliasImpact.match_method_percentages[method]
  })) : [];

  return (
    <div className="max-w-7xl mx-auto space-y-6" data-testid="audit-dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <BarChart3 className="w-6 h-6 text-primary" />
            Automation Audit Dashboard
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Performance metrics and ROI proof
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Select value={days} onValueChange={setDays}>
            <SelectTrigger className="w-32" data-testid="days-select">
              <SelectValue placeholder="Period" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="14">Last 14 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
              <SelectItem value="90">Last 90 days</SelectItem>
            </SelectContent>
          </Select>
          <Button variant="secondary" onClick={fetchAllMetrics} data-testid="refresh-btn">
            <RefreshCw className="w-4 h-4 mr-2" /> Refresh
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 md:grid-cols-5 gap-4" data-testid="kpi-cards">
        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                <Zap className="w-5 h-5 text-emerald-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{metrics?.automation_rate || 0}%</p>
                <p className="text-xs text-muted-foreground">Auto-Link Rate</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                <AlertTriangle className="w-5 h-5 text-amber-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{metrics?.review_rate || 0}%</p>
                <p className="text-xs text-muted-foreground">Review Rate</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                <Shield className="w-5 h-5 text-blue-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{metrics?.duplicate_prevented || 0}</p>
                <p className="text-xs text-muted-foreground">Duplicates Blocked</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                <Clock className="w-5 h-5 text-purple-600" />
              </div>
              <div>
                <p className="text-2xl font-bold">{resolutionTime?.median_minutes || 0}m</p>
                <p className="text-xs text-muted-foreground">Median Resolution</p>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card className="border border-border">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                <FileText className="w-5 h-5 text-primary" />
              </div>
              <div>
                <p className="text-2xl font-bold">{metrics?.total_documents || 0}</p>
                <p className="text-xs text-muted-foreground">Total Documents</p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList data-testid="audit-tabs">
          <TabsTrigger value="overview" data-testid="tab-overview">Overview</TabsTrigger>
          <TabsTrigger value="vendors" data-testid="tab-vendors">Vendor Friction</TabsTrigger>
          <TabsTrigger value="intelligence" data-testid="tab-intelligence">Intelligence</TabsTrigger>
          <TabsTrigger value="trends" data-testid="tab-trends">Trends</TabsTrigger>
        </TabsList>

        {/* ==================== OVERVIEW TAB ==================== */}
        <TabsContent value="overview" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Status Distribution Pie */}
            <Card className="border border-border" data-testid="status-distribution-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Status Distribution
                </CardTitle>
                <CardDescription>Document processing outcomes</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <PieChart>
                      <Pie
                        data={statusData}
                        cx="50%"
                        cy="50%"
                        innerRadius={60}
                        outerRadius={80}
                        paddingAngle={5}
                        dataKey="value"
                        label={({ name, value }) => `${name}: ${value}`}
                      >
                        {statusData.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={entry.color} />
                        ))}
                      </Pie>
                      <Tooltip />
                    </PieChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* Confidence Distribution */}
            <Card className="border border-border" data-testid="confidence-distribution-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Confidence Distribution
                </CardTitle>
                <CardDescription>AI classification confidence scores</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={confidenceData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="range" />
                      <YAxis />
                      <Tooltip />
                      <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
                <div className="mt-2 text-center">
                  <Badge variant="outline" className="text-sm">
                    Average Confidence: {(metrics?.average_confidence * 100).toFixed(0)}%
                  </Badge>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Job Type Breakdown */}
          {metrics?.job_type_breakdown && Object.keys(metrics.job_type_breakdown).length > 0 && (
            <Card className="border border-border" data-testid="job-type-breakdown-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Job Type Performance
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {Object.entries(metrics.job_type_breakdown).map(([jt, stats]) => (
                    <div key={jt} className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="font-medium">{jt.replace('_', ' ')}</span>
                        <div className="flex items-center gap-2">
                          <Badge variant="secondary">{stats.total} docs</Badge>
                          <Badge className={stats.auto_rate >= 50 ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}>
                            {stats.auto_rate}% auto
                          </Badge>
                        </div>
                      </div>
                      <Progress value={stats.auto_rate} className="h-2" />
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ==================== VENDOR FRICTION TAB ==================== */}
        <TabsContent value="vendors" className="space-y-4">
          <Card className="border border-border" data-testid="vendor-friction-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Users className="w-5 h-5 text-primary" />
                Vendor Friction Index
              </CardTitle>
              <CardDescription>
                Vendors causing the most manual review - alias mapping opportunities
              </CardDescription>
            </CardHeader>
            <CardContent>
              {vendorFriction?.vendors && vendorFriction.vendors.length > 0 ? (
                <div className="space-y-3">
                  {vendorFriction.vendors.map((vendor, idx) => (
                    <div key={idx} className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
                      <div className="flex items-center gap-3">
                        <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                          vendor.friction_index >= 80 ? 'bg-red-100 text-red-700' :
                          vendor.friction_index >= 50 ? 'bg-amber-100 text-amber-700' :
                          'bg-emerald-100 text-emerald-700'
                        }`}>
                          {idx + 1}
                        </div>
                        <div>
                          <p className="font-medium">{vendor.vendor}</p>
                          <p className="text-xs text-muted-foreground">
                            {vendor.total_documents} docs • {vendor.auto_rate}% auto-linked
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="text-right">
                          <p className="text-sm font-mono">{vendor.friction_index}%</p>
                          <p className="text-xs text-muted-foreground">friction</p>
                        </div>
                        <Button size="sm" variant="outline" data-testid={`add-alias-${idx}`}>
                          Add Alias
                        </Button>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-center text-muted-foreground py-8">
                  No vendor friction data yet
                </p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ==================== INTELLIGENCE TAB ==================== */}
        <TabsContent value="intelligence" className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {/* Match Method Distribution */}
            <Card className="border border-border" data-testid="match-method-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Match Method Distribution
                </CardTitle>
                <CardDescription>How vendors/customers are being matched</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={matchMethodData} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis type="number" />
                      <YAxis dataKey="method" type="category" width={100} />
                      <Tooltip />
                      <Bar dataKey="count" fill="#8b5cf6" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </CardContent>
            </Card>

            {/* Alias Impact */}
            <Card className="border border-border" data-testid="alias-impact-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Alias Intelligence
                </CardTitle>
                <CardDescription>Learning from manual resolutions</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold text-primary">{aliasImpact?.total_aliases || 0}</p>
                    <p className="text-xs text-muted-foreground">Total Aliases</p>
                  </div>
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold text-emerald-600">{aliasImpact?.alias_contribution || 0}%</p>
                    <p className="text-xs text-muted-foreground">Alias Contribution</p>
                  </div>
                </div>

                {aliasImpact?.top_aliases && aliasImpact.top_aliases.length > 0 && (
                  <div>
                    <p className="text-sm font-medium mb-2">Top Used Aliases</p>
                    <div className="space-y-2">
                      {aliasImpact.top_aliases.slice(0, 5).map((alias, idx) => (
                        <div key={idx} className="flex items-center justify-between text-sm">
                          <span className="truncate">{alias.alias_string}</span>
                          <Badge variant="secondary">{alias.usage_count} uses</Badge>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        {/* ==================== TRENDS TAB ==================== */}
        <TabsContent value="trends" className="space-y-4">
          <Card className="border border-border" data-testid="trends-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                Daily Processing Trends
              </CardTitle>
              <CardDescription>Document volume and automation rate over time</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-80">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={dailyMetrics?.daily_metrics || []}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} />
                    <YAxis yAxisId="left" />
                    <YAxis yAxisId="right" orientation="right" domain={[0, 100]} />
                    <Tooltip />
                    <Legend />
                    <Line yAxisId="left" type="monotone" dataKey="total" stroke="#6366f1" name="Total Docs" />
                    <Line yAxisId="left" type="monotone" dataKey="auto_linked" stroke="#10b981" name="Auto-Linked" />
                    <Line yAxisId="left" type="monotone" dataKey="needs_review" stroke="#f59e0b" name="Needs Review" />
                    <Line yAxisId="right" type="monotone" dataKey="auto_rate" stroke="#8b5cf6" strokeDasharray="5 5" name="Auto Rate %" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Resolution Time Stats */}
          <Card className="border border-border" data-testid="resolution-time-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
                Resolution Time by Job Type
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
                {resolutionTime?.by_job_type && Object.entries(resolutionTime.by_job_type).map(([jt, stats]) => (
                  <div key={jt} className="p-4 bg-muted/30 rounded-lg">
                    <p className="text-sm font-medium">{jt.replace('_', ' ')}</p>
                    <p className="text-2xl font-bold mt-1">{stats.median_minutes}m</p>
                    <p className="text-xs text-muted-foreground">median ({stats.count} docs)</p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
