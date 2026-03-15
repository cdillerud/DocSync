import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  ScanSearch, RefreshCw, CheckCircle, AlertTriangle, XCircle, Pencil, Save, X, Loader2,
  History, ChevronDown, ChevronUp, Zap, ExternalLink, Copy, FileText
} from 'lucide-react';
import {
  getDocumentIntelligence, processDocumentIntelligence, correctDocumentIntelligence,
  createAutoDraft, getAutomationAction
} from '@/lib/api';

const READINESS_COLORS = {
  ready: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', icon: CheckCircle },
  needs_review: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', icon: AlertTriangle },
  blocked: { bg: 'bg-red-500/10', border: 'border-red-500/30', text: 'text-red-400', icon: XCircle },
};

const DRAFT_TYPE_LABELS = {
  sales_order_draft: 'Sales Order Draft',
  po_draft: 'PO Draft',
  ap_intake_draft: 'AP Intake Draft',
};

export default function DocumentIntelligencePanel({ document, onUpdate }) {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editType, setEditType] = useState('');
  const [editFields, setEditFields] = useState({});
  const [saving, setSaving] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [creatingDraft, setCreatingDraft] = useState(false);
  const [draftResult, setDraftResult] = useState(null);

  const docId = document?.id;

  const fetchResult = useCallback(async () => {
    if (!docId) return;
    setLoading(true);
    try {
      const { data } = await getDocumentIntelligence(docId);
      setResult(data);
      // Check for existing draft
      if (data.auto_draft_created && data.target_entity_id) {
        setDraftResult({
          status: 'existing',
          target_entity_type: data.target_entity_type,
          target_entity_id: data.target_entity_id,
        });
      }
    } catch {
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => { fetchResult(); }, [fetchResult]);

  const handleProcess = async () => {
    setProcessing(true);
    try {
      const { data } = await processDocumentIntelligence(docId);
      setResult(data);
      setDraftResult(null); // Reset draft state on re-process
      toast.success('Document intelligence processed');
      onUpdate?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Processing failed');
    } finally {
      setProcessing(false);
    }
  };

  const handleCreateDraft = async () => {
    setCreatingDraft(true);
    try {
      const { data } = await createAutoDraft(docId);
      if (data.status === 'duplicate') {
        setDraftResult({
          status: 'duplicate',
          target_entity_type: data.existing_action?.target_entity_type,
          target_entity_id: data.existing_action?.target_entity_id,
          message: data.message,
        });
        toast.info('Draft already exists for this document');
      } else {
        setDraftResult({
          status: 'created',
          target_entity_type: data.target_entity_type,
          target_entity_id: data.target_entity_id,
          action_id: data.automation_action_id,
        });
        toast.success(`${DRAFT_TYPE_LABELS[data.target_entity_type] || 'Draft'} created successfully`);
        fetchResult(); // Refresh to get updated intel
      }
      onUpdate?.();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Auto-draft creation failed';
      toast.error(detail);
      setDraftResult({ status: 'failed', message: detail });
    } finally {
      setCreatingDraft(false);
    }
  };

  const startEditing = () => {
    setEditing(true);
    setEditType(result?.document_type || '');
    setEditFields({ ...(result?.extracted_fields || {}) });
  };

  const cancelEditing = () => {
    setEditing(false);
    setEditType('');
    setEditFields({});
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = { corrected_by: 'admin', notes: 'Manual correction from UI' };
      if (editType && editType !== result?.document_type) payload.corrected_type = editType;
      const changedFields = {};
      for (const [k, v] of Object.entries(editFields)) {
        if (v !== (result?.extracted_fields?.[k] ?? '')) changedFields[k] = v;
      }
      if (Object.keys(changedFields).length > 0) payload.corrected_fields = changedFields;
      if (!payload.corrected_type && !payload.corrected_fields) {
        toast.info('No changes to save');
        cancelEditing();
        return;
      }
      const { data } = await correctDocumentIntelligence(docId, payload);
      setResult(data);
      setEditing(false);
      toast.success('Corrections applied');
      onUpdate?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to save corrections');
    } finally {
      setSaving(false);
    }
  };

  const handleFieldChange = (key, value) => {
    setEditFields(prev => ({ ...prev, [key]: value }));
  };

  if (!docId) return null;

  const readiness = result?.automation_readiness || 'unknown';
  const rc = READINESS_COLORS[readiness] || { bg: 'bg-muted', border: 'border-border', text: 'text-muted-foreground', icon: ScanSearch };
  const ReadinessIcon = rc.icon;
  const schema = result?.extraction_schema || { required: [], optional: [] };
  const allFields = [...new Set([...schema.required, ...schema.optional, ...Object.keys(result?.extracted_fields || {})])];
  const isReady = readiness === 'ready';
  const hasDraft = draftResult && (draftResult.status === 'created' || draftResult.status === 'existing' || draftResult.status === 'duplicate');

  return (
    <Card className={`border ${rc.border}`} data-testid="document-intelligence-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScanSearch className={`w-4 h-4 ${rc.text}`} />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Document Intelligence
            </CardTitle>
          </div>
          <div className="flex items-center gap-1">
            {!editing && result && (
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={startEditing} data-testid="edit-intelligence-btn">
                <Pencil className="w-3 h-3 mr-1" /> Edit
              </Button>
            )}
            <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={handleProcess} disabled={processing} data-testid="process-intelligence-btn">
              {processing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <RefreshCw className="w-3 h-3 mr-1" />}
              {result ? 'Re-process' : 'Process'}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {loading ? (
          <div className="flex items-center justify-center py-6 text-muted-foreground">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading...
          </div>
        ) : !result ? (
          <div className="text-center py-6">
            <ScanSearch className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
            <p className="text-xs text-muted-foreground mb-2">No intelligence result yet</p>
            <Button size="sm" variant="outline" onClick={handleProcess} disabled={processing} data-testid="initial-process-btn">
              {processing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <ScanSearch className="w-3 h-3 mr-1" />}
              Run Intelligence Pipeline
            </Button>
          </div>
        ) : (
          <>
            {/* Readiness Banner */}
            <div className={`flex items-center gap-3 p-3 rounded-lg ${rc.bg} border ${rc.border}`} data-testid="readiness-banner">
              <ReadinessIcon className={`w-5 h-5 ${rc.text}`} />
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold uppercase ${rc.text}`}>{readiness.replace('_', ' ')}</span>
                  <span className={`text-xs font-mono font-bold ${rc.text}`}>{result.automation_readiness_score}/100</span>
                </div>
                {result.automation_reasoning && (
                  <p className="text-[11px] text-muted-foreground mt-0.5">{result.automation_reasoning}</p>
                )}
              </div>
              {result.manually_corrected && (
                <Badge variant="outline" className="text-[9px] border-blue-500/30 text-blue-400">Corrected</Badge>
              )}
            </div>

            {/* Readiness Reasons */}
            {result.automation_readiness_reasons?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.automation_readiness_reasons.map((r, i) => (
                  <Badge key={i} variant="outline" className="text-[9px] font-mono border-muted-foreground/30">{r}</Badge>
                ))}
              </div>
            )}

            {/* Auto-Draft Action Section */}
            {isReady && !editing && (
              <div className="border border-border rounded-lg p-3 space-y-2" data-testid="auto-draft-section">
                {!hasDraft ? (
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold">Automation Available</p>
                      <p className="text-[11px] text-muted-foreground">
                        Create {DRAFT_TYPE_LABELS[result.target_entity_type] || 'draft'} from extracted fields
                      </p>
                    </div>
                    <Button
                      size="sm"
                      onClick={handleCreateDraft}
                      disabled={creatingDraft}
                      className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      data-testid="create-draft-btn"
                    >
                      {creatingDraft ? (
                        <Loader2 className="w-3 h-3 animate-spin mr-1.5" />
                      ) : (
                        <Zap className="w-3 h-3 mr-1.5" />
                      )}
                      Create Draft
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-4 h-4 text-emerald-500" />
                      <span className="text-xs font-semibold text-emerald-400">
                        {draftResult.status === 'duplicate' ? 'Draft Already Exists' : 'Draft Created'}
                      </span>
                    </div>
                    <div className="flex items-center gap-2 p-2 bg-accent/30 rounded">
                      <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                      <div className="flex-1">
                        <p className="text-xs font-medium">
                          {DRAFT_TYPE_LABELS[draftResult.target_entity_type] || draftResult.target_entity_type}
                        </p>
                        <p className="text-[10px] font-mono text-muted-foreground">{draftResult.target_entity_id}</p>
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs"
                        onClick={() => {
                          navigator.clipboard.writeText(draftResult.target_entity_id || '');
                          toast.success('Copied draft ID');
                        }}
                        data-testid="copy-draft-id-btn"
                      >
                        <Copy className="w-3 h-3" />
                      </Button>
                    </div>
                    {draftResult.message && draftResult.status === 'duplicate' && (
                      <p className="text-[10px] text-amber-400">{draftResult.message}</p>
                    )}
                  </div>
                )}

                {draftResult?.status === 'failed' && (
                  <div className="p-2 bg-red-500/10 border border-red-500/30 rounded text-[11px] text-red-400">
                    {draftResult.message}
                  </div>
                )}
              </div>
            )}

            {/* Classification */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Classification</p>
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2 bg-accent/30 rounded">
                  <p className="text-[10px] text-muted-foreground">Type</p>
                  {editing ? (
                    <Input value={editType} onChange={e => setEditType(e.target.value)} className="h-7 text-xs mt-1" data-testid="edit-doc-type-input" />
                  ) : (
                    <p className="text-xs font-mono font-semibold">{result.document_type}</p>
                  )}
                </div>
                <div className="p-2 bg-accent/30 rounded">
                  <p className="text-[10px] text-muted-foreground">Confidence</p>
                  <div className="flex items-center gap-2 mt-1">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full ${
                          result.classification_confidence >= 0.9 ? 'bg-emerald-500' :
                          result.classification_confidence >= 0.75 ? 'bg-amber-500' : 'bg-red-500'
                        }`}
                        style={{ width: `${(result.classification_confidence || 0) * 100}%` }}
                      />
                    </div>
                    <span className="text-xs font-mono font-semibold">{((result.classification_confidence || 0) * 100).toFixed(0)}%</span>
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-muted-foreground">
                <span>Model: <span className="font-mono">{result.model_name}</span></span>
                <span>v{result.prompt_version}</span>
                <span>{result.processing_duration_ms}ms</span>
              </div>
            </div>

            {/* Extracted Fields */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Extracted Fields</p>
              <div className="space-y-1">
                {allFields.filter(f => f !== 'line_items').map(field => {
                  const val = editing ? (editFields[field] ?? '') : (result.extracted_fields?.[field] ?? '');
                  const isRequired = schema.required.includes(field);
                  const isMissing = !val || (typeof val === 'string' && !val.trim());

                  return (
                    <div key={field} className="flex items-center gap-2 py-1">
                      <span className={`text-[11px] w-28 truncate ${isRequired ? 'font-semibold' : 'text-muted-foreground'}`}>
                        {field}
                        {isRequired && <span className="text-red-400 ml-0.5">*</span>}
                      </span>
                      {editing ? (
                        <Input
                          value={typeof val === 'object' ? JSON.stringify(val) : val}
                          onChange={e => handleFieldChange(field, e.target.value)}
                          className="h-6 text-xs flex-1 font-mono"
                          data-testid={`edit-field-${field}`}
                        />
                      ) : (
                        <span className={`text-xs font-mono flex-1 truncate ${isMissing ? 'text-red-400 italic' : ''}`}>
                          {isMissing ? 'missing' : (typeof val === 'object' ? JSON.stringify(val) : String(val))}
                        </span>
                      )}
                      {!editing && isRequired && (
                        isMissing
                          ? <XCircle className="w-3 h-3 text-red-400 shrink-0" />
                          : <CheckCircle className="w-3 h-3 text-emerald-500 shrink-0" />
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Edit Actions */}
            {editing && (
              <div className="flex items-center gap-2 pt-2 border-t border-border">
                <Button size="sm" onClick={handleSave} disabled={saving} data-testid="save-corrections-btn">
                  {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />}
                  Save Corrections
                </Button>
                <Button size="sm" variant="ghost" onClick={cancelEditing} data-testid="cancel-edit-btn">
                  <X className="w-3 h-3 mr-1" /> Cancel
                </Button>
              </div>
            )}

            {/* Correction History */}
            {result.correction_history?.length > 0 && (
              <div className="pt-2 border-t border-border">
                <button
                  className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors"
                  onClick={() => setShowHistory(!showHistory)}
                  data-testid="toggle-correction-history"
                >
                  <History className="w-3 h-3" />
                  <span>{result.correction_history.length} correction{result.correction_history.length > 1 ? 's' : ''}</span>
                  {showHistory ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showHistory && (
                  <div className="mt-2 space-y-2">
                    {result.correction_history.map((h, i) => (
                      <div key={i} className="p-2 bg-accent/30 rounded text-[11px]">
                        <div className="flex justify-between">
                          <span className="font-medium">{h.corrected_by}</span>
                          <span className="text-muted-foreground font-mono">{new Date(h.corrected_at).toLocaleString()}</span>
                        </div>
                        {h.notes && <p className="text-muted-foreground mt-0.5">{h.notes}</p>}
                        {h.changes?.document_type && (
                          <p className="mt-0.5">Type: <span className="font-mono">{h.changes.document_type.from}</span> → <span className="font-mono font-semibold">{h.changes.document_type.to}</span></p>
                        )}
                        {h.changes?.extracted_fields && (
                          <div className="mt-0.5">
                            {Object.entries(h.changes.extracted_fields).map(([k, v]) => (
                              <p key={k}>{k}: <span className="font-mono">{v.from || '(empty)'}</span> → <span className="font-mono font-semibold">{v.to}</span></p>
                            ))}
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
