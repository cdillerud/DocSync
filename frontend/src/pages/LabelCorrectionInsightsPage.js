import React, { useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { toast } from 'sonner';
import {
  ArrowRight, RefreshCw, Loader2, Target, TrendingUp, Users,
  AlertTriangle, Lightbulb, ChevronDown, ChevronUp, Search,
  BarChart3, ArrowUpRight, ExternalLink, Filter, Bell, BellOff,
  TrendingDown, Minus, ShieldAlert, CheckCircle2, XCircle, Eye
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell,
  LineChart, Line, PieChart, Pie, Legend
} from 'recharts';

const API = process.env.REACT_APP_BACKEND_URL;

const LABEL_COLORS = {
  PO: '#ef4444',
  INVOICE: '#f59e0b',
  ORDER: '#3b82f6',
  BOL: '#8b5cf6',
  SHIPMENT: '#22c55e',
  REF: '#6b7280',
};
const ENTITY_COLORS = {
  posted_sales_shipment: '#22c55e',
  purchase_order: '#3b82f6',
  posted_purchase_invoice: '#f59e0b',
  sales_order: '#8b5cf6',
  posted_sales_invoice: '#ef4444',
};
const SEVERITY_CONFIG = {
  high: { color: 'bg-red-500/20 text-red-400 border-red-400/30', icon: AlertTriangle },
  medium: { color: 'bg-amber-500/20 text-amber-400 border-amber-400/30', icon: AlertTriangle },
  low: { color: 'bg-blue-500/20 text-blue-400 border-blue-400/30', icon: Lightbulb },
};
const CHART_COLORS = ['#3b82f6', '#22c55e', '#8b5cf6', '#f59e0b', '#ef4444', '#06b6d4'];

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export default function LabelCorrectionInsightsPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [summary, setSummary] = useState(null);
  const [patterns, setPatterns] = useState([]);
  const [vendors, setVendors] = useState([]);
  const [timeline, setTimeline] = useState([]);
  const [recommendations, setRecommendations] = useState([]);
  const [expandedRec, setExpandedRec] = useState(null);
  const [expandedVendor, setExpandedVendor] = useState(null);
  const [vendorDetail, setVendorDetail] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [alertSummary, setAlertSummary] = useState(null);
  const [alertFilter, setAlertFilter] = useState(null); // severity filter
  const [showDismissed, setShowDismissed] = useState(false);

  // Part 7: filter from matching debug link
  const filterVendor = searchParams.get('vendor');
  const filterLabel = searchParams.get('label');
  const filterRef = searchParams.get('ref');
  const filterPattern = searchParams.get('pattern');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sumRes, patRes, venRes, timeRes, recRes, alertRes, alertSumRes] = await Promise.all([
        fetch(`${API}/api/label-corrections/summary`),
        fetch(`${API}/api/label-corrections/top-patterns`),
        fetch(`${API}/api/label-corrections/vendors`),
        fetch(`${API}/api/label-corrections/over-time`),
        fetch(`${API}/api/label-corrections/recommendations`),
        fetch(`${API}/api/alerts/active`),
        fetch(`${API}/api/alerts/summary`),
      ]);
      if (sumRes.ok) setSummary(await sumRes.json());
      if (patRes.ok) setPatterns((await patRes.json()).patterns || []);
      if (venRes.ok) setVendors(await venRes.json());
      if (timeRes.ok) setTimeline(await timeRes.json());
      if (recRes.ok) setRecommendations(await recRes.json());
      if (alertRes.ok) setAlerts(await alertRes.json());
      if (alertSumRes.ok) setAlertSummary(await alertSumRes.json());
    } catch { toast.error('Failed to load insights'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fetchVendorDetail = async (vendorId) => {
    if (expandedVendor === vendorId) { setExpandedVendor(null); setVendorDetail(null); return; }
    setExpandedVendor(vendorId);
    try {
      const res = await fetch(`${API}/api/label-corrections/vendor/${encodeURIComponent(vendorId)}`);
      if (res.ok) setVendorDetail(await res.json());
    } catch { /* silent */ }
  };

  const handleDismissAlert = async (patternKey) => {
    try {
      const res = await fetch(`${API}/api/alerts/${encodeURIComponent(patternKey)}/dismiss`, { method: 'POST' });
      if (res.ok) {
        toast.success('Alert dismissed');
        setAlerts(prev => prev.filter(a => a.pattern_key !== patternKey));
      }
    } catch { toast.error('Failed to dismiss'); }
  };

  const handleResolveAlert = async (patternKey) => {
    try {
      const res = await fetch(`${API}/api/alerts/${encodeURIComponent(patternKey)}/resolve`, { method: 'POST' });
      if (res.ok) {
        toast.success('Alert resolved');
        setAlerts(prev => prev.filter(a => a.pattern_key !== patternKey));
      }
    } catch { toast.error('Failed to resolve'); }
  };

  const handleTriggerEval = async () => {
    try {
      const res = await fetch(`${API}/api/alerts/evaluate`, { method: 'POST' });
      if (res.ok) {
        const result = await res.json();
        toast.success(`Evaluation complete: ${result.alerts_created} new, ${result.alerts_updated} updated`);
        await fetchData();
      }
    } catch { toast.error('Evaluation failed'); }
  };

  // Apply filters
  const filteredPatterns = patterns.filter(p => {
    if (filterLabel && p.predicted_label !== filterLabel) return false;
    if (filterVendor && !p.vendor_names?.some(v => v.toLowerCase().includes(filterVendor.toLowerCase()))) return false;
    if (filterPattern) {
      const pk = `${p.predicted_label}→${p.actual_entity_type}`;
      if (pk !== filterPattern && `${p.predicted_label}→${p.correct_label}` !== filterPattern) return false;
    }
    return true;
  });
  const filteredVendors = vendors.filter(v => {
    if (filterVendor && !v.vendor.toLowerCase().includes(filterVendor.toLowerCase())) return false;
    return true;
  });
  const filteredAlerts = alerts.filter(a => {
    if (alertFilter && a.severity_level !== alertFilter) return false;
    if (filterVendor && !a.affected_vendors?.some(v => v.toLowerCase().includes(filterVendor.toLowerCase()))) return false;
    if (filterPattern && a.pattern_key !== filterPattern) return false;
    return true;
  });

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const pieData = summary?.most_common_predicted_labels?.map((l, i) => ({
    name: l.label, value: l.count, fill: LABEL_COLORS[l.label] || CHART_COLORS[i % CHART_COLORS.length]
  })) || [];

  const entityBarData = summary?.most_common_actual_entities?.map(e => ({
    name: e.entity.replace('posted_', '').replace('_', ' '),
    full: e.entity,
    count: e.count,
  })) || [];

  return (
    <div className="space-y-6" data-testid="label-correction-insights-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}
            data-testid="insights-page-title">
            Label Correction Insights
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Analytics for reference label mislabeling patterns and extraction quality
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} data-testid="insights-refresh-btn">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
        </Button>
      </div>

      {/* Active Filters */}
      {(filterVendor || filterLabel || filterRef || filterPattern) && (
        <div className="flex items-center gap-2 text-xs" data-testid="insights-active-filters">
          <Filter className="w-3.5 h-3.5 text-muted-foreground" />
          <span className="text-muted-foreground">Filters:</span>
          {filterVendor && <Badge variant="outline">{filterVendor}</Badge>}
          {filterLabel && <Badge variant="outline">{filterLabel}</Badge>}
          {filterRef && <Badge variant="outline" className="font-mono">{filterRef}</Badge>}
          {filterPattern && <Badge variant="outline" className="font-mono">{filterPattern}</Badge>}
          <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]"
            onClick={() => navigate('/label-correction-insights')}>Clear</Button>
        </div>
      )}

      {/* Extraction Alert Panel (Part 4) */}
      {filteredAlerts.length > 0 && (
        <Card className="border-l-4 border-l-red-500/60" data-testid="extraction-alert-panel">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2"
                style={{ fontFamily: 'Chivo, sans-serif' }}>
                <ShieldAlert className="w-4 h-4 text-red-400" />
                Extraction Alerts
                {alertSummary?.total_active > 0 && (
                  <Badge className="bg-red-500/20 text-red-400 text-[10px]">{alertSummary.total_active} active</Badge>
                )}
              </CardTitle>
              <div className="flex items-center gap-1.5">
                {['critical', 'warning', 'info'].map(sev => (
                  <Button key={sev} variant={alertFilter === sev ? 'default' : 'ghost'} size="sm"
                    className={`h-6 px-2 text-[10px] ${alertFilter === sev ? '' : 'text-muted-foreground'}`}
                    onClick={() => setAlertFilter(alertFilter === sev ? null : sev)}
                    data-testid={`alert-filter-${sev}`}>
                    {sev}
                    {alertSummary?.[sev] > 0 && <span className="ml-1">({alertSummary[sev]})</span>}
                  </Button>
                ))}
                <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]" onClick={handleTriggerEval}
                  data-testid="alert-trigger-eval">
                  <RefreshCw className="w-3 h-3" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {filteredAlerts.map((alert, i) => {
              const sevConf = SEVERITY_CONFIG[alert.severity_level] || SEVERITY_CONFIG.low;
              const SevIcon = sevConf.icon;
              const TrendIcon = alert.trend === 'increasing' ? TrendingUp
                : alert.trend === 'decreasing' ? TrendingDown : Minus;
              const trendColor = alert.trend === 'increasing' ? 'text-red-400'
                : alert.trend === 'decreasing' ? 'text-emerald-400' : 'text-muted-foreground';
              return (
                <div key={alert.pattern_key} className="border border-border/50 rounded-md p-3 space-y-2"
                  data-testid={`alert-card-${i}`}>
                  <div className="flex items-center gap-3">
                    <SevIcon className="w-4 h-4 shrink-0" />
                    <Badge className={`${sevConf.color} text-[10px] shrink-0`}>{alert.severity_level}</Badge>
                    <span className="font-mono text-xs font-semibold">{alert.pattern_key}</span>
                    <div className="flex-1" />
                    <div className="flex items-center gap-1 text-[10px]">
                      <TrendIcon className={`w-3 h-3 ${trendColor}`} />
                      <span className={trendColor}>
                        {alert.trend} {alert.trend_pct !== 0 && `(${alert.trend_pct > 0 ? '+' : ''}${alert.trend_pct}%)`}
                      </span>
                    </div>
                  </div>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
                    <div>
                      <span className="text-muted-foreground text-[10px]">30-day count</span>
                      <div className="font-mono font-bold">{alert.occurrence_count_30d}</div>
                    </div>
                    <div>
                      <span className="text-muted-foreground text-[10px]">7-day count</span>
                      <div className="font-mono font-bold">{alert.occurrence_count_7d}</div>
                    </div>
                    <div>
                      <span className="text-muted-foreground text-[10px]">Vendors affected</span>
                      <div className="font-bold">{alert.affected_vendor_count}</div>
                    </div>
                    <div>
                      <span className="text-muted-foreground text-[10px]">
                        {alert.vendor_scope !== 'global' ? 'Vendor mislabel rate' : 'Avg score'}
                      </span>
                      <div className="font-mono font-bold">
                        {alert.vendor_mislabel_rate != null
                          ? `${(alert.vendor_mislabel_rate * 100).toFixed(0)}%`
                          : `${(alert.avg_match_score * 100).toFixed(0)}%`}
                      </div>
                    </div>
                  </div>
                  {alert.affected_vendors?.length > 0 && (
                    <div className="text-[10px] text-muted-foreground">
                      Vendors: {alert.affected_vendors.slice(0, 4).join(', ')}
                      {alert.affected_vendors.length > 4 && ` +${alert.affected_vendors.length - 4} more`}
                    </div>
                  )}
                  {alert.suggested_action && (
                    <div className="bg-amber-500/10 border border-amber-500/20 rounded p-2 text-xs text-muted-foreground">
                      <Lightbulb className="w-3 h-3 inline mr-1 text-amber-400" />
                      {alert.suggested_action}
                    </div>
                  )}
                  <div className="flex items-center gap-2 pt-1">
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px]"
                      onClick={() => navigate(`/label-correction-insights?pattern=${encodeURIComponent(alert.pattern_key)}`)}
                      data-testid={`alert-view-${i}`}>
                      <Eye className="w-3 h-3 mr-1" /> View Pattern
                    </Button>
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-muted-foreground"
                      onClick={() => handleDismissAlert(alert.pattern_key)}
                      data-testid={`alert-dismiss-${i}`}>
                      <BellOff className="w-3 h-3 mr-1" /> Dismiss
                    </Button>
                    <Button variant="ghost" size="sm" className="h-6 px-2 text-[10px] text-emerald-400"
                      onClick={() => handleResolveAlert(alert.pattern_key)}
                      data-testid={`alert-resolve-${i}`}>
                      <CheckCircle2 className="w-3 h-3 mr-1" /> Resolve
                    </Button>
                  </div>
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4" data-testid="insights-summary-cards">
        <Card>
          <CardContent className="pt-5 pb-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Target className="w-3.5 h-3.5" /> Total Corrections
            </div>
            <div className="text-3xl font-bold tracking-tight" data-testid="total-corrections-value">
              {summary?.total_corrections || 0}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">
              {summary?.corrections_last_7_days || 0} last 7d / {summary?.corrections_last_30_days || 0} last 30d
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <TrendingUp className="w-3.5 h-3.5" /> Label Accuracy
            </div>
            <div className="text-3xl font-bold tracking-tight" data-testid="label-accuracy-value">
              {summary?.label_accuracy_rate?.toFixed(1) || '100.0'}%
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">
              {summary?.unique_reference_values || 0} unique references
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <Users className="w-3.5 h-3.5" /> Vendors Impacted
            </div>
            <div className="text-3xl font-bold tracking-tight" data-testid="vendors-impacted-value">
              {summary?.vendors_impacted || 0}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">
              Across {filteredPatterns.length} pattern{filteredPatterns.length !== 1 ? 's' : ''}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-5 pb-4">
            <div className="flex items-center gap-2 text-muted-foreground text-xs mb-1">
              <AlertTriangle className="w-3.5 h-3.5" /> Top Mislabel
            </div>
            <div className="text-lg font-bold tracking-tight" data-testid="top-mislabel-value">
              {filteredPatterns[0]
                ? `${filteredPatterns[0].predicted_label} → ${filteredPatterns[0].correct_label}`
                : 'None'}
            </div>
            <div className="text-[10px] text-muted-foreground mt-1">
              {filteredPatterns[0]?.count || 0} occurrences
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Recommendations (Part 5+6) */}
      {recommendations.length > 0 && (
        <Card data-testid="insights-recommendations">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2"
              style={{ fontFamily: 'Chivo, sans-serif' }}>
              <Lightbulb className="w-4 h-4 text-amber-400" />
              Resolver Improvement Suggestions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {recommendations.map((rec, i) => {
              const sev = SEVERITY_CONFIG[rec.severity] || SEVERITY_CONFIG.low;
              const Icon = sev.icon;
              const isExpanded = expandedRec === i;
              return (
                <div key={i} className="border border-border/50 rounded-md overflow-hidden" data-testid={`recommendation-${i}`}>
                  <button
                    className="w-full flex items-center gap-3 p-3 text-left hover:bg-muted/30 transition-colors"
                    onClick={() => setExpandedRec(isExpanded ? null : i)}
                  >
                    <Icon className="w-4 h-4 shrink-0" />
                    <Badge className={`${sev.color} text-[10px] shrink-0`}>{rec.severity}</Badge>
                    <span className="font-mono text-xs font-semibold">{rec.pattern}</span>
                    <span className="text-xs text-muted-foreground">({rec.count}x)</span>
                    <div className="flex-1" />
                    {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                  </button>
                  {isExpanded && (
                    <div className="px-3 pb-3 space-y-2 text-xs border-t border-border/30 pt-2">
                      <p className="text-muted-foreground">{rec.recommendation}</p>
                      {rec.extraction_adjustment && (
                        <div className="bg-violet-500/10 border border-violet-500/20 rounded p-2">
                          <p className="text-violet-400 font-semibold text-[10px] mb-0.5">
                            Suggested Extraction Adjustment
                          </p>
                          <p className="text-muted-foreground">{rec.extraction_adjustment}</p>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </CardContent>
        </Card>
      )}

      {/* Charts Row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Mislabel by Label Type (Pie) */}
        <Card data-testid="insights-label-pie-chart">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground"
              style={{ fontFamily: 'Chivo, sans-serif' }}>
              Mislabel by Label Type
            </CardTitle>
          </CardHeader>
          <CardContent>
            {pieData.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <PieChart>
                  <Pie data={pieData} cx="50%" cy="50%" outerRadius={65} dataKey="value"
                    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    labelLine={false} fontSize={10}>
                    {pieData.map((e, i) => <Cell key={i} fill={e.fill} />)}
                  </Pie>
                  <Tooltip formatter={(v) => [v, 'Count']} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-muted-foreground text-center py-8">No data yet</p>
            )}
          </CardContent>
        </Card>

        {/* Entity Distribution (Bar) */}
        <Card data-testid="insights-entity-bar-chart">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground"
              style={{ fontFamily: 'Chivo, sans-serif' }}>
              Actual Entity Distribution
            </CardTitle>
          </CardHeader>
          <CardContent>
            {entityBarData.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={entityBarData}>
                  <XAxis dataKey="name" tick={{ fontSize: 9 }} angle={-20} textAnchor="end" height={50} />
                  <YAxis tick={{ fontSize: 9 }} width={30} />
                  <Tooltip formatter={(v) => [v, 'Count']} />
                  <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                    {entityBarData.map((e, i) => (
                      <Cell key={i} fill={ENTITY_COLORS[e.full] || CHART_COLORS[i % CHART_COLORS.length]} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-muted-foreground text-center py-8">No data yet</p>
            )}
          </CardContent>
        </Card>

        {/* Corrections Over Time (Line) */}
        <Card data-testid="insights-timeline-chart">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-bold uppercase tracking-wider text-muted-foreground"
              style={{ fontFamily: 'Chivo, sans-serif' }}>
              Corrections Over Time
            </CardTitle>
          </CardHeader>
          <CardContent>
            {timeline.length > 0 ? (
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={timeline}>
                  <XAxis dataKey="date" tick={{ fontSize: 9 }} />
                  <YAxis tick={{ fontSize: 9 }} width={25} />
                  <Tooltip />
                  <Line type="monotone" dataKey="count" stroke="#8b5cf6" strokeWidth={2}
                    dot={{ r: 3, fill: '#8b5cf6' }} />
                </LineChart>
              </ResponsiveContainer>
            ) : (
              <p className="text-xs text-muted-foreground text-center py-8">No timeline data</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Top Mislabel Patterns Table */}
      <Card data-testid="insights-patterns-table">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2"
            style={{ fontFamily: 'Chivo, sans-serif' }}>
            <BarChart3 className="w-4 h-4" />
            Top Mislabel Patterns
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredPatterns.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px]">Predicted Label</TableHead>
                  <TableHead className="text-[10px]"></TableHead>
                  <TableHead className="text-[10px]">Actual Entity</TableHead>
                  <TableHead className="text-[10px] text-right">Count</TableHead>
                  <TableHead className="text-[10px] text-right">%</TableHead>
                  <TableHead className="text-[10px] text-right">Vendors</TableHead>
                  <TableHead className="text-[10px]">Example References</TableHead>
                  <TableHead className="text-[10px]">Avg Score</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredPatterns.map((p, i) => (
                  <TableRow key={i} data-testid={`pattern-row-${i}`}>
                    <TableCell>
                      <Badge style={{ backgroundColor: `${LABEL_COLORS[p.predicted_label] || '#6b7280'}20`,
                        color: LABEL_COLORS[p.predicted_label] || '#6b7280' }}
                        className="text-[10px] font-mono">{p.predicted_label}</Badge>
                    </TableCell>
                    <TableCell><ArrowRight className="w-3 h-3 text-muted-foreground" /></TableCell>
                    <TableCell>
                      <Badge variant="outline" className="text-[10px] font-mono">{p.correct_label}</Badge>
                      <span className="text-[10px] text-muted-foreground ml-1">({p.actual_entity_type.replace('posted_', '').replace('_', ' ')})</span>
                    </TableCell>
                    <TableCell className="text-right font-mono font-bold">{p.count}</TableCell>
                    <TableCell className="text-right text-muted-foreground">{p.percentage}%</TableCell>
                    <TableCell className="text-right">{p.vendors_impacted}</TableCell>
                    <TableCell>
                      <div className="flex gap-1 flex-wrap">
                        {p.example_references.slice(0, 3).map((ref, j) => (
                          <span key={j} className="font-mono text-[10px] bg-muted/50 px-1 rounded">{ref}</span>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-[10px]">{(p.avg_score * 100).toFixed(0)}%</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-6">
              {patterns.length === 0 ? 'No corrections recorded yet. Patterns will appear as the resolver learns.' : 'No patterns match the current filter.'}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Vendor Correction Table */}
      <Card data-testid="insights-vendor-table">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold uppercase tracking-wider flex items-center gap-2"
            style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Users className="w-4 h-4" />
            Vendor Corrections
          </CardTitle>
        </CardHeader>
        <CardContent>
          {filteredVendors.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-[10px]">Vendor</TableHead>
                  <TableHead className="text-[10px] text-right">Corrections</TableHead>
                  <TableHead className="text-[10px]">Top Pattern</TableHead>
                  <TableHead className="text-[10px] text-right">Unique Refs</TableHead>
                  <TableHead className="text-[10px]">Avg Score</TableHead>
                  <TableHead className="text-[10px]">Last Seen</TableHead>
                  <TableHead className="text-[10px]"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredVendors.map((v, i) => (
                  <React.Fragment key={v.vendor}>
                    <TableRow data-testid={`vendor-row-${i}`}
                      className="cursor-pointer hover:bg-muted/30"
                      onClick={() => fetchVendorDetail(v.vendor)}>
                      <TableCell className="font-semibold text-xs">{v.vendor}</TableCell>
                      <TableCell className="text-right font-mono font-bold">{v.total_corrections}</TableCell>
                      <TableCell>
                        {v.top_pattern && (
                          <span className="font-mono text-[10px] bg-violet-500/10 text-violet-400 px-1.5 py-0.5 rounded">
                            {v.top_pattern}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="text-right">{v.unique_references}</TableCell>
                      <TableCell className="font-mono text-[10px]">{(v.avg_score * 100).toFixed(0)}%</TableCell>
                      <TableCell className="text-[10px] text-muted-foreground">{formatDate(v.latest)}</TableCell>
                      <TableCell>
                        {expandedVendor === v.vendor
                          ? <ChevronUp className="w-3.5 h-3.5" />
                          : <ChevronDown className="w-3.5 h-3.5" />}
                      </TableCell>
                    </TableRow>
                    {expandedVendor === v.vendor && vendorDetail && (
                      <TableRow key={`${v.vendor}-detail`}>
                        <TableCell colSpan={7} className="bg-muted/20 p-4">
                          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-3">
                            <div>
                              <span className="text-[10px] text-muted-foreground">Correction Rate</span>
                              <div className="font-bold text-sm">{vendorDetail.correction_rate || 0}%</div>
                            </div>
                            <div>
                              <span className="text-[10px] text-muted-foreground">Total Resolutions</span>
                              <div className="font-bold text-sm">{vendorDetail.total_resolutions || 0}</div>
                            </div>
                            <div>
                              <span className="text-[10px] text-muted-foreground">Stability</span>
                              <Badge className={vendorDetail.pattern_stability === 'stable'
                                ? 'bg-emerald-500/20 text-emerald-400' : 'bg-red-500/20 text-red-400'}
                                data-testid="vendor-stability-badge">
                                {vendorDetail.pattern_stability || 'N/A'}
                              </Badge>
                            </div>
                            <div>
                              <span className="text-[10px] text-muted-foreground">Unstable Labels</span>
                              <div className="text-sm">
                                {vendorDetail.unstable_labels?.length > 0
                                  ? vendorDetail.unstable_labels.join(', ')
                                  : <span className="text-muted-foreground">None</span>}
                              </div>
                            </div>
                          </div>
                          {vendorDetail.patterns?.length > 0 && (
                            <div>
                              <p className="text-[10px] text-muted-foreground font-semibold mb-1">Correction Patterns</p>
                              {vendorDetail.patterns.map((p, j) => (
                                <div key={j} className="flex items-center gap-2 py-0.5 text-xs">
                                  <Badge variant="outline" className="text-[10px]">{p.predicted_label}</Badge>
                                  <ArrowRight className="w-3 h-3 text-muted-foreground" />
                                  <Badge className="bg-violet-500/20 text-violet-400 text-[10px]">{p.correct_label}</Badge>
                                  <span className="text-muted-foreground">
                                    {p.count}x ({(p.frequency * 100).toFixed(0)}%) avg: {(p.avg_score * 100).toFixed(0)}%
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                          {vendorDetail.label_remaps && Object.keys(vendorDetail.label_remaps).length > 0 && (
                            <div className="mt-2 p-2 bg-violet-500/10 rounded">
                              <p className="text-violet-400 font-semibold text-[10px] mb-1">Active Label Remaps</p>
                              {Object.entries(vendorDetail.label_remaps).map(([from, info]) => (
                                <div key={from} className="flex items-center gap-2 text-[10px]">
                                  <span className="font-mono">{from}</span>
                                  <ArrowRight className="w-3 h-3" />
                                  <span className="font-mono text-violet-400">{info.remap_to}</span>
                                  <span className="text-muted-foreground">
                                    ({info.count}x, conf: {(info.confidence * 100).toFixed(0)}%)
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </TableCell>
                      </TableRow>
                    )}
                  </React.Fragment>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-xs text-muted-foreground text-center py-6">
              No vendor corrections recorded yet.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
