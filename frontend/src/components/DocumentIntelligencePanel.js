import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import {
  ScanSearch, RefreshCw, CheckCircle, AlertTriangle, XCircle, Pencil, Save, X, Loader2,
  History, ChevronDown, ChevronUp, Zap, Copy, FileText, Link2, Users, Unlink, ArrowRight, GitMerge, Ban, Layers, PackageSearch, Activity, ShieldAlert, Brain, Play
} from 'lucide-react';
import {
  getDocumentIntelligence, processDocumentIntelligence, correctDocumentIntelligence,
  createAutoDraft, resolveDocumentEntities, getDocumentResolutions, correctResolution,
  matchTransactions, getTransactionMatches, autoLinkDocument, confirmTransactionMatch,
  getBundle, validateLifecycle, evaluateDecision, executeDecision, getDecision
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

  // Transaction matching state
  const [txMatches, setTxMatches] = useState([]);
  const [matching, setMatching] = useState(false);
  const [showMatches, setShowMatches] = useState(true);
  const [linking, setLinking] = useState(false);
  const [linkResult, setLinkResult] = useState(null);
  const [confirmingMatchId, setConfirmingMatchId] = useState(null);

  // Bundle state
  const [bundleInfo, setBundleInfo] = useState(null);
  const [showBundle, setShowBundle] = useState(true);

  // Lifecycle state
  const [showLifecycle, setShowLifecycle] = useState(true);
  const [lifecycleValidating, setLifecycleValidating] = useState(false);

  // Decision state
  const [decisionData, setDecisionData] = useState(null);
  const [showDecision, setShowDecision] = useState(true);
  const [evaluating, setEvaluating] = useState(false);
  const [executing, setExecuting] = useState(false);

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
      if (data.auto_link_created) {
        setLinkResult({ status: 'linked', target: data.best_transaction_match });
      }
      // Fetch bundle info if document belongs to one
      if (data.bundle_id) {
        try {
          const { data: bData } = await getBundle(data.bundle_id);
          setBundleInfo(bData);
        } catch { setBundleInfo(null); }
      } else {
        setBundleInfo(null);
      }
    } catch { setResult(null); }
    // Fetch resolutions
    try {
      const { data: resData } = await getDocumentResolutions(docId);
      setResolutions(resData.resolutions || []);
    } catch { setResolutions([]); }
    // Fetch transaction matches
    try {
      const { data: tmData } = await getTransactionMatches(docId);
      setTxMatches(tmData.matches || []);
    } catch { setTxMatches([]); }
    // Fetch latest decision
    try {
      const { data: decData } = await getDecision(docId);
      setDecisionData(decData);
    } catch { setDecisionData(null); }
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

  const handleMatchTransactions = async () => {
    setMatching(true);
    try {
      const { data } = await matchTransactions(docId);
      setTxMatches(data.matches || []);
      setResult(prev => prev ? { ...prev, transaction_match_status: data.overall_status, auto_link_available: data.auto_link_available, matched_transaction_count: data.total_candidates, best_transaction_match: data.best_match } : prev);
      toast.success(`${data.total_candidates} transaction candidate${data.total_candidates !== 1 ? 's' : ''} found`);
      onUpdate?.();
    } catch (err) { toast.error(err.response?.data?.detail || 'Matching failed'); }
    finally { setMatching(false); }
  };

  const handleAutoLink = async () => {
    setLinking(true);
    try {
      const { data } = await autoLinkDocument(docId);
      if (data.linked) {
        setLinkResult({ status: 'linked', target: { entity_type: data.target_entity_type, entity_id: data.target_entity_id, display_name: data.target_display_name, confidence: data.match_confidence } });
        toast.success(`Linked to ${data.target_display_name}`);
        fetchResult();
      }
      onUpdate?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Auto-link failed');
    } finally { setLinking(false); }
  };

  const handleConfirmTxMatch = async (matchId) => {
    setConfirmingMatchId(matchId);
    try {
      await confirmTransactionMatch(matchId, { confirmed: true, selected_by: 'admin', notes: 'Confirmed from UI' });
      toast.success('Match confirmed');
      fetchResult();
    } catch (err) { toast.error(err.response?.data?.detail || 'Confirmation failed'); }
    finally { setConfirmingMatchId(null); }
  };

  const handleRejectTxMatch = async (matchId) => {
    setConfirmingMatchId(matchId);
    try {
      await confirmTransactionMatch(matchId, { confirmed: false, selected_by: 'admin', notes: 'Rejected from UI' });
      toast.success('Match rejected');
      fetchResult();
    } catch (err) { toast.error(err.response?.data?.detail || 'Rejection failed'); }
    finally { setConfirmingMatchId(null); }
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
  const tmStatus = result?.transaction_match_status;
  const hasLink = linkResult?.status === 'linked' || result?.auto_link_created;
  const canAutoLink = result?.auto_link_available && !hasLink;
  const draftSuppressed = result?.auto_draft_suppressed_due_to_match && !hasLink;

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
            <div data-testid="entity-resolution-section">
              <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors" onClick={() => setShowResolutions(!showResolutions)}>
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
              </div>

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

            {/* Transaction Matching Section */}
            {result && !editing && (
              <div className="border border-border rounded-lg overflow-hidden" data-testid="transaction-matching-section">
                <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors" onClick={() => setShowMatches(!showMatches)}>
                  <div className="flex items-center gap-2">
                    <GitMerge className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Transaction Matching</span>
                    {tmStatus && (
                      <Badge variant="outline" className={`text-[9px] ${tmStatus === 'matched' || tmStatus === 'confirmed' ? 'border-emerald-500/30 text-emerald-400' : tmStatus === 'ambiguous' ? 'border-amber-500/30 text-amber-400' : 'border-muted-foreground/30'}`}>
                        {tmStatus}
                      </Badge>
                    )}
                    {result.matched_transaction_count > 0 && <span className="text-[10px] text-muted-foreground">{result.matched_transaction_count} candidate{result.matched_transaction_count !== 1 ? 's' : ''}</span>}
                  </div>
                  <div className="flex items-center gap-1">
                    <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={(e) => { e.stopPropagation(); handleMatchTransactions(); }} disabled={matching} data-testid="match-transactions-btn">
                      {matching ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <GitMerge className="w-3 h-3 mr-1" />}
                      {txMatches.length > 0 ? 'Re-match' : 'Match'}
                    </Button>
                    {showMatches ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                  </div>
                </div>

                {showMatches && (
                  <div className="border-t border-border p-3 space-y-2">
                    {/* Linked state */}
                    {hasLink && (
                      <div className="flex items-center gap-2 p-2.5 bg-emerald-500/10 border border-emerald-500/30 rounded-md" data-testid="linked-transaction">
                        <Link2 className="w-4 h-4 text-emerald-400" />
                        <div className="flex-1">
                          <p className="text-xs font-semibold text-emerald-400">Linked to Existing Transaction</p>
                          <p className="text-[10px] font-mono text-muted-foreground">{linkResult?.target?.display_name || result?.best_transaction_match?.display_name || result?.best_transaction_match?.entity_id}</p>
                        </div>
                        <Button variant="ghost" size="sm" className="h-6 text-xs" onClick={() => { navigator.clipboard.writeText(linkResult?.target?.entity_id || result?.best_transaction_match?.entity_id || ''); toast.success('Copied'); }} data-testid="copy-link-id-btn"><Copy className="w-3 h-3" /></Button>
                      </div>
                    )}

                    {/* Candidates */}
                    {!hasLink && txMatches.length === 0 && <p className="text-[11px] text-muted-foreground text-center py-2">No transaction matches yet. Click "Match" to search.</p>}

                    {!hasLink && txMatches.map((m) => {
                      const isHigh = m.match_confidence >= 0.90;
                      const isConfirmed = m.match_status === 'confirmed';
                      const isRejected = m.match_status === 'rejected';
                      const isProcessing = confirmingMatchId === m.transaction_match_id;

                      return (
                        <div key={m.transaction_match_id} className={`p-2.5 rounded-md border ${isConfirmed ? 'border-emerald-500/30 bg-emerald-500/10' : isRejected ? 'border-red-500/20 bg-red-500/5 opacity-50' : isHigh ? 'border-emerald-500/20 bg-accent/30' : 'border-border bg-accent/20'}`} data-testid={`tx-match-${m.transaction_match_id}`}>
                          <div className="flex items-start justify-between gap-2">
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1.5 mb-1">
                                {isConfirmed ? <CheckCircle className="w-3.5 h-3.5 text-emerald-400 shrink-0" /> : isRejected ? <Ban className="w-3.5 h-3.5 text-red-400 shrink-0" /> : <FileText className="w-3.5 h-3.5 text-muted-foreground shrink-0" />}
                                <Badge variant="secondary" className="text-[8px] font-mono">{m.candidate_entity_type}</Badge>
                                <span className={`text-[9px] font-mono font-bold ${isHigh ? 'text-emerald-400' : m.match_confidence >= 0.70 ? 'text-amber-400' : 'text-muted-foreground'}`}>{(m.match_confidence * 100).toFixed(0)}%</span>
                                {isConfirmed && <Badge variant="outline" className="text-[8px] border-emerald-500/30 text-emerald-400">Confirmed</Badge>}
                                {isRejected && <Badge variant="outline" className="text-[8px] border-red-500/30 text-red-400">Rejected</Badge>}
                              </div>
                              <p className="text-[11px] font-medium truncate">{m.candidate_display_name}</p>
                              <p className="text-[9px] text-muted-foreground font-mono mt-0.5">Basis: {m.match_basis}</p>
                            </div>
                            {!isConfirmed && !isRejected && (
                              <div className="flex items-center gap-1 shrink-0">
                                <Button variant="ghost" size="sm" className="h-6 text-[9px] text-emerald-400 hover:text-emerald-300" onClick={() => handleConfirmTxMatch(m.transaction_match_id)} disabled={isProcessing} data-testid={`confirm-tx-${m.transaction_match_id}`}>
                                  {isProcessing ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : <CheckCircle className="w-2.5 h-2.5 mr-0.5" />} Confirm
                                </Button>
                                <Button variant="ghost" size="sm" className="h-6 text-[9px] text-red-400 hover:text-red-300" onClick={() => handleRejectTxMatch(m.transaction_match_id)} disabled={isProcessing} data-testid={`reject-tx-${m.transaction_match_id}`}>
                                  <Ban className="w-2.5 h-2.5 mr-0.5" /> Reject
                                </Button>
                              </div>
                            )}
                          </div>
                        </div>
                      );
                    })}

                    {/* Auto-link button */}
                    {canAutoLink && !hasLink && (
                      <Button size="sm" onClick={handleAutoLink} disabled={linking} className="w-full bg-blue-600 hover:bg-blue-700 text-white" data-testid="auto-link-btn">
                        {linking ? <Loader2 className="w-3 h-3 animate-spin mr-1.5" /> : <Link2 className="w-3 h-3 mr-1.5" />}
                        Link to Existing Transaction
                      </Button>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Auto-Draft / Link Action Section */}

            {/* Document Bundle Section */}
            {(result?.bundle_id || bundleInfo) && (
              <div data-testid="bundle-membership-section">
                <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors" onClick={() => setShowBundle(!showBundle)}>
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Document Bundle</span>
                    {result?.bundle_completeness_status && (
                      <Badge variant="outline" className={`text-[9px] ${result.bundle_completeness_status === 'complete' ? 'border-emerald-500/30 text-emerald-400' : result.bundle_completeness_status === 'partial' ? 'border-amber-500/30 text-amber-400' : 'border-red-500/30 text-red-400'}`}>
                        {result.bundle_completeness_status}
                      </Badge>
                    )}
                    {result?.related_document_count > 0 && (
                      <span className="text-[10px] text-muted-foreground">{result.related_document_count} related doc{result.related_document_count !== 1 ? 's' : ''}</span>
                    )}
                  </div>
                  {showBundle ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                </div>

                {showBundle && bundleInfo && (
                  <div className="border-t border-border p-3 space-y-2">
                    <div className="flex items-center gap-2 p-2 bg-accent/30 rounded">
                      <PackageSearch className="w-3.5 h-3.5 text-muted-foreground" />
                      <div className="flex-1">
                        <p className="text-[11px] font-semibold">{bundleInfo.bundle_id}</p>
                        <div className="flex items-center gap-1.5 mt-0.5">
                          <Badge variant="secondary" className="text-[8px]">
                            {({'customer_order_packet':'Customer Order','purchasing_packet':'Purchasing','ap_packet':'AP Packet','warehouse_packet':'Warehouse','unknown':'Unknown'})[bundleInfo.bundle_type] || bundleInfo.bundle_type}
                          </Badge>
                          <Badge variant="outline" className={`text-[8px] ${bundleInfo.bundle_status === 'complete' ? 'border-emerald-500/30 text-emerald-400' : bundleInfo.bundle_status === 'needs_review' ? 'border-amber-500/30 text-amber-400' : 'border-border'}`}>
                            {bundleInfo.bundle_status}
                          </Badge>
                        </div>
                      </div>
                      <Button variant="ghost" size="sm" className="h-6 text-[9px]" onClick={() => { navigator.clipboard.writeText(bundleInfo.bundle_id); toast.success('Copied'); }} data-testid="copy-bundle-id-btn">
                        <Copy className="w-3 h-3" />
                      </Button>
                    </div>

                    {/* Related docs */}
                    {bundleInfo.member_documents?.filter(d => d.document_id !== docId).map(doc => (
                      <div key={doc.document_id} className="flex items-center gap-2 p-1.5 bg-accent/10 rounded text-[10px]">
                        <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
                        <span className="font-mono truncate flex-1">{doc.file_name || doc.document_id}</span>
                        <Badge variant="secondary" className="text-[8px]">{doc.document_type}</Badge>
                      </div>
                    ))}

                    {/* Missing docs warning */}
                    {bundleInfo.missing_expected_documents?.length > 0 && (
                      <div className="p-2 bg-red-500/5 border border-red-500/20 rounded" data-testid="bundle-missing-docs">
                        <p className="text-[10px] text-red-400 font-semibold mb-1">Missing from packet:</p>
                        {bundleInfo.missing_expected_documents.map((m, i) => (
                          <p key={i} className="text-[10px] text-red-300 flex items-center gap-1"><XCircle className="w-2.5 h-2.5" /> {m}</p>
                        ))}
                      </div>
                    )}

                    {bundleInfo.suggested_next_action && (
                      <p className="text-[10px] text-blue-400 font-medium">{bundleInfo.suggested_next_action}</p>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Lifecycle Status Section */}
            {result && (
              <div data-testid="lifecycle-status-section">
                <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors" onClick={() => setShowLifecycle(!showLifecycle)}>
                  <div className="flex items-center gap-2">
                    <Activity className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Lifecycle Status</span>
                    {result.lifecycle_status && (
                      <Badge variant="outline" className={`text-[9px] ${result.lifecycle_status === 'valid' ? 'border-emerald-500/30 text-emerald-400' : result.lifecycle_status === 'duplicate_detected' ? 'border-red-500/30 text-red-400' : result.lifecycle_status === 'inconsistent' ? 'border-orange-500/30 text-orange-400' : result.lifecycle_status === 'incomplete' ? 'border-amber-500/30 text-amber-400' : 'border-blue-500/30 text-blue-400'}`}>
                        {result.lifecycle_status === 'valid' ? 'Valid' : result.lifecycle_status === 'duplicate_detected' ? 'Duplicate' : result.lifecycle_status === 'inconsistent' ? 'Inconsistent' : result.lifecycle_status === 'incomplete' ? 'Incomplete' : result.lifecycle_status || 'Not Validated'}
                      </Badge>
                    )}
                    {result.lifecycle_stage && result.lifecycle_stage !== 'unknown' && (
                      <span className="text-[10px] text-muted-foreground">Stage: {result.lifecycle_stage}</span>
                    )}
                  </div>
                  {showLifecycle ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                </div>

                {showLifecycle && (
                  <div className="border-t border-border p-3 space-y-2">
                    {!result.lifecycle_status ? (
                      <p className="text-[10px] text-muted-foreground italic">Lifecycle not yet validated for this document's entity</p>
                    ) : (
                      <>
                        {result.lifecycle_missing_documents?.length > 0 && (
                          <div className="p-2 bg-amber-500/5 border border-amber-500/20 rounded" data-testid="lifecycle-panel-missing">
                            <p className="text-[10px] text-amber-400 font-semibold mb-1">Missing from lifecycle:</p>
                            {result.lifecycle_missing_documents.map((m, i) => (
                              <p key={i} className="text-[10px] text-amber-300 flex items-center gap-1"><AlertTriangle className="w-2.5 h-2.5" /> {m}</p>
                            ))}
                          </div>
                        )}
                        {result.lifecycle_duplicate_flags?.length > 0 && (
                          <div className="p-2 bg-red-500/5 border border-red-500/20 rounded" data-testid="lifecycle-panel-duplicates">
                            <p className="text-[10px] text-red-400 font-semibold mb-1">Duplicates detected:</p>
                            {result.lifecycle_duplicate_flags.map((d, i) => (
                              <p key={i} className="text-[10px] text-red-300 flex items-center gap-1"><XCircle className="w-2.5 h-2.5" /> {d}</p>
                            ))}
                          </div>
                        )}
                        {result.lifecycle_status === 'valid' && (
                          <div className="flex items-center gap-1.5 text-[10px] text-emerald-400">
                            <CheckCircle className="w-3 h-3" /> Lifecycle is valid — no issues detected
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {/* Decision Engine Section */}
            {result && (
              <div data-testid="decision-engine-section">
                <div className="flex items-center justify-between p-3 cursor-pointer hover:bg-accent/30 transition-colors" onClick={() => setShowDecision(!showDecision)}>
                  <div className="flex items-center gap-2">
                    <Brain className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Decision Engine</span>
                    {result.latest_decision_action && (
                      <Badge variant="outline" className={`text-[9px] ${result.latest_decision_action === 'create_draft' ? 'border-emerald-500/30 text-emerald-400' : result.latest_decision_action === 'link_existing' ? 'border-blue-500/30 text-blue-400' : result.latest_decision_action === 'hold_for_review' ? 'border-amber-500/30 text-amber-400' : 'border-red-500/30 text-red-400'}`}>
                        {result.latest_decision_action === 'create_draft' ? 'Create Draft' : result.latest_decision_action === 'link_existing' ? 'Link Existing' : result.latest_decision_action === 'hold_for_review' ? 'Hold' : result.latest_decision_action === 'block' ? 'Blocked' : result.latest_decision_action || '—'}
                      </Badge>
                    )}
                    {result.latest_automation_level && (
                      <Badge variant="secondary" className="text-[8px]">{result.latest_automation_level}</Badge>
                    )}
                  </div>
                  {showDecision ? <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" /> : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />}
                </div>

                {showDecision && (
                  <div className="border-t border-border p-3 space-y-2">
                    {!decisionData ? (
                      <div className="flex items-center justify-between">
                        <p className="text-[10px] text-muted-foreground italic">No decision evaluated yet</p>
                        <Button variant="outline" size="sm" className="h-6 text-[10px]" onClick={async () => {
                          setEvaluating(true);
                          try { const { data } = await evaluateDecision(docId); setDecisionData(data); fetchResult(); toast.success(`Decision: ${data.decision_action}`); }
                          catch (err) { toast.error(err.response?.data?.detail || 'Evaluation failed'); }
                          finally { setEvaluating(false); }
                        }} disabled={evaluating} data-testid="evaluate-decision-btn">
                          {evaluating ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Brain className="w-3 h-3 mr-1" />} Evaluate
                        </Button>
                      </div>
                    ) : (
                      <>
                        {/* Status + Target */}
                        <div className={`p-2 rounded border ${decisionData.decision_status === 'ready' ? 'bg-emerald-500/5 border-emerald-500/30' : decisionData.decision_status === 'executed' ? 'bg-blue-500/5 border-blue-500/30' : decisionData.decision_status === 'blocked' ? 'bg-red-500/5 border-red-500/30' : 'bg-amber-500/5 border-amber-500/30'}`}>
                          <div className="flex items-center gap-2">
                            <Badge variant="outline" className={`text-[9px] ${decisionData.decision_status === 'ready' ? 'border-emerald-500/30 text-emerald-400' : decisionData.decision_status === 'executed' ? 'border-blue-500/30 text-blue-400' : decisionData.decision_status === 'blocked' ? 'border-red-500/30 text-red-400' : 'border-amber-500/30 text-amber-400'}`}>
                              {decisionData.decision_status}
                            </Badge>
                            <span className="text-[10px] font-mono">{decisionData.policy_name}</span>
                          </div>
                          {decisionData.target_summary && (
                            <p className="text-[10px] mt-1 text-muted-foreground">{decisionData.target_summary}</p>
                          )}
                        </div>

                        {/* Reasons */}
                        {decisionData.decision_reasons?.length > 0 && (
                          <div data-testid="decision-reasons">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-1">Reasons</p>
                            {decisionData.decision_reasons.map((r, i) => (
                              <div key={i} className="flex items-start gap-1.5 mt-0.5">
                                <ArrowRight className="w-2.5 h-2.5 text-muted-foreground mt-0.5 shrink-0" />
                                <span className="text-[10px] text-muted-foreground">{r.message}</span>
                              </div>
                            ))}
                          </div>
                        )}

                        {/* Action Buttons */}
                        <div className="flex items-center gap-2 pt-1">
                          {decisionData.decision_status === 'ready' && (
                            <Button size="sm" className={`h-6 text-[10px] ${decisionData.decision_action === 'create_draft' ? 'bg-emerald-600 hover:bg-emerald-700' : 'bg-blue-600 hover:bg-blue-700'} text-white`} onClick={async () => {
                              setExecuting(true);
                              try { const { data } = await executeDecision(decisionData.decision_id); if (data.executed) { toast.success(`Executed: ${data.decision_action}`); fetchResult(); } else { toast.info(data.reason); } }
                              catch (err) { toast.error(err.response?.data?.detail || 'Execution failed'); }
                              finally { setExecuting(false); }
                            }} disabled={executing} data-testid="execute-decision-btn">
                              {executing ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Play className="w-3 h-3 mr-1" />}
                              {decisionData.decision_action === 'create_draft' ? 'Execute: Create Draft' : decisionData.decision_action === 'link_existing' ? 'Execute: Link Existing' : 'Execute'}
                            </Button>
                          )}
                          {(decisionData.decision_status === 'review_required' || decisionData.decision_status === 'blocked') && (
                            <p className="text-[10px] text-amber-400 italic">
                              {decisionData.decision_status === 'blocked' ? 'Blocked — resolve issues to proceed' : 'Awaiting human review'}
                            </p>
                          )}
                          {decisionData.decision_status === 'executed' && (
                            <p className="text-[10px] text-emerald-400 flex items-center gap-1"><CheckCircle className="w-3 h-3" /> Decision executed</p>
                          )}
                          <Button variant="ghost" size="sm" className="h-6 text-[10px] ml-auto" onClick={async () => {
                            setEvaluating(true);
                            try { const { data } = await evaluateDecision(docId); setDecisionData(data); fetchResult(); toast.success(`Re-evaluated: ${data.decision_action}`); }
                            catch (err) { toast.error(err.response?.data?.detail || 'Re-evaluation failed'); }
                            finally { setEvaluating(false); }
                          }} disabled={evaluating} data-testid="re-evaluate-btn">
                            {evaluating ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                          </Button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )}

            {isReady && !editing && !hasLink && (
              <div className="border border-border rounded-lg p-3 space-y-2" data-testid="auto-draft-section">
                {draftSuppressed && !hasDraft ? (
                  <div className="flex items-center gap-2 p-2 bg-blue-500/10 border border-blue-500/30 rounded">
                    <GitMerge className="w-4 h-4 text-blue-400" />
                    <div className="flex-1">
                      <p className="text-xs font-semibold text-blue-400">Existing Match Found</p>
                      <p className="text-[10px] text-muted-foreground">Draft creation suppressed — use "Link to Existing Transaction" above</p>
                    </div>
                  </div>
                ) : !hasDraft ? (
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-xs font-semibold">Create New Draft</p>
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
