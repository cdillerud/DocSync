/**
 * SalesWorkflowsPage - Sales/AR Document Workflow Observation
 * 
 * Shadow pilot observation page for SALES_INVOICE documents.
 * This page is read-only during the pilot - no mutation actions.
 */

import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { toast } from 'sonner';
import { 
  RefreshCw, Filter, ShoppingCart, Receipt, TrendingUp, 
  Users, Search, Eye, AlertTriangle
} from 'lucide-react';

import { WorkflowQueue } from '@/components/WorkflowQueue';
import { DocumentDetailPanel } from '@/components/DocumentDetailPanel';
import {
  DOC_TYPES,
  SALES_WORKFLOW_STATUSES,
  SALES_QUEUE_CONFIG,
  SALES_PRIMARY_QUEUES,
  SALES_SECONDARY_QUEUES,
  SOURCE_SYSTEMS,
  SOURCE_SYSTEM_LABELS,
  getQueueConfig,
  PILOT_CONFIG,
} from '@/lib/workflowConstants';
import { getGenericQueue, getPilotStatus } from '@/lib/api';

// Summary card component
function SummaryCard({ title, value, description, icon: Icon, color = 'bg-primary' }) {
  return (
    <Card data-testid={`summary-card-${title.toLowerCase().replace(/\s+/g, '-')}`}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-2xl font-bold">{value}</p>
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

// Queue count badge for tabs
function QueueBadge({ count, isActive }) {
  return (
    <Badge 
      variant="secondary" 
      className={`ml-2 ${count > 0 && isActive ? 'text-blue-400' : 'text-muted-foreground'}`}
    >
      {count}
    </Badge>
  );
}

export default function SalesWorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  
  // State
  const [activeTab, setActiveTab] = useState(searchParams.get('status') || SALES_WORKFLOW_STATUSES.EXTRACTED);
  const [statusCounts, setStatusCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [pilotStatus, setPilotStatus] = useState(null);
  
  // Filters
  const [customerSearch, setCustomerSearch] = useState('');
  const [sourceSystem, setSourceSystem] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [pilotOnly, setPilotOnly] = useState(false);
  
  // Selected document
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);

  // Fetch status counts for each queue
  const fetchStatusCounts = useCallback(async () => {
    const counts = {};
    const allStatuses = [...SALES_PRIMARY_QUEUES, ...SALES_SECONDARY_QUEUES];
    
    for (const status of allStatuses) {
      try {
        const res = await getGenericQueue(DOC_TYPES.SALES_INVOICE, { 
          status, 
          page: 1, 
          page_size: 1,
          ...(pilotOnly ? { pilot_phase: PILOT_CONFIG.CURRENT_PHASE } : {})
        });
        counts[status] = res.data.total || 0;
      } catch (err) {
        counts[status] = 0;
      }
    }
    setStatusCounts(counts);
  }, [pilotOnly]);

  // Fetch pilot status
  const fetchPilotStatus = useCallback(async () => {
    try {
      const res = await getPilotStatus();
      setPilotStatus(res.data);
    } catch (err) {
      console.error('Failed to fetch pilot status:', err);
    }
  }, []);

  useEffect(() => {
    fetchStatusCounts();
    fetchPilotStatus();
  }, [fetchStatusCounts, fetchPilotStatus]);

  // Update URL when tab changes
  useEffect(() => {
    setSearchParams({ status: activeTab });
  }, [activeTab, setSearchParams]);

  const handleRefreshAll = () => {
    setLoading(true);
    fetchStatusCounts();
    setRefreshTrigger(t => t + 1);
    setTimeout(() => setLoading(false), 500);
  };

  // Build filters object for queue API
  const buildFilters = () => {
    const filters = {};
    if (customerSearch.trim()) filters.customer = customerSearch.trim();
    if (sourceSystem !== 'all') filters.source_system = sourceSystem;
    if (dateFrom) filters.date_from = dateFrom;
    if (dateTo) filters.date_to = dateTo;
    if (pilotOnly) filters.pilot_phase = PILOT_CONFIG.CURRENT_PHASE;
    return filters;
  };

  const handleDocumentSelect = (doc) => {
    setSelectedDoc(doc);
    setDetailPanelOpen(true);
  };

  // Calculate summary metrics
  const totalSales = Object.values(statusCounts).reduce((sum, c) => sum + c, 0);
  const activeQueueCount = SALES_PRIMARY_QUEUES.reduce((sum, status) => sum + (statusCounts[status] || 0), 0);
  const exportedCount = statusCounts[SALES_WORKFLOW_STATUSES.EXPORTED] || 0;

  const hasActiveFilters = customerSearch || sourceSystem !== 'all' || dateFrom || dateTo || pilotOnly;

  const clearFilters = () => {
    setCustomerSearch('');
    setSourceSystem('all');
    setDateFrom('');
    setDateTo('');
    setPilotOnly(false);
  };

  return (
    <div className="space-y-6" data-testid="sales-workflows-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Sales Workflows</h1>
            {pilotStatus?.pilot_mode_enabled && (
              <Badge variant="outline" className="bg-blue-500/20 text-blue-400 border-blue-500/30">
                <Eye className="h-3 w-3 mr-1" /> Observation Mode
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground">Monitor Sales Invoice documents through workflow stages</p>
        </div>
        <Button onClick={handleRefreshAll} variant="outline" disabled={loading} data-testid="refresh-all">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Pilot Warning Banner */}
      {pilotStatus?.pilot_mode_enabled && (
        <Card className="border-blue-500/30 bg-blue-500/5">
          <CardContent className="p-4 flex items-center gap-3">
            <AlertTriangle className="h-5 w-5 text-blue-400" />
            <div>
              <p className="font-medium text-blue-400">Shadow Pilot Mode Active</p>
              <p className="text-sm text-muted-foreground">
                This page is for observation only. No actions will be taken on documents during the pilot.
              </p>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard
          title="Total Sales Invoices"
          value={totalSales.toLocaleString()}
          icon={Receipt}
          color="bg-blue-500"
        />
        <SummaryCard
          title="Active Queue"
          value={activeQueueCount.toLocaleString()}
          description="Documents needing action"
          icon={ShoppingCart}
          color="bg-yellow-500"
        />
        <SummaryCard
          title="Customers"
          value="-"
          description="Unique customers"
          icon={Users}
          color="bg-green-500"
        />
        <SummaryCard
          title="Exported"
          value={exportedCount.toLocaleString()}
          description="Completed"
          icon={TrendingUp}
          color="bg-emerald-500"
        />
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4 flex-wrap">
            <div className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Filters</span>
            </div>
            
            <div className="flex-1 grid grid-cols-2 md:grid-cols-5 gap-3">
              {/* Customer Search */}
              <div className="relative col-span-2">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search customer..."
                  value={customerSearch}
                  onChange={(e) => setCustomerSearch(e.target.value)}
                  className="pl-9"
                  data-testid="customer-search"
                />
              </div>
              
              {/* Source System */}
              <Select value={sourceSystem} onValueChange={setSourceSystem}>
                <SelectTrigger data-testid="source-system-filter">
                  <SelectValue placeholder="Source" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Sources</SelectItem>
                  {Object.entries(SOURCE_SYSTEM_LABELS).map(([key, label]) => (
                    <SelectItem key={key} value={key}>{label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
              
              {/* Date From */}
              <Input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                placeholder="From date"
                data-testid="date-from"
              />
              
              {/* Pilot Only Toggle */}
              <Button
                variant={pilotOnly ? "default" : "outline"}
                size="sm"
                onClick={() => setPilotOnly(!pilotOnly)}
                className="h-10"
                data-testid="pilot-filter"
              >
                <Eye className="h-4 w-4 mr-1" />
                Pilot Only
              </Button>
            </div>
            
            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={clearFilters} data-testid="clear-filters">
                Clear
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Queue Tabs */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle>Workflow Queues</CardTitle>
          <CardDescription>Sales documents grouped by workflow status (Observation Mode)</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs value={activeTab} onValueChange={setActiveTab}>
            <TabsList className="mb-6 flex flex-wrap h-auto gap-1">
              {SALES_PRIMARY_QUEUES.map((status) => {
                const config = SALES_QUEUE_CONFIG[status] || {};
                return (
                  <TabsTrigger
                    key={status}
                    value={status}
                    className="flex items-center"
                    data-testid={`tab-${status}`}
                  >
                    {config.shortLabel || status}
                    <QueueBadge count={statusCounts[status] || 0} isActive={config.isActiveQueue} />
                  </TabsTrigger>
                );
              })}
              
              {/* Secondary queues */}
              <div className="ml-2 pl-2 border-l border-border flex gap-1">
                {SALES_SECONDARY_QUEUES.map((status) => {
                  const config = SALES_QUEUE_CONFIG[status] || {};
                  return (
                    <TabsTrigger
                      key={status}
                      value={status}
                      className="flex items-center opacity-70"
                      data-testid={`tab-${status}`}
                    >
                      {config.shortLabel || status}
                      <QueueBadge count={statusCounts[status] || 0} isActive={false} />
                    </TabsTrigger>
                  );
                })}
              </div>
            </TabsList>

            {/* Render queue content for each status */}
            {[...SALES_PRIMARY_QUEUES, ...SALES_SECONDARY_QUEUES].map((status) => (
              <TabsContent key={status} value={status}>
                <WorkflowQueue
                  docType={DOC_TYPES.SALES_INVOICE}
                  status={status}
                  filters={buildFilters()}
                  rowActions={[]} // No actions during pilot - observation only
                  onDocumentSelect={handleDocumentSelect}
                  refreshTrigger={refreshTrigger}
                />
              </TabsContent>
            ))}
          </Tabs>
        </CardContent>
      </Card>

      {/* Document Detail Panel */}
      <DocumentDetailPanel
        document={selectedDoc}
        open={detailPanelOpen}
        onOpenChange={setDetailPanelOpen}
        actions={[]} // No actions during pilot
      />
    </div>
  );
}
