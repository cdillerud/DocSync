/**
 * PilotDashboardPage - Shadow Pilot Summary Dashboard
 * 
 * Comprehensive dashboard for monitoring the 14-day shadow pilot.
 * Shows:
 * - Summary cards with key metrics
 * - Trend chart of documents per day by doc_type
 * - Misclassification table
 * - Workflow stall table
 * - CSV export
 * - Send daily summary email button
 */

import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { 
  RefreshCw, Download, FileText, Brain, TrendingUp, 
  AlertTriangle, CheckCircle, Clock, BarChart3, Eye, Mail
} from 'lucide-react';

import {
  PILOT_CONFIG,
} from '@/lib/workflowConstants';
import {
  getPilotStatus,
  getPilotDailyMetrics,
  getPilotAccuracy,
  getPilotTrend,
  sendPilotSummaryEmail,
} from '@/lib/api';

// Summary card component
function MetricCard({ title, value, description, icon: Icon, color = 'bg-primary', trend }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <div className="flex items-center gap-2">
              <p className="text-2xl font-bold">{value}</p>
              {trend && (
                <Badge variant="outline" className={trend > 0 ? 'text-green-400' : 'text-muted-foreground'}>
                  {trend > 0 ? '+' : ''}{trend}%
                </Badge>
              )}
            </div>
            {description && <p className="text-xs text-muted-foreground mt-1">{description}</p>}
          </div>
          <div className={`p-3 rounded-lg ${color}`}>
            <Icon className="h-5 w-5 text-white" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

// Simple bar chart component
function SimpleBarChart({ data, docTypes }) {
  if (!data || data.length === 0) {
    return (
      <div className="h-64 flex items-center justify-center text-muted-foreground">
        <p>No data available</p>
      </div>
    );
  }

  // Get max value for scaling
  const maxValue = Math.max(
    ...data.map(d => 
      docTypes.reduce((sum, dt) => sum + (d[dt] || 0), 0)
    )
  );

  // Color map for doc types
  const colorMap = {
    AP_INVOICE: 'bg-blue-500',
    SALES_INVOICE: 'bg-green-500',
    PURCHASE_ORDER: 'bg-purple-500',
    QUALITY_DOC: 'bg-orange-500',
    STATEMENT: 'bg-yellow-500',
    OTHER: 'bg-gray-500',
  };

  return (
    <div className="space-y-4">
      {/* Legend */}
      <div className="flex flex-wrap gap-3">
        {docTypes.map(dt => (
          <div key={dt} className="flex items-center gap-2 text-sm">
            <div className={`w-3 h-3 rounded ${colorMap[dt] || 'bg-gray-500'}`} />
            <span className="text-muted-foreground">{dt}</span>
          </div>
        ))}
      </div>

      {/* Chart */}
      <div className="h-64 flex items-end gap-1 overflow-x-auto pb-6">
        {data.slice(-14).map((d, idx) => {
          const total = docTypes.reduce((sum, dt) => sum + (d[dt] || 0), 0);
          const height = maxValue > 0 ? (total / maxValue) * 100 : 0;
          
          return (
            <div key={idx} className="flex-1 min-w-[40px] flex flex-col items-center">
              <div 
                className="w-full flex flex-col-reverse rounded-t"
                style={{ height: `${Math.max(height, 2)}%` }}
              >
                {docTypes.map((dt, i) => {
                  const value = d[dt] || 0;
                  const segmentHeight = total > 0 ? (value / total) * 100 : 0;
                  return (
                    <div
                      key={dt}
                      className={`w-full ${colorMap[dt] || 'bg-gray-500'} ${i === 0 ? 'rounded-b' : ''} ${i === docTypes.length - 1 ? 'rounded-t' : ''}`}
                      style={{ height: `${segmentHeight}%` }}
                      title={`${dt}: ${value}`}
                    />
                  );
                })}
              </div>
              <span className="text-xs text-muted-foreground mt-2 -rotate-45 origin-left whitespace-nowrap">
                {d.date?.slice(5) || ''}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function PilotDashboardPage() {
  const [loading, setLoading] = useState(false);
  const [pilotStatus, setPilotStatus] = useState(null);
  const [dailyMetrics, setDailyMetrics] = useState(null);
  const [accuracyReport, setAccuracyReport] = useState(null);
  const [trendData, setTrendData] = useState(null);
  const [stuckDocuments, setStuckDocuments] = useState([]);
  const [selectedDays, setSelectedDays] = useState('14');

  const fetchAllData = useCallback(async () => {
    setLoading(true);
    try {
      const [statusRes, metricsRes, accuracyRes, trendRes] = await Promise.all([
        getPilotStatus(),
        getPilotDailyMetrics(PILOT_CONFIG.CURRENT_PHASE),
        getPilotAccuracy(PILOT_CONFIG.CURRENT_PHASE),
        getPilotTrend(PILOT_CONFIG.CURRENT_PHASE, parseInt(selectedDays)),
      ]);

      setPilotStatus(statusRes.data);
      setDailyMetrics(metricsRes.data);
      setAccuracyReport(accuracyRes.data);
      setTrendData(trendRes.data);

      // Extract stuck documents from metrics
      if (metricsRes.data?.stuck_documents?.by_status) {
        const stuck = [];
        for (const [status, count] of Object.entries(metricsRes.data.stuck_documents.by_status)) {
          if (count > 0) {
            stuck.push({ status, count });
          }
        }
        setStuckDocuments(stuck);
      }
    } catch (err) {
      console.error('Failed to fetch pilot data:', err);
      toast.error('Failed to load pilot data');
    }
    setLoading(false);
  }, [selectedDays]);

  useEffect(() => {
    fetchAllData();
  }, [fetchAllData]);

  const handleExportCSV = () => {
    if (!dailyMetrics) return;

    // Build CSV content
    const rows = [
      ['Metric', 'Value'],
      ['Phase', dailyMetrics.phase],
      ['Total Documents', dailyMetrics.summary?.total_documents],
      ['Deterministic Classified', dailyMetrics.summary?.deterministic_classified],
      ['AI Classified', dailyMetrics.summary?.ai_classified],
      ['AI Usage Rate', `${dailyMetrics.summary?.ai_usage_rate?.toFixed(1)}%`],
      ['Vendor Extraction Rate', `${dailyMetrics.summary?.vendor_extraction_rate?.toFixed(1)}%`],
      ['Export Rate', `${dailyMetrics.summary?.export_rate?.toFixed(1)}%`],
      [''],
      ['Doc Type', 'Count'],
      ...Object.entries(dailyMetrics.by_doc_type || {}).map(([dt, count]) => [dt, count]),
      [''],
      ['Stuck Status', 'Count'],
      ...Object.entries(dailyMetrics.stuck_documents?.by_status || {}).map(([status, count]) => [status, count]),
    ];

    const csvContent = rows.map(row => row.join(',')).join('\n');
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pilot_metrics_${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    toast.success('CSV exported');
  };

  const [sendingEmail, setSendingEmail] = useState(false);
  
  const handleSendSummaryEmail = async () => {
    setSendingEmail(true);
    try {
      const res = await sendPilotSummaryEmail();
      if (res.data.sent) {
        toast.success(`Daily summary email sent to ${res.data.recipients?.length || 0} recipients`);
      } else {
        toast.error(`Email not sent: ${res.data.reason || 'Unknown error'}`);
      }
    } catch (err) {
      console.error('Failed to send summary email:', err);
      toast.error(err.response?.data?.detail || 'Failed to send summary email');
    }
    setSendingEmail(false);
  };

  const summary = dailyMetrics?.summary || {};
  const byDocType = dailyMetrics?.by_doc_type || {};

  return (
    <div className="space-y-6" data-testid="pilot-dashboard-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Pilot Dashboard</h1>
            <Badge variant="outline" className="bg-blue-500/20 text-blue-400 border-blue-500/30">
              {PILOT_CONFIG.CURRENT_PHASE}
            </Badge>
          </div>
          <p className="text-muted-foreground">
            Shadow pilot: {PILOT_CONFIG.START_DATE} to {PILOT_CONFIG.END_DATE}
          </p>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleExportCSV} variant="outline" disabled={!dailyMetrics}>
            <Download className="mr-2 h-4 w-4" /> Export CSV
          </Button>
          <Button onClick={fetchAllData} variant="outline" disabled={loading}>
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>
      </div>

      {/* Pilot Status Banner */}
      {pilotStatus && (
        <Card className={pilotStatus.pilot_mode_enabled ? 'border-blue-500/30 bg-blue-500/5' : 'border-gray-500/30'}>
          <CardContent className="p-4 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <Eye className={`h-5 w-5 ${pilotStatus.pilot_mode_enabled ? 'text-blue-400' : 'text-gray-400'}`} />
              <div>
                <p className="font-medium">{pilotStatus.pilot_mode_enabled ? 'Pilot Mode Active' : 'Pilot Mode Disabled'}</p>
                <p className="text-sm text-muted-foreground">
                  {pilotStatus.pilot_mode_enabled 
                    ? 'External writes blocked • Read-only validation mode'
                    : 'Normal operation mode'
                  }
                </p>
              </div>
            </div>
            <div className="flex gap-4 text-sm">
              <span>Exports: <Badge variant={pilotStatus.exports_blocked ? 'destructive' : 'secondary'}>{pilotStatus.exports_blocked ? 'Blocked' : 'Enabled'}</Badge></span>
              <span>BC Validation: <Badge variant={pilotStatus.bc_validation_blocked ? 'destructive' : 'secondary'}>{pilotStatus.bc_validation_blocked ? 'Blocked' : 'Enabled'}</Badge></span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <MetricCard
          title="Total Pilot Docs"
          value={summary.total_documents?.toLocaleString() || 0}
          icon={FileText}
          color="bg-blue-500"
        />
        <MetricCard
          title="Accuracy Score"
          value={`${accuracyReport?.accuracy_score?.toFixed(1) || 100}%`}
          description={`${accuracyReport?.corrected_documents || 0} corrected`}
          icon={CheckCircle}
          color="bg-green-500"
        />
        <MetricCard
          title="AI Usage Rate"
          value={`${summary.ai_usage_rate?.toFixed(1) || 0}%`}
          description={`${summary.ai_classified || 0} AI classified`}
          icon={Brain}
          color="bg-purple-500"
        />
        <MetricCard
          title="Vendor Extraction"
          value={`${summary.vendor_extraction_rate?.toFixed(1) || 0}%`}
          description="AP vendor detection"
          icon={TrendingUp}
          color="bg-emerald-500"
        />
        <MetricCard
          title="Stuck Documents"
          value={dailyMetrics?.stuck_documents?.total || 0}
          description=">24h in status"
          icon={AlertTriangle}
          color={dailyMetrics?.stuck_documents?.total > 0 ? 'bg-red-500' : 'bg-gray-500'}
        />
      </div>

      {/* Document Type Breakdown */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Documents by Type</CardTitle>
          <CardDescription>Pilot ingestion breakdown by document classification</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
            {Object.entries(byDocType).map(([docType, count]) => (
              <div key={docType} className="p-4 rounded-lg bg-muted">
                <p className="text-xs text-muted-foreground">{docType}</p>
                <p className="text-xl font-bold">{count.toLocaleString()}</p>
              </div>
            ))}
            {Object.keys(byDocType).length === 0 && (
              <p className="col-span-5 text-center text-muted-foreground py-8">
                No pilot documents ingested yet
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Trend Chart */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>Daily Trend</CardTitle>
              <CardDescription>Documents ingested per day by type</CardDescription>
            </div>
            <Select value={selectedDays} onValueChange={setSelectedDays}>
              <SelectTrigger className="w-32">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="7">Last 7 days</SelectItem>
                <SelectItem value="14">Last 14 days</SelectItem>
                <SelectItem value="30">Last 30 days</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <SimpleBarChart 
            data={trendData?.trend || []} 
            docTypes={trendData?.doc_types || []}
          />
        </CardContent>
      </Card>

      {/* Two Column Layout for Tables */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Stuck Documents */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Clock className="h-5 w-5" />
              Workflow Stalls
            </CardTitle>
            <CardDescription>Documents in actionable status {">"} 24 hours</CardDescription>
          </CardHeader>
          <CardContent>
            {stuckDocuments.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Count</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {stuckDocuments.map((item) => (
                    <TableRow key={item.status}>
                      <TableCell>
                        <Badge variant="outline" className="text-red-400 border-red-500/30">
                          {item.status}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right font-mono">{item.count}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <CheckCircle className="mx-auto h-8 w-8 mb-2 text-green-400" />
                <p>No stuck documents</p>
              </div>
            )}
          </CardContent>
        </Card>

        {/* Misclassifications */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="h-5 w-5" />
              Misclassifications
            </CardTitle>
            <CardDescription>Documents requiring manual correction</CardDescription>
          </CardHeader>
          <CardContent>
            {accuracyReport?.corrections?.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Document</TableHead>
                    <TableHead>Original</TableHead>
                    <TableHead>Corrected</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {accuracyReport.corrections.slice(0, 10).map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-xs">{item.id?.slice(0, 8)}...</TableCell>
                      <TableCell>
                        <Badge variant="outline">{item.original_doc_type || '-'}</Badge>
                      </TableCell>
                      <TableCell>
                        <Badge>{item.corrected_doc_type || '-'}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <div className="text-center py-8 text-muted-foreground">
                <CheckCircle className="mx-auto h-8 w-8 mb-2 text-green-400" />
                <p>No misclassifications detected</p>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Time in Status Distribution */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Time in Status Distribution
          </CardTitle>
          <CardDescription>How long documents spend in each status bucket</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 md:grid-cols-7 gap-3">
            {Object.entries(accuracyReport?.time_in_status_distribution || {}).map(([bucket, count]) => (
              <div key={bucket} className="p-3 rounded-lg bg-muted text-center">
                <p className="text-xs text-muted-foreground">{bucket}</p>
                <p className="text-lg font-bold">{count}</p>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
