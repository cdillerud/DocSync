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
  PieChart, Pie, Cell, LineChart, Line, Legend, AreaChart, Area
} from 'recharts';
import {
  TrendingUp, TrendingDown, AlertTriangle, CheckCircle2, Clock, 
  RefreshCw, Users, FileText, Zap, Shield, BarChart3, DollarSign,
  Target, Award, ArrowUpRight, ArrowDownRight, Building2
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
  const [settingsStatus, setSettingsStatus] = useState(null);
  // Phase 6: Shadow Mode metrics
  const [matchScoreDistribution, setMatchScoreDistribution] = useState(null);
  const [aliasExceptions, setAliasExceptions] = useState(null);
  const [shadowModeStatus, setShadowModeStatus] = useState(null);

  const fetchAllMetrics = async () => {
    setLoading(true);
    try {
      const [metricsRes, vendorRes, aliasRes, timeRes, dailyRes, settingsRes, scoreDistRes, aliasExcRes, shadowRes] = await Promise.all([
        fetch(`${API}/api/metrics/automation?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/vendors?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/alias-impact`).then(r => r.json()),
        fetch(`${API}/api/metrics/resolution-time?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/metrics/daily?days=14`).then(r => r.json()),
        fetch(`${API}/api/settings/status`).then(r => r.json()),
        // Phase 6 endpoints
        fetch(`${API}/api/metrics/match-score-distribution`).then(r => r.json()),
        fetch(`${API}/api/metrics/alias-exceptions?days=${days}`).then(r => r.json()),
        fetch(`${API}/api/settings/shadow-mode`).then(r => r.json())
      ]);
      setMetrics(metricsRes);
      setVendorFriction(vendorRes);
      setAliasImpact(aliasRes);
      setResolutionTime(timeRes);
      setDailyMetrics(dailyRes);
      setSettingsStatus(settingsRes);
      setMatchScoreDistribution(scoreDistRes);
      setAliasExceptions(aliasExcRes);
      setShadowModeStatus(shadowRes);
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
    { range: '<70%', count: metrics.confidence_distribution['below_0.70'] },
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

      <Tabs defaultValue="roi" className="space-y-4">
        <TabsList data-testid="audit-tabs">
          <TabsTrigger value="roi" data-testid="tab-roi">
            <DollarSign className="w-4 h-4 mr-1" />
            ROI Summary
          </TabsTrigger>
          <TabsTrigger value="overview" data-testid="tab-overview">Overview</TabsTrigger>
          <TabsTrigger value="vendors" data-testid="tab-vendors">Vendor Friction</TabsTrigger>
          <TabsTrigger value="intelligence" data-testid="tab-intelligence">Intelligence</TabsTrigger>
          <TabsTrigger value="trends" data-testid="tab-trends">Trends</TabsTrigger>
        </TabsList>

        {/* ==================== ROI SUMMARY TAB (NEW) ==================== */}
        <TabsContent value="roi" className="space-y-6" data-testid="roi-tab-content">
          {/* Section 1: Automation Overview */}
          <Card className="border border-border" data-testid="roi-automation-overview">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Target className="w-5 h-5 text-primary" />
                Automation Overview
              </CardTitle>
              <CardDescription>Document processing efficiency at a glance</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-4 mb-6">
                <div className="p-4 bg-gradient-to-br from-primary/10 to-primary/5 rounded-lg border border-primary/20 text-center">
                  <p className="text-3xl font-bold text-primary">{metrics?.total_documents || 0}</p>
                  <p className="text-sm text-muted-foreground">Total Documents</p>
                </div>
                <div className="p-4 bg-gradient-to-br from-emerald-500/10 to-emerald-500/5 rounded-lg border border-emerald-500/20 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <p className="text-3xl font-bold text-emerald-600">{metrics?.automation_rate || 0}%</p>
                    {metrics?.automation_rate >= 50 && <ArrowUpRight className="w-5 h-5 text-emerald-600" />}
                  </div>
                  <p className="text-sm text-muted-foreground">Fully Automated</p>
                </div>
                <div className="p-4 bg-gradient-to-br from-amber-500/10 to-amber-500/5 rounded-lg border border-amber-500/20 text-center">
                  <div className="flex items-center justify-center gap-1">
                    <p className="text-3xl font-bold text-amber-600">{metrics?.review_rate || 0}%</p>
                    {metrics?.review_rate > 30 && <AlertTriangle className="w-4 h-4 text-amber-600" />}
                  </div>
                  <p className="text-sm text-muted-foreground">Needs Review</p>
                </div>
                <div className="p-4 bg-gradient-to-br from-blue-500/10 to-blue-500/5 rounded-lg border border-blue-500/20 text-center">
                  <p className="text-3xl font-bold text-blue-600">
                    {metrics?.status_distribution?.counts?.Classified || 0}
                  </p>
                  <p className="text-sm text-muted-foreground">Manual Resolved</p>
                </div>
                <div className="p-4 bg-gradient-to-br from-purple-500/10 to-purple-500/5 rounded-lg border border-purple-500/20 text-center">
                  <p className="text-3xl font-bold text-purple-600">{metrics?.duplicate_prevented || 0}</p>
                  <p className="text-sm text-muted-foreground">Duplicates Blocked</p>
                </div>
              </div>
              
              {/* Trend chart */}
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={dailyMetrics?.daily_metrics || []}>
                    <defs>
                      <linearGradient id="autoGradient" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.3}/>
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0}/>
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="date" tickFormatter={(d) => d.slice(5)} fontSize={12} />
                    <YAxis fontSize={12} />
                    <Tooltip />
                    <Area type="monotone" dataKey="auto_linked" stroke="#10b981" fill="url(#autoGradient)" name="Auto-Linked" />
                    <Area type="monotone" dataKey="needs_review" stroke="#f59e0b" fill="#f59e0b20" name="Needs Review" />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            </CardContent>
          </Card>

          {/* Section 2: Alias Impact - Data Hygiene ROI */}
          <Card className="border border-border" data-testid="roi-alias-impact">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Award className="w-5 h-5 text-purple-600" />
                Alias Impact — Data Hygiene ROI
              </CardTitle>
              <CardDescription>How learned aliases are improving automation rates</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg text-center border border-purple-200 dark:border-purple-800">
                  <p className="text-3xl font-bold text-purple-600">{metrics?.alias_auto_linked || 0}</p>
                  <p className="text-sm text-muted-foreground">Docs Via Alias</p>
                </div>
                <div className="p-4 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg text-center border border-emerald-200 dark:border-emerald-800">
                  <p className="text-3xl font-bold text-emerald-600">{aliasImpact?.alias_contribution || 0}%</p>
                  <p className="text-sm text-muted-foreground">Automation From Alias</p>
                </div>
                <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-center border border-blue-200 dark:border-blue-800">
                  <p className="text-3xl font-bold text-blue-600">{aliasImpact?.total_aliases || 0}</p>
                  <p className="text-sm text-muted-foreground">Vendors w/ Alias</p>
                </div>
                <div className="p-4 bg-amber-50 dark:bg-amber-900/20 rounded-lg text-center border border-amber-200 dark:border-amber-800">
                  <p className="text-3xl font-bold text-amber-600">{metrics?.alias_exception_rate || 0}%</p>
                  <p className="text-sm text-muted-foreground">Alias Exception Rate</p>
                </div>
              </div>
              
              {/* ROI Story */}
              <div className="p-4 bg-gradient-to-r from-purple-50 to-emerald-50 dark:from-purple-900/10 dark:to-emerald-900/10 rounded-lg border border-purple-200 dark:border-purple-800">
                <div className="flex items-start gap-3">
                  <div className="w-10 h-10 rounded-full bg-purple-100 dark:bg-purple-800 flex items-center justify-center flex-shrink-0">
                    <TrendingUp className="w-5 h-5 text-purple-600" />
                  </div>
                  <div>
                    <p className="font-medium text-sm">Data Hygiene Improvement</p>
                    <p className="text-sm text-muted-foreground mt-1">
                      {aliasImpact?.total_aliases > 0 ? (
                        <>
                          Your {aliasImpact?.total_aliases} vendor aliases have reduced manual touches by{' '}
                          <span className="font-bold text-emerald-600">{aliasImpact?.alias_contribution || 0}%</span>.{' '}
                          Each alias learned from manual corrections compounds future automation.
                        </>
                      ) : (
                        <>
                          No aliases configured yet. As you resolve documents manually, aliases are created
                          that will automate future matches for the same vendors.
                        </>
                      )}
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Phase 6: Match Score Distribution Chart */}
          <Card className="border border-border" data-testid="roi-match-score-distribution">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <BarChart3 className="w-5 h-5 text-indigo-600" />
                Match Score Distribution
              </CardTitle>
              <CardDescription>
                Score threshold analysis — determines if 0.92 threshold is conservative
              </CardDescription>
            </CardHeader>
            <CardContent>
              {matchScoreDistribution ? (
                <>
                  <div className="grid grid-cols-4 gap-2 mb-4">
                    {[
                      { key: '0.95_1.00', label: '0.95-1.00', color: 'bg-emerald-500', desc: 'Very High' },
                      { key: '0.92_0.95', label: '0.92-0.95', color: 'bg-blue-500', desc: 'High' },
                      { key: '0.88_0.92', label: '0.88-0.92', color: 'bg-amber-500', desc: 'Near' },
                      { key: 'lt_0.88', label: '<0.88', color: 'bg-red-500', desc: 'Below' }
                    ].map(bucket => (
                      <div key={bucket.key} className="text-center p-3 bg-muted/30 rounded-lg">
                        <div className={`w-3 h-3 ${bucket.color} rounded-full mx-auto mb-2`}></div>
                        <p className="text-2xl font-bold">
                          {matchScoreDistribution.buckets?.[bucket.key]?.count || 0}
                        </p>
                        <p className="text-xs text-muted-foreground">{bucket.label}</p>
                        <p className="text-xs text-muted-foreground/60">{bucket.desc}</p>
                      </div>
                    ))}
                  </div>
                  
                  {/* Bar chart */}
                  <div className="h-40 mb-4">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={[
                        { bucket: '0.95-1.00', count: matchScoreDistribution.buckets?.['0.95_1.00']?.count || 0, fill: '#10b981' },
                        { bucket: '0.92-0.95', count: matchScoreDistribution.buckets?.['0.92_0.95']?.count || 0, fill: '#3b82f6' },
                        { bucket: '0.88-0.92', count: matchScoreDistribution.buckets?.['0.88_0.92']?.count || 0, fill: '#f59e0b' },
                        { bucket: '<0.88', count: matchScoreDistribution.buckets?.['lt_0.88']?.count || 0, fill: '#ef4444' }
                      ]}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis dataKey="bucket" fontSize={11} />
                        <YAxis fontSize={11} />
                        <Tooltip />
                        <Bar dataKey="count" name="Documents">
                          {[
                            { bucket: '0.95-1.00', fill: '#10b981' },
                            { bucket: '0.92-0.95', fill: '#3b82f6' },
                            { bucket: '0.88-0.92', fill: '#f59e0b' },
                            { bucket: '<0.88', fill: '#ef4444' }
                          ].map((entry, index) => (
                            <Cell key={`cell-${index}`} fill={entry.fill} />
                          ))}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                  
                  {/* Interpretation */}
                  <div className={`p-4 rounded-lg border ${
                    matchScoreDistribution.summary?.high_confidence_pct >= 60 
                      ? 'bg-emerald-50 dark:bg-emerald-900/20 border-emerald-200 dark:border-emerald-800'
                      : matchScoreDistribution.summary?.high_confidence_pct >= 40
                      ? 'bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800'
                      : 'bg-red-50 dark:bg-red-900/20 border-red-200 dark:border-red-800'
                  }`}>
                    <div className="flex items-center gap-2 mb-2">
                      <span className="font-medium">High-confidence eligible (≥0.92):</span>
                      <span className="font-bold text-lg">{matchScoreDistribution.summary?.high_confidence_eligible || 0}</span>
                      <span className="text-muted-foreground">
                        ({matchScoreDistribution.summary?.high_confidence_pct || 0}%)
                      </span>
                    </div>
                    <p className="text-sm text-muted-foreground">
                      {matchScoreDistribution.summary?.interpretation}
                    </p>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  Loading match score data...
                </div>
              )}
            </CardContent>
          </Card>

          {/* Phase 6: Shadow Mode Status Card */}
          {shadowModeStatus && (
            <Card className={`border-2 ${
              shadowModeStatus.shadow_mode?.is_active 
                ? 'border-indigo-500/50 bg-indigo-50/30 dark:bg-indigo-900/10' 
                : 'border-border'
            }`} data-testid="roi-shadow-mode">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    <Clock className="w-5 h-5 text-indigo-600" />
                    Shadow Mode Status
                  </CardTitle>
                  {shadowModeStatus.shadow_mode?.is_active && (
                    <Badge className="bg-indigo-100 text-indigo-800 border border-indigo-200">
                      Active
                    </Badge>
                  )}
                </div>
                <CardDescription>
                  Production instrumentation without BC writes — collect real metrics safely
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold text-indigo-600">
                      {shadowModeStatus.shadow_mode?.days_running || 0}
                    </p>
                    <p className="text-sm text-muted-foreground">Days in Shadow</p>
                  </div>
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold">
                      {shadowModeStatus.health_indicators_7d?.high_confidence_docs_pct || 0}%
                    </p>
                    <p className="text-sm text-muted-foreground">High Conf. (7d)</p>
                  </div>
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold">
                      {shadowModeStatus.health_indicators_7d?.alias_exception_rate || 0}%
                    </p>
                    <p className="text-sm text-muted-foreground">Alias Exc. (7d)</p>
                  </div>
                  <div className="p-4 bg-muted/30 rounded-lg text-center">
                    <p className="text-3xl font-bold">
                      {shadowModeStatus.health_indicators_7d?.total_docs_processed || 0}
                    </p>
                    <p className="text-sm text-muted-foreground">Docs (7d)</p>
                  </div>
                </div>
                
                {/* Feature Flags */}
                <div className="flex flex-wrap gap-2 mb-4">
                  <Badge variant={shadowModeStatus.feature_flags?.CREATE_DRAFT_HEADER ? 'default' : 'secondary'}>
                    CREATE_DRAFT_HEADER: {shadowModeStatus.feature_flags?.CREATE_DRAFT_HEADER ? 'ON' : 'OFF'}
                  </Badge>
                  <Badge variant="outline">
                    DEMO_MODE: {shadowModeStatus.feature_flags?.DEMO_MODE ? 'ON' : 'OFF'}
                  </Badge>
                </div>
                
                {/* Readiness Assessment */}
                <div className={`p-4 rounded-lg ${
                  shadowModeStatus.readiness_assessment?.recommended_action?.includes('Ready')
                    ? 'bg-emerald-50 dark:bg-emerald-900/20 border border-emerald-200 dark:border-emerald-800'
                    : 'bg-muted/50 border border-border'
                }`}>
                  <div className="flex items-center gap-2 mb-2">
                    {shadowModeStatus.readiness_assessment?.recommended_action?.includes('Ready') ? (
                      <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                    ) : (
                      <Clock className="w-5 h-5 text-muted-foreground" />
                    )}
                    <span className="font-medium">Readiness Assessment</span>
                  </div>
                  <p className="text-sm text-muted-foreground">
                    {shadowModeStatus.readiness_assessment?.recommended_action}
                  </p>
                  <div className="flex flex-wrap gap-4 mt-3 text-xs">
                    <span className={shadowModeStatus.readiness_assessment?.high_confidence_ok ? 'text-emerald-600' : 'text-muted-foreground'}>
                      High Conf: {shadowModeStatus.readiness_assessment?.high_confidence_ok ? '✓' : '✗'}
                    </span>
                    <span className={shadowModeStatus.readiness_assessment?.alias_exception_ok ? 'text-emerald-600' : 'text-muted-foreground'}>
                      Alias Exc: {shadowModeStatus.readiness_assessment?.alias_exception_ok ? '✓' : '✗'}
                    </span>
                    <span className={shadowModeStatus.readiness_assessment?.sufficient_data ? 'text-emerald-600' : 'text-muted-foreground'}>
                      Data Vol: {shadowModeStatus.readiness_assessment?.sufficient_data ? '✓' : '✗'}
                    </span>
                  </div>
                </div>
                
                {/* Top Friction Vendor */}
                {shadowModeStatus.health_indicators_7d?.top_friction_vendor && (
                  <div className="mt-4 p-3 bg-amber-50 dark:bg-amber-900/20 rounded-lg border border-amber-200 dark:border-amber-800">
                    <div className="flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-amber-600" />
                      <span className="text-sm font-medium">Top Friction Vendor (7d):</span>
                      <span className="text-sm">
                        {shadowModeStatus.health_indicators_7d.top_friction_vendor.vendor}
                      </span>
                      <Badge variant="destructive" className="text-xs">
                        {shadowModeStatus.health_indicators_7d.top_friction_vendor.exception_count} exceptions
                      </Badge>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Section 3: Vendor Friction Matrix */}
          <Card className="border border-border" data-testid="roi-vendor-matrix">
            <CardHeader className="pb-2">
              <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                <Building2 className="w-5 h-5 text-blue-600" />
                Vendor Friction Matrix
              </CardTitle>
              <CardDescription>Where process breakdowns are happening — sortable by automation rate</CardDescription>
            </CardHeader>
            <CardContent>
              {vendorFriction?.vendors && vendorFriction.vendors.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full text-sm" data-testid="vendor-friction-table">
                    <thead>
                      <tr className="border-b">
                        <th className="text-left py-3 px-2 font-medium">Vendor</th>
                        <th className="text-center py-3 px-2 font-medium">Docs</th>
                        <th className="text-center py-3 px-2 font-medium">Automation %</th>
                        <th className="text-center py-3 px-2 font-medium">Exception %</th>
                        <th className="text-center py-3 px-2 font-medium">Avg Score</th>
                        <th className="text-center py-3 px-2 font-medium">Alias Usage</th>
                      </tr>
                    </thead>
                    <tbody>
                      {vendorFriction.vendors.slice(0, 10).map((vendor, idx) => (
                        <tr key={idx} className="border-b hover:bg-muted/30 transition-colors">
                          <td className="py-3 px-2">
                            <div className="flex items-center gap-2">
                              <span className="font-medium truncate max-w-[200px]">{vendor.vendor}</span>
                              {vendor.has_alias && (
                                <Badge variant="secondary" className="text-xs">Alias</Badge>
                              )}
                            </div>
                          </td>
                          <td className="text-center py-3 px-2 font-mono">{vendor.total_documents}</td>
                          <td className="text-center py-3 px-2">
                            <div className="flex items-center justify-center gap-2">
                              <Progress 
                                value={vendor.auto_rate} 
                                className="w-16 h-2" 
                              />
                              <span className={`font-mono ${
                                vendor.auto_rate >= 70 ? 'text-emerald-600' :
                                vendor.auto_rate >= 40 ? 'text-amber-600' : 'text-red-600'
                              }`}>{vendor.auto_rate}%</span>
                            </div>
                          </td>
                          <td className="text-center py-3 px-2">
                            <Badge variant={vendor.friction_index >= 50 ? 'destructive' : 'secondary'}>
                              {vendor.friction_index}%
                            </Badge>
                          </td>
                          <td className="text-center py-3 px-2 font-mono">
                            {vendor.avg_confidence ? (vendor.avg_confidence * 100).toFixed(0) + '%' : '-'}
                          </td>
                          <td className="text-center py-3 px-2">
                            {vendor.alias_matches > 0 ? (
                              <Badge variant="outline" className="text-purple-600">
                                {vendor.alias_matches} uses
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground">-</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="text-center py-8 text-muted-foreground">
                  No vendor data available yet
                </div>
              )}
            </CardContent>
          </Card>

          {/* Section 4: Draft Creation Confidence (Shown when feature exists) */}
          {(metrics?.draft_feature_enabled !== undefined) && (
            <Card className={`border ${metrics?.draft_feature_enabled ? 'border-emerald-500/50' : 'border-border opacity-60'}`} data-testid="roi-draft-confidence">
              <CardHeader className="pb-2">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-lg font-bold flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    <Shield className="w-5 h-5 text-emerald-600" />
                    Draft Creation Confidence
                    {!metrics?.draft_feature_enabled && (
                      <Badge variant="outline" className="ml-2 text-muted-foreground">Feature Disabled</Badge>
                    )}
                  </CardTitle>
                  {metrics?.draft_feature_enabled && (
                    <Badge className="bg-emerald-100 text-emerald-800 border border-emerald-200">
                      <CheckCircle2 className="w-3 h-3 mr-1" />
                      Active
                    </Badge>
                  )}
                </div>
                <CardDescription>
                  {metrics?.draft_feature_enabled 
                    ? 'Purchase Invoice draft creation metrics — risk calibration indicator'
                    : 'Enable CREATE_DRAFT_HEADER feature flag to see draft creation metrics'
                  }
                </CardDescription>
              </CardHeader>
              <CardContent>
                {metrics?.draft_feature_enabled ? (
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 bg-muted/30 rounded-lg text-center">
                      <p className="text-3xl font-bold">
                        {(metrics?.status_distribution?.counts?.LinkedToBC || 0) - (metrics?.draft_created_count || 0)}
                      </p>
                      <p className="text-sm text-muted-foreground">Eligible for Draft</p>
                    </div>
                    <div className="p-4 bg-emerald-50 dark:bg-emerald-900/20 rounded-lg text-center border border-emerald-200 dark:border-emerald-800">
                      <p className="text-3xl font-bold text-emerald-600">{metrics?.draft_created_count || 0}</p>
                      <p className="text-sm text-muted-foreground">Drafts Created</p>
                    </div>
                    <div className="p-4 bg-blue-50 dark:bg-blue-900/20 rounded-lg text-center border border-blue-200 dark:border-blue-800">
                      <p className="text-3xl font-bold text-blue-600">{metrics?.draft_creation_rate || 0}%</p>
                      <p className="text-sm text-muted-foreground">Draft Creation Rate</p>
                    </div>
                    <div className="p-4 bg-purple-50 dark:bg-purple-900/20 rounded-lg text-center border border-purple-200 dark:border-purple-800">
                      <p className="text-3xl font-bold text-purple-600">
                        {metrics?.header_only_flag ? 'Header' : 'Full'}
                      </p>
                      <p className="text-sm text-muted-foreground">Draft Mode</p>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-6 space-y-3">
                    <div className="w-16 h-16 mx-auto rounded-full bg-muted flex items-center justify-center">
                      <Shield className="w-8 h-8 text-muted-foreground" />
                    </div>
                    <p className="text-sm text-muted-foreground">
                      Draft creation is disabled. Enable in Settings → Features to begin creating Purchase Invoice drafts automatically.
                    </p>
                    <div className="text-xs text-muted-foreground bg-muted/50 p-3 rounded-lg max-w-md mx-auto">
                      <p className="font-medium mb-1">Safety Requirements:</p>
                      <ul className="list-disc list-inside text-left">
                        <li>Match score ≥ 92%</li>
                        <li>AI confidence ≥ 92%</li>
                        <li>Match method: exact, normalized, or alias</li>
                        <li>No duplicate invoices</li>
                      </ul>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* ELT Summary Box */}
          <Card className="border-2 border-primary/30 bg-primary/5" data-testid="roi-elt-summary">
            <CardContent className="p-6">
              <div className="flex items-start gap-4">
                <div className="w-12 h-12 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                  <DollarSign className="w-6 h-6 text-primary" />
                </div>
                <div className="space-y-2">
                  <h3 className="font-bold text-lg" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    Executive Summary
                  </h3>
                  <div className="text-sm text-muted-foreground space-y-1">
                    <p>
                      <span className="font-medium text-foreground">Automation Rate:</span>{' '}
                      {metrics?.automation_rate || 0}% of documents processed without human intervention
                    </p>
                    <p>
                      <span className="font-medium text-foreground">Data Hygiene ROI:</span>{' '}
                      {aliasImpact?.total_aliases || 0} vendor aliases contributing {aliasImpact?.alias_contribution || 0}% of automation
                    </p>
                    <p>
                      <span className="font-medium text-foreground">Risk Mitigation:</span>{' '}
                      {metrics?.duplicate_prevented || 0} duplicate invoices blocked
                    </p>
                    <p>
                      <span className="font-medium text-foreground">Processing Time:</span>{' '}
                      Median resolution in {resolutionTime?.median_minutes || 0} minutes
                    </p>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

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
                    <div key={idx} className="p-4 bg-muted/30 rounded-lg space-y-2">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center text-sm font-bold ${
                            vendor.friction_index >= 80 ? 'bg-red-100 text-red-700' :
                            vendor.friction_index >= 50 ? 'bg-amber-100 text-amber-700' :
                            'bg-emerald-100 text-emerald-700'
                          }`}>
                            {idx + 1}
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="font-medium">{vendor.vendor}</p>
                              {vendor.has_alias && (
                                <Badge variant="secondary" className="text-xs">Has Alias</Badge>
                              )}
                            </div>
                            <p className="text-xs text-muted-foreground">
                              {vendor.total_documents} docs • {vendor.auto_rate}% auto-linked • {vendor.alias_matches || 0} alias matches
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-3">
                          <div className="text-right">
                            <p className="text-sm font-mono">{vendor.friction_index}%</p>
                            <p className="text-xs text-muted-foreground">friction</p>
                          </div>
                          {!vendor.has_alias && (
                            <Button size="sm" variant="outline" data-testid={`add-alias-${idx}`}>
                              Add Alias
                            </Button>
                          )}
                        </div>
                      </div>
                      {/* ROI Hint */}
                      {vendor.roi_hint && (
                        <div className={`text-xs p-2 rounded ${
                          vendor.has_alias 
                            ? 'bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300' 
                            : 'bg-amber-50 text-amber-700 dark:bg-amber-900/20 dark:text-amber-300'
                        }`}>
                          💡 {vendor.roi_hint}
                        </div>
                      )}
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
          {/* Match Method Summary Cards */}
          <div className="grid grid-cols-2 md:grid-cols-6 gap-3">
            {metrics?.match_method_breakdown && Object.entries(metrics.match_method_breakdown).map(([method, count]) => (
              <Card key={method} className="border border-border">
                <CardContent className="p-3 text-center">
                  <p className="text-2xl font-bold">{count}</p>
                  <p className="text-xs text-muted-foreground capitalize">{method.replace('_', ' ')}</p>
                </CardContent>
              </Card>
            ))}
          </div>

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
