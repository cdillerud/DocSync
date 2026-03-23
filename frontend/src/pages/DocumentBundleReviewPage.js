import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { toast } from 'sonner';
import {
  PackageSearch, RefreshCw, Loader2, CheckCircle, AlertTriangle, XCircle,
  ChevronRight, FileText, Layers, ArrowUpDown, Pencil, Save, X, Plus, Trash2
} from 'lucide-react';
import { listBundles, getBundle, updateBundle, detectBundles, getBundleReviewQueue } from '@/lib/api';

const STATUS_STYLE = {
  grouped: { label: 'Grouped', cls: 'bg-blue-500/15 text-blue-400 border-blue-500/30', icon: Layers },
  needs_review: { label: 'Needs Review', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30', icon: AlertTriangle },
  complete: { label: 'Complete', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', icon: CheckCircle },
  incomplete: { label: 'Incomplete', cls: 'bg-red-500/15 text-red-400 border-red-500/30', icon: XCircle },
};

const COMP_STYLE = {
  complete: { label: 'Complete', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' },
  partial: { label: 'Partial', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  insufficient: { label: 'Insufficient', cls: 'bg-red-500/15 text-red-400 border-red-500/30' },
};

const TYPE_LABELS = {
  customer_order_packet: 'Customer Order',
  purchasing_packet: 'Purchasing',
  ap_packet: 'AP Packet',
  warehouse_packet: 'Warehouse',
  unknown: 'Unknown',
};

export default function DocumentBundleReviewPage() {
  const navigate = useNavigate();
  const [bundles, setBundles] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusCounts, setStatusCounts] = useState({});
  const [completenessCounts, setCompletenessCounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [detecting, setDetecting] = useState(false);

  const [statusFilter, setStatusFilter] = useState('all');
  const [typeFilter, setTypeFilter] = useState('all');
  const [compFilter, setCompFilter] = useState('all');

  const [selectedBundle, setSelectedBundle] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);

  // Edit state
  const [editingType, setEditingType] = useState(false);
  const [editType, setEditType] = useState('');
  const [editNotes, setEditNotes] = useState('');
  const [addDocId, setAddDocId] = useState('');
  const [saving, setSaving] = useState(false);

  const fetchBundles = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (statusFilter !== 'all') params.bundle_status = statusFilter;
      if (typeFilter !== 'all') params.bundle_type = typeFilter;
      if (compFilter !== 'all') params.completeness_status = compFilter;
      const { data } = await listBundles(params);
      setBundles(data.bundles || []);
      setTotal(data.total || 0);
      setStatusCounts(data.status_counts || {});
      setCompletenessCounts(data.completeness_counts || {});
    } catch { toast.error('Failed to load bundles'); }
    finally { setLoading(false); }
  }, [statusFilter, typeFilter, compFilter]);

  useEffect(() => { fetchBundles(); }, [fetchBundles]);

  const handleDetect = async () => {
    setDetecting(true);
    try {
      const { data } = await detectBundles({});
      toast.success(`${data.bundles_detected} bundle(s) detected from ${data.documents_scanned} documents`);
      fetchBundles();
    } catch (err) { toast.error(err.response?.data?.detail || 'Detection failed'); }
    finally { setDetecting(false); }
  };

  const openDetail = async (bundleId) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    setEditingType(false);
    try {
      const { data } = await getBundle(bundleId);
      setSelectedBundle(data);
      setEditType(data.bundle_type || '');
      setEditNotes(data.notes || '');
    } catch { toast.error('Failed to load bundle detail'); }
    finally { setDetailLoading(false); }
  };

  const handleSaveBundle = async (updates) => {
    if (!selectedBundle) return;
    setSaving(true);
    try {
      const { data } = await updateBundle(selectedBundle.bundle_id, updates);
      setSelectedBundle(prev => ({ ...prev, ...data }));
      setEditingType(false);
      toast.success('Bundle updated');
      fetchBundles();
    } catch (err) { toast.error(err.response?.data?.detail || 'Update failed'); }
    finally { setSaving(false); }
  };

  const handleRemoveDoc = async (docId) => {
    await handleSaveBundle({ remove_document_ids: [docId] });
    // Refresh detail
    if (selectedBundle) openDetail(selectedBundle.bundle_id);
  };

  const handleAddDoc = async () => {
    if (!addDocId.trim()) return;
    await handleSaveBundle({ add_document_ids: [addDocId.trim()] });
    setAddDocId('');
    if (selectedBundle) openDetail(selectedBundle.bundle_id);
  };

  const totalBundles = Object.values(statusCounts).reduce((a, b) => a + b, 0);
  const reviewCount = statusCounts.needs_review || 0;
  const incompleteCount = completenessCounts.insufficient || 0;
  const completeCount = completenessCounts.complete || 0;

  return (
    <div className="space-y-6" data-testid="document-bundles-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Bundles</h1>
          <p className="text-sm text-muted-foreground mt-1">Group related documents into transaction packets</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchBundles} disabled={loading} data-testid="refresh-bundles-btn">
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          <Button size="sm" onClick={handleDetect} disabled={detecting} data-testid="detect-bundles-btn">
            {detecting ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : <PackageSearch className="w-3.5 h-3.5 mr-1.5" />}
            Detect Bundles
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="bundle-summary-cards">
        <Card className="border-border"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">Total Bundles</p>
          <p className="text-2xl font-bold mt-1">{totalBundles}</p>
        </CardContent></Card>
        <Card className="border-amber-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-amber-400 font-bold">Needs Review</p>
          <p className="text-2xl font-bold mt-1 text-amber-400">{reviewCount}</p>
        </CardContent></Card>
        <Card className="border-red-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-red-400 font-bold">Insufficient</p>
          <p className="text-2xl font-bold mt-1 text-red-400">{incompleteCount}</p>
        </CardContent></Card>
        <Card className="border-emerald-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-emerald-400 font-bold">Complete</p>
          <p className="text-2xl font-bold mt-1 text-emerald-400">{completeCount}</p>
        </CardContent></Card>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[160px] h-8 text-xs" data-testid="status-filter"><SelectValue placeholder="Status" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            <SelectItem value="grouped">Grouped</SelectItem>
            <SelectItem value="needs_review">Needs Review</SelectItem>
            <SelectItem value="complete">Complete</SelectItem>
            <SelectItem value="incomplete">Incomplete</SelectItem>
          </SelectContent>
        </Select>
        <Select value={typeFilter} onValueChange={setTypeFilter}>
          <SelectTrigger className="w-[180px] h-8 text-xs" data-testid="type-filter"><SelectValue placeholder="Bundle Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Types</SelectItem>
            <SelectItem value="customer_order_packet">Customer Order</SelectItem>
            <SelectItem value="purchasing_packet">Purchasing</SelectItem>
            <SelectItem value="ap_packet">AP Packet</SelectItem>
            <SelectItem value="warehouse_packet">Warehouse</SelectItem>
            <SelectItem value="unknown">Unknown</SelectItem>
          </SelectContent>
        </Select>
        <Select value={compFilter} onValueChange={setCompFilter}>
          <SelectTrigger className="w-[170px] h-8 text-xs" data-testid="completeness-filter"><SelectValue placeholder="Completeness" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Completeness</SelectItem>
            <SelectItem value="complete">Complete</SelectItem>
            <SelectItem value="partial">Partial</SelectItem>
            <SelectItem value="insufficient">Insufficient</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Bundle Table */}
      <Card className="border-border">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading bundles...</div>
          ) : bundles.length === 0 ? (
            <div className="text-center py-12">
              <PackageSearch className="w-10 h-10 mx-auto mb-3 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No bundles found</p>
              <p className="text-xs text-muted-foreground/60 mt-1">Click "Detect Bundles" to scan recent documents</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid="bundles-table">
                <thead><tr className="border-b border-border bg-muted/30">
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Bundle ID</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Type</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Status</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Completeness</th>
                  <th className="text-center p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Docs</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Missing</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Updated</th>
                  <th className="p-3"></th>
                </tr></thead>
                <tbody>
                  {bundles.map((b) => {
                    const ss = STATUS_STYLE[b.bundle_status] || STATUS_STYLE.grouped;
                    const cs = COMP_STYLE[b.completeness_status] || COMP_STYLE.partial;
                    return (
                      <tr key={b.bundle_id} className="border-b border-border/50 hover:bg-accent/20 cursor-pointer transition-colors" onClick={() => openDetail(b.bundle_id)} data-testid={`bundle-row-${b.bundle_id}`}>
                        <td className="p-3 font-mono font-semibold">{b.bundle_id}</td>
                        <td className="p-3"><Badge variant="secondary" className="text-[9px]">{TYPE_LABELS[b.bundle_type] || b.bundle_type}</Badge></td>
                        <td className="p-3"><Badge variant="outline" className={`text-[9px] ${ss.cls}`}>{ss.label}</Badge></td>
                        <td className="p-3"><Badge variant="outline" className={`text-[9px] ${cs.cls}`}>{cs.label}</Badge></td>
                        <td className="p-3 text-center font-mono">{b.document_count}</td>
                        <td className="p-3 max-w-[200px]">
                          {b.missing_expected_documents?.length > 0 ? (
                            <span className="text-[10px] text-red-400 truncate block">{b.missing_expected_documents[0]}</span>
                          ) : <span className="text-[10px] text-emerald-400">None</span>}
                        </td>
                        <td className="p-3 text-[10px] text-muted-foreground font-mono">{b.updated_at ? new Date(b.updated_at).toLocaleDateString() : '—'}</td>
                        <td className="p-3"><ChevronRight className="w-3.5 h-3.5 text-muted-foreground" /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Bundle Detail Drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto" data-testid="bundle-detail-drawer">
          <SheetHeader>
            <SheetTitle className="text-sm font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Bundle Detail
            </SheetTitle>
          </SheetHeader>

          {detailLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : selectedBundle ? (
            <div className="space-y-4 mt-4 text-sm">
              {/* Header */}
              <div className="flex items-center justify-between">
                <span className="font-mono font-bold text-sm">{selectedBundle.bundle_id}</span>
                <div className="flex gap-1.5">
                  {(() => { const ss = STATUS_STYLE[selectedBundle.bundle_status] || STATUS_STYLE.grouped; return <Badge variant="outline" className={`text-[9px] ${ss.cls}`}>{ss.label}</Badge>; })()}
                  {(() => { const cs = COMP_STYLE[selectedBundle.completeness_status] || COMP_STYLE.partial; return <Badge variant="outline" className={`text-[9px] ${cs.cls}`}>{cs.label}</Badge>; })()}
                </div>
              </div>

              {/* Type */}
              <div className="p-3 bg-accent/30 rounded-lg">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold">Bundle Type</p>
                    {editingType ? (
                      <Select value={editType} onValueChange={setEditType}>
                        <SelectTrigger className="w-[200px] h-7 text-xs mt-1"><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {Object.entries(TYPE_LABELS).map(([k, v]) => <SelectItem key={k} value={k}>{v}</SelectItem>)}
                        </SelectContent>
                      </Select>
                    ) : (
                      <p className="text-xs font-semibold mt-0.5">{TYPE_LABELS[selectedBundle.bundle_type] || selectedBundle.bundle_type}</p>
                    )}
                  </div>
                  {editingType ? (
                    <div className="flex gap-1">
                      <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => handleSaveBundle({ bundle_type: editType })} disabled={saving} data-testid="save-type-btn">
                        {saving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                      </Button>
                      <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditingType(false)}><X className="w-3 h-3" /></Button>
                    </div>
                  ) : (
                    <Button size="sm" variant="ghost" className="h-6 text-xs" onClick={() => setEditingType(true)} data-testid="edit-type-btn"><Pencil className="w-3 h-3" /></Button>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground mt-1">Grouping: <span className="font-mono">{selectedBundle.grouping_basis}</span></p>
                <p className="text-[10px] text-muted-foreground">Confidence: <span className="font-mono">{((selectedBundle.grouping_confidence || 0) * 100).toFixed(0)}%</span></p>
              </div>

              {/* Next Action */}
              {selectedBundle.suggested_next_action && (
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/30 rounded-lg">
                  <p className="text-[10px] uppercase tracking-wider text-blue-400 font-bold">Suggested Next Action</p>
                  <p className="text-xs mt-0.5">{selectedBundle.suggested_next_action}</p>
                </div>
              )}

              {/* Missing Documents */}
              {selectedBundle.missing_expected_documents?.length > 0 && (
                <div className="p-2.5 bg-red-500/5 border border-red-500/30 rounded-lg" data-testid="missing-documents">
                  <p className="text-[10px] uppercase tracking-wider text-red-400 font-bold mb-1">Missing Documents</p>
                  {selectedBundle.missing_expected_documents.map((m, i) => (
                    <div key={i} className="flex items-center gap-1.5 mt-1">
                      <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                      <span className="text-[11px] text-red-300">{m}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Member Documents */}
              <div data-testid="member-documents">
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Member Documents ({selectedBundle.member_documents?.length || 0})</p>
                <div className="space-y-1.5">
                  {(selectedBundle.member_documents || []).map((doc) => (
                    <div key={doc.document_id} className="flex items-center gap-2 p-2 bg-accent/20 rounded border border-border/50 group" data-testid={`member-doc-${doc.document_id}`}>
                      <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                      <div className="flex-1 min-w-0">
                        <p className="text-[11px] font-medium truncate">{doc.file_name || doc.document_id}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <Badge variant="secondary" className="text-[8px]">{doc.document_type}</Badge>
                          {doc.automation_readiness && (
                            <Badge variant="outline" className={`text-[8px] ${doc.automation_readiness === 'ready' ? 'border-emerald-500/30 text-emerald-400' : doc.automation_readiness === 'blocked' ? 'border-red-500/30 text-red-400' : 'border-amber-500/30 text-amber-400'}`}>
                              {doc.automation_readiness}
                            </Badge>
                          )}
                        </div>
                      </div>
                      <Button variant="ghost" size="sm" className="h-6 text-[9px] opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); navigate(`/documents/${encodeURIComponent(doc.document_id)}`); }}>
                        <ChevronRight className="w-3 h-3" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 text-[9px] text-red-400 opacity-0 group-hover:opacity-100" onClick={(e) => { e.stopPropagation(); handleRemoveDoc(doc.document_id); }} data-testid={`remove-doc-${doc.document_id}`}>
                        <Trash2 className="w-3 h-3" />
                      </Button>
                    </div>
                  ))}
                </div>

                {/* Add document */}
                <div className="flex items-center gap-2 mt-2">
                  <Input value={addDocId} onChange={e => setAddDocId(e.target.value)} placeholder="Document ID to add..." className="h-7 text-xs flex-1" data-testid="add-doc-input" />
                  <Button size="sm" variant="outline" className="h-7 text-xs" onClick={handleAddDoc} disabled={!addDocId.trim()} data-testid="add-doc-btn">
                    <Plus className="w-3 h-3 mr-1" /> Add
                  </Button>
                </div>
              </div>

              {/* Detected Keys */}
              {selectedBundle.detected_keys && Object.keys(selectedBundle.detected_keys).length > 0 && (
                <div>
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Detected Keys</p>
                  <div className="grid grid-cols-2 gap-1.5">
                    {Object.entries(selectedBundle.detected_keys).map(([k, v]) => (
                      <div key={k} className="p-1.5 bg-accent/20 rounded">
                        <p className="text-[9px] text-muted-foreground">{k}</p>
                        <p className="text-[10px] font-mono font-semibold truncate">{String(v)}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Notes */}
              <div>
                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-1">Notes</p>
                <Input value={editNotes} onChange={e => setEditNotes(e.target.value)} placeholder="Add notes..." className="h-7 text-xs" data-testid="bundle-notes-input" />
                <Button size="sm" variant="outline" className="h-6 text-xs mt-1" onClick={() => handleSaveBundle({ notes: editNotes })} data-testid="save-notes-btn">
                  <Save className="w-3 h-3 mr-1" /> Save Notes
                </Button>
              </div>

              {/* Actions */}
              <div className="flex gap-2 pt-2 border-t border-border">
                {selectedBundle.bundle_status === 'needs_review' && (
                  <Button size="sm" className="text-xs bg-emerald-600 hover:bg-emerald-700" onClick={() => handleSaveBundle({ bundle_status: 'grouped' })} data-testid="mark-reviewed-btn">
                    <CheckCircle className="w-3 h-3 mr-1" /> Mark Reviewed
                  </Button>
                )}
                {selectedBundle.completeness_status === 'complete' && selectedBundle.bundle_status !== 'complete' && (
                  <Button size="sm" className="text-xs" onClick={() => handleSaveBundle({ bundle_status: 'complete' })} data-testid="mark-complete-btn">
                    <CheckCircle className="w-3 h-3 mr-1" /> Mark Complete
                  </Button>
                )}
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
