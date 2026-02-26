import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Input } from '../components/ui/input';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '../components/ui/dialog';
import { Label } from '../components/ui/label';
import { toast } from 'sonner';
import { 
  Search, RefreshCw, Play, FolderSync, Brain, Upload, 
  ExternalLink, CheckCircle2, AlertCircle, Clock, FileText,
  ChevronRight, Loader2 
} from 'lucide-react';
import axios from 'axios';

const API_BASE = process.env.REACT_APP_BACKEND_URL;
const API = axios.create({ baseURL: API_BASE });

// Add auth interceptor
API.interceptors.request.use((config) => {
  const token = localStorage.getItem('gpi_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

const STATUS_BADGES = {
  discovered: { label: 'Discovered', variant: 'outline', icon: FileText },
  classified: { label: 'Classified', variant: 'secondary', icon: Brain },
  ready_for_migration: { label: 'Ready', variant: 'default', icon: CheckCircle2 },
  migrated: { label: 'Migrated', variant: 'success', icon: Upload },
  error: { label: 'Error', variant: 'destructive', icon: AlertCircle },
};

const DOC_TYPE_COLORS = {
  spec_sheet: 'bg-blue-100 text-blue-800',
  artwork: 'bg-purple-100 text-purple-800',
  invoice: 'bg-green-100 text-green-800',
  po: 'bg-yellow-100 text-yellow-800',
  contract: 'bg-red-100 text-red-800',
  correspondence: 'bg-orange-100 text-orange-800',
  report: 'bg-cyan-100 text-cyan-800',
  unknown: 'bg-gray-100 text-gray-600',
};

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleDateString('en-US', { 
    month: 'short', 
    day: 'numeric', 
    year: 'numeric' 
  });
}

function ConfidenceBadge({ confidence }) {
  if (confidence === null || confidence === undefined) {
    return <Badge variant="outline" className="text-gray-400">N/A</Badge>;
  }
  
  const pct = Math.round(confidence * 100);
  if (pct >= 90) {
    return <Badge className="bg-green-100 text-green-800">{pct}%</Badge>;
  } else if (pct >= 85) {
    return <Badge className="bg-yellow-100 text-yellow-800">{pct}%</Badge>;
  } else {
    return <Badge className="bg-red-100 text-red-800">{pct}%</Badge>;
  }
}

function StatusBadge({ status }) {
  const config = STATUS_BADGES[status] || STATUS_BADGES.error;
  const Icon = config.icon;
  
  const variantClasses = {
    outline: 'border border-gray-300 text-gray-600 bg-white',
    secondary: 'bg-blue-100 text-blue-800 border-blue-200',
    default: 'bg-emerald-100 text-emerald-800 border-emerald-200',
    success: 'bg-green-500 text-white',
    destructive: 'bg-red-100 text-red-800 border-red-200',
  };
  
  return (
    <Badge className={`flex items-center gap-1 ${variantClasses[config.variant]}`}>
      <Icon className="w-3 h-3" />
      {config.label}
    </Badge>
  );
}

export default function SharePointMigrationPage() {
  const [summary, setSummary] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState(null);
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('all');
  const [docTypeFilter, setDocTypeFilter] = useState('all');
  const [search, setSearch] = useState('');
  
  // Detail dialog
  const [selectedCandidate, setSelectedCandidate] = useState(null);
  const [editMode, setEditMode] = useState(false);
  const [editForm, setEditForm] = useState({});

  const fetchSummary = useCallback(async () => {
    try {
      const res = await API.get('/api/migration/sharepoint/summary');
      setSummary(res.data);
    } catch (err) {
      console.error('Failed to fetch summary:', err);
    }
  }, []);

  const fetchCandidates = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (statusFilter !== 'all') params.append('status', statusFilter);
      if (docTypeFilter !== 'all') params.append('doc_type', docTypeFilter);
      params.append('limit', '100');
      
      const res = await API.get(`/api/migration/sharepoint/candidates?${params}`);
      setCandidates(res.data.candidates || []);
    } catch (err) {
      toast.error('Failed to load candidates');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, docTypeFilter]);

  useEffect(() => {
    fetchSummary();
    fetchCandidates();
  }, [fetchSummary, fetchCandidates]);

  const handleDiscover = async () => {
    setActionLoading('discover');
    try {
      const res = await API.post('/api/migration/sharepoint/discover', {
        sourceSiteUrl: 'https://gamerpackaging1.sharepoint.com/sites/OneGamer',
        sourceLibraryName: 'Documents',
        sourceFolderPath: 'Customer Relations'
      });
      toast.success(`Discovered ${res.data.total_discovered} files (${res.data.new_candidates} new)`);
      await fetchSummary();
      await fetchCandidates();
    } catch (err) {
      toast.error('Discovery failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(null);
    }
  };

  const handleClassify = async () => {
    setActionLoading('classify');
    try {
      const res = await API.post('/api/migration/sharepoint/classify', { maxCount: 25 });
      toast.success(`Classified ${res.data.processed} files (${res.data.high_confidence} high confidence)`);
      await fetchSummary();
      await fetchCandidates();
    } catch (err) {
      toast.error('Classification failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(null);
    }
  };

  const handleMigrate = async () => {
    setActionLoading('migrate');
    try {
      const res = await API.post('/api/migration/sharepoint/migrate', {
        targetSiteUrl: 'https://gamerpackaging1.sharepoint.com/sites/One_Gamer-Flat-Test',
        targetLibraryName: 'Documents',
        maxCount: 20
      });
      toast.success(`Migrated ${res.data.migrated} files (${res.data.errors} errors)`);
      await fetchSummary();
      await fetchCandidates();
    } catch (err) {
      toast.error('Migration failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setActionLoading(null);
    }
  };

  const handleRowClick = (candidate) => {
    setSelectedCandidate(candidate);
    setEditForm({
      doc_type: candidate.doc_type || '',
      department: candidate.department || '',
      customer_name: candidate.customer_name || '',
      vendor_name: candidate.vendor_name || '',
      project_or_part_number: candidate.project_or_part_number || '',
      document_date: candidate.document_date || '',
      retention_category: candidate.retention_category || '',
    });
    setEditMode(false);
  };

  const handleSaveEdit = async () => {
    if (!selectedCandidate) return;
    
    try {
      await API.patch(`/api/migration/sharepoint/candidates/${selectedCandidate.id}`, editForm);
      toast.success('Candidate updated');
      
      // Refresh
      await fetchCandidates();
      
      // Update local state
      const res = await API.get(`/api/migration/sharepoint/candidates/${selectedCandidate.id}`);
      setSelectedCandidate(res.data.candidate);
      setEditMode(false);
    } catch (err) {
      toast.error('Update failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleApprove = async () => {
    if (!selectedCandidate) return;
    
    try {
      await API.post(`/api/migration/sharepoint/candidates/${selectedCandidate.id}/approve`);
      toast.success('Candidate approved for migration');
      
      await fetchSummary();
      await fetchCandidates();
      
      const res = await API.get(`/api/migration/sharepoint/candidates/${selectedCandidate.id}`);
      setSelectedCandidate(res.data.candidate);
    } catch (err) {
      toast.error('Approval failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  const filteredCandidates = candidates.filter(c => {
    if (search) {
      const s = search.toLowerCase();
      if (!c.file_name?.toLowerCase().includes(s) && 
          !c.legacy_path?.toLowerCase().includes(s) &&
          !c.customer_name?.toLowerCase().includes(s)) {
        return false;
      }
    }
    return true;
  });

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">
            SharePoint Migration POC
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            OneGamer → One_Gamer-Flat-Test • Customer Relations folder
          </p>
        </div>
        <Button 
          variant="outline" 
          size="sm" 
          onClick={() => { fetchSummary(); fetchCandidates(); }}
          disabled={loading}
        >
          <RefreshCw className={`w-4 h-4 mr-2 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4">
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold">{summary.total_candidates}</div>
              <div className="text-xs text-muted-foreground">Total Files</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-blue-600">{summary.by_status?.discovered || 0}</div>
              <div className="text-xs text-muted-foreground">Discovered</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-yellow-600">{summary.by_status?.classified || 0}</div>
              <div className="text-xs text-muted-foreground">Classified</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-emerald-600">{summary.by_status?.ready_for_migration || 0}</div>
              <div className="text-xs text-muted-foreground">Ready</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-green-600">{summary.by_status?.migrated || 0}</div>
              <div className="text-xs text-muted-foreground">Migrated</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-red-600">{summary.by_status?.error || 0}</div>
              <div className="text-xs text-muted-foreground">Errors</div>
            </CardContent>
          </Card>
          <Card className="bg-purple-50 dark:bg-purple-950/30">
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-purple-600">{summary.by_classification_source?.folder_tree || 0}</div>
              <div className="text-xs text-muted-foreground">Folder Tree Matches</div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Action Buttons */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-medium">Migration Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            <Button 
              onClick={handleDiscover}
              disabled={actionLoading !== null}
              className="bg-blue-600 hover:bg-blue-700"
            >
              {actionLoading === 'discover' ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <FolderSync className="w-4 h-4 mr-2" />
              )}
              Discover Customer Relations Files
            </Button>
            
            <Button 
              onClick={handleClassify}
              disabled={actionLoading !== null || !summary?.by_status?.discovered}
              variant="secondary"
            >
              {actionLoading === 'classify' ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Brain className="w-4 h-4 mr-2" />
              )}
              Classify Discovered Files
            </Button>
            
            <Button 
              onClick={handleMigrate}
              disabled={actionLoading !== null || !summary?.by_status?.ready_for_migration}
              className="bg-green-600 hover:bg-green-700"
            >
              {actionLoading === 'migrate' ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Upload className="w-4 h-4 mr-2" />
              )}
              Migrate Ready Files
            </Button>
          </div>
          
          <p className="text-xs text-muted-foreground mt-3">
            Source: OneGamer/Documents/Customer Relations → Target: One_Gamer-Flat-Test/Documents
          </p>
        </CardContent>
      </Card>

      {/* Filters */}
      <div className="flex flex-wrap gap-3 items-center">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Filter by status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="discovered">Discovered</SelectItem>
            <SelectItem value="classified">Classified</SelectItem>
            <SelectItem value="ready_for_migration">Ready</SelectItem>
            <SelectItem value="migrated">Migrated</SelectItem>
            <SelectItem value="error">Error</SelectItem>
          </SelectContent>
        </Select>

        <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
          <SelectTrigger className="w-[160px]">
            <SelectValue placeholder="Filter by type" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="spec_sheet">Spec Sheet</SelectItem>
            <SelectItem value="artwork">Artwork</SelectItem>
            <SelectItem value="invoice">Invoice</SelectItem>
            <SelectItem value="po">PO</SelectItem>
            <SelectItem value="contract">Contract</SelectItem>
            <SelectItem value="correspondence">Correspondence</SelectItem>
            <SelectItem value="unknown">Unknown</SelectItem>
          </SelectContent>
        </Select>

        <div className="relative flex-1 max-w-md">
          <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-gray-400" />
          <Input
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-10"
          />
        </div>
      </div>

      {/* Candidates Table */}
      <Card>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-[280px]">File Name</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Level1/Level2</TableHead>
                <TableHead>Doc Type</TableHead>
                <TableHead>Customer</TableHead>
                <TableHead>Date</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Status</TableHead>
                <TableHead className="w-10"></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto text-gray-400" />
                  </TableCell>
                </TableRow>
              ) : filteredCandidates.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={9} className="text-center py-8 text-gray-500">
                    No migration candidates found. Click "Discover" to start.
                  </TableCell>
                </TableRow>
              ) : (
                filteredCandidates.map((candidate) => (
                  <TableRow 
                    key={candidate.id} 
                    className="cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800"
                    onClick={() => handleRowClick(candidate)}
                  >
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <FileText className="w-4 h-4 text-gray-400 flex-shrink-0" />
                        <div className="min-w-0">
                          <div className="font-medium text-sm truncate max-w-[260px]" title={candidate.file_name}>
                            {candidate.file_name}
                          </div>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {candidate.classification_source === 'folder_tree' && (
                        <Badge className="bg-purple-100 text-purple-800 text-[10px]">CSV</Badge>
                      )}
                      {candidate.classification_source === 'hybrid' && (
                        <Badge className="bg-indigo-100 text-indigo-800 text-[10px]">Hybrid</Badge>
                      )}
                      {candidate.classification_source === 'ai' && (
                        <Badge className="bg-blue-100 text-blue-800 text-[10px]">AI</Badge>
                      )}
                      {!candidate.classification_source && (
                        <Badge variant="outline" className="text-[10px]">-</Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {candidate.level1 && (
                        <div className="text-xs">
                          <span className="font-medium">{candidate.level1}</span>
                          {candidate.level2 && <span className="text-muted-foreground"> / {candidate.level2}</span>}
                        </div>
                      )}
                    </TableCell>
                    <TableCell>
                      {candidate.doc_type && (
                        <Badge className={`text-[10px] ${DOC_TYPE_COLORS[candidate.doc_type] || DOC_TYPE_COLORS.unknown}`}>
                          {candidate.doc_type}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs">{candidate.customer_name || '-'}</TableCell>
                    <TableCell className="text-xs">{formatDate(candidate.document_date)}</TableCell>
                    <TableCell>
                      <ConfidenceBadge confidence={candidate.classification_confidence} />
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={candidate.status} />
                    </TableCell>
                    <TableCell>
                      <ChevronRight className="w-4 h-4 text-gray-400" />
                    </TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Detail Dialog */}
      <Dialog open={!!selectedCandidate} onOpenChange={() => setSelectedCandidate(null)}>
        <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileText className="w-5 h-5" />
              {selectedCandidate?.file_name}
            </DialogTitle>
          </DialogHeader>

          {selectedCandidate && (
            <div className="space-y-4">
              {/* Source Info */}
              <div className="bg-gray-50 dark:bg-gray-800 rounded-lg p-3 space-y-2">
                <div className="text-xs font-medium text-gray-500 uppercase">Source Location</div>
                <div className="text-sm break-all">{selectedCandidate.legacy_path}</div>
                {selectedCandidate.legacy_url && (
                  <a 
                    href={selectedCandidate.legacy_url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-xs text-blue-600 hover:underline flex items-center gap-1"
                  >
                    Open in SharePoint <ExternalLink className="w-3 h-3" />
                  </a>
                )}
              </div>

              {/* Target Info (if migrated) */}
              {selectedCandidate.status === 'migrated' && selectedCandidate.target_url && (
                <div className="bg-green-50 dark:bg-green-900/20 rounded-lg p-3 space-y-2">
                  <div className="text-xs font-medium text-green-600 uppercase">Migrated To</div>
                  <a 
                    href={selectedCandidate.target_url} 
                    target="_blank" 
                    rel="noopener noreferrer"
                    className="text-sm text-green-700 hover:underline flex items-center gap-1"
                  >
                    {selectedCandidate.target_url} <ExternalLink className="w-3 h-3" />
                  </a>
                  <div className="text-xs text-green-600">
                    Migrated: {formatDate(selectedCandidate.migration_timestamp)}
                  </div>
                </div>
              )}

              {/* Error Info */}
              {selectedCandidate.status === 'error' && selectedCandidate.migration_error && (
                <div className="bg-red-50 dark:bg-red-900/20 rounded-lg p-3">
                  <div className="text-xs font-medium text-red-600 uppercase">Error</div>
                  <div className="text-sm text-red-700">{selectedCandidate.migration_error}</div>
                </div>
              )}

              {/* Status & Confidence */}
              <div className="flex items-center gap-4">
                <div>
                  <div className="text-xs text-gray-500 mb-1">Status</div>
                  <StatusBadge status={selectedCandidate.status} />
                </div>
                <div>
                  <div className="text-xs text-gray-500 mb-1">AI Confidence</div>
                  <ConfidenceBadge confidence={selectedCandidate.classification_confidence} />
                </div>
                <div>
                  <div className="text-xs text-gray-500 mb-1">Method</div>
                  <Badge variant="outline">{selectedCandidate.classification_method || 'N/A'}</Badge>
                </div>
              </div>

              {/* Metadata Fields */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">AI-Inferred Metadata</div>
                  {!editMode && selectedCandidate.status !== 'migrated' && (
                    <Button variant="outline" size="sm" onClick={() => setEditMode(true)}>
                      Edit
                    </Button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <Label className="text-xs">Document Type</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.doc_type} 
                        onValueChange={(v) => setEditForm({...editForm, doc_type: v})}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="spec_sheet">Spec Sheet</SelectItem>
                          <SelectItem value="artwork">Artwork</SelectItem>
                          <SelectItem value="invoice">Invoice</SelectItem>
                          <SelectItem value="po">PO</SelectItem>
                          <SelectItem value="contract">Contract</SelectItem>
                          <SelectItem value="correspondence">Correspondence</SelectItem>
                          <SelectItem value="report">Report</SelectItem>
                          <SelectItem value="unknown">Unknown</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.doc_type || '-'}</div>
                    )}
                  </div>

                  <div>
                    <Label className="text-xs">Department</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.department} 
                        onValueChange={(v) => setEditForm({...editForm, department: v})}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="CustomerRelations">Customer Relations</SelectItem>
                          <SelectItem value="Sales">Sales</SelectItem>
                          <SelectItem value="Marketing">Marketing</SelectItem>
                          <SelectItem value="Finance">Finance</SelectItem>
                          <SelectItem value="Quality">Quality</SelectItem>
                          <SelectItem value="Operations">Operations</SelectItem>
                          <SelectItem value="Unknown">Unknown</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.department || '-'}</div>
                    )}
                  </div>

                  <div>
                    <Label className="text-xs">Customer Name</Label>
                    {editMode ? (
                      <Input 
                        value={editForm.customer_name}
                        onChange={(e) => setEditForm({...editForm, customer_name: e.target.value})}
                      />
                    ) : (
                      <div className="text-sm">{selectedCandidate.customer_name || '-'}</div>
                    )}
                  </div>

                  <div>
                    <Label className="text-xs">Vendor Name</Label>
                    {editMode ? (
                      <Input 
                        value={editForm.vendor_name}
                        onChange={(e) => setEditForm({...editForm, vendor_name: e.target.value})}
                      />
                    ) : (
                      <div className="text-sm">{selectedCandidate.vendor_name || '-'}</div>
                    )}
                  </div>

                  <div>
                    <Label className="text-xs">Project/Part Number</Label>
                    {editMode ? (
                      <Input 
                        value={editForm.project_or_part_number}
                        onChange={(e) => setEditForm({...editForm, project_or_part_number: e.target.value})}
                      />
                    ) : (
                      <div className="text-sm">{selectedCandidate.project_or_part_number || '-'}</div>
                    )}
                  </div>

                  <div>
                    <Label className="text-xs">Document Date</Label>
                    {editMode ? (
                      <Input 
                        type="date"
                        value={editForm.document_date}
                        onChange={(e) => setEditForm({...editForm, document_date: e.target.value})}
                      />
                    ) : (
                      <div className="text-sm">{formatDate(selectedCandidate.document_date)}</div>
                    )}
                  </div>

                  <div className="col-span-2">
                    <Label className="text-xs">Retention Category</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.retention_category} 
                        onValueChange={(v) => setEditForm({...editForm, retention_category: v})}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="CustomerComm_LongTerm">Customer Comm - Long Term</SelectItem>
                          <SelectItem value="WorkingDoc_2yrs">Working Doc - 2 Years</SelectItem>
                          <SelectItem value="Accounting_7yrs">Accounting - 7 Years</SelectItem>
                          <SelectItem value="Legal_10yrs">Legal - 10 Years</SelectItem>
                          <SelectItem value="Unknown">Unknown</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.retention_category || '-'}</div>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          <DialogFooter className="gap-2">
            {editMode ? (
              <>
                <Button variant="outline" onClick={() => setEditMode(false)}>Cancel</Button>
                <Button onClick={handleSaveEdit}>Save Changes</Button>
              </>
            ) : (
              <>
                {selectedCandidate?.status === 'classified' && (
                  <Button onClick={handleApprove} className="bg-emerald-600 hover:bg-emerald-700">
                    <CheckCircle2 className="w-4 h-4 mr-2" />
                    Approve for Migration
                  </Button>
                )}
                <Button variant="outline" onClick={() => setSelectedCandidate(null)}>
                  Close
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
