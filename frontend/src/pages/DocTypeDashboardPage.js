import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Progress } from '@/components/ui/progress';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { toast } from 'sonner';
import { 
  RefreshCw, FileText, TrendingUp, CheckCircle, AlertCircle, 
  Building2, Package, Receipt, FileCheck, HelpCircle, Filter, Download, Brain, Cpu
} from 'lucide-react';
import { getDocumentTypesDashboard, exportDocumentTypesDashboard } from '@/lib/api';

const DOC_TYPE_CONFIG = {
  AP_INVOICE: { label: 'AP Invoice', icon: Receipt, color: 'bg-blue-500', description: 'Vendor invoices' },
  SALES_INVOICE: { label: 'Sales Invoice', icon: FileCheck, color: 'bg-green-500', description: 'Invoices we send' },
  PURCHASE_ORDER: { label: 'Purchase Order', icon: Package, color: 'bg-purple-500', description: 'Purchase orders' },
  SALES_CREDIT_MEMO: { label: 'Sales Credit Memo', icon: FileText, color: 'bg-orange-500', description: 'Credit memos issued' },
  PURCHASE_CREDIT_MEMO: { label: 'Purchase Credit Memo', icon: FileText, color: 'bg-amber-500', description: 'Credit memos received' },
  STATEMENT: { label: 'Statement', icon: FileText, color: 'bg-slate-500', description: 'Account statements' },
  REMINDER: { label: 'Reminder', icon: AlertCircle, color: 'bg-red-400', description: 'Payment reminders' },
  FINANCE_CHARGE_MEMO: { label: 'Finance Charge', icon: FileText, color: 'bg-pink-500', description: 'Finance charges' },
  QUALITY_DOC: { label: 'Quality Doc', icon: CheckCircle, color: 'bg-teal-500', description: 'Quality documents' },
  OTHER: { label: 'Other', icon: HelpCircle, color: 'bg-gray-500', description: 'Unclassified' },
};

const SOURCE_SYSTEM_LABELS = {
  SQUARE9: 'Square9',
  ZETADOCS: 'Zetadocs',
  GPI_HUB_NATIVE: 'GPI Hub Native',
  MIGRATION: 'Migration',
  UNKNOWN: 'Unknown'
};

function ExtractionRateBar({ rate, count, label }) {
  const percentage = Math.round(rate * 100);
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <div className="w-full">
            <div className="flex justify-between text-xs mb-1">
              <span className="text-muted-foreground">{label}</span>
              <span className={percentage >= 80 ? 'text-green-400' : percentage >= 50 ? 'text-yellow-400' : 'text-red-400'}>
                {percentage}%
              </span>
            </div>
            <Progress value={percentage} className="h-1.5" />
          </div>
        </TooltipTrigger>
        <TooltipContent>
          <p>{count} of documents have {label.toLowerCase()}</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function MatchMethodBadge({ method, count }) {
  const colors = {
    exact: 'bg-green-500/20 text-green-400 border-green-500/30',
    normalized: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
    alias: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
    fuzzy: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
    manual: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
    none: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
  };
  
  return (
    <Badge variant="outline" className={`text-xs ${colors[method] || colors.none}`}>
      {method}: {count}
    </Badge>
  );
}

function ClassificationBadge({ type, count }) {
  const config = {
    deterministic: { 
      icon: Cpu, 
      color: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
      label: 'Det'
    },
    ai: { 
      icon: Brain, 
      color: 'bg-violet-500/20 text-violet-400 border-violet-500/30',
      label: 'AI'
    },
    other: { 
      icon: HelpCircle, 
      color: 'bg-gray-500/20 text-gray-400 border-gray-500/30',
      label: 'Oth'
    }
  };
  
  const cfg = config[type] || config.other;
  const Icon = cfg.icon;
  
  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant="outline" className={`text-xs ${cfg.color} flex items-center gap-1`}>
            <Icon className="h-3 w-3" />
            {count}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          <p>{type === 'deterministic' ? 'Deterministic' : type === 'ai' ? 'AI-assisted' : 'Other/Unknown'}: {count} documents</p>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}

function DocTypeRow({ docType, data }) {
  const config = DOC_TYPE_CONFIG[docType] || DOC_TYPE_CONFIG.OTHER;
  const Icon = config.icon;
  
  // Key workflow statuses to show
  const statusCounts = data.status_counts || {};
  const captured = statusCounts.captured || 0;
  const extracted = statusCounts.extracted || 0;
  const readyForApproval = statusCounts.ready_for_approval || 0;
  const approved = statusCounts.approved || 0;
  const exported = statusCounts.exported || 0;
  
  // Calculate processing progress
  const totalProcessed = extracted + readyForApproval + approved + exported;
  const progressPct = data.total > 0 ? Math.round((totalProcessed / data.total) * 100) : 0;
  
  // Classification counts
  const classificationCounts = data.classification_counts || { deterministic: 0, ai: 0, other: 0 };
  
  return (
    <TableRow data-testid={`doctype-row-${docType}`}>
      <TableCell>
        <div className="flex items-center gap-3">
          <div className={`p-2 rounded-lg ${config.color}`}>
            <Icon className="h-4 w-4 text-white" />
          </div>
          <div>
            <p className="font-medium">{config.label}</p>
            <p className="text-xs text-muted-foreground">{config.description}</p>
          </div>
        </div>
      </TableCell>
      <TableCell className="text-center font-bold text-lg">
        {data.total.toLocaleString()}
      </TableCell>
      <TableCell>
        <div className="flex items-center gap-1">
          <ClassificationBadge type="deterministic" count={classificationCounts.deterministic} />
          <ClassificationBadge type="ai" count={classificationCounts.ai} />
          {classificationCounts.other > 0 && (
            <ClassificationBadge type="other" count={classificationCounts.other} />
          )}
        </div>
      </TableCell>
      <TableCell className="text-center">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger>
              <div className="flex items-center gap-2 justify-center">
                <Progress value={progressPct} className="w-16 h-2" />
                <span className="text-sm">{progressPct}%</span>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <div className="text-xs space-y-1">
                <p>Captured: {captured}</p>
                <p>Extracted: {extracted}</p>
                <p>Ready: {readyForApproval}</p>
                <p>Approved: {approved}</p>
                <p>Exported: {exported}</p>
              </div>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </TableCell>
      <TableCell>
        <div className="flex gap-2 flex-wrap text-xs">
          <span className="text-blue-400">Cap: {captured}</span>
          <span className="text-purple-400">Ext: {extracted}</span>
          <span className="text-yellow-400">Rdy: {readyForApproval}</span>
          <span className="text-green-400">Exp: {exported}</span>
        </div>
      </TableCell>
      <TableCell>
        <div className="space-y-1 min-w-[120px]">
          <ExtractionRateBar 
            rate={data.extraction?.vendor?.rate || 0} 
            count={data.extraction?.vendor?.count || 0}
            label="Vendor" 
          />
          <ExtractionRateBar 
            rate={data.extraction?.invoice_number?.rate || 0} 
            count={data.extraction?.invoice_number?.count || 0}
            label="Invoice #" 
          />
          <ExtractionRateBar 
            rate={data.extraction?.amount?.rate || 0} 
            count={data.extraction?.amount?.count || 0}
            label="Amount" 
          />
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap gap-1">
          {Object.entries(data.match_methods || {}).slice(0, 4).map(([method, count]) => (
            <MatchMethodBadge key={method} method={method} count={count} />
          ))}
        </div>
      </TableCell>
    </TableRow>
  );
}

function SummaryCard({ title, value, icon: Icon, description, color = 'bg-primary' }) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-muted-foreground">{title}</p>
            <p className="text-2xl font-bold">{value}</p>
            {description && <p className="text-xs text-muted-foreground">{description}</p>}
          </div>
          <div className={`p-3 rounded-lg ${color}`}>
            <Icon className="h-5 w-5 text-white" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

export default function DocTypeDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sourceSystemFilter, setSourceSystemFilter] = useState('all');
  const [docTypeFilter, setDocTypeFilter] = useState('all');
  const [classificationFilter, setClassificationFilter] = useState('all');

  const fetchData = async () => {
    setLoading(true);
    try {
      const params = {};
      if (sourceSystemFilter !== 'all') params.source_system = sourceSystemFilter;
      if (docTypeFilter !== 'all') params.doc_type = docTypeFilter;
      if (classificationFilter !== 'all') params.classification = classificationFilter;
      
      const res = await getDocumentTypesDashboard(params);
      setData(res.data);
    } catch (err) {
      toast.error('Failed to load dashboard data');
      console.error(err);
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
  }, [sourceSystemFilter, docTypeFilter, classificationFilter]);

  // Calculate summary stats
  const grandTotal = data?.grand_total || 0;
  const docTypeCount = Object.keys(data?.by_type || {}).length;
  
  // Classification totals
  const classificationTotals = data?.classification_totals || { deterministic: 0, ai: 0, other: 0 };
  
  // Calculate overall extraction rates
  let totalDocs = 0;
  let totalWithVendor = 0;
  let totalWithAmount = 0;
  let totalExported = 0;
  
  Object.values(data?.by_type || {}).forEach(typeData => {
    totalDocs += typeData.total;
    totalWithVendor += typeData.extraction?.vendor?.count || 0;
    totalWithAmount += typeData.extraction?.amount?.count || 0;
    totalExported += typeData.status_counts?.exported || 0;
  });
  
  const overallVendorRate = totalDocs > 0 ? Math.round((totalWithVendor / totalDocs) * 100) : 0;
  const overallAmountRate = totalDocs > 0 ? Math.round((totalWithAmount / totalDocs) * 100) : 0;
  const overallExportRate = totalDocs > 0 ? Math.round((totalExported / totalDocs) * 100) : 0;

  const handleExportCSV = () => {
    const params = {};
    if (sourceSystemFilter !== 'all') params.source_system = sourceSystemFilter;
    if (docTypeFilter !== 'all') params.doc_type = docTypeFilter;
    if (classificationFilter !== 'all') params.classification = classificationFilter;
    
    toast.success('Starting CSV export...');
    exportDocumentTypesDashboard(params);
  };

  return (
    <div className="space-y-6" data-testid="doctype-dashboard-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Document Type Dashboard</h1>
          <p className="text-muted-foreground">Migration progress and extraction quality by document type</p>
        </div>
        <div className="flex gap-2">
          <Button onClick={handleExportCSV} variant="outline" disabled={loading || grandTotal === 0} data-testid="export-csv-btn">
            <Download className="mr-2 h-4 w-4" /> Export CSV
          </Button>
          <Button onClick={fetchData} variant="outline" disabled={loading} data-testid="refresh-dashboard">
            <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
        </div>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="p-4">
          <div className="flex items-center gap-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="flex gap-4">
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Source System</label>
                <Select value={sourceSystemFilter} onValueChange={setSourceSystemFilter}>
                  <SelectTrigger className="w-[180px]" data-testid="source-system-filter">
                    <SelectValue placeholder="All Sources" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Sources</SelectItem>
                    {Object.entries(data?.source_systems_available || {}).map(([sys, count]) => (
                      <SelectItem key={sys} value={sys}>
                        {SOURCE_SYSTEM_LABELS[sys] || sys} ({count})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1">
                <label className="text-xs text-muted-foreground">Document Type</label>
                <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
                  <SelectTrigger className="w-[180px]" data-testid="doc-type-filter">
                    <SelectValue placeholder="All Types" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">All Types</SelectItem>
                    {(data?.doc_types_available || []).map(dt => (
                      <SelectItem key={dt} value={dt}>
                        {DOC_TYPE_CONFIG[dt]?.label || dt}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard 
          title="Total Documents" 
          value={grandTotal.toLocaleString()} 
          icon={FileText}
          color="bg-blue-500"
        />
        <SummaryCard 
          title="Vendor Extraction" 
          value={`${overallVendorRate}%`} 
          icon={Building2}
          description={`${totalWithVendor.toLocaleString()} extracted`}
          color="bg-green-500"
        />
        <SummaryCard 
          title="Amount Extraction" 
          value={`${overallAmountRate}%`} 
          icon={TrendingUp}
          description={`${totalWithAmount.toLocaleString()} extracted`}
          color="bg-purple-500"
        />
        <SummaryCard 
          title="Export Rate" 
          value={`${overallExportRate}%`} 
          icon={CheckCircle}
          description={`${totalExported.toLocaleString()} exported`}
          color="bg-emerald-500"
        />
      </div>

      {/* Main Table */}
      <Card>
        <CardHeader>
          <CardTitle>Document Types Overview</CardTitle>
          <CardDescription>
            {docTypeCount} document type{docTypeCount !== 1 ? 's' : ''} with data
            {sourceSystemFilter !== 'all' && ` • Filtered by ${SOURCE_SYSTEM_LABELS[sourceSystemFilter]}`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : Object.keys(data?.by_type || {}).length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <FileText className="mx-auto h-12 w-12 mb-4 opacity-50" />
              <p>No documents found</p>
              <p className="text-sm">Upload or ingest documents to see metrics</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-[200px]">Document Type</TableHead>
                  <TableHead className="text-center w-[100px]">Total</TableHead>
                  <TableHead className="text-center w-[120px]">Progress</TableHead>
                  <TableHead className="w-[180px]">Status Distribution</TableHead>
                  <TableHead className="w-[150px]">Extraction (Core)</TableHead>
                  <TableHead className="w-[150px]">Extraction (Extended)</TableHead>
                  <TableHead className="w-[200px]">Match Methods</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {Object.entries(data?.by_type || {})
                  .sort((a, b) => b[1].total - a[1].total)
                  .map(([docType, typeData]) => (
                    <DocTypeRow key={docType} docType={docType} data={typeData} />
                  ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
