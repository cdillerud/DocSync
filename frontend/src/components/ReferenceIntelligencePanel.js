import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { toast } from 'sonner';
import {
  Brain, FileSearch, Loader2, ChevronDown, ChevronRight,
  CheckCircle2, AlertTriangle, XCircle, Clock, Target,
  Search, ArrowRight, Zap, Database, Hash
} from 'lucide-react';
import { resolveDocumentIntelligence, getDocumentReferenceIntelligence } from '../lib/api';

const OUTCOME_CONFIG = {
  exact_match: { label: 'Exact Match', color: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300', icon: CheckCircle2 },
  likely_match: { label: 'Likely Match', color: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300', icon: Target },
  ambiguous_match: { label: 'Ambiguous', color: 'bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300', icon: AlertTriangle },
  no_match: { label: 'No Match', color: 'bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300', icon: XCircle },
};

const DOMAIN_COLORS = {
  purchase: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
  sales: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
  shipping: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
  unknown: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
};

const LABEL_COLORS = {
  PO: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-950/40 dark:text-violet-300 dark:border-violet-700',
  BOL: 'bg-teal-50 text-teal-700 border-teal-200 dark:bg-teal-950/40 dark:text-teal-300 dark:border-teal-700',
  ORDER: 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-700',
  INVOICE: 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-950/40 dark:text-orange-300 dark:border-orange-700',
  SHIPMENT: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-950/40 dark:text-cyan-300 dark:border-cyan-700',
  LOAD: 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-700',
  PRO: 'bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-950/40 dark:text-pink-300 dark:border-pink-700',
  REF: 'bg-gray-50 text-gray-700 border-gray-200 dark:bg-gray-800 dark:text-gray-300 dark:border-gray-600',
  UNKNOWN: 'bg-gray-50 text-gray-500 border-gray-200 dark:bg-gray-800 dark:text-gray-400 dark:border-gray-600',
};

export default function ReferenceIntelligencePanel({ document, onUpdate }) {
  const [intelligence, setIntelligence] = useState(null);
  const [loading, setLoading] = useState(false);
  const [resolving, setResolving] = useState(false);
  const [debugOpen, setDebugOpen] = useState(false);

  const docId = document?.id;

  const fetchIntelligence = useCallback(async () => {
    if (!docId) return;
    try {
      setLoading(true);
      const res = await getDocumentReferenceIntelligence(docId);
      if (res.data && res.data.status !== 'not_resolved') {
        setIntelligence(res.data);
      }
    } catch {
      // No intelligence data yet - that's fine
    } finally {
      setLoading(false);
    }
  }, [docId]);

  useEffect(() => {
    fetchIntelligence();
  }, [fetchIntelligence]);

  // Also check if document already has reference_intelligence stored
  useEffect(() => {
    if (document?.reference_intelligence) {
      setIntelligence(document.reference_intelligence);
    }
  }, [document]);

  const handleResolve = async () => {
    try {
      setResolving(true);
      const res = await resolveDocumentIntelligence(docId);
      setIntelligence(res.data);
      toast.success('Reference intelligence resolution complete');
      onUpdate?.();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Resolution failed');
    } finally {
      setResolving(false);
    }
  };

  const outcome = intelligence?.match_outcome;
  const outcomeConfig = OUTCOME_CONFIG[outcome] || OUTCOME_CONFIG.no_match;
  const OutcomeIcon = outcomeConfig.icon;
  const candidates = intelligence?.reference_candidates || [];
  const bestMatch = intelligence?.best_match;
  const alternates = intelligence?.alternate_matches || [];

  return (
    <Card className="border border-border" data-testid="reference-intelligence-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-4 h-4 text-violet-500" />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Reference Intelligence
            </CardTitle>
          </div>
          <Button
            variant="outline"
            size="sm"
            onClick={handleResolve}
            disabled={resolving}
            className="h-7 text-xs gap-1"
            data-testid="resolve-intelligence-btn"
          >
            {resolving ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
            {resolving ? 'Resolving...' : intelligence ? 'Re-resolve' : 'Resolve'}
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-4 text-sm">
        {/* Auto-resolution status */}
        {document?.reference_intelligence_status === 'pending' && !intelligence && (
          <div className="flex items-center gap-2 text-xs text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/30 rounded px-3 py-2" data-testid="ref-intel-pending">
            <Loader2 className="w-3 h-3 animate-spin" />
            Auto-resolving references in background...
          </div>
        )}
        {document?.reference_intelligence_status === 'failed' && !intelligence && (
          <div className="flex items-center gap-2 text-xs text-red-600 dark:text-red-400 bg-red-50 dark:bg-red-950/30 rounded px-3 py-2" data-testid="ref-intel-failed">
            <XCircle className="w-3 h-3" />
            Auto-resolution failed. Click <strong className="mx-0.5">Resolve</strong> to retry manually.
          </div>
        )}
        {document?.reference_intelligence_status === 'retry_scheduled' && !intelligence && (
          <div className="flex items-center gap-2 text-xs text-orange-600 dark:text-orange-400 bg-orange-50 dark:bg-orange-950/30 rounded px-3 py-2" data-testid="ref-intel-retrying">
            <Clock className="w-3 h-3" />
            Resolution failed — retry scheduled...
          </div>
        )}

        {loading && !intelligence && (
          <div className="flex items-center gap-2 text-xs text-muted-foreground py-2">
            <Loader2 className="w-3 h-3 animate-spin" />
            Loading reference data...
          </div>
        )}

        {!loading && !intelligence && (
          <div className="text-xs text-muted-foreground py-2" data-testid="no-intelligence-msg">
            No reference intelligence data yet. Click <strong>Resolve</strong> to extract and match references against BC.
          </div>
        )}

        {intelligence && (
          <>
            {/* Match Outcome Banner */}
            <div className={`flex items-center justify-between rounded-md px-3 py-2 ${outcomeConfig.color}`} data-testid="match-outcome-banner">
              <div className="flex items-center gap-2">
                <OutcomeIcon className="w-4 h-4" />
                <span className="text-xs font-semibold">{outcomeConfig.label}</span>
              </div>
              {bestMatch && (
                <span className="text-xs font-mono">
                  Score: {(bestMatch.match_score * 100).toFixed(0)}%
                </span>
              )}
            </div>

            {/* Best Match Details */}
            {bestMatch && (
              <div className="border border-border rounded-md p-3 space-y-2" data-testid="best-match-section">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Best Match</p>
                <div className="grid grid-cols-2 gap-y-1.5 text-xs">
                  <span className="text-muted-foreground">BC Doc No:</span>
                  <span className="font-mono font-medium">{bestMatch.bc_document_no}</span>
                  <span className="text-muted-foreground">Entity Type:</span>
                  <Badge variant="outline" className="text-[10px] w-fit">{bestMatch.entity_type?.replace(/_/g, ' ')}</Badge>
                  {bestMatch.bc_record_info?.vendor_name && (
                    <>
                      <span className="text-muted-foreground">Vendor:</span>
                      <span>{bestMatch.bc_record_info.vendor_name}</span>
                    </>
                  )}
                  {bestMatch.bc_record_info?.customer_name && (
                    <>
                      <span className="text-muted-foreground">Customer:</span>
                      <span>{bestMatch.bc_record_info.customer_name}</span>
                    </>
                  )}
                  {bestMatch.bc_record_info?.status && (
                    <>
                      <span className="text-muted-foreground">Status:</span>
                      <span>{bestMatch.bc_record_info.status}</span>
                    </>
                  )}
                  {(bestMatch.bc_record_info?.order_date || bestMatch.bc_record_info?.posting_date) && (
                    <>
                      <span className="text-muted-foreground">Date:</span>
                      <span>{bestMatch.bc_record_info.order_date || bestMatch.bc_record_info.posting_date}</span>
                    </>
                  )}
                </div>
                <p className="text-[10px] text-muted-foreground mt-1 italic">{bestMatch.match_reasoning}</p>
              </div>
            )}

            {/* Alternate Matches */}
            {alternates.length > 0 && (
              <div className="space-y-1.5" data-testid="alternate-matches">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Alternate Matches</p>
                {alternates.map((alt, idx) => (
                  <div key={idx} className="bg-muted/40 rounded px-2.5 py-1.5 flex items-center justify-between text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-mono">{alt.bc_document_no}</span>
                      <Badge variant="outline" className="text-[9px]">{alt.entity_type?.replace(/_/g, ' ')}</Badge>
                    </div>
                    <span className="text-muted-foreground">{(alt.match_score * 100).toFixed(0)}%</span>
                  </div>
                ))}
              </div>
            )}

            {/* Extracted Candidates */}
            {candidates.length > 0 && (
              <div className="space-y-2" data-testid="reference-candidates">
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                  Extracted References ({candidates.length})
                </p>
                <div className="space-y-1">
                  {candidates.map((c, idx) => (
                    <div key={idx} className="bg-muted/30 border border-border/50 rounded px-2.5 py-2 space-y-1">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Hash className="w-3 h-3 text-muted-foreground" />
                          <code className="text-xs font-mono font-medium">{c.reference_value_normalized}</code>
                          <Badge variant="outline" className={`text-[9px] border ${LABEL_COLORS[c.detected_label] || LABEL_COLORS.UNKNOWN}`}>
                            {c.detected_label}
                          </Badge>
                        </div>
                        <span className="text-[10px] text-muted-foreground">{(c.confidence * 100).toFixed(0)}%</span>
                      </div>
                      {c.predicted_domain && (
                        <div className="flex items-center gap-1.5 ml-5">
                          <ArrowRight className="w-2.5 h-2.5 text-muted-foreground" />
                          <Badge variant="secondary" className={`text-[9px] ${DOMAIN_COLORS[c.predicted_domain] || DOMAIN_COLORS.unknown}`}>
                            {c.predicted_domain}
                          </Badge>
                          {c.predicted_entity_types?.length > 0 && (
                            <span className="text-[10px] text-muted-foreground">
                              {c.predicted_entity_types.slice(0, 2).map(e => e.replace(/_/g, ' ')).join(', ')}
                            </span>
                          )}
                        </div>
                      )}
                      {c.reference_value_raw !== c.reference_value_normalized && (
                        <div className="ml-5 text-[10px] text-muted-foreground">
                          Raw: <span className="font-mono">{c.reference_value_raw}</span>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Resolver Debug Panel (collapsible) */}
            <div className="border-t border-border pt-3" data-testid="resolver-debug-panel">
              <button
                onClick={() => setDebugOpen(!debugOpen)}
                className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors w-full"
                data-testid="toggle-debug-panel"
              >
                {debugOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                <Database className="w-3 h-3" />
                <span className="font-medium uppercase tracking-wider">Resolver Debug</span>
              </button>

              {debugOpen && (
                <div className="mt-2 space-y-2 bg-muted/30 rounded-md p-2.5 text-[11px]">
                  <div className="grid grid-cols-2 gap-y-1">
                    <span className="text-muted-foreground">Document Type:</span>
                    <span className="font-mono">{intelligence.document_type}</span>
                    <span className="text-muted-foreground">Strategy:</span>
                    <span className="font-mono">{intelligence.resolver_strategy}</span>
                    <span className="text-muted-foreground">BC Queries:</span>
                    <span>{intelligence.total_bc_queries}</span>
                    <span className="text-muted-foreground">Data Source:</span>
                    <span className={bestMatch?.bc_record_info?.source === 'cache' ? 'text-emerald-600 dark:text-emerald-400 font-medium' : ''}>
                      {bestMatch?.bc_record_info?.source === 'cache' ? 'Cache (local)' : 'BC API (live)'}
                    </span>
                    <span className="text-muted-foreground">Processing Time:</span>
                    <span>{intelligence.processing_time_ms}ms</span>
                    <span className="text-muted-foreground">Resolved At:</span>
                    <span>{intelligence.resolved_at ? new Date(intelligence.resolved_at).toLocaleString() : '-'}</span>
                  </div>

                  {intelligence.search_order?.length > 0 && (
                    <div className="mt-2">
                      <p className="text-[10px] font-medium text-muted-foreground mb-1">Search Order:</p>
                      <div className="flex flex-wrap gap-1">
                        {intelligence.search_order.map((entity, idx) => (
                          <div key={idx} className="flex items-center gap-0.5">
                            {idx > 0 && <ArrowRight className="w-2.5 h-2.5 text-muted-foreground" />}
                            <Badge variant="outline" className="text-[9px] font-mono">{entity.replace(/_/g, ' ')}</Badge>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
