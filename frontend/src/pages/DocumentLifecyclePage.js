import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { toast } from 'sonner';
import {
  Activity, RefreshCw, Loader2, CheckCircle, AlertTriangle, XCircle, Copy,
  ChevronRight, FileText, ShieldAlert, ArrowRight
} from 'lucide-react';
import { getLifecycleIssues, getLifecycle, validateLifecycle } from '@/lib/api';

const STATUS_STYLE = {
  valid: { label: 'Valid', cls: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30', icon: CheckCircle },
  incomplete: { label: 'Incomplete', cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30', icon: AlertTriangle },
  duplicate_detected: { label: 'Duplicate', cls: 'bg-red-500/15 text-red-400 border-red-500/30', icon: Copy },
  inconsistent: { label: 'Inconsistent', cls: 'bg-orange-500/15 text-orange-400 border-orange-500/30', icon: ShieldAlert },
  needs_review: { label: 'Needs Review', cls: 'bg-blue-500/15 text-blue-400 border-blue-500/30', icon: AlertTriangle },
};

const STAGE_LABELS = {
  order_received: 'Order Received', order_created: 'Order Created', proofing: 'Proofing',
  shipped: 'Shipped', invoiced: 'Invoiced', po_created: 'PO Created', po_drafted: 'PO Drafted',
  received: 'Received', vendor_invoiced: 'Vendor Invoiced', invoice_received: 'Invoice Received',
  receiving_support: 'Receiving Support', ap_drafted: 'AP Drafted', unknown: 'Unknown',
};

export default function DocumentLifecyclePage() {
  const [issues, setIssues] = useState([]);
  const [total, setTotal] = useState(0);
  const [statusCounts, setStatusCounts] = useState({});
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState('all');
  const [entityTypeFilter, setEntityTypeFilter] = useState('all');

  const [selectedIssue, setSelectedIssue] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [validating, setValidating] = useState(null);

  const fetchIssues = useCallback(async () => {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (statusFilter !== 'all') params.issue_type = statusFilter;
      if (entityTypeFilter !== 'all') params.entity_type = entityTypeFilter;
      const { data } = await getLifecycleIssues(params);
      setIssues(data.issues || []);
      setTotal(data.total || 0);
      setStatusCounts(data.status_counts || {});
    } catch { toast.error('Failed to load lifecycle issues'); }
    finally { setLoading(false); }
  }, [statusFilter, entityTypeFilter]);

  useEffect(() => { fetchIssues(); }, [fetchIssues]);

  const openDetail = async (issue) => {
    setDrawerOpen(true);
    setDetailLoading(true);
    try {
      const { data } = await getLifecycle(issue.entity_type, issue.entity_id);
      setSelectedIssue(data);
    } catch {
      setSelectedIssue(issue);
    }
    setDetailLoading(false);
  };

  const handleRevalidate = async (entityType, entityId) => {
    setValidating(entityId);
    try {
      const { data } = await validateLifecycle(entityType, entityId);
      toast.success(`Validation: ${data.validation_status}`);
      setSelectedIssue(data);
      fetchIssues();
    } catch (err) { toast.error(err.response?.data?.detail || 'Validation failed'); }
    finally { setValidating(null); }
  };

  const totalAll = Object.values(statusCounts).reduce((a, b) => a + b, 0);
  const validCount = statusCounts.valid || 0;
  const incompleteCount = statusCounts.incomplete || 0;
  const dupCount = statusCounts.duplicate_detected || 0;
  const inconsistentCount = statusCounts.inconsistent || 0;

  return (
    <div className="space-y-6" data-testid="document-lifecycle-page">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Lifecycle</h1>
          <p className="text-sm text-muted-foreground mt-1">Validate transaction document completeness and consistency</p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchIssues} disabled={loading} data-testid="refresh-lifecycle-btn">
          <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3" data-testid="lifecycle-summary-cards">
        <Card className="border-border"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">Total Validated</p>
          <p className="text-2xl font-bold mt-1">{totalAll}</p>
        </CardContent></Card>
        <Card className="border-emerald-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-emerald-400 font-bold">Valid</p>
          <p className="text-2xl font-bold mt-1 text-emerald-400">{validCount}</p>
        </CardContent></Card>
        <Card className="border-amber-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-amber-400 font-bold">Incomplete</p>
          <p className="text-2xl font-bold mt-1 text-amber-400">{incompleteCount}</p>
        </CardContent></Card>
        <Card className="border-red-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-red-400 font-bold">Duplicates</p>
          <p className="text-2xl font-bold mt-1 text-red-400">{dupCount}</p>
        </CardContent></Card>
        <Card className="border-orange-500/30"><CardContent className="p-4">
          <p className="text-[10px] uppercase tracking-wider text-orange-400 font-bold">Inconsistent</p>
          <p className="text-2xl font-bold mt-1 text-orange-400">{inconsistentCount}</p>
        </CardContent></Card>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[170px] h-8 text-xs" data-testid="lifecycle-status-filter"><SelectValue placeholder="Issue Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Issues</SelectItem>
            <SelectItem value="incomplete">Incomplete</SelectItem>
            <SelectItem value="duplicate_detected">Duplicates</SelectItem>
            <SelectItem value="inconsistent">Inconsistent</SelectItem>
            <SelectItem value="needs_review">Needs Review</SelectItem>
          </SelectContent>
        </Select>
        <Select value={entityTypeFilter} onValueChange={setEntityTypeFilter}>
          <SelectTrigger className="w-[180px] h-8 text-xs" data-testid="lifecycle-entity-filter"><SelectValue placeholder="Entity Type" /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Entity Types</SelectItem>
            <SelectItem value="so_draft">Sales Order</SelectItem>
            <SelectItem value="po_draft">Purchasing</SelectItem>
            <SelectItem value="ap_intake_draft">AP</SelectItem>
            <SelectItem value="customer_order_packet">Customer Order Packet</SelectItem>
            <SelectItem value="ap_packet">AP Packet</SelectItem>
            <SelectItem value="purchasing_packet">Purchasing Packet</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {/* Issues Table */}
      <Card className="border-border">
        <CardContent className="p-0">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-muted-foreground"><Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...</div>
          ) : issues.length === 0 ? (
            <div className="text-center py-12">
              <Activity className="w-10 h-10 mx-auto mb-3 text-muted-foreground/40" />
              <p className="text-sm text-muted-foreground">No lifecycle issues found</p>
              <p className="text-xs text-muted-foreground/60 mt-1">Run lifecycle validation on entities to detect issues</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs" data-testid="lifecycle-issues-table">
                <thead><tr className="border-b border-border bg-muted/30">
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Entity</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Type</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Status</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Stage</th>
                  <th className="text-center p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Docs</th>
                  <th className="text-left p-3 font-semibold text-muted-foreground uppercase tracking-wider text-[10px]">Issue</th>
                  <th className="p-3"></th>
                </tr></thead>
                <tbody>
                  {issues.map((issue) => {
                    const ss = STATUS_STYLE[issue.validation_status] || STATUS_STYLE.needs_review;
                    const Icon = ss.icon;
                    return (
                      <tr key={`${issue.entity_type}-${issue.entity_id}`} className="border-b border-border/50 hover:bg-accent/20 cursor-pointer transition-colors" onClick={() => openDetail(issue)} data-testid={`lifecycle-row-${issue.entity_id}`}>
                        <td className="p-3 font-mono font-semibold text-[11px]">{issue.entity_id}</td>
                        <td className="p-3"><Badge variant="secondary" className="text-[9px]">{issue.entity_type}</Badge></td>
                        <td className="p-3"><Badge variant="outline" className={`text-[9px] ${ss.cls}`}><Icon className="w-2.5 h-2.5 mr-1 inline" />{ss.label}</Badge></td>
                        <td className="p-3 text-[11px]">{STAGE_LABELS[issue.detected_stage] || issue.detected_stage}</td>
                        <td className="p-3 text-center font-mono">{issue.document_count || 0}</td>
                        <td className="p-3 max-w-[250px]">
                          {issue.validation_messages?.length > 0 && (
                            <span className="text-[10px] text-muted-foreground truncate block">{issue.validation_messages[0]}</span>
                          )}
                        </td>
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

      {/* Detail Drawer */}
      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent className="w-full sm:max-w-lg overflow-y-auto" data-testid="lifecycle-detail-drawer">
          <SheetHeader>
            <SheetTitle className="text-sm font-bold uppercase tracking-wider" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Lifecycle Detail
            </SheetTitle>
          </SheetHeader>

          {detailLoading ? (
            <div className="flex items-center justify-center py-12"><Loader2 className="w-5 h-5 animate-spin" /></div>
          ) : selectedIssue ? (
            <div className="space-y-4 mt-4 text-sm">
              {/* Header */}
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-mono font-bold text-sm">{selectedIssue.entity_id}</span>
                  <Badge variant="secondary" className="text-[9px] ml-2">{selectedIssue.entity_type}</Badge>
                </div>
                {(() => { const ss = STATUS_STYLE[selectedIssue.validation_status] || STATUS_STYLE.needs_review; return <Badge variant="outline" className={`text-[9px] ${ss.cls}`}>{ss.label}</Badge>; })()}
              </div>

              {/* Stage Progress */}
              <div className="p-3 bg-accent/30 rounded-lg" data-testid="lifecycle-stage-section">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider font-bold mb-2">Lifecycle Stage</p>
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className="text-[10px] border-emerald-500/30 text-emerald-400">
                    {STAGE_LABELS[selectedIssue.detected_stage] || selectedIssue.detected_stage}
                  </Badge>
                  {selectedIssue.expected_next_stage && (
                    <>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <Badge variant="outline" className="text-[10px] border-blue-500/30 text-blue-400">
                        Next: {STAGE_LABELS[selectedIssue.expected_next_stage] || selectedIssue.expected_next_stage}
                      </Badge>
                    </>
                  )}
                </div>
                {selectedIssue.completed_stages?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-2">
                    {selectedIssue.completed_stages.map((s, i) => (
                      <Badge key={i} variant="secondary" className="text-[8px] bg-emerald-500/10 text-emerald-400">{STAGE_LABELS[s] || s}</Badge>
                    ))}
                  </div>
                )}
                <p className="text-[10px] text-muted-foreground mt-1">Template: {selectedIssue.lifecycle_template}</p>
              </div>

              {/* Recommended Action */}
              {selectedIssue.recommended_next_action && (
                <div className="p-2.5 bg-blue-500/10 border border-blue-500/30 rounded-lg" data-testid="lifecycle-next-action">
                  <p className="text-[10px] uppercase tracking-wider text-blue-400 font-bold">Recommended Action</p>
                  <p className="text-xs mt-0.5">{selectedIssue.recommended_next_action}</p>
                </div>
              )}

              {/* Missing Documents */}
              {selectedIssue.missing_documents?.length > 0 && (
                <div className="p-2.5 bg-amber-500/5 border border-amber-500/30 rounded-lg" data-testid="lifecycle-missing-docs">
                  <p className="text-[10px] uppercase tracking-wider text-amber-400 font-bold mb-1">Missing Documents</p>
                  {selectedIssue.missing_documents.map((m, i) => (
                    <div key={i} className="flex items-center gap-1.5 mt-1">
                      <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0" />
                      <span className="text-[11px] text-amber-300">{m.message || m.label}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Duplicates */}
              {selectedIssue.duplicate_documents?.length > 0 && (
                <div className="p-2.5 bg-red-500/5 border border-red-500/30 rounded-lg" data-testid="lifecycle-duplicates">
                  <p className="text-[10px] uppercase tracking-wider text-red-400 font-bold mb-1">Duplicate Documents</p>
                  {selectedIssue.duplicate_documents.map((d, i) => (
                    <div key={i} className="flex items-center gap-1.5 mt-1">
                      <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                      <span className="text-[11px] text-red-300">{d.message}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Inconsistencies */}
              {selectedIssue.inconsistent_references?.length > 0 && (
                <div className="p-2.5 bg-orange-500/5 border border-orange-500/30 rounded-lg" data-testid="lifecycle-inconsistencies">
                  <p className="text-[10px] uppercase tracking-wider text-orange-400 font-bold mb-1">Inconsistencies</p>
                  {selectedIssue.inconsistent_references.map((inc, i) => (
                    <div key={i} className="flex items-center gap-1.5 mt-1">
                      <ShieldAlert className="w-3 h-3 text-orange-400 shrink-0" />
                      <span className="text-[11px] text-orange-300">{inc.message}</span>
                    </div>
                  ))}
                </div>
              )}

              {/* Validation Messages */}
              {selectedIssue.validation_messages?.length > 0 && (
                <div data-testid="lifecycle-messages">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-1">Validation Messages</p>
                  {selectedIssue.validation_messages.map((msg, i) => (
                    <p key={i} className="text-[10px] text-muted-foreground mt-0.5">{msg}</p>
                  ))}
                </div>
              )}

              {/* Documents */}
              {selectedIssue.documents?.length > 0 && (
                <div data-testid="lifecycle-documents">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Documents ({selectedIssue.documents.length})</p>
                  <div className="space-y-1.5">
                    {selectedIssue.documents.map((doc) => (
                      <div key={doc.document_id} className="flex items-center gap-2 p-1.5 bg-accent/20 rounded border border-border/50">
                        <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
                        <span className="text-[11px] font-mono truncate flex-1">{doc.file_name || doc.document_id}</span>
                        <Badge variant="secondary" className="text-[8px]">{doc.document_type}</Badge>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Re-validate */}
              <div className="pt-2 border-t border-border">
                <Button size="sm" variant="outline" className="text-xs" onClick={() => handleRevalidate(selectedIssue.entity_type, selectedIssue.entity_id)} disabled={validating === selectedIssue.entity_id} data-testid="revalidate-btn">
                  {validating === selectedIssue.entity_id ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <RefreshCw className="w-3 h-3 mr-1" />}
                  Re-validate Lifecycle
                </Button>
                <p className="text-[9px] text-muted-foreground mt-1">
                  Last validated: {selectedIssue.validated_at ? new Date(selectedIssue.validated_at).toLocaleString() : '—'} by {selectedIssue.validated_by || '—'}
                </p>
              </div>
            </div>
          ) : null}
        </SheetContent>
      </Sheet>
    </div>
  );
}
