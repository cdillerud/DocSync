/**
 * OperationsWorkflowsPage - Warehouse (PO + Quality) Workflow Observation
 * 
 * Shadow pilot observation page for PURCHASE_ORDER and QUALITY_DOC documents.
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
  RefreshCw, Filter, Package, ClipboardCheck, TrendingUp, 
  FileCheck, Search, Eye, AlertTriangle, Layers
} from 'lucide-react';

import { WorkflowQueue } from '@/components/WorkflowQueue';
import { DocumentDetailPanel } from '@/components/DocumentDetailPanel';
import {
  DOC_TYPES,
  PO_WORKFLOW_STATUSES,
  PO_QUEUE_CONFIG,
  PO_PRIMARY_QUEUES,
  PO_SECONDARY_QUEUES,
  QUALITY_WORKFLOW_STATUSES,
  QUALITY_QUEUE_CONFIG,
  QUALITY_PRIMARY_QUEUES,
  QUALITY_SECONDARY_QUEUES,
  SOURCE_SYSTEMS,
  SOURCE_SYSTEM_LABELS,
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

export default function OperationsWorkflowsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  
  // State
  const [activeSection, setActiveSection] = useState(searchParams.get('section') || 'po');
  const [activePoTab, setActivePoTab] = useState(PO_WORKFLOW_STATUSES.VALIDATION_PENDING);
  const [activeQualityTab, setActiveQualityTab] = useState(QUALITY_WORKFLOW_STATUSES.TAGGED);
  const [poStatusCounts, setPoStatusCounts] = useState({});
  const [qualityStatusCounts, setQualityStatusCounts] = useState({});
  const [loading, setLoading] = useState(false);
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  const [pilotStatus, setPilotStatus] = useState(null);
  
  // Filters
  const [searchTerm, setSearchTerm] = useState('');
  const [sourceSystem, setSourceSystem] = useState('all');
  const [pilotOnly, setPilotOnly] = useState(false);
  
  // Selected document
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);

  // Fetch status counts for PO queues
  const fetchPoStatusCounts = useCallback(async () => {
    const counts = {};
    const allStatuses = [...PO_PRIMARY_QUEUES, ...PO_SECONDARY_QUEUES];
    
    for (const status of allStatuses) {
      try {
        const res = await getGenericQueue(DOC_TYPES.PURCHASE_ORDER, { 
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
    setPoStatusCounts(counts);
  }, [pilotOnly]);

  // Fetch status counts for Quality queues
  const fetchQualityStatusCounts = useCallback(async () => {
    const counts = {};
    const allStatuses = [...QUALITY_PRIMARY_QUEUES, ...QUALITY_SECONDARY_QUEUES];
    
    for (const status of allStatuses) {
      try {
        const res = await getGenericQueue(DOC_TYPES.QUALITY_DOC, { 
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
    setQualityStatusCounts(counts);
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
    fetchPoStatusCounts();
    fetchQualityStatusCounts();
    fetchPilotStatus();
  }, [fetchPoStatusCounts, fetchQualityStatusCounts, fetchPilotStatus]);

  // Update URL when section changes
  useEffect(() => {
    setSearchParams({ section: activeSection });
  }, [activeSection, setSearchParams]);

  const handleRefreshAll = () => {
    setLoading(true);
    fetchPoStatusCounts();
    fetchQualityStatusCounts();
    setRefreshTrigger(t => t + 1);
    setTimeout(() => setLoading(false), 500);
  };

  // Build filters object for queue API
  const buildFilters = () => {
    const filters = {};
    if (searchTerm.trim()) filters.search = searchTerm.trim();
    if (sourceSystem !== 'all') filters.source_system = sourceSystem;
    if (pilotOnly) filters.pilot_phase = PILOT_CONFIG.CURRENT_PHASE;
    return filters;
  };

  const handleDocumentSelect = (doc) => {
    setSelectedDoc(doc);
    setDetailPanelOpen(true);
  };

  // Calculate summary metrics
  const totalPO = Object.values(poStatusCounts).reduce((sum, c) => sum + c, 0);
  const totalQuality = Object.values(qualityStatusCounts).reduce((sum, c) => sum + c, 0);
  const activePOCount = PO_PRIMARY_QUEUES.reduce((sum, status) => sum + (poStatusCounts[status] || 0), 0);
  const activeQualityCount = QUALITY_PRIMARY_QUEUES.reduce((sum, status) => sum + (qualityStatusCounts[status] || 0), 0);

  const hasActiveFilters = searchTerm || sourceSystem !== 'all' || pilotOnly;

  const clearFilters = () => {
    setSearchTerm('');
    setSourceSystem('all');
    setPilotOnly(false);
  };

  return (
    <div className="space-y-6" data-testid="operations-workflows-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold">Operations Workflows</h1>
            {pilotStatus?.pilot_mode_enabled && (
              <Badge variant="outline" className="bg-blue-500/20 text-blue-400 border-blue-500/30">
                <Eye className="h-3 w-3 mr-1" /> Observation Mode
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground">Monitor Purchase Orders and Quality Documents</p>
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
          title="Purchase Orders"
          value={totalPO.toLocaleString()}
          description={`${activePOCount} active`}
          icon={Package}
          color="bg-blue-500"
        />
        <SummaryCard
          title="Quality Docs"
          value={totalQuality.toLocaleString()}
          description={`${activeQualityCount} active`}
          icon={ClipboardCheck}
          color="bg-purple-500"
        />
        <SummaryCard
          title="Validation Pending"
          value={(poStatusCounts[PO_WORKFLOW_STATUSES.VALIDATION_PENDING] || 0).toLocaleString()}
          description="POs awaiting validation"
          icon={FileCheck}
          color="bg-yellow-500"
        />
        <SummaryCard
          title="Ready for Review"
          value={(qualityStatusCounts[QUALITY_WORKFLOW_STATUSES.READY_FOR_REVIEW] || 0).toLocaleString()}
          description="Quality docs to review"
          icon={TrendingUp}
          color="bg-green-500"
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
            
            <div className="flex-1 grid grid-cols-2 md:grid-cols-4 gap-3">
              {/* Search */}
              <div className="relative col-span-2">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Search PO # or Quality doc..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-9"
                  data-testid="search-input"
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

      {/* Section Toggle */}
      <div className="flex gap-2">
        <Button
          variant={activeSection === 'po' ? 'default' : 'outline'}
          onClick={() => setActiveSection('po')}
          data-testid="section-po"
        >
          <Package className="h-4 w-4 mr-2" />
          Purchase Orders
          <Badge variant="secondary" className="ml-2">{totalPO}</Badge>
        </Button>
        <Button
          variant={activeSection === 'quality' ? 'default' : 'outline'}
          onClick={() => setActiveSection('quality')}
          data-testid="section-quality"
        >
          <ClipboardCheck className="h-4 w-4 mr-2" />
          Quality Docs
          <Badge variant="secondary" className="ml-2">{totalQuality}</Badge>
        </Button>
      </div>

      {/* Purchase Orders Section */}
      {activeSection === 'po' && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <Package className="h-5 w-5" />
              Purchase Order Queues
            </CardTitle>
            <CardDescription>PO documents grouped by workflow status (Observation Mode)</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activePoTab} onValueChange={setActivePoTab}>
              <TabsList className="mb-6 flex flex-wrap h-auto gap-1">
                {PO_PRIMARY_QUEUES.map((status) => {
                  const config = PO_QUEUE_CONFIG[status] || {};
                  return (
                    <TabsTrigger
                      key={status}
                      value={status}
                      className="flex items-center"
                      data-testid={`po-tab-${status}`}
                    >
                      {config.shortLabel || status}
                      <QueueBadge count={poStatusCounts[status] || 0} isActive={config.isActiveQueue} />
                    </TabsTrigger>
                  );
                })}
                
                <div className="ml-2 pl-2 border-l border-border flex gap-1">
                  {PO_SECONDARY_QUEUES.map((status) => {
                    const config = PO_QUEUE_CONFIG[status] || {};
                    return (
                      <TabsTrigger
                        key={status}
                        value={status}
                        className="flex items-center opacity-70"
                        data-testid={`po-tab-${status}`}
                      >
                        {config.shortLabel || status}
                        <QueueBadge count={poStatusCounts[status] || 0} isActive={false} />
                      </TabsTrigger>
                    );
                  })}
                </div>
              </TabsList>

              {[...PO_PRIMARY_QUEUES, ...PO_SECONDARY_QUEUES].map((status) => (
                <TabsContent key={status} value={status}>
                  <WorkflowQueue
                    docType={DOC_TYPES.PURCHASE_ORDER}
                    status={status}
                    filters={buildFilters()}
                    rowActions={[]}
                    onDocumentSelect={handleDocumentSelect}
                    refreshTrigger={refreshTrigger}
                  />
                </TabsContent>
              ))}
            </Tabs>
          </CardContent>
        </Card>
      )}

      {/* Quality Docs Section */}
      {activeSection === 'quality' && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2">
              <ClipboardCheck className="h-5 w-5" />
              Quality Document Queues
            </CardTitle>
            <CardDescription>Quality documents grouped by workflow status (Observation Mode)</CardDescription>
          </CardHeader>
          <CardContent>
            <Tabs value={activeQualityTab} onValueChange={setActiveQualityTab}>
              <TabsList className="mb-6 flex flex-wrap h-auto gap-1">
                {QUALITY_PRIMARY_QUEUES.map((status) => {
                  const config = QUALITY_QUEUE_CONFIG[status] || {};
                  return (
                    <TabsTrigger
                      key={status}
                      value={status}
                      className="flex items-center"
                      data-testid={`quality-tab-${status}`}
                    >
                      {config.shortLabel || status}
                      <QueueBadge count={qualityStatusCounts[status] || 0} isActive={config.isActiveQueue} />
                    </TabsTrigger>
                  );
                })}
                
                <div className="ml-2 pl-2 border-l border-border flex gap-1">
                  {QUALITY_SECONDARY_QUEUES.map((status) => {
                    const config = QUALITY_QUEUE_CONFIG[status] || {};
                    return (
                      <TabsTrigger
                        key={status}
                        value={status}
                        className="flex items-center opacity-70"
                        data-testid={`quality-tab-${status}`}
                      >
                        {config.shortLabel || status}
                        <QueueBadge count={qualityStatusCounts[status] || 0} isActive={false} />
                      </TabsTrigger>
                    );
                  })}
                </div>
              </TabsList>

              {[...QUALITY_PRIMARY_QUEUES, ...QUALITY_SECONDARY_QUEUES].map((status) => (
                <TabsContent key={status} value={status}>
                  <WorkflowQueue
                    docType={DOC_TYPES.QUALITY_DOC}
                    status={status}
                    filters={buildFilters()}
                    rowActions={[]}
                    onDocumentSelect={handleDocumentSelect}
                    refreshTrigger={refreshTrigger}
                  />
                </TabsContent>
              ))}
            </Tabs>
          </CardContent>
        </Card>
      )}

      {/* Document Detail Panel */}
      <DocumentDetailPanel
        document={selectedDoc}
        open={detailPanelOpen}
        onOpenChange={setDetailPanelOpen}
        actions={[]}
      />
    </div>
  );
}
