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
  ChevronRight, Loader2, Settings 
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
  // Legacy doc_type colors
  spec_sheet: 'bg-blue-100 text-blue-800',
  artwork: 'bg-purple-100 text-purple-800',
  invoice: 'bg-green-100 text-green-800',
  po: 'bg-yellow-100 text-yellow-800',
  contract: 'bg-red-100 text-red-800',
  correspondence: 'bg-orange-100 text-orange-800',
  report: 'bg-cyan-100 text-cyan-800',
  unknown: 'bg-gray-100 text-gray-600',
};

// NEW: Document type colors from Excel structure
const DOCUMENT_TYPE_COLORS = {
  'Product Specification Sheet': 'bg-blue-100 text-blue-800',
  'Product Drawings': 'bg-purple-100 text-purple-800',
  'Product Pack-Out Specs': 'bg-indigo-100 text-indigo-800',
  'Graphical Die Line': 'bg-violet-100 text-violet-800',
  'Supplier Documents': 'bg-amber-100 text-amber-800',
  'Marketing Literature': 'bg-pink-100 text-pink-800',
  'Capabilities / Catalogs': 'bg-rose-100 text-rose-800',
  'SOPs / Resources': 'bg-teal-100 text-teal-800',
  'Customer Documents': 'bg-emerald-100 text-emerald-800',
  'Customer Quote': 'bg-lime-100 text-lime-800',
  'Supplier Quote': 'bg-orange-100 text-orange-800',
  'Agreement Resources': 'bg-red-100 text-red-800',
  'Quality Documents': 'bg-cyan-100 text-cyan-800',
  'Training': 'bg-sky-100 text-sky-800',
  'Other': 'bg-gray-100 text-gray-600',
};

// Acct Type colors
const ACCT_TYPE_COLORS = {
  'Customer Accounts': 'bg-green-100 text-green-800',
  'Manufacturers / Vendors': 'bg-orange-100 text-orange-800',
  'Corporate Internal': 'bg-blue-100 text-blue-800',
  'System Resources': 'bg-gray-100 text-gray-600',
};

// Document Status colors
const DOC_STATUS_COLORS = {
  'Active': 'bg-green-100 text-green-800',
  'Archived': 'bg-gray-100 text-gray-600',
  'Pending': 'bg-yellow-100 text-yellow-800',
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
  
  // Source configuration (editable)
  const [sourceConfig, setSourceConfig] = useState({
    siteUrl: 'https://gamerpackaging1.sharepoint.com/sites/OneGamer',
    libraryName: 'Documents',
    folderPath: 'Customer Relations'
  });
  const [showSourceConfig, setShowSourceConfig] = useState(false);
  const [pasteUrl, setPasteUrl] = useState('');

  // Parse SharePoint URL to extract site, library, and folder
  const parseSharePointUrl = (url) => {
    try {
      // Handle URLs like:
      // https://tenant.sharepoint.com/sites/SiteName/Shared%20Documents/Folder/Subfolder
      // https://tenant.sharepoint.com/sites/SiteName/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FSiteName%2FShared%20Documents%2FFolder
      // https://tenant.sharepoint.com/:f:/s/SiteName/EncodedHash?e=xxx (sharing links)
      
      let cleanUrl = decodeURIComponent(url).trim();
      
      // Handle sharing link format: /:f:/s/SiteName/hash
      const sharingMatch = cleanUrl.match(/https:\/\/([^\/]+)\/:f:\/s\/([^\/]+)\/([^?]+)/);
      if (sharingMatch) {
        const tenant = sharingMatch[1];
        const siteName = sharingMatch[2];
        const siteUrl = `https://${tenant}/sites/${siteName}`;
        
        // For sharing links, we can't decode the path - ask user to provide it
        setSourceConfig({
          siteUrl,
          libraryName: 'Shared Documents',
          folderPath: ''
        });
        setPasteUrl('');
        toast.success(`Parsed site: ${siteName}. Please enter the folder path manually below.`, {
          duration: 5000
        });
        return;
      }
      
      // Extract from ?id= parameter if present
      const idMatch = cleanUrl.match(/[?&]id=([^&]+)/);
      if (idMatch) {
        cleanUrl = decodeURIComponent(idMatch[1]);
      }
      
      // Remove query string and hash for simpler parsing
      cleanUrl = cleanUrl.split('?')[0].split('#')[0];
      
      // Extract site URL (everything up to and including /sites/SiteName)
      const siteMatch = cleanUrl.match(/(https:\/\/[^\/]+\/sites\/[^\/]+)/);
      if (!siteMatch) {
        toast.error('Could not parse SharePoint URL. Make sure it contains /sites/SiteName');
        return;
      }
      const siteUrl = siteMatch[1];
      
      // Get the path after the site
      const afterSite = cleanUrl.substring(siteUrl.length);
      const pathParts = afterSite.split('/').filter(p => p && p !== 'Forms' && p !== 'AllItems.aspx');
      
      // First part is usually the library name (Shared Documents, Documents, etc.)
      let libraryName = 'Documents';
      let folderPath = '';
      
      if (pathParts.length > 0) {
        // Handle "Shared Documents" vs "Documents"
        if (pathParts[0] === 'Shared Documents' || pathParts[0] === 'Shared%20Documents') {
          libraryName = 'Shared Documents';
          folderPath = pathParts.slice(1).join('/');
        } else {
          libraryName = pathParts[0];
          folderPath = pathParts.slice(1).join('/');
        }
      }
      
      setSourceConfig({
        siteUrl,
        libraryName,
        folderPath
      });
      setPasteUrl('');
      toast.success(`Parsed: ${siteUrl.split('/sites/')[1]} / ${libraryName} / ${folderPath || '(root)'}`);
      
    } catch (err) {
      toast.error('Failed to parse URL: ' + err.message);
    }
  };
  
  // Filters
  const [statusFilter, setStatusFilter] = useState('pending'); // Default to pending (excludes migrated)
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
      // 'pending' = all except migrated
      if (statusFilter === 'pending') {
        params.append('exclude_status', 'migrated');
      } else if (statusFilter !== 'all') {
        params.append('status', statusFilter);
      }
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
        sourceSiteUrl: sourceConfig.siteUrl,
        sourceLibraryName: sourceConfig.libraryName,
        sourceFolderPath: sourceConfig.folderPath
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
      // NEW: Excel metadata fields
      acct_type: candidate.acct_type || '',
      acct_name: candidate.acct_name || '',
      document_type: candidate.document_type || '',
      document_sub_type: candidate.document_sub_type || '',
      document_status: candidate.document_status || 'Active',
      // Legacy fields
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
            Source: {sourceConfig.siteUrl.split('/sites/')[1] || 'OneGamer'}/{sourceConfig.folderPath} → One_Gamer-Flat-Test/Documents
          </p>
        </div>
        <div className="flex gap-2">
          <Button 
            variant="outline" 
            size="sm" 
            onClick={() => setShowSourceConfig(!showSourceConfig)}
          >
            <Settings className="w-4 h-4 mr-2" />
            Configure Source
          </Button>
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
      </div>

      {/* Source Configuration */}
      {showSourceConfig && (
        <Card className="border-blue-200 bg-blue-50/50 dark:bg-blue-950/20">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-medium">Source Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Paste URL Section */}
            <div className="p-3 bg-white dark:bg-gray-900 rounded-lg border border-dashed border-blue-300">
              <Label className="text-xs font-medium text-blue-700 dark:text-blue-400">
                Quick Setup: Paste SharePoint URL
              </Label>
              <p className="text-xs text-muted-foreground mb-2">
                Copy a folder URL from SharePoint and paste it here to auto-fill the fields below
              </p>
              <div className="flex gap-2">
                <Input 
                  value={pasteUrl}
                  onChange={(e) => setPasteUrl(e.target.value)}
                  placeholder="Paste SharePoint folder URL here..."
                  className="flex-1"
                  onPaste={(e) => {
                    const pasted = e.clipboardData.getData('text');
                    if (pasted.includes('sharepoint.com')) {
                      e.preventDefault();
                      parseSharePointUrl(pasted);
                    }
                  }}
                />
                <Button 
                  size="sm" 
                  onClick={() => parseSharePointUrl(pasteUrl)}
                  disabled={!pasteUrl}
                >
                  Parse URL
                </Button>
              </div>
            </div>

            {/* Manual Configuration */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <Label className="text-xs">SharePoint Site URL</Label>
                <Input 
                  value={sourceConfig.siteUrl}
                  onChange={(e) => setSourceConfig({...sourceConfig, siteUrl: e.target.value})}
                  placeholder="https://tenant.sharepoint.com/sites/SiteName"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Library Name</Label>
                <Input 
                  value={sourceConfig.libraryName}
                  onChange={(e) => setSourceConfig({...sourceConfig, libraryName: e.target.value})}
                  placeholder="Documents"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">Folder Path (leave empty for root)</Label>
                <Input 
                  value={sourceConfig.folderPath}
                  onChange={(e) => setSourceConfig({...sourceConfig, folderPath: e.target.value})}
                  placeholder="Customer Relations"
                  className="mt-1"
                />
              </div>
            </div>
            <div className="flex justify-end">
              <Button size="sm" variant="outline" onClick={() => setShowSourceConfig(false)}>
                Done
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary Cards */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-4">
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
              <div className="text-2xl font-bold text-purple-600">
                {(summary.by_classification_source?.folder_tree || 0) + (summary.by_classification_source?.hybrid || 0)}
              </div>
              <div className="text-xs text-muted-foreground">Folder Tree Matches</div>
            </CardContent>
          </Card>
          <Card className="bg-green-50 dark:bg-green-950/30">
            <CardContent className="pt-4">
              <div className="text-2xl font-bold text-green-600">
                {Object.keys(summary.by_document_type || {}).length}
              </div>
              <div className="text-xs text-muted-foreground">Doc Types Found</div>
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
              Discover Files from {sourceConfig.folderPath || 'Root'}
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
            Source: {sourceConfig.siteUrl.split('/sites/')[1] || 'SharePoint'}/{sourceConfig.libraryName}/{sourceConfig.folderPath || '(root)'} → Target: One_Gamer-Flat-Test/Documents
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
            <SelectItem value="pending">Pending (Not Migrated)</SelectItem>
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
                <TableHead className="w-[260px]">File Name</TableHead>
                <TableHead>Source</TableHead>
                <TableHead>Acct Type</TableHead>
                <TableHead>Document Type</TableHead>
                <TableHead>Acct Name</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Confidence</TableHead>
                <TableHead>Migration</TableHead>
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
                          <div className="font-medium text-sm truncate max-w-[240px]" title={candidate.file_name}>
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
                      {candidate.acct_type && (
                        <Badge className={`text-[10px] ${ACCT_TYPE_COLORS[candidate.acct_type] || 'bg-gray-100 text-gray-600'}`}>
                          {candidate.acct_type === 'Manufacturers / Vendors' ? 'Vendor' : 
                           candidate.acct_type === 'Customer Accounts' ? 'Customer' :
                           candidate.acct_type === 'Corporate Internal' ? 'Internal' : 
                           candidate.acct_type}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell>
                      {candidate.document_type && (
                        <Badge className={`text-[10px] ${DOCUMENT_TYPE_COLORS[candidate.document_type] || 'bg-gray-100 text-gray-600'}`}>
                          {candidate.document_type.length > 20 
                            ? candidate.document_type.substring(0, 20) + '...' 
                            : candidate.document_type}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs max-w-[120px] truncate" title={candidate.acct_name}>
                      {candidate.acct_name || candidate.customer_name || candidate.vendor_name || '-'}
                    </TableCell>
                    <TableCell>
                      {candidate.document_status && (
                        <Badge className={`text-[10px] ${DOC_STATUS_COLORS[candidate.document_status] || 'bg-gray-100 text-gray-600'}`}>
                          {candidate.document_status}
                        </Badge>
                      )}
                    </TableCell>
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

              {/* Metadata Fields - NEW Excel Structure */}
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm font-medium">Metadata (Excel Structure)</div>
                  {!editMode && selectedCandidate.status !== 'migrated' && (
                    <Button variant="outline" size="sm" onClick={() => setEditMode(true)}>
                      Edit
                    </Button>
                  )}
                </div>

                <div className="grid grid-cols-2 gap-3">
                  {/* Account Type */}
                  <div>
                    <Label className="text-xs">Account Type</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.acct_type} 
                        onValueChange={(v) => setEditForm({...editForm, acct_type: v})}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select type" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Customer Accounts">Customer Accounts</SelectItem>
                          <SelectItem value="Manufacturers / Vendors">Manufacturers / Vendors</SelectItem>
                          <SelectItem value="Corporate Internal">Corporate Internal</SelectItem>
                          <SelectItem value="System Resources">System Resources</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.acct_type || '-'}</div>
                    )}
                  </div>

                  {/* Account Name */}
                  <div>
                    <Label className="text-xs">Account Name</Label>
                    {editMode ? (
                      <Input 
                        value={editForm.acct_name}
                        onChange={(e) => setEditForm({...editForm, acct_name: e.target.value})}
                        placeholder="Customer or vendor name"
                      />
                    ) : (
                      <div className="text-sm">{selectedCandidate.acct_name || '-'}</div>
                    )}
                  </div>

                  {/* Document Type (NEW - from Excel) */}
                  <div>
                    <Label className="text-xs">Document Type</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.document_type} 
                        onValueChange={(v) => setEditForm({...editForm, document_type: v})}
                      >
                        <SelectTrigger>
                          <SelectValue placeholder="Select type" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Product Specification Sheet">Product Specification Sheet</SelectItem>
                          <SelectItem value="Product Drawings">Product Drawings</SelectItem>
                          <SelectItem value="Product Pack-Out Specs">Product Pack-Out Specs</SelectItem>
                          <SelectItem value="Graphical Die Line">Graphical Die Line</SelectItem>
                          <SelectItem value="Supplier Documents">Supplier Documents</SelectItem>
                          <SelectItem value="Marketing Literature">Marketing Literature</SelectItem>
                          <SelectItem value="Capabilities / Catalogs">Capabilities / Catalogs</SelectItem>
                          <SelectItem value="SOPs / Resources">SOPs / Resources</SelectItem>
                          <SelectItem value="Customer Documents">Customer Documents</SelectItem>
                          <SelectItem value="Customer Quote">Customer Quote</SelectItem>
                          <SelectItem value="Supplier Quote">Supplier Quote</SelectItem>
                          <SelectItem value="Cost Analysis">Cost Analysis</SelectItem>
                          <SelectItem value="Agreement Resources">Agreement Resources</SelectItem>
                          <SelectItem value="Supply Agreement">Supply Agreement</SelectItem>
                          <SelectItem value="Quality Documents">Quality Documents</SelectItem>
                          <SelectItem value="Training">Training</SelectItem>
                          <SelectItem value="Other">Other</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.document_type || '-'}</div>
                    )}
                  </div>

                  {/* Document Sub Type */}
                  <div>
                    <Label className="text-xs">Document Sub Type</Label>
                    {editMode ? (
                      <Input 
                        value={editForm.document_sub_type}
                        onChange={(e) => setEditForm({...editForm, document_sub_type: e.target.value})}
                        placeholder="e.g., Beard Care, Face Care"
                      />
                    ) : (
                      <div className="text-sm">{selectedCandidate.document_sub_type || '-'}</div>
                    )}
                  </div>

                  {/* Document Status */}
                  <div>
                    <Label className="text-xs">Document Status</Label>
                    {editMode ? (
                      <Select 
                        value={editForm.document_status} 
                        onValueChange={(v) => setEditForm({...editForm, document_status: v})}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="Active">Active</SelectItem>
                          <SelectItem value="Archived">Archived</SelectItem>
                          <SelectItem value="Pending">Pending</SelectItem>
                        </SelectContent>
                      </Select>
                    ) : (
                      <div className="text-sm">{selectedCandidate.document_status || '-'}</div>
                    )}
                  </div>

                  {/* Project/Part Number */}
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

                  {/* Document Date */}
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

                  {/* Retention Category */}
                  <div>
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

                {/* Folder Tree Info (read-only) */}
                {selectedCandidate.level1 && (
                  <div className="mt-3 p-2 bg-gray-50 dark:bg-gray-800 rounded text-xs">
                    <div className="font-medium text-gray-500 mb-1">Folder Tree Path</div>
                    <div>
                      {selectedCandidate.level1}
                      {selectedCandidate.level2 && ` / ${selectedCandidate.level2}`}
                      {selectedCandidate.level3 && ` / ${selectedCandidate.level3}`}
                      {selectedCandidate.level4 && ` / ${selectedCandidate.level4}`}
                    </div>
                  </div>
                )}
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
