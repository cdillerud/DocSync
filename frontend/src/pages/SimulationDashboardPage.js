import React, { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '../components/ui/sheet';
import { ScrollArea } from '../components/ui/scroll-area';
import { Separator } from '../components/ui/separator';
import { toast } from 'sonner';
import { 
  RefreshCw, CheckCircle, XCircle, AlertTriangle, BarChart3, 
  FileText, Building2, GitBranch, Clock, ArrowRight, Play,
  ChevronRight, Eye, X
} from 'lucide-react';
import api from '../lib/api';
import DocumentDetailPanel from '../components/DocumentDetailPanel';

export default function SimulationDashboardPage() {
  const [metrics, setMetrics] = useState(null);
  const [trend, setTrend] = useState(null);
  const [failureDetails, setFailureDetails] = useState(null);
  const [pendingDocs, setPendingDocs] = useState(null);
  const [loading, setLoading] = useState(true);
  const [runningBatch, setRunningBatch] = useState(false);
  
  // Filters
  const [selectedDocType, setSelectedDocType] = useState('all');
  const [selectedFailureReason, setSelectedFailureReason] = useState('all');
  const [days, setDays] = useState(14);

  // Drill-down state
  const [drillDownOpen, setDrillDownOpen] = useState(false);
  const [drillDownTitle, setDrillDownTitle] = useState('');
  const [drillDownType, setDrillDownType] = useState(''); // 'failures', 'successes', 'doc_type', 'source_system'
  const [drillDownFilter, setDrillDownFilter] = useState({});
  const [drillDownData, setDrillDownData] = useState([]);
  const [drillDownLoading, setDrillDownLoading] = useState(false);
  
  // Document detail panel state
  const [selectedDocument, setSelectedDocument] = useState(null);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);

  const fetchMetrics = useCallback(async () => {
    try {
      const params = new URLSearchParams({ days: days.toString() });
      if (selectedDocType !== 'all') {
        params.append('doc_type', selectedDocType);
      }
      
      const response = await api.get(`/pilot/simulation/metrics?${params}`);
      setMetrics(response.data);
    } catch (error) {
      console.error('Failed to fetch metrics:', error);
    }
  }, [days, selectedDocType]);

  const fetchTrend = useCallback(async () => {
    try {
      const response = await api.get(`/pilot/simulation/metrics/trend?days=${days}`);
      setTrend(response.data);
    } catch (error) {
      console.error('Failed to fetch trend:', error);
    }
  }, [days]);

  const fetchFailureDetails = useCallback(async () => {
    try {
      const params = new URLSearchParams({ limit: '20' });
      if (selectedFailureReason !== 'all') {
        params.append('failure_reason', selectedFailureReason);
      }
      if (selectedDocType !== 'all') {
        params.append('doc_type', selectedDocType);
      }
      
      const response = await api.get(`/pilot/simulation/metrics/failures?${params}`);
      setFailureDetails(response.data);
    } catch (error) {
      console.error('Failed to fetch failure details:', error);
    }
  }, [selectedFailureReason, selectedDocType]);

  const fetchPendingDocs = useCallback(async () => {
    try {
      const response = await api.get('/pilot/simulation/metrics/pending?limit=10');
      setPendingDocs(response.data);
    } catch (error) {
      console.error('Failed to fetch pending docs:', error);
    }
  }, []);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    await Promise.all([
      fetchMetrics(),
      fetchTrend(),
      fetchFailureDetails(),
      fetchPendingDocs()
    ]);
    setLoading(false);
  }, [fetchMetrics, fetchTrend, fetchFailureDetails, fetchPendingDocs]);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  const runBatchSimulation = async (docType) => {
    setRunningBatch(true);
    try {
      const response = await api.post(`/pilot/simulation/batch?doc_type=${docType}&limit=50`);
      toast.success(`Simulated ${response.data.documents_processed} documents`);
      fetchAll();
    } catch (error) {
      toast.error('Failed to run batch simulation');
    } finally {
      setRunningBatch(false);
    }
  };

  const runSingleSimulation = async (docId) => {
    try {
      await api.post(`/pilot/simulation/document/${docId}/run`);
      toast.success('Simulation complete');
      fetchAll();
    } catch (error) {
      toast.error('Failed to run simulation');
    }
  };

  // Drill-down functions
  const openDrillDown = async (type, filter, title) => {
    setDrillDownType(type);
    setDrillDownFilter(filter);
    setDrillDownTitle(title);
    setDrillDownOpen(true);
    setDrillDownLoading(true);
    
    try {
      let response;
      const params = new URLSearchParams({ limit: '100' });
      
      if (type === 'failures') {
        if (filter.failure_reason) params.append('failure_reason', filter.failure_reason);
        if (filter.doc_type) params.append('doc_type', filter.doc_type);
        response = await api.get(`/pilot/simulation/metrics/failures?${params}`);
        setDrillDownData(response.data.failures || []);
      } else if (type === 'successes') {
        if (filter.doc_type) params.append('doc_type', filter.doc_type);
        response = await api.get(`/pilot/simulation/metrics/successes?${params}`);
        setDrillDownData(response.data.successes || []);
      } else if (type === 'doc_type_failures') {
        params.append('doc_type', filter.doc_type);
        response = await api.get(`/pilot/simulation/metrics/failures?${params}`);
        setDrillDownData(response.data.failures || []);
      } else if (type === 'doc_type_successes') {
        params.append('doc_type', filter.doc_type);
        response = await api.get(`/pilot/simulation/metrics/successes?${params}`);
        setDrillDownData(response.data.successes || []);
      }
    } catch (error) {
      console.error('Failed to fetch drill-down data:', error);
      toast.error('Failed to load details');
    } finally {
      setDrillDownLoading(false);
    }
  };

  const openDocumentDetail = async (docId) => {
    try {
      const response = await api.get(`/documents/${docId}`);
      setSelectedDocument(response.data);
      setDetailPanelOpen(true);
    } catch (error) {
      console.error('Failed to fetch document:', error);
      toast.error('Failed to load document details');
    }
  };

  const closeDrillDown = () => {
    setDrillDownOpen(false);
    setDrillDownData([]);
    setDrillDownType('');
    setDrillDownFilter({});
  };

  const successRate = metrics?.success_rate || 0;
  const successColor = successRate >= 80 ? 'text-green-500' : successRate >= 50 ? 'text-yellow-500' : 'text-red-500';

  return (
    <div className="space-y-6" data-testid="simulation-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Simulation Dashboard</h1>
          <p className="text-muted-foreground">
            Phase 2 Shadow Pilot • Read-only BC simulation results
          </p>
        </div>
        <div className="flex gap-2">
          <Select value={days.toString()} onValueChange={(v) => setDays(parseInt(v))}>
            <SelectTrigger className="w-[140px]" data-testid="days-filter">
              <SelectValue placeholder="Period" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="7">Last 7 days</SelectItem>
              <SelectItem value="14">Last 14 days</SelectItem>
              <SelectItem value="30">Last 30 days</SelectItem>
            </SelectContent>
          </Select>
          <Button onClick={fetchAll} variant="outline" disabled={loading} data-testid="refresh-btn">
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Global Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card data-testid="total-simulations-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Total Simulations
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold">{metrics?.total_simulations || 0}</div>
            <p className="text-xs text-muted-foreground">
              {metrics?.total_simulated_docs || 0} unique documents
            </p>
          </CardContent>
        </Card>

        <Card data-testid="success-rate-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Success Rate
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className={`text-3xl font-bold ${successColor}`}>
              {successRate}%
            </div>
            <p className="text-xs text-muted-foreground">
              Would succeed in production
            </p>
          </CardContent>
        </Card>

        <Card data-testid="success-count-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-green-500" />
              Would Succeed
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-green-500">{metrics?.success_count || 0}</div>
          </CardContent>
        </Card>

        <Card data-testid="failure-count-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2">
              <XCircle className="h-4 w-4 text-red-500" />
              Would Fail
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-3xl font-bold text-red-500">{metrics?.failure_count || 0}</div>
          </CardContent>
        </Card>
      </div>

      {/* Breakdown Section */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* By Doc Type */}
        <Card data-testid="by-doc-type-card">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <FileText className="h-4 w-4" />
              By Document Type
            </CardTitle>
            <CardDescription>Click to view documents</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {metrics?.by_doc_type && Object.entries(metrics.by_doc_type).map(([type, data]) => (
                <div key={type} className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/50 transition-colors">
                  <span className="text-sm font-medium">{type}</span>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 bg-green-500/10 text-green-500 hover:bg-green-500/20"
                      onClick={() => openDrillDown('doc_type_successes', { doc_type: type }, `${type} - Would Succeed`)}
                      data-testid={`drill-${type}-success`}
                    >
                      {data.success} ✓
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 bg-red-500/10 text-red-500 hover:bg-red-500/20"
                      onClick={() => openDrillDown('doc_type_failures', { doc_type: type }, `${type} - Would Fail`)}
                      data-testid={`drill-${type}-failure`}
                    >
                      {data.failure} ✗
                    </Button>
                  </div>
                </div>
              ))}
              {(!metrics?.by_doc_type || Object.keys(metrics.by_doc_type).length === 0) && (
                <p className="text-sm text-muted-foreground">No data yet</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* By Failure Reason */}
        <Card data-testid="by-failure-reason-card">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" />
              By Failure Reason
            </CardTitle>
            <CardDescription>Click to view failed documents</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {metrics?.by_failure_reason && Object.entries(metrics.by_failure_reason)
                .sort((a, b) => b[1] - a[1])
                .map(([reason, count]) => (
                  <div 
                    key={reason} 
                    className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/50 cursor-pointer transition-colors"
                    onClick={() => openDrillDown('failures', { failure_reason: reason }, `Failed: ${reason.replace(/_/g, ' ')}`)}
                    data-testid={`drill-reason-${reason}`}
                  >
                    <span className="text-sm font-medium truncate max-w-[160px]" title={reason}>
                      {reason.replace(/_/g, ' ')}
                    </span>
                    <div className="flex items-center gap-2">
                      <Badge variant="destructive">{count}</Badge>
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </div>
                  </div>
                ))}
              {(!metrics?.by_failure_reason || Object.keys(metrics.by_failure_reason).length === 0) && (
                <p className="text-sm text-muted-foreground">No failures</p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* By Source System */}
        <Card data-testid="by-source-system-card">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Building2 className="h-4 w-4" />
              By Source System
            </CardTitle>
            <CardDescription>Click to filter by source</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {metrics?.by_source_system && Object.entries(metrics.by_source_system).map(([source, data]) => (
                <div key={source} className="flex items-center justify-between p-2 rounded-lg hover:bg-muted/50 transition-colors">
                  <span className="text-sm font-medium">{source || 'Unknown'}</span>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="bg-green-500/10 text-green-500">
                      {data.success} ✓
                    </Badge>
                    <Badge variant="outline" className="bg-red-500/10 text-red-500">
                      {data.failure} ✗
                    </Badge>
                  </div>
                </div>
              ))}
              {(!metrics?.by_source_system || Object.keys(metrics.by_source_system).length === 0) && (
                <p className="text-sm text-muted-foreground">No data yet</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Trend and Details Section */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Trend Chart (Simple Bar Representation) */}
        <Card data-testid="trend-card">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <BarChart3 className="h-4 w-4" />
              Simulation Trend
            </CardTitle>
            <CardDescription>Daily success/failure over time</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {trend?.trend?.slice(-7).map((day) => {
                const total = day.success + day.failure;
                const successPct = total > 0 ? (day.success / total) * 100 : 0;
                return (
                  <div key={day.date} className="flex items-center gap-2">
                    <span className="text-xs w-20 text-muted-foreground">{day.date.slice(5)}</span>
                    <div className="flex-1 h-4 bg-muted rounded overflow-hidden flex">
                      <div 
                        className="h-full bg-green-500" 
                        style={{ width: `${successPct}%` }}
                      />
                      <div 
                        className="h-full bg-red-500" 
                        style={{ width: `${100 - successPct}%` }}
                      />
                    </div>
                    <span className="text-xs w-12 text-right">{total}</span>
                  </div>
                );
              })}
              {(!trend?.trend || trend.trend.length === 0) && (
                <p className="text-sm text-muted-foreground text-center py-4">
                  No trend data available
                </p>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Workflow Status Breakdown */}
        <Card data-testid="by-workflow-status-card">
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <GitBranch className="h-4 w-4" />
              By Workflow Status
            </CardTitle>
            <CardDescription>Simulation results by document workflow state</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-3 max-h-[200px] overflow-y-auto">
              {metrics?.by_workflow_status && Object.entries(metrics.by_workflow_status)
                .sort((a, b) => b[1].total - a[1].total)
                .map(([status, data]) => (
                  <div key={status} className="flex items-center justify-between">
                    <Badge variant="outline" className="truncate max-w-[150px]">
                      {status}
                    </Badge>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-green-500">{data.success}</span>
                      <span className="text-xs text-muted-foreground">/</span>
                      <span className="text-xs text-red-500">{data.failure}</span>
                    </div>
                  </div>
                ))}
              {(!metrics?.by_workflow_status || Object.keys(metrics.by_workflow_status).length === 0) && (
                <p className="text-sm text-muted-foreground">No data yet</p>
              )}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Failed Simulations Detail */}
      <Card data-testid="failure-details-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <XCircle className="h-4 w-4 text-red-500" />
                Recent Failed Simulations
              </CardTitle>
              <CardDescription>Documents that would fail if exported to BC</CardDescription>
            </div>
            <Select value={selectedFailureReason} onValueChange={setSelectedFailureReason}>
              <SelectTrigger className="w-[200px]" data-testid="failure-reason-filter">
                <SelectValue placeholder="Filter by reason" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Reasons</SelectItem>
                <SelectItem value="MISSING_FILE_URL">Missing File URL</SelectItem>
                <SelectItem value="MISSING_VENDOR">Missing Vendor</SelectItem>
                <SelectItem value="MISSING_CUSTOMER">Missing Customer</SelectItem>
                <SelectItem value="MISSING_REQUIRED_FIELDS">Missing Fields</SelectItem>
                <SelectItem value="VENDOR_NOT_FOUND">Vendor Not Found</SelectItem>
                <SelectItem value="OTHER">Other</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {failureDetails?.failures?.map((failure) => (
              <div 
                key={`${failure.document_id}-${failure.simulation_type}`}
                className="flex items-center justify-between p-3 bg-muted/50 rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <Badge variant="outline">{failure.doc_type || 'Unknown'}</Badge>
                  <span className="text-sm font-mono text-muted-foreground">
                    {failure.document_id?.slice(0, 8)}...
                  </span>
                  <Badge variant="destructive" className="text-xs">
                    {failure.failure_reason_code}
                  </Badge>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground">
                    {failure.simulation_type}
                  </span>
                  <Button 
                    size="sm" 
                    variant="ghost"
                    onClick={() => runSingleSimulation(failure.document_id)}
                  >
                    <Play className="h-3 w-3" />
                  </Button>
                </div>
              </div>
            ))}
            {(!failureDetails?.failures || failureDetails.failures.length === 0) && (
              <p className="text-sm text-muted-foreground text-center py-4">
                No failed simulations found
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Pending Documents */}
      <Card data-testid="pending-docs-card">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle className="text-base flex items-center gap-2">
                <Clock className="h-4 w-4" />
                Documents Pending Simulation
              </CardTitle>
              <CardDescription>
                {pendingDocs?.total_needing_simulation || 0} documents haven't been simulated yet
              </CardDescription>
            </div>
            <Button 
              onClick={() => runBatchSimulation('AP_INVOICE')}
              disabled={runningBatch}
              data-testid="run-batch-btn"
            >
              {runningBatch ? (
                <RefreshCw className="mr-2 h-4 w-4 animate-spin" />
              ) : (
                <Play className="mr-2 h-4 w-4" />
              )}
              Run Batch Simulation
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {pendingDocs?.documents?.map((doc) => (
              <div 
                key={doc.id}
                className="flex items-center justify-between p-3 bg-muted/50 rounded-lg"
              >
                <div className="flex items-center gap-3">
                  <Badge variant="outline">{doc.doc_type || 'Unknown'}</Badge>
                  <span className="text-sm font-mono text-muted-foreground">
                    {doc.id?.slice(0, 8)}...
                  </span>
                  <Badge variant="secondary">{doc.workflow_status}</Badge>
                </div>
                <Button 
                  size="sm" 
                  variant="outline"
                  onClick={() => runSingleSimulation(doc.id)}
                >
                  <ArrowRight className="h-4 w-4" />
                </Button>
              </div>
            ))}
            {(!pendingDocs?.documents || pendingDocs.documents.length === 0) && (
              <p className="text-sm text-muted-foreground text-center py-4">
                All documents have been simulated
              </p>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Footer Info */}
      <div className="text-center text-sm text-muted-foreground">
        <p>
          Last updated: {metrics?.generated_at ? new Date(metrics.generated_at).toLocaleString() : 'Never'}
          {' • '}
          Data from last {days} days
          {' • '}
          <span className="text-yellow-500">READ-ONLY: No real BC writes</span>
        </p>
      </div>

      {/* Drill-Down Sheet */}
      <Sheet open={drillDownOpen} onOpenChange={setDrillDownOpen}>
        <SheetContent className="w-[600px] sm:max-w-[600px]" data-testid="drill-down-sheet">
          <SheetHeader>
            <SheetTitle className="flex items-center gap-2">
              {drillDownType.includes('success') ? (
                <CheckCircle className="h-5 w-5 text-green-500" />
              ) : (
                <XCircle className="h-5 w-5 text-red-500" />
              )}
              {drillDownTitle}
            </SheetTitle>
            <SheetDescription>
              {drillDownData.length} documents • Click a row to view details
            </SheetDescription>
          </SheetHeader>
          
          <ScrollArea className="h-[calc(100vh-150px)] mt-4">
            {drillDownLoading ? (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="h-6 w-6 animate-spin text-muted-foreground" />
              </div>
            ) : (
              <div className="space-y-2 pr-4">
                {drillDownData.map((item, index) => (
                  <div
                    key={`${item.document_id}-${index}`}
                    className="p-3 border rounded-lg hover:bg-muted/50 cursor-pointer transition-colors"
                    onClick={() => openDocumentDetail(item.document_id)}
                    data-testid={`drill-item-${index}`}
                  >
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline">{item.doc_type || 'Unknown'}</Badge>
                        <span className="text-sm font-mono text-muted-foreground">
                          {item.document_id?.slice(0, 12)}...
                        </span>
                      </div>
                      <Button variant="ghost" size="sm">
                        <Eye className="h-4 w-4" />
                      </Button>
                    </div>
                    
                    <div className="flex flex-wrap gap-2 text-xs">
                      {item.workflow_status && (
                        <Badge variant="secondary">{item.workflow_status}</Badge>
                      )}
                      {item.source_system && (
                        <Badge variant="outline">{item.source_system}</Badge>
                      )}
                      {item.simulation_type && (
                        <span className="text-muted-foreground">{item.simulation_type}</span>
                      )}
                    </div>
                    
                    {item.failure_reason_code && (
                      <div className="mt-2">
                        <Badge variant="destructive" className="text-xs">
                          {item.failure_reason_code.replace(/_/g, ' ')}
                        </Badge>
                      </div>
                    )}
                    
                    {item.simulated_bc_number && (
                      <div className="mt-2 text-xs text-muted-foreground">
                        Simulated BC #: {item.simulated_bc_number}
                      </div>
                    )}
                    
                    {(item.vendor || item.customer || item.invoice) && (
                      <div className="mt-2 flex gap-4 text-xs text-muted-foreground">
                        {item.vendor && <span>Vendor: {item.vendor}</span>}
                        {item.customer && <span>Customer: {item.customer}</span>}
                        {item.invoice && <span>Invoice: {item.invoice}</span>}
                      </div>
                    )}
                  </div>
                ))}
                
                {drillDownData.length === 0 && (
                  <p className="text-center text-muted-foreground py-8">
                    No documents found
                  </p>
                )}
              </div>
            )}
          </ScrollArea>
        </SheetContent>
      </Sheet>

      {/* Document Detail Panel */}
      <Sheet open={detailPanelOpen} onOpenChange={setDetailPanelOpen}>
        <SheetContent className="w-[700px] sm:max-w-[700px] p-0" data-testid="document-detail-sheet">
          {selectedDocument && (
            <DocumentDetailPanel
              document={selectedDocument}
              onClose={() => setDetailPanelOpen(false)}
              onUpdate={(updated) => {
                setSelectedDocument(updated);
                fetchAll();
              }}
            />
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
