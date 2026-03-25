import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
  DialogDescription,
} from '../components/ui/dialog';
import { toast } from 'sonner';
import {
  Loader2, Search, RefreshCw, ChevronRight, FileText, Clock,
  AlertCircle, UserPlus, Inbox,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

export default function TriageQueuePage() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [reps, setReps] = useState([]);

  // Assign modal
  const [assignModal, setAssignModal] = useState({ open: false, docId: '', fileName: '' });
  const [assignRep, setAssignRep] = useState('');
  const [assigning, setAssigning] = useState(false);

  useEffect(() => {
    const t = setTimeout(() => setSearch(searchInput), 400);
    return () => clearTimeout(t);
  }, [searchInput]);

  // Load reps for assignment
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/sales-dashboard/reps`);
        const data = await res.json();
        setReps(data.reps || []);
      } catch { /* ignore */ }
    })();
  }, []);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ limit: '200' });
      if (search) params.set('search', search);
      const res = await fetch(`${API}/api/sales-dashboard/triage-queue?${params}`);
      const data = await res.json();
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch {
      toast.error('Failed to load triage queue');
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  const handleAssign = async () => {
    if (!assignModal.docId || !assignRep) return;
    setAssigning(true);
    try {
      const rep = reps.find(r => r.rep_email === assignRep);
      const res = await fetch(`${API}/api/sales-dashboard/queue/${assignModal.docId}/assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rep_email: assignRep, rep_name: rep?.rep_name || '' }),
      });
      if (!res.ok) throw new Error('Assign failed');
      toast.success(`Assigned to ${rep?.rep_name || assignRep}`);
      setAssignModal({ open: false, docId: '', fileName: '' });
      setAssignRep('');
      fetchQueue();
    } catch {
      toast.error('Failed to assign document');
    } finally {
      setAssigning(false);
    }
  };

  const formatDate = (d) => {
    if (!d) return '-';
    try { return new Date(d).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: '2-digit' }); } catch { return d; }
  };

  const formatAmount = (a) => {
    if (a == null) return '-';
    const num = typeof a === 'string' ? parseFloat(a.replace(/,/g, '')) : Number(a);
    if (isNaN(num)) return '-';
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  return (
    <div className="max-w-[1400px] mx-auto space-y-6" data-testid="triage-queue-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <AlertCircle className="w-5 h-5 text-orange-500" />
            Triage Queue
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Unassigned documents needing rep assignment &mdash; {total} document{total !== 1 ? 's' : ''}
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchQueue} disabled={loading} data-testid="triage-refresh-btn">
          <RefreshCw className={`w-4 h-4 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </Button>
      </div>

      {/* Search */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <Input placeholder="Search PO, customer, filename..." value={searchInput} onChange={(e) => setSearchInput(e.target.value)} className="pl-9 h-9 text-sm" data-testid="triage-search" />
        </div>
      </div>

      {/* Queue Table */}
      <Card className="border border-border" data-testid="triage-queue-table">
        <CardContent className="p-0">
          {loading && items.length === 0 ? (
            <div className="flex items-center justify-center py-16">
              <Loader2 className="w-6 h-6 animate-spin text-primary" />
            </div>
          ) : items.length === 0 ? (
            <div className="py-16 text-center text-muted-foreground">
              <Inbox className="w-10 h-10 mx-auto mb-3 opacity-20" />
              <p className="text-sm">No unassigned documents — all clear</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase tracking-wider">
                    <th className="text-left py-3 px-4 font-medium">Status</th>
                    <th className="text-left py-3 px-3 font-medium">Customer</th>
                    <th className="text-left py-3 px-3 font-medium">PO / Ext Doc</th>
                    <th className="text-left py-3 px-3 font-medium">File</th>
                    <th className="text-right py-3 px-3 font-medium">Amount</th>
                    <th className="text-left py-3 px-3 font-medium">Date</th>
                    <th className="text-right py-3 px-4 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(item => (
                    <tr key={item.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors" data-testid={`triage-row-${item.id}`}>
                      <td className="py-3 px-4">
                        <Badge variant="outline" className="text-[10px] font-medium bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 border-orange-200 dark:border-orange-700">
                          <AlertCircle className="w-3 h-3 mr-1" />
                          Unassigned
                        </Badge>
                      </td>
                      <td className="py-3 px-3">
                        {item.customer_name ? (
                          <span className="text-xs font-medium truncate block max-w-[160px]" title={item.customer_name}>{item.customer_name}</span>
                        ) : (
                          <span className="text-xs text-muted-foreground italic">Unknown</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        {item.external_doc_no ? (
                          <span className="text-xs font-mono">{item.external_doc_no}</span>
                        ) : (
                          <span className="text-xs text-muted-foreground italic">None</span>
                        )}
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1.5">
                          <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                          <span className="text-xs truncate max-w-[180px]" title={item.file_name}>{item.file_name || '-'}</span>
                        </div>
                      </td>
                      <td className="py-3 px-3 text-right">
                        <span className="text-xs font-mono font-medium">{formatAmount(item.amount)}</span>
                      </td>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-1">
                          <Clock className="w-3 h-3 text-muted-foreground" />
                          <span className="text-xs text-muted-foreground">{formatDate(item.created_utc)}</span>
                        </div>
                      </td>
                      <td className="py-3 px-4 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            variant="default"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => { setAssignModal({ open: true, docId: item.id, fileName: item.file_name }); setAssignRep(''); }}
                            data-testid={`triage-assign-${item.id}`}
                          >
                            <UserPlus className="w-3 h-3 mr-1" />
                            Assign
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            onClick={() => navigate(`/documents/${encodeURIComponent(item.id)}`)}
                          >
                            <ChevronRight className="w-3 h-3" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!loading && items.length > 0 && (
            <div className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
              {items.length} unassigned document{items.length !== 1 ? 's' : ''}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Assign Modal */}
      <Dialog open={assignModal.open} onOpenChange={(open) => { if (!open) setAssignModal({ open: false, docId: '', fileName: '' }); }}>
        <DialogContent className="sm:max-w-md" data-testid="assign-modal">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <UserPlus className="w-4 h-4 text-primary" />
              Assign Sales Rep
            </DialogTitle>
            <DialogDescription>
              Assign <span className="font-mono font-medium">{assignModal.fileName}</span> to a sales rep
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <Select value={assignRep} onValueChange={setAssignRep}>
              <SelectTrigger className="w-full" data-testid="assign-rep-select">
                <SelectValue placeholder="Select a sales rep..." />
              </SelectTrigger>
              <SelectContent>
                {reps.map(r => (
                  <SelectItem key={r.rep_email} value={r.rep_email}>
                    {r.rep_name || r.rep_email}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <DialogFooter>
            <Button variant="outline" size="sm" onClick={() => setAssignModal({ open: false, docId: '', fileName: '' })}>
              Cancel
            </Button>
            <Button size="sm" onClick={handleAssign} disabled={!assignRep || assigning} data-testid="assign-confirm-btn">
              {assigning ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <UserPlus className="w-4 h-4 mr-1.5" />}
              Assign Rep
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
