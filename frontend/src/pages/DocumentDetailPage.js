import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { getDocument, linkDocument, updateDocument, resubmitDocument, refreshDocumentState } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import {
  ArrowLeft, ExternalLink, Link, RefreshCw, FileText,
  CheckCircle2, AlertCircle, Clock, Loader2, Copy, RotateCcw, 
  ShieldCheck, ShieldAlert, Building2, FileSearch, Receipt,
  Zap, User, Cpu, Eye, Inbox, Check, XCircle, AlertTriangle
} from 'lucide-react';
import { Square9WorkflowTracker } from '../components/Square9WorkflowTracker';
import APReviewPanel from '../components/APReviewPanel';
import PDFPreviewPanel from '../components/PDFPreviewPanel';
import ReferenceIntelligencePanel from '../components/ReferenceIntelligencePanel';
import FreightGLRoutingPanel from '../components/FreightGLRoutingPanel';
import APValidationPanel from '../components/APValidationPanel';
import MatchingDebugPanel from '../components/MatchingDebugPanel';
import CreateBCSalesOrderPanel from '../components/CreateBCSalesOrderPanel';
import CreateBCPurchaseInvoicePanel from '../components/CreateBCPurchaseInvoicePanel';

const STATUS_CLASSES = {
  Received: 'status-received',
  Classified: 'status-classified',
  LinkedToBC: 'status-linked',
  Exception: 'status-exception',
  Completed: 'status-completed',
};

const DOC_TYPES = ['SalesOrder', 'SalesInvoice', 'PurchaseInvoice', 'PurchaseOrder', 'Shipment', 'Receipt', 'Other'];

const STEP_ICONS = {
  completed: <CheckCircle2 className="w-4 h-4 text-emerald-500" />,
  failed: <AlertCircle className="w-4 h-4 text-red-500" />,
  warning: <AlertCircle className="w-4 h-4 text-amber-500" />,
  running: <Loader2 className="w-4 h-4 text-blue-500 animate-spin" />,
};

// State badge configurations
const STATE_BADGE_COLORS = {
  validation_state: {
    pending: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    pass: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    warning: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    fail: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
  },
  workflow_state: {
    received: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    processing: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    reviewing: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    ready: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    completed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    failed: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400'
  },
  automation_state: {
    manual: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    assisted: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    autonomous: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400'
  }
};

const STATE_ICONS = {
  validation_state: { pending: Clock, pass: CheckCircle2, warning: AlertTriangle, fail: XCircle },
  workflow_state: { received: Inbox, processing: Loader2, reviewing: Eye, ready: Check, completed: CheckCircle2, failed: XCircle },
  automation_state: { manual: User, assisted: Cpu, autonomous: Zap }
};

function formatDate(iso) {
  if (!iso) return '-';
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

const ROUTING_STYLES = {
  auto_ready: { label: 'Auto Ready', classes: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700' },
  low_priority_review: { label: 'Low Priority', classes: 'bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300 border-sky-300 dark:border-sky-700' },
  manual_review: { label: 'Manual Review', classes: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300 border-gray-300 dark:border-gray-600' },
};

function RoutingBadge({ routing, className = '' }) {
  const style = ROUTING_STYLES[routing] || ROUTING_STYLES.manual_review;
  return (
    <Badge data-testid={`routing-badge-${routing}`} className={`text-[10px] font-semibold border ${style.classes} ${className}`}>
      {style.label}
    </Badge>
  );
}

export default function DocumentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [doc, setDoc] = useState(null);
  const [workflows, setWorkflows] = useState([]);
  const [eventTimeline, setEventTimeline] = useState([]);
  const [derivedState, setDerivedState] = useState(null);
  const [loading, setLoading] = useState(true);
  const [linking, setLinking] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState({});
  const [resubmitting, setResubmitting] = useState(false);
  const [showLegacyWorkflows, setShowLegacyWorkflows] = useState(false);

  const fetchDoc = async () => {
    try {
      const res = await getDocument(id);
      setDoc(res.data.document);
      setWorkflows(res.data.workflows || []);
      setEventTimeline(res.data.event_timeline || []);
      setDerivedState(res.data.derived_state);
    } catch (err) {
      toast.error('Document not found');
      navigate('/queue');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchDoc(); }, [id]);

  const handleLink = async () => {
    setLinking(true);
    try {
      const res = await linkDocument(id);
      toast.success('Document linked to BC');
      setDoc(res.data.document);
      fetchDoc();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Link failed');
    } finally {
      setLinking(false);
    }
  };

  const handleSaveEdit = async () => {
    try {
      const updated = await updateDocument(id, editData);
      setDoc(updated.data);
      setEditing(false);
      toast.success('Document updated');
    } catch (err) {
      toast.error('Update failed');
    }
  };

  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    toast.success('Copied to clipboard');
  };

  const handleResubmit = async () => {
    setResubmitting(true);
    try {
      const res = await resubmitDocument(id);
      toast.success('Document re-submitted successfully');
      setDoc(res.data.document);
      fetchDoc();
    } catch (err) {
      toast.error('Re-submit failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setResubmitting(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="doc-detail-loading">
        <RefreshCw className="w-6 h-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!doc) return null;

  return (
    <div className="max-w-[1600px] mx-auto" data-testid="document-detail-page">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Button variant="ghost" size="icon" onClick={() => navigate('/queue')} data-testid="back-to-queue-btn">
          <ArrowLeft className="w-4 h-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-3">
            <h2 className="text-2xl font-bold tracking-tight truncate" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {doc.file_name}
            </h2>
            <span className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-semibold shrink-0 ${
              derivedState ? (
                derivedState.validation_state === 'pass' ? 'bg-emerald-100 text-emerald-700 border-emerald-300 dark:bg-emerald-900/30 dark:text-emerald-400 dark:border-emerald-700' :
                derivedState.validation_state === 'warning' ? 'bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-400 dark:border-amber-700' :
                derivedState.validation_state === 'fail' ? 'bg-red-100 text-red-700 border-red-300 dark:bg-red-900/30 dark:text-red-400 dark:border-red-700' :
                'bg-gray-100 text-gray-700 border-gray-300 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600'
              ) : (STATUS_CLASSES[doc.status] || '')
            }`} data-testid="doc-status-badge">
              {derivedState ? (
                derivedState.validation_state === 'pass' ? 'Validated' :
                derivedState.validation_state === 'warning' ? 'Warnings' :
                derivedState.validation_state === 'fail' ? 'Failed' :
                doc.status
              ) : doc.status}
            </span>
          </div>
          <p className="text-xs text-muted-foreground font-mono mt-1" data-testid="doc-id-display">{doc.id}</p>
        </div>
        <div className="flex gap-2 shrink-0">
          {doc.sharepoint_share_link_url && (
            <Button variant="secondary" size="sm" asChild data-testid="open-sharepoint-btn">
              <a href={doc.sharepoint_share_link_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="w-3 h-3 mr-1.5" /> SharePoint
              </a>
            </Button>
          )}
          {/* Re-process button - always visible for all documents */}
          <Button size="sm" variant="outline" onClick={handleResubmit} disabled={resubmitting} data-testid="resubmit-btn">
            {resubmitting ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <RotateCcw className="w-3 h-3 mr-1.5" />}
            {resubmitting ? 'Re-processing...' : 'Re-process'}
          </Button>
          {(doc.status === 'Classified' || doc.status === 'Exception') && doc.bc_document_no && (
            <Button size="sm" onClick={handleLink} disabled={linking} data-testid="link-to-bc-btn">
              {linking ? <Loader2 className="w-3 h-3 mr-1.5 animate-spin" /> : <Link className="w-3 h-3 mr-1.5" />}
              Link to BC
            </Button>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: Document Info */}
        <div className="lg:col-span-1 space-y-4">
          <Card className="border border-border" data-testid="doc-info-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                Document Info
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <InfoRow label="Source" value={doc.source} />
              <InfoRow label="Content Type" value={doc.content_type} mono />
              <InfoRow label="File Size" value={doc.file_size ? `${(doc.file_size / 1024).toFixed(1)} KB` : '-'} />
              <InfoRow label="SHA-256" value={doc.sha256_hash?.slice(0, 16) + '...'} mono copyable={doc.sha256_hash} onCopy={copyToClipboard} />
              <InfoRow label="Created" value={formatDate(doc.created_utc)} mono />
              <InfoRow label="Updated" value={formatDate(doc.updated_utc)} mono />
            </CardContent>
          </Card>

          <Card className="border border-border" data-testid="doc-classification-card">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Classification
                </CardTitle>
                {!editing && (
                  <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => { setEditing(true); setEditData({ document_type: doc.document_type, bc_document_no: doc.bc_document_no || '' }); }} data-testid="edit-classification-btn">
                    Edit
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent>
              {editing ? (
                <div className="space-y-3">
                  <div>
                    <Label className="text-xs">Document Type</Label>
                    <Select value={editData.document_type} onValueChange={(val) => setEditData({ ...editData, document_type: val })}>
                      <SelectTrigger className="h-8 text-xs" data-testid="edit-doc-type-select">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {DOC_TYPES.map((t) => <SelectItem key={t} value={t}>{t}</SelectItem>)}
                      </SelectContent>
                    </Select>
                  </div>
                  <div>
                    <Label className="text-xs">BC Document No</Label>
                    <Input className="h-8 text-xs" value={editData.bc_document_no || ''} onChange={(e) => setEditData({ ...editData, bc_document_no: e.target.value })} data-testid="edit-bc-doc-no-input" />
                  </div>
                  <div className="flex gap-2">
                    <Button size="sm" className="h-7 text-xs" onClick={handleSaveEdit} data-testid="save-edit-btn">Save</Button>
                    <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={() => setEditing(false)} data-testid="cancel-edit-btn">Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-3 text-sm">
                  <InfoRow label="Document Type" value={<Badge variant="secondary">{doc.document_type}</Badge>} />
                  <InfoRow label="BC Record Type" value={doc.bc_record_type || '-'} />
                  <InfoRow label="BC Document No" value={doc.bc_document_no || '-'} mono />
                  <InfoRow label="BC Record ID" value={doc.bc_record_id ? doc.bc_record_id.slice(0, 12) + '...' : '-'} mono />
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="border border-border" data-testid="doc-sharepoint-card">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                SharePoint
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-sm">
              <InfoRow label="Drive ID" value={doc.sharepoint_drive_id ? doc.sharepoint_drive_id.slice(0, 16) + '...' : '-'} mono />
              <InfoRow label="Item ID" value={doc.sharepoint_item_id ? doc.sharepoint_item_id.slice(0, 12) + '...' : '-'} mono />
              {doc.sharepoint_share_link_url && (
                <div>
                  <p className="text-xs text-muted-foreground mb-1">Share Link</p>
                  <div className="flex items-center gap-2">
                    <code className="text-xs bg-muted px-2 py-1 rounded flex-1 truncate">{doc.sharepoint_share_link_url}</code>
                    <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0" onClick={() => copyToClipboard(doc.sharepoint_share_link_url)} data-testid="copy-share-link-btn">
                      <Copy className="w-3 h-3" />
                    </Button>
                  </div>
                </div>
              )}
              {doc.last_error && (
                <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5" data-testid="doc-error-display">
                  <p className="text-xs font-medium text-red-700 dark:text-red-300">Last Error</p>
                  <p className="text-xs text-red-600 dark:text-red-400 mt-0.5">{doc.last_error}</p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* BC Validation Results Card */}
          {doc.validation_results && (
            <Card className="border border-border" data-testid="doc-bc-validation-card">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  {doc.validation_results.all_passed ? (
                    <ShieldCheck className="w-4 h-4 text-emerald-500" />
                  ) : (
                    <ShieldAlert className="w-4 h-4 text-amber-500" />
                  )}
                  <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    BC Validation
                  </CardTitle>
                  <Badge variant={doc.validation_results.all_passed ? "secondary" : "destructive"} className="text-[10px]">
                    {doc.validation_results.all_passed ? 'PASSED' : 'FAILED'}
                  </Badge>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Validation Checks */}
                {doc.validation_results.checks?.map((check, idx) => (
                  <div key={idx} className={`flex items-start gap-2 p-2 rounded-md ${check.passed ? 'bg-emerald-50 dark:bg-emerald-950/30' : 'bg-red-50 dark:bg-red-950/30'}`}>
                    {check.passed ? (
                      <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
                    ) : (
                      <AlertCircle className="w-4 h-4 text-red-500 mt-0.5 shrink-0" />
                    )}
                    <div className="flex-1 min-w-0">
                      <p className="text-xs font-medium">
                        {check.check_name?.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                      </p>
                      {check.details && (
                        <p className="text-[11px] text-muted-foreground mt-0.5">{check.details}</p>
                      )}
                      {check.match_method && (
                        <p className="text-[10px] text-muted-foreground mt-1 font-mono">
                          Method: {check.match_method} | Score: {(check.score * 100).toFixed(0)}%
                        </p>
                      )}
                      {check.vendor_no && (
                        <p className="text-[10px] text-muted-foreground font-mono">
                          BC Vendor: {check.vendor_no} - {check.vendor_name}
                        </p>
                      )}
                    </div>
                  </div>
                ))}

                {/* Extraction Quality */}
                {doc.validation_results.extraction_quality && (() => {
                  const eq = doc.validation_results.extraction_quality;
                  const reqFields = eq.required_fields || [];
                  const optFields = eq.optional_fields || [];
                  const totalFields = reqFields.length + optFields.length;
                  const extractedCount = (eq.required_extracted || 0) + (eq.optional_extracted || 0);
                  // Fallback to legacy keys if present
                  const finalExtracted = extractedCount || eq.extracted_count || 0;
                  const finalTotal = totalFields || eq.total_fields || 0;
                  const completeness = eq.completeness_score || 0;
                  return (
                  <div className="border-t border-border pt-3 mt-3">
                    <p className="text-xs font-medium mb-2 flex items-center gap-1.5">
                      <FileSearch className="w-3 h-3" /> Extraction Quality
                    </p>
                    <div className="grid grid-cols-2 gap-2 text-[11px]">
                      <div className="bg-muted/50 rounded px-2 py-1">
                        <span className="text-muted-foreground">Fields Extracted:</span>
                        <span className="font-mono ml-1">{finalExtracted}/{finalTotal}</span>
                      </div>
                      <div className="bg-muted/50 rounded px-2 py-1">
                        <span className="text-muted-foreground">Completeness:</span>
                        <span className="font-mono ml-1">{(completeness * 100).toFixed(0)}%</span>
                      </div>
                    </div>
                  </div>
                  );
                })()}

                {/* Match Info */}
                {doc.validation_results.match_method && (
                  <div className="border-t border-border pt-3 mt-3">
                    <p className="text-xs font-medium mb-2 flex items-center gap-1.5">
                      <Building2 className="w-3 h-3" /> Vendor Match Details
                    </p>
                    <div className="bg-muted/50 rounded p-2 text-[11px] space-y-1">
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Match Method:</span>
                        <span className="font-mono font-medium">{doc.validation_results.match_method}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-muted-foreground">Match Score:</span>
                        <span className="font-mono font-medium">{((doc.validation_results.match_score || 0) * 100).toFixed(0)}%</span>
                      </div>
                      {doc.validation_results.bc_record_info && (
                        <>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">BC Vendor No:</span>
                            <span className="font-mono">{doc.validation_results.bc_record_info.number}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">BC Vendor Name:</span>
                            <span className="font-mono truncate max-w-[150px]">{doc.validation_results.bc_record_info.displayName}</span>
                          </div>
                        </>
                      )}
                    </div>
                  </div>
                )}

                {/* Warnings */}
                {doc.validation_results.warnings?.length > 0 && (
                  <div className="border-t border-border pt-3 mt-3">
                    <p className="text-xs font-medium mb-2 text-amber-600 dark:text-amber-400">Warnings</p>
                    {doc.validation_results.warnings.map((warn, idx) => (
                      <p key={idx} className="text-[11px] text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/30 rounded px-2 py-1 mb-1">
                        {typeof warn === 'string' ? warn : warn.message || JSON.stringify(warn)}
                      </p>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* AI Classification Card */}
          {(doc.ai_confidence || doc.classification_method) && (
            <Card className="border border-border" data-testid="doc-ai-classification-card">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <Receipt className="w-4 h-4 text-blue-500" />
                  <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    AI Classification
                  </CardTitle>
                </div>
              </CardHeader>
              <CardContent className="space-y-2 text-sm">
                {doc.ai_model && (
                  <InfoRow label="Model" value={doc.ai_model} mono />
                )}
                {doc.classification_method && (
                  <InfoRow label="Method" value={doc.classification_method} mono />
                )}
                {doc.ai_confidence !== undefined && (
                  <InfoRow label="Confidence" value={`${(doc.ai_confidence * 100).toFixed(0)}%`} />
                )}
              </CardContent>
            </Card>
          )}

          {/* BC Sales Order Panel - for eligible document types */}
          <CreateBCSalesOrderPanel 
            document={doc} 
            onUpdate={() => fetchDoc()} 
          />

          {/* BC Purchase Invoice Panel - for AP_Invoice document types */}
          <CreateBCPurchaseInvoicePanel 
            document={doc} 
            onUpdate={() => fetchDoc()} 
          />

          {/* Reference Intelligence Panel */}
          <ReferenceIntelligencePanel 
            document={doc} 
            onUpdate={() => fetchData()} 
          />

          {/* AP Validation Panel */}
          <APValidationPanel
            document={doc}
            onUpdate={() => fetchData()}
          />

          {/* Freight G/L Routing Panel */}
          <FreightGLRoutingPanel
            document={doc}
            onUpdate={() => fetchData()}
          />

          {/* Matching Debug Panel */}
          <MatchingDebugPanel
            document={doc}
          />

          {/* Square9 Workflow Tracker */}
          <Square9WorkflowTracker 
            documentId={id} 
            onRetry={(result) => {
              toast.success(`Retry ${result.retry_count} completed`);
              fetchData(); // Refresh document data
            }}
          />
        </div>

        {/* Right: Document Preview + AP Review (if AP_Invoice) + Event Timeline */}
        <div className="lg:col-span-2 space-y-4">
          {/* Derived State Summary Card - Always show */}
          {derivedState && (
            <Card className="border border-border" data-testid="derived-state-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Document Status
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-3 gap-4 mb-4">
                  {/* Validation State */}
                  <div className="text-center">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Validation</p>
                    <StateBadge 
                      type="validation_state" 
                      value={derivedState.validation_state}
                    />
                  </div>
                  {/* Workflow State */}
                  <div className="text-center">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Workflow</p>
                    <StateBadge 
                      type="workflow_state" 
                      value={derivedState.workflow_state}
                    />
                  </div>
                  {/* Automation State */}
                  <div className="text-center">
                    <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1">Automation</p>
                    <StateBadge 
                      type="automation_state" 
                      value={derivedState.automation_state}
                    />
                  </div>
                </div>
                
                {/* State Reason */}
                {derivedState.state_reason && (
                  <div className="bg-muted/50 rounded-md p-2.5 mb-3">
                    <p className="text-xs text-muted-foreground">{derivedState.state_reason}</p>
                  </div>
                )}
                
                {/* Blocking Issues */}
                {derivedState.blocking_issues?.length > 0 && (
                  <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5 mb-3">
                    <p className="text-xs font-medium text-red-700 dark:text-red-300 mb-1">Blocking Issues</p>
                    {derivedState.blocking_issues.map((issue, idx) => (
                      <p key={idx} className="text-xs text-red-600 dark:text-red-400">• {issue}</p>
                    ))}
                  </div>
                )}
                
                {/* Warnings */}
                {derivedState.warnings?.length > 0 && (
                  <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-md p-2.5 mb-3">
                    <p className="text-xs font-medium text-amber-700 dark:text-amber-300 mb-1">Warnings</p>
                    {derivedState.warnings.map((warn, idx) => (
                      <p key={idx} className="text-xs text-amber-600 dark:text-amber-400">• {typeof warn === 'string' ? warn : warn.message || JSON.stringify(warn)}</p>
                    ))}
                  </div>
                )}
                
                {/* Review Queue */}
                {derivedState.needs_review && derivedState.review_queue && (
                  <div className="flex items-center gap-2 text-xs">
                    <Eye className="w-3.5 h-3.5 text-amber-500" />
                    <span className="text-muted-foreground">In queue:</span>
                    <Badge variant="outline" className="text-[10px]">{derivedState.review_queue}</Badge>
                  </div>
                )}
                
                {/* Derived From indicator */}
                <p className="text-[10px] text-muted-foreground mt-3 text-right">
                  Derived from: {derivedState.derived_from === 'events' ? 'Event history' : 'Legacy fields'}
                </p>
              </CardContent>
            </Card>
          )}
          
          {/* Stable Vendor Routing Decision */}
          {doc.stable_vendor_routing && (
            <Card className="border border-border" data-testid="stable-vendor-routing-card">
              <CardHeader className="pb-3">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                    Auto-Ready Routing
                  </CardTitle>
                  <RoutingBadge routing={doc.stable_vendor_routing.routing} />
                </div>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 mb-3 text-xs">
                  <div className="flex items-center gap-2" data-testid="sv-vendor-stable">
                    {doc.stable_vendor_routing.vendor_stable 
                      ? <ShieldCheck className="w-3.5 h-3.5 text-emerald-500" />
                      : <ShieldAlert className="w-3.5 h-3.5 text-muted-foreground" />}
                    <span className="text-muted-foreground">Stable Vendor:</span>
                    <span className="font-medium">{doc.stable_vendor_routing.vendor_stable ? 'Yes' : 'No'}</span>
                  </div>
                  <div className="flex items-center gap-2" data-testid="sv-vendor-score">
                    <Zap className="w-3.5 h-3.5 text-amber-500" />
                    <span className="text-muted-foreground">Score:</span>
                    <span className="font-medium font-mono">{(doc.stable_vendor_routing.vendor_score || 0).toFixed(3)}</span>
                  </div>
                </div>
                {/* Decision Reasoning */}
                <div className="bg-muted/50 rounded-md p-2.5" data-testid="sv-reasons">
                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground mb-1.5">Decision Reasoning</p>
                  {(doc.stable_vendor_routing.reasons || []).map((reason, idx) => (
                    <p key={idx} className="text-xs text-muted-foreground leading-relaxed">
                      {reason.includes('Final routing') ? <span className="font-semibold text-foreground">{reason}</span> : `• ${reason}`}
                    </p>
                  ))}
                </div>
                {doc.vendor_canonical && (
                  <p className="text-xs text-muted-foreground mt-2 underline underline-offset-2 cursor-pointer hover:text-foreground"
                    onClick={() => navigate('/stable-vendors')} data-testid="sv-view-vendor-link">
                    View Stable Vendor Details
                  </p>
                )}
              </CardContent>
            </Card>
          )}

          {/* PDF Preview - show for ALL documents */}
          <PDFPreviewPanel document={doc} />
          
          {/* AP Review Panel - only for AP Invoice documents */}
          {(doc.document_type === 'AP_Invoice' || doc.suggested_job_type === 'AP_Invoice') && (
            <APReviewPanel 
              document={doc} 
              onUpdate={(updatedDoc) => {
                setDoc(prev => ({ ...prev, ...updatedDoc }));
                fetchDoc();
              }} 
            />
          )}
          
          {/* Event Timeline - New Event-Driven UI */}
          <Card className="border border-border" data-testid="event-timeline-card">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Workflow Events
                </CardTitle>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-muted-foreground">{eventTimeline.length} events</span>
                  {workflows.length > 0 && (
                    <Button 
                      variant="ghost" 
                      size="sm" 
                      className="h-6 text-[10px]"
                      onClick={() => setShowLegacyWorkflows(!showLegacyWorkflows)}
                    >
                      {showLegacyWorkflows ? 'Hide' : 'Show'} Legacy
                    </Button>
                  )}
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {eventTimeline.length > 0 ? (
                <div className="space-y-0">
                  {eventTimeline.map((event, idx) => (
                    <EventTimelineItem key={event.event_id || idx} event={event} />
                  ))}
                </div>
              ) : (
                <div className="py-8 text-center text-sm text-muted-foreground">
                  No workflow events recorded yet
                </div>
              )}
            </CardContent>
          </Card>
          
          {/* Legacy Workflow Runs - Collapsible */}
          {showLegacyWorkflows && workflows.length > 0 && (
            <Card className="border border-border border-dashed opacity-75" data-testid="workflow-audit-card">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
                  Legacy Workflow Runs
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-6">
                  {workflows.map((wf) => (
                    <div key={wf.id} className="border border-border rounded-lg p-4" data-testid={`workflow-item-${wf.id}`}>
                      <div className="flex items-center justify-between mb-3">
                        <div className="flex items-center gap-2">
                          <span className="font-mono text-sm font-semibold">{wf.workflow_name}</span>
                          <Badge variant={wf.status === 'Completed' ? 'secondary' : wf.status === 'Failed' ? 'destructive' : 'default'} className="text-xs">
                            {wf.status}
                          </Badge>
                        </div>
                        <span className="text-xs text-muted-foreground font-mono">{formatDate(wf.started_utc)}</span>
                      </div>

                      {/* Steps */}
                      <div className="space-y-0">
                        {wf.steps?.map((step, idx) => (
                          <div key={idx} className="workflow-step py-2" data-testid={`workflow-step-${idx}`}>
                            <div className={`workflow-step-dot ${step.status === 'completed' ? 'bg-emerald-100 dark:bg-emerald-900' : step.status === 'failed' ? 'bg-red-100 dark:bg-red-900' : step.status === 'warning' ? 'bg-amber-100 dark:bg-amber-900' : 'bg-blue-100 dark:bg-blue-900'}`}>
                              {STEP_ICONS[step.status] || <Clock className="w-4 h-4 text-muted-foreground" />}
                            </div>
                            <div className="flex items-center justify-between">
                              <div>
                                <p className="text-sm font-medium">{step.step.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}</p>
                                {step.result && (
                                  <pre className="text-xs text-muted-foreground mt-1 font-mono bg-muted/50 rounded px-2 py-1 max-w-lg overflow-auto">
                                    {JSON.stringify(step.result, null, 2)}
                                  </pre>
                                )}
                                {step.error && <p className="text-xs text-red-500 mt-1">{step.error}</p>}
                              </div>
                              {step.ended && (
                                <span className="text-[10px] text-muted-foreground font-mono shrink-0 ml-4">{formatDate(step.ended)}</span>
                              )}
                            </div>
                          </div>
                        ))}
                      </div>

                      {wf.error && (
                        <div className="mt-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5">
                          <p className="text-xs text-red-600 dark:text-red-400 font-mono">{wf.error}</p>
                        </div>
                      )}

                      <div className="mt-3 pt-3 border-t border-border flex items-center gap-4 text-[10px] text-muted-foreground font-mono">
                        <span>ID: {wf.id.slice(0, 8)}</span>
                        <span>Correlation: {wf.correlation_id?.slice(0, 8)}</span>
                        {wf.ended_utc && <span>Duration: {((new Date(wf.ended_utc) - new Date(wf.started_utc)) / 1000).toFixed(2)}s</span>}
                      </div>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// State Badge Component
function StateBadge({ type, value }) {
  const IconComponent = STATE_ICONS[type]?.[value] || Clock;
  const colorClass = STATE_BADGE_COLORS[type]?.[value] || 'bg-gray-100 text-gray-700';
  
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${colorClass}`}>
      <IconComponent className="w-3 h-3" />
      {value.replace(/_/g, ' ')}
    </span>
  );
}

// Event Timeline Item Component
function EventTimelineItem({ event }) {
  const getEventIcon = (eventType, status) => {
    if (status === 'failed') return <XCircle className="w-4 h-4 text-red-500" />;
    if (status === 'warning') return <AlertTriangle className="w-4 h-4 text-amber-500" />;
    
    // Map event types to icons
    const typeIconMap = {
      'document.received': <Inbox className="w-4 h-4 text-blue-500" />,
      'classification.completed': <FileText className="w-4 h-4 text-emerald-500" />,
      'classification.failed': <XCircle className="w-4 h-4 text-red-500" />,
      'vendor.match.completed': <Building2 className="w-4 h-4 text-emerald-500" />,
      'vendor.match.failed': <Building2 className="w-4 h-4 text-red-500" />,
      'bc.validation.completed': <ShieldCheck className="w-4 h-4 text-emerald-500" />,
      'bc.validation.failed': <ShieldAlert className="w-4 h-4 text-red-500" />,
      'sharepoint.upload.succeeded': <ExternalLink className="w-4 h-4 text-emerald-500" />,
      'automation.decision.completed': <Zap className="w-4 h-4 text-purple-500" />,
    };
    
    return typeIconMap[eventType] || <CheckCircle2 className="w-4 h-4 text-emerald-500" />;
  };
  
  const getStatusColor = (status) => {
    switch (status) {
      case 'completed': return 'bg-emerald-100 dark:bg-emerald-900/30';
      case 'failed': return 'bg-red-100 dark:bg-red-900/30';
      case 'warning': return 'bg-amber-100 dark:bg-amber-900/30';
      default: return 'bg-blue-100 dark:bg-blue-900/30';
    }
  };
  
  const formatEventType = (type) => {
    return type.split('.').map(part => 
      part.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
    ).join(' › ');
  };
  
  return (
    <div className="workflow-step py-2.5 border-l-2 border-border pl-4 ml-2 relative" data-testid={`event-item-${event.event_id?.slice(0, 8)}`}>
      <div className={`absolute left-0 top-3 -translate-x-1/2 w-6 h-6 rounded-full flex items-center justify-center ${getStatusColor(event.status)}`}>
        {getEventIcon(event.event_type, event.status)}
      </div>
      
      <div className="flex items-start justify-between">
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{formatEventType(event.event_type)}</p>
          
          {event.payload_summary && (
            <p className="text-xs text-muted-foreground mt-0.5">{event.payload_summary}</p>
          )}
          
          <div className="flex items-center gap-3 mt-1 text-[10px] text-muted-foreground font-mono">
            <span>{event.source_service}</span>
            {event.actor && <span>by {event.actor}</span>}
            {event.correlation_id && <span>#{event.correlation_id.slice(0, 6)}</span>}
            {event.source === 'legacy_history' && (
              <Badge variant="outline" className="text-[9px] h-4 px-1">legacy</Badge>
            )}
          </div>
        </div>
        
        <span className="text-[10px] text-muted-foreground font-mono shrink-0 ml-4">
          {formatDate(event.timestamp)}
        </span>
      </div>
    </div>
  );
}


function InfoRow({ label, value, mono, copyable, onCopy }) {
  return (
    <div className="flex items-start justify-between gap-4">
      <span className="text-xs text-muted-foreground shrink-0">{label}</span>
      <div className="flex items-center gap-1.5 min-w-0">
        <span className={`text-xs text-right truncate ${mono ? 'font-mono' : ''}`}>{value}</span>
        {copyable && onCopy && (
          <button onClick={() => onCopy(copyable)} className="text-muted-foreground hover:text-foreground shrink-0">
            <Copy className="w-3 h-3" />
          </button>
        )}
      </div>
    </div>
  );
}
