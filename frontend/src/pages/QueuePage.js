import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { listDocuments, deleteDocument } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Tabs, TabsList, TabsTrigger } from '../components/ui/tabs';
import { Badge } from '../components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import { Search, RefreshCw, FileText, ExternalLink, Filter, RotateCcw, Trash2, FolderOpen } from 'lucide-react';

const STATUS_CLASSES = {
  Received: 'status-received',
  Classified: 'status-classified',
  LinkedToBC: 'status-linked',
  Exception: 'status-exception',
  Completed: 'status-completed',
  NeedsReview: 'status-classified',
  StoredInSP: 'status-classified',
  ReadyToLink: 'status-linked',
};

const CATEGORY_COLORS = {
  AP: 'bg-blue-100 text-blue-800 border-blue-200',
  Sales: 'bg-emerald-100 text-emerald-800 border-emerald-200',
  Unknown: 'bg-gray-100 text-gray-600 border-gray-200',
};

const ALL_STATUSES = ['All', 'Received', 'Classified', 'NeedsReview', 'StoredInSP', 'LinkedToBC', 'Exception', 'Completed'];
const ALL_CATEGORIES = ['All', 'AP', 'Sales'];

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

function formatSize(bytes) {
  if (!bytes) return '-';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1048576).toFixed(1) + ' MB';
}

export default function QueuePage() {
  const [docs, setDocs] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('All');
  const [categoryFilter, setCategoryFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const navigate = useNavigate();
  const limit = 20;

  const fetchDocs = async () => {
    setLoading(true);
    try {
      const params = { skip: page * limit, limit };
      if (statusFilter !== 'All') params.status = statusFilter;
      if (categoryFilter !== 'All') params.category = categoryFilter;
      if (search) params.search = search;
      const res = await listDocuments(params);
      setDocs(res.data.documents || []);
      setTotal(res.data.total || 0);
    } catch (err) {
      toast.error('Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDocs(); }, [statusFilter, categoryFilter, page]);

  const handleSearch = (e) => {
    e.preventDefault();
    setPage(0);
    fetchDocs();
  };

  const handleDelete = async (e, docId, fileName) => {
    e.stopPropagation();
    if (!window.confirm(`Delete "${fileName}"? This will remove the document, its workflows, and stored file.`)) return;
    try {
      await deleteDocument(docId);
      toast.success('Document deleted');
      fetchDocs();
    } catch (err) {
      toast.error('Delete failed: ' + (err.response?.data?.detail || err.message));
    }
  };

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto" data-testid="queue-page">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Queue</h2>
          <p className="text-sm text-muted-foreground mt-0.5">{total} document{total !== 1 ? 's' : ''} total</p>
        </div>
        <div className="flex items-center gap-2">
          <form onSubmit={handleSearch} className="flex gap-2">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                className="pl-9 w-64"
                placeholder="Search by filename..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                data-testid="queue-search-input"
              />
            </div>
            <Button variant="secondary" type="submit" data-testid="queue-search-btn">
              <Filter className="w-4 h-4" />
            </Button>
          </form>
          <Button variant="ghost" size="icon" onClick={fetchDocs} data-testid="queue-refresh-btn">
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </Button>
        </div>
      </div>

      {/* Category Filter + Status Tabs */}
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2">
          <FolderOpen className="w-4 h-4 text-muted-foreground" />
          <Select value={categoryFilter} onValueChange={(val) => { setCategoryFilter(val); setPage(0); }}>
            <SelectTrigger className="w-32" data-testid="category-filter">
              <SelectValue placeholder="Category" />
            </SelectTrigger>
            <SelectContent>
              {ALL_CATEGORIES.map((c) => (
                <SelectItem key={c} value={c}>{c === 'All' ? 'All Categories' : c}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Tabs value={statusFilter} onValueChange={(val) => { setStatusFilter(val); setPage(0); }}>
          <TabsList data-testid="queue-status-tabs">
            {ALL_STATUSES.map((s) => (
              <TabsTrigger key={s} value={s} data-testid={`queue-tab-${s.toLowerCase()}`} className="text-xs">
                {s === 'LinkedToBC' ? 'Linked' : s === 'NeedsReview' ? 'Review' : s === 'StoredInSP' ? 'Stored' : s}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* Documents Table */}
      <Card className="border border-border" data-testid="queue-table-card">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-16">
              <RefreshCw className="w-5 h-5 animate-spin text-primary" />
            </div>
          ) : docs.length > 0 ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="text-xs uppercase tracking-wider">File</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider">Category</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider">Type</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider">Status</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider hidden md:table-cell">BC Ref</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider hidden lg:table-cell">Size</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider hidden md:table-cell">Created</TableHead>
                  <TableHead className="text-xs uppercase tracking-wider text-right">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {docs.map((doc) => (
                  <TableRow
                    key={doc.id}
                    className="cursor-pointer"
                    onClick={() => navigate(`/documents/${doc.id}`)}
                    data-testid={`queue-row-${doc.id}`}
                  >
                    <TableCell>
                      <div className="flex items-center gap-2.5">
                        <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
                        <div className="min-w-0">
                          <p className="text-sm font-medium truncate max-w-[200px]">{doc.file_name}</p>
                          <p className="text-xs text-muted-foreground font-mono">{doc.id.slice(0, 8)}...</p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-xs ${CATEGORY_COLORS[doc.category] || CATEGORY_COLORS.Unknown}`}>
                        {doc.category || 'AP'}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary" className="text-xs">{doc.document_type}</Badge>
                    </TableCell>
                    <TableCell>
                      <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold ${STATUS_CLASSES[doc.status] || ''}`}>
                        {doc.status}
                      </span>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <span className="font-mono text-xs">{doc.bc_document_no || '-'}</span>
                    </TableCell>
                    <TableCell className="hidden lg:table-cell text-xs text-muted-foreground">
                      {formatSize(doc.file_size)}
                    </TableCell>
                    <TableCell className="hidden md:table-cell text-xs text-muted-foreground font-mono">
                      {formatDate(doc.created_utc)}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        {doc.status === 'Exception' && (
                          <Button
                            variant="ghost" size="sm" className="h-7 text-xs text-destructive hover:text-destructive"
                            onClick={(e) => { e.stopPropagation(); navigate(`/documents/${doc.id}`); }}
                            data-testid={`resubmit-doc-${doc.id}`}
                          >
                            <RotateCcw className="w-3 h-3 mr-1" /> Re-submit
                          </Button>
                        )}
                        <Button
                          variant="ghost" size="sm" className="h-7 text-xs"
                          onClick={(e) => { e.stopPropagation(); navigate(`/documents/${doc.id}`); }}
                          data-testid={`view-doc-${doc.id}`}
                        >
                          <ExternalLink className="w-3 h-3 mr-1" /> View
                        </Button>
                        <Button
                          variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                          onClick={(e) => handleDelete(e, doc.id, doc.file_name)}
                          data-testid={`delete-doc-${doc.id}`}
                        >
                          <Trash2 className="w-3 h-3" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <div className="py-16 text-center">
              <FileText className="w-10 h-10 text-muted-foreground/40 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">No documents found</p>
              <Button variant="ghost" className="mt-2 text-primary text-sm" onClick={() => navigate('/upload')} data-testid="queue-empty-upload-btn">
                Upload your first document
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between" data-testid="queue-pagination">
          <p className="text-xs text-muted-foreground">
            Showing {page * limit + 1}-{Math.min((page + 1) * limit, total)} of {total}
          </p>
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)} data-testid="queue-prev-btn">
              Previous
            </Button>
            <Button variant="secondary" size="sm" disabled={(page + 1) * limit >= total} onClick={() => setPage(page + 1)} data-testid="queue-next-btn">
              Next
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
