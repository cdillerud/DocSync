import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  ScanSearch, RefreshCw, CheckCircle, AlertTriangle, XCircle, Pencil, Save, X, Loader2,
  History, ChevronDown, ChevronUp, Zap, Copy, FileText, Link2, Users, Unlink
} from 'lucide-react';
import {
  getDocumentIntelligence, processDocumentIntelligence, correctDocumentIntelligence,
  createAutoDraft, resolveDocumentEntities, getDocumentResolutions, correctResolution
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

const RES_STATUS_STYLE = {
  matched: { icon: CheckCircle, color: 'text-emerald-400', bg: 'bg-emerald-500/10', label: 'Matched' },
  ambiguous: { icon: AlertTriangle, color: 'text-amber-400', bg: 'bg-amber-500/10', label: 'Ambiguous' },
  unmatched: { icon: XCircle, color: 'text-red-400', bg: 'bg-red-500/10', label: 'Unmatched' },
  corrected: { icon: CheckCircle, color: 'text-blue-400', bg: 'bg-blue-500/10', label: 'Corrected' },
};

const ENTITY_LABELS = { customer: 'Customer', vendor: 'Vendor', purchase_order: 'PO #', invoice: 'Invoice #', sales_order: 'SO #' };

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

  // Entity resolution state
  const [resolutions, setResolutions] = useState([]);
  const [resolving, setResolving] = useState(false);
  const [showResolutions, setShowResolutions] = useState(true);
  const [correctingId, setCorrectingId] = useState(null);
  const [correctionInput, setCorrectionInput] = useState({ id: '', name: '' });

  const docId = document?.id;

  const fetchResult = useCallback(async () => {
    if (!docId) return;
    setLoading(true);
    try {
      const { data } = await getDocumentIntelligence(docId);
      setResult(data);
      if (data.auto_draft_created && data.target_entity_id) {
        setDraftResult({ status: 'existing', target_entity_type: data.target_entity_type, target_entity_id: data.target_entity_id });
      }
    } catch { setResult(null); }
    // Fetch resolutions
    try {
      const { data: resData } = await getDocumentResolutions(docId);
      setResolutions(resData.resolutions || []);
    } catch { setResolutions([]); }
    setLoading(false);
  }, [docId]);

  useEffect(() => { fetchResult(); }, [fetchResult]);

  const handleProcess = async () => {
    setProcessing(true);
    try {
      const { data } = await processDocumentIntelligence(docId);
      setResult(data);
      setDraftResult(null);
      toast.success('Document intelligence processed');
      onUpdate?.();
    } catch (err) { toast.error(err.response?.data?.detail || 'Processing failed'); }
    finally { setProcessing(false); }
  };

  const handleResolveEntities = async () => {
    setResolving(true);
    try {
      const { data } = await resolveDocumentEntities(docId);
      setResolutions(data.resolutions || []);
      setResult(prev => prev ? { ...prev, entity_resolution_status: data.summary?.status, entity_resolution_blocking_items: data.summary?.blocking_items, unresolved_entity_count: data.summary?.unresolved_count, ambiguous_entity_count: data.summary?.ambiguous_count } : prev);
      toast.success(`${data.resolutions?.length || 0} entities resolved`);
      onUpdate?.();
    } catch (err) { toast.error(err.response?.data?.detail || 'Entity resolution failed'); }
    finally { setResolving(false); }
  };

  const handleCorrectResolution = async (resolutionId) => {
    setCorrectingId(resolutionId);
    try {
      const { data } = await correctResolution(resolutionId, {
        matched_entity_id: correctionInput.id,
        matched_entity_name: correctionInput.name,
        corrected_by: 'admin',
        notes: 'Manual correction from UI',
      });
      setResolutions(prev => prev.map(r => r.resolution_id === resolutionId ? data : r));
      setCorrectionInput({ id: '', name: '' });
      toast.success('Resolution corrected');
      fetchResult();
    } catch (err) { toast.error(err.response?.data?.detail || 'Correction failed'); }
    finally { setCorrectingId(null); }
  };

  const handleConfirmCandidate = async (resolutionId, candidate) => {
    setCorrectingId(resolutionId);
    try {
      const { data } = await correctResolution(resolutionId, {
        matched_entity_id: candidate.entity_id,
        matched_entity_name: candidate.entity_name,
        corrected_by: 'admin',
        notes: 'Confirmed candidate from UI',
      });
      setResolutions(prev => prev.map(r => r.resolution_id === resolutionId ? data : r));
      toast.success('Resolution confirmed');
      fetchResult();
    } catch (err) { toast.error(err.response?.data?.detail || 'Confirmation failed'); }
    finally { setCorrectingId(null); }
  };

  const handleCreateDraft = async () => {
    setCreatingDraft(true);
    try {
      const { data } = await createAutoDraft(docId);
      if (data.status === 'duplicate') {
        setDraftResult({ status: 'duplicate', target_entity_type: data.existing_action?.target_entity_type, target_entity_id: data.existing_action?.target_entity_id, message: data.message });
        toast.info('Draft already exists');
      } else {
        setDraftResult({ status: 'created', target_entity_type: data.target_entity_type, target_entity_id: data.target_entity_id });
        toast.success(`${DRAFT_TYPE_LABELS[data.target_entity_type] || 'Draft'} created`);
        fetchResult();
      }
      onUpdate?.();
    } catch (err) {
      const detail = err.response?.data?.detail || 'Auto-draft failed';
      toast.error(detail);
      setDraftResult({ status: 'failed', message: detail });
    } finally { setCreatingDraft(false); }
  };

  const startEditing = () => { setEditing(true); setEditType(result?.document_type || ''); setEditFields({ ...(result?.extracted_fields || {}) }); };
  const cancelEditing = () => { setEditing(false); setEditType(''); setEditFields({}); };

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
      if (!payload.corrected_type && !payload.corrected_fields) { toast.info('No changes'); cancelEditing(); return; }
      const { data } = await correctDocumentIntelligence(docId, payload);
      setResult(data);
      setEditing(false);
      toast.success('Corrections applied');
      onUpdate?.();
    } catch (err) { toast.error(err.response?.data?.detail || 'Failed to save'); }
    finally { setSaving(false); }
  };

  if (!docId) return null;
  const readiness = result?.automation_readiness || 'unknown';
  const rc = READINESS_COLORS[readiness] || { bg: 'bg-muted', border: 'border-border', text: 'text-muted-foreground', icon: ScanSearch };
  const ReadinessIcon = rc.icon;
  const schema = result?.extraction_schema || { required: [], optional: [] };
  const allFields = [...new Set([...schema.required, ...schema.optional, ...Object.keys(result?.extracted_fields || {})])];
  const isReady = readiness === 'ready';
  const hasDraft = draftResult && (draftResult.status === 'created' || draftResult.status === 'existing' || draftResult.status === 'duplicate');
  const erStatus = result?.entity_resolution_status;
  const erBlocked = erStatus === 'blocked';
  const erNeedsReview = erStatus === 'needs_review';

  return (
    <Card className={`border ${rc.border}`} data-testid="document-intelligence-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ScanSearch className={`w-4 h-4 ${rc.text}`} />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>Document Intelligence</CardTitle>
          </div>
          <div className="flex items-center gap-1">
            {!editing && result && (
              <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={startEditing} data-testid="edit-intelligence-btn"><Pencil className="w-3 h-3 mr-1" /> Edit</Button>
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
          <div className="flex items-center justify-center py-6 text-muted-foreground"><Loader2 className="w-4 h-4 animate-spin mr-2" /> Loading...</div>
        ) : !result ? (
          <div className="text-center py-6">
            <ScanSearch className="w-8 h-8 mx-auto mb-2 text-muted-foreground/50" />
            <p className="text-xs text-muted-foreground mb-2">No intelligence result yet</p>
            <Button size="sm" variant="outline" onClick={handleProcess} disabled={processing} data-testid="initial-process-btn">
              {processing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <ScanSearch className="w-3 h-3 mr-1" />} Run Intelligence Pipeline
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
                {result.automation_reasoning && <p className="text-[11px] text-muted-foreground mt-0.5">{result.automation_reasoning}</p>}
              </div>
              {result.manually_corrected && <Badge variant="outline" className="text-[9px] border-blue-500/30 text-blue-400">Corrected</Badge>}
            </div>

            {result.automation_readiness_reasons?.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {result.automation_readiness_reasons.map((r, i) => (
                  <Badge key={i} variant="outline" className="text-[9px] font-mono border-muted-foreground/30">{r}</Badge>
                ))}
              </div>
            )}

            {/* Entity Resolution Section */}
            <div className="border border-border rounded-lg overflow-hidden" data-testid="entity-resolution-section">
              <button className="w-full flex items-center justify-between p-3 hover:bg-accent/30 transition-colors" onClick={() => setShowResolutions(!showResolutions)}>
                <div className="flex items-center gap-2">
                  <Link2 className="w-4 h-4 text-muted-foreground" />
                  <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Entity Resolution</span>
                  {erStatus && (
                    <Badge variant="outline" className={`text-[9px] ${erStatus === 'resolved' ? 'border-emerald-500/30 text-emerald-400' : erStatus === 'needs_review' ? 'border-amber-500/30 text-amber-400' : erStatus === 'blocked' ? 'border-red-500/30 text-red-400' : 'border-border'}`}>
                      {erStatus}
                    </Badge>
                  )}
                  {(result.unresolved_entity_count > 0 || result.ambiguous_entity_count > 0) && (
                    <span className="text-[10px] text-muted-foreground">
                      {result.unresolved_entity_count > 0 && <span className="text-red-400">{result.unresolved_entity_count} unresolved</span>}
                      {result.unresolved_entity_count > 0 && result.ambiguous_entity_count > 0 && ' · '}
                      {result.ambiguous_entity_count > 0 && <span className="text-amber-400">{result.ambiguous_entity_count} ambiguous</span>}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={(e) => { e.stopPropagation(); handleResolveEntities(); }} disabled={resolving} data-testid="resolve-entities-btn">
                    {resolving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Users className="w-3 h-3 mr-1" />}
                    {resolutions.length > 0 ? 'Re-resolve' : 'Resolve'}
                  </Button>
                  {showResolutions ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                </div>
              </button>

              {showResolutions && (
                <div className="border-t border-border p-3 space-y-2">
                  {resolutions.length === 0 ? (
                    <p className="text-[11px] text-muted-foreground text-center py-2">No entity resolutions yet. Click "Resolve" to match extracted entities.</p>
                  ) : (
                    resolutions.map((res) => {
                      const st = RES_STATUS_STYLE[res.resolution_status] || RES_STATUS_STYLE.unmatched;
                      const StIcon = st.icon;
                      const isCorrectingThis = correctingId === res.resolution_id;

                      return (
                        <div key={res.resolution_id} className={`p-2.5 rounded-md ${st.bg} border border-transparent`} data-testid={`resolution-${res.resolution_id}`}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                <StIcon className={`w-3.5 h-3.5 ${st.color} shrink-0`} />
                                <span className="text-[10px] font-bold uppercase tracking-wider text-muted-foreground">{ENTITY_LABELS[res.entity_kind] || res.entity_kind}</span>
                                <Badge variant="outline" className={`text-[8px] ${st.color} border-current/30`}>{st.label}</Badge>
                                <span className="text-[9px] text-muted-foreground font-mono">{((res.match_confidence || 0) * 100).toFixed(0)}%</span>
                              </div>
                              <div className="flex items-center gap-1 text-[11px]">
                                <span className="text-muted-foreground truncate max-w-[100px]">{res.source_field}:</span>
                                <span className="font-mono font-medium truncate max-w-[140px]">"{res.source_value}"</span>
                              </div>
                              {res.matched_entity_name && (
                                <div className="flex items-center gap-1 mt-0.5 text-[11px]">
                                  <span className="text-muted-foreground">→</span>
                                  <span className={`font-medium ${st.color}`}>{res.matched_entity_name}</span>
                                  <span className="text-[9px] text-muted-foreground">via {res.match_method}</span>
                                </div>
                              )}
                            </div>
                          </div>

                          {/* Candidates for ambiguous / low confidence */}
                          {res.candidate_matches?.length > 1 && (res.resolution_status === 'ambiguous' || res.resolution_status === 'unmatched') && (
                            <div className="mt-2 space-y-1">
                              <p className="text-[9px] text-muted-foreground uppercase tracking-wider">Candidates:</p>
                              {res.candidate_matches.slice(0, 4).map((c, ci) => (
                                <div key={ci} className="flex items-center justify-between py-0.5">
                                  <span className="text-[10px] font-mono truncate max-w-[180px]">{c.entity_name} ({(c.score * 100).toFixed(0)}%)</span>
                                  <Button
                                    variant="ghost" size="sm" className="h-5 text-[9px] px-1.5"
                                    onClick={() => handleConfirmCandidate(res.resolution_id, c)}
                                    disabled={isCorrectingThis}
                                    data-testid={`confirm-candidate-${res.resolution_id}-${ci}`}
                                  >
                                    {isCorrectingThis ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <CheckCircle className="w-2.5 h-2.5 mr-0.5" />}
                                    Confirm
                                  </Button>
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Manual override for unmatched */}
                          {(res.resolution_status === 'unmatched') && (
                            <div className="mt-2 flex items-center gap-1">
                              <Input
                                placeholder="Entity ID"
                                value={correctionInput.id}
                                onChange={e => setCorrectionInput(prev => ({ ...prev, id: e.target.value }))}
                                className="h-6 text-[10px] flex-1 font-mono"
                                data-testid={`manual-id-${res.resolution_id}`}
                              />
                              <Input
                                placeholder="Name"
                                value={correctionInput.name}
                                onChange={e => setCorrectionInput(prev => ({ ...prev, name: e.target.value }))}
                                className="h-6 text-[10px] flex-1"
                                data-testid={`manual-name-${res.resolution_id}`}
                              />
                              <Button
                                variant="outline" size="sm" className="h-6 text-[9px] px-2"
                                onClick={() => handleCorrectResolution(res.resolution_id)}
                                disabled={isCorrectingThis || !correctionInput.id}
                                data-testid={`manual-resolve-btn-${res.resolution_id}`}
                              >
                                {isCorrectingThis ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <Save className="w-2.5 h-2.5" />}
                              </Button>
                            </div>
                          )}
                        </div>
                      );
                    })
                  )}
                </div>
              )}
            </div>

            {/* Auto-Draft Action Section */}
            {isReady && !editing && (
              <div className="border border-border rounded-lg p-3 space-y-2" data-testid="auto-draft-section">
                {!hasDraft ? (
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold">Automation Available</p>
                      <p className="text-[11px] text-muted-foreground">Create {DRAFT_TYPE_LABELS[result.target_entity_type] || 'draft'} from extracted fields</p>
                      {erNeedsReview && <p className="text-[10px] text-amber-400 mt-0.5">Some entities need review — draft will use extracted values</p>}
                    </div>
                    <Button size="sm" onClick={handleCreateDraft} disabled={creatingDraft || erBlocked} className="bg-emerald-600 hover:bg-emerald-700 text-white" data-testid="create-draft-btn">
                      {creatingDraft ? <Loader2 className="w-3 h-3 animate-spin mr-1.5" /> : <Zap className="w-3 h-3 mr-1.5" />}
                      Create Draft
                    </Button>
                  </div>
                ) : (
                  <div className="space-y-2">
                    <div className="flex items-center gap-2">
                      <CheckCircle className="w-4 h-4 text-emerald-500" />
                      <span className="text-xs font-semibold text-emerald-400">{draftResult.status === 'duplicate' ? 'Draft Already Exists' : 'Draft Created'}</span>
                    </div>
                    <div className="flex items-center gap-2 p-2 bg-accent/30 rounded">
                      <FileText className="w-3.5 h-3.5 text-muted-foreground" />
                      <div className="flex-1">
                        <p className="text-xs font-medium">{DRAFT_TYPE_LABELS[draftResult.target_entity_type] || draftResult.target_entity_type}</p>
                        <p className="text-[10px] font-mono text-muted-foreground">{draftResult.target_entity_id}</p>
                      </div>
                      <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => { navigator.clipboard.writeText(draftResult.target_entity_id || ''); toast.success('Copied'); }} data-testid="copy-draft-id-btn"><Copy className="w-3 h-3" /></Button>
                    </div>
                    {draftResult.message && draftResult.status === 'duplicate' && <p className="text-[10px] text-amber-400">{draftResult.message}</p>}
                  </div>
                )}
                {draftResult?.status === 'failed' && <div className="p-2 bg-red-500/10 border border-red-500/30 rounded text-[11px] text-red-400">{draftResult.message}</div>}
              </div>
            )}

            {/* Entity resolution blocking auto-draft */}
            {erBlocked && !editing && (
              <div className="border border-red-500/30 rounded-lg p-3 bg-red-500/5" data-testid="er-blocked-notice">
                <div className="flex items-center gap-2 mb-1">
                  <Unlink className="w-4 h-4 text-red-400" />
                  <span className="text-xs font-semibold text-red-400">Auto-Draft Blocked</span>
                </div>
                <p className="text-[11px] text-muted-foreground">Resolve unmatched entities before creating drafts.</p>
                {result.entity_resolution_blocking_items?.map((item, i) => (
                  <Badge key={i} variant="outline" className="text-[9px] font-mono border-red-500/30 text-red-400 mt-1 mr-1">{item}</Badge>
                ))}
              </div>
            )}

            {/* Classification */}
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Classification</p>
              <div className="grid grid-cols-2 gap-2">
                <div className="p-2 bg-accent/30 rounded">
                  <p className="text-[10px] text-muted-foreground">Type</p>
                  {editing ? <Input value={editType} onChange={e => setEditType(e.target.value)} className="h-7 text-xs mt-1" data-testid="edit-doc-type-input" />
                    : <p className="text-xs font-mono font-semibold">{result.document_type}</p>}
                </div>
                <div className="p-2 bg-accent/30 rounded">
                  <p className="text-[10px] text-muted-foreground">Confidence</p>
                  <div className="flex items-center gap-2 mt-1">
                    <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${result.classification_confidence >= 0.9 ? 'bg-emerald-500' : result.classification_confidence >= 0.75 ? 'bg-amber-500' : 'bg-red-500'}`} style={{ width: `${(result.classification_confidence || 0) * 100}%` }} />
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
                        {field}{isRequired && <span className="text-red-400 ml-0.5">*</span>}
                      </span>
                      {editing ? (
                        <Input value={typeof val === 'object' ? JSON.stringify(val) : val} onChange={e => setEditFields(p => ({ ...p, [field]: e.target.value }))} className="h-6 text-xs flex-1 font-mono" data-testid={`edit-field-${field}`} />
                      ) : (
                        <span className={`text-xs font-mono flex-1 truncate ${isMissing ? 'text-red-400 italic' : ''}`}>
                          {isMissing ? 'missing' : (typeof val === 'object' ? JSON.stringify(val) : String(val))}
                        </span>
                      )}
                      {!editing && isRequired && (isMissing ? <XCircle className="w-3 h-3 text-red-400 shrink-0" /> : <CheckCircle className="w-3 h-3 text-emerald-500 shrink-0" />)}
                    </div>
                  );
                })}
              </div>
            </div>

            {editing && (
              <div className="flex items-center gap-2 pt-2 border-t border-border">
                <Button size="sm" onClick={handleSave} disabled={saving} data-testid="save-corrections-btn">
                  {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />} Save Corrections
                </Button>
                <Button size="sm" variant="ghost" onClick={cancelEditing} data-testid="cancel-edit-btn"><X className="w-3 h-3 mr-1" /> Cancel</Button>
              </div>
            )}

            {result.correction_history?.length > 0 && (
              <div className="pt-2 border-t border-border">
                <button className="flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground transition-colors" onClick={() => setShowHistory(!showHistory)} data-testid="toggle-correction-history">
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
                        {h.changes?.document_type && <p className="mt-0.5">Type: <span className="font-mono">{h.changes.document_type.from}</span> → <span className="font-mono font-semibold">{h.changes.document_type.to}</span></p>}
                        {h.changes?.extracted_fields && Object.entries(h.changes.extracted_fields).map(([k, v]) => (
                          <p key={k}>{k}: <span className="font-mono">{v.from || '(empty)'}</span> → <span className="font-mono font-semibold">{v.to}</span></p>
                        ))}
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
