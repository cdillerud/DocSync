import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { toast } from 'sonner';
import {
  Bug, RefreshCw, Loader2, ChevronDown, ChevronUp,
  Search, Database, ArrowRight, XCircle, Repeat, Zap
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const OUTCOME_CONFIG = {
  exact_match: { label: 'Exact', bg: 'bg-emerald-500/20 text-emerald-400' },
  likely_match: { label: 'Likely', bg: 'bg-blue-500/20 text-blue-400' },
  ambiguous_match: { label: 'Ambiguous', bg: 'bg-amber-500/20 text-amber-400' },
  no_match: { label: 'No Match', bg: 'bg-red-500/20 text-red-400' },
};

export default function MatchingDebugPanel({ document: doc }) {
  const [debug, setDebug] = useState(null);
  const [loading, setLoading] = useState(false);
  const [rerunning, setRerunning] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showNorm, setShowNorm] = useState(false);
  const [showScores, setShowScores] = useState(false);
  const [showCache, setShowCache] = useState(false);
  const [showCorrections, setShowCorrections] = useState(false);

  const fetchDebug = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/documents/${doc.id}/matching-debug`);
      if (res.ok) setDebug(await res.json());
    } catch (err) { /* silent */ }
    finally { setLoading(false); }
  };

  const handleRerun = async () => {
    setRerunning(true);
    try {
      const res = await fetch(`${API}/api/documents/${doc.id}/matching-debug/rerun`, { method: 'POST' });
      if (res.ok) {
        toast.success('Resolution re-run with diagnostics');
        await fetchDebug();
      }
    } catch (err) { toast.error('Rerun failed'); }
    finally { setRerunning(false); }
  };

  const diag = debug?.diagnostics;
  const outcome = debug?.match_outcome;
  const outcomeConfig = OUTCOME_CONFIG[outcome] || { label: outcome || 'N/A', bg: 'bg-gray-500/20 text-gray-400' };
  const corrections = debug?.label_corrections || [];
  const vendorPatterns = debug?.vendor_correction_patterns;
  const lcHints = diag?.label_correction_hints || {};
  const vendorHints = diag?.vendor_hints || {};
  const hasLearningSignals = corrections.length > 0 || vendorPatterns?.has_patterns || Object.keys(lcHints).length > 0;

  return (
    <Card className="border border-border" data-testid="matching-debug-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <button
            onClick={() => { setExpanded(!expanded); if (!expanded && !debug) fetchDebug(); }}
            className="flex items-center gap-2 text-sm font-bold uppercase tracking-wider text-muted-foreground hover:text-foreground transition-colors"
            style={{ fontFamily: 'Chivo, sans-serif' }}
            data-testid="matching-debug-toggle"
          >
            <Bug className="w-4 h-4" />
            Matching Debug
            {hasLearningSignals && expanded && (
              <Badge className="bg-violet-500/20 text-violet-400 text-[10px] ml-1">
                <Zap className="w-2.5 h-2.5 mr-0.5" />Learning
              </Badge>
            )}
            {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {expanded && (
            <Button
              variant="ghost" size="sm"
              onClick={handleRerun} disabled={rerunning}
              data-testid="matching-debug-rerun"
            >
              {rerunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
              <span className="ml-1 text-xs">Re-run</span>
            </Button>
          )}
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-4 text-xs">
          {loading ? (
            <div className="flex justify-center py-4"><Loader2 className="w-5 h-5 animate-spin text-muted-foreground" /></div>
          ) : !debug ? (
            <p className="text-muted-foreground">No debug data. Click Re-run to generate.</p>
          ) : (
            <>
              {/* Strategy + Outcome Summary */}
              <div className="flex flex-wrap items-center gap-3 p-2.5 bg-muted/40 rounded-md" data-testid="matching-debug-summary">
                <div>
                  <span className="text-muted-foreground">Strategy:</span>{' '}
                  <span className="font-mono font-semibold">{diag?.effective_strategy || 'default'}</span>
                </div>
                <ArrowRight className="w-3 h-3 text-muted-foreground" />
                <Badge className={`${outcomeConfig.bg} text-[10px]`}>{outcomeConfig.label}</Badge>
                {diag?.is_freight_carrier && (
                  <Badge className="bg-purple-500/20 text-purple-400 text-[10px]">Freight Carrier</Badge>
                )}
                {diag?.dynamic_strategy?.applied && (
                  <Badge className="bg-violet-500/20 text-violet-400 text-[10px]">Dynamic Strategy</Badge>
                )}
                {diag?.shipment_clustering?.cluster_matches_added > 0 && (
                  <Badge className="bg-blue-500/20 text-blue-400 text-[10px]">
                    +{diag.shipment_clustering.cluster_matches_added} cluster
                  </Badge>
                )}
                {diag?.processing_time_ms != null && (
                  <span className="text-muted-foreground">{diag.processing_time_ms}ms</span>
                )}
              </div>

              {/* Strategy Reason */}
              {diag?.strategy_reason?.length > 0 && (
                <div className="text-muted-foreground">
                  {diag.strategy_reason.map((r, i) => <span key={i} className="mr-2">{r}</span>)}
                </div>
              )}

              {/* Extraction Summary */}
              <div>
                <p className="font-semibold text-muted-foreground mb-1">
                  <Search className="w-3 h-3 inline mr-1" />
                  Extraction ({diag?.extraction?.unique_count || 0} candidates)
                </p>
                {diag?.candidates?.length > 0 && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead className="text-[10px]">Raw</TableHead>
                        <TableHead className="text-[10px]">Normalized</TableHead>
                        <TableHead className="text-[10px]">Label</TableHead>
                        <TableHead className="text-[10px]">Domain</TableHead>
                        <TableHead className="text-[10px]">Conf</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {diag.candidates.map((c, i) => (
                        <TableRow key={i}>
                          <TableCell className="font-mono text-[10px]">{c.raw}</TableCell>
                          <TableCell className="font-mono text-[10px] font-semibold">{c.normalized}</TableCell>
                          <TableCell>
                            <Badge variant="outline" className="text-[10px]">{c.label}</Badge>
                            {lcHints[c.label]?.has_hints && (
                              <Badge className="bg-violet-500/20 text-violet-400 text-[10px] ml-1">learned</Badge>
                            )}
                          </TableCell>
                          <TableCell className="text-[10px]">{c.domain}</TableCell>
                          <TableCell className="text-[10px]">{(c.confidence * 100).toFixed(0)}%</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
              </div>

              {/* Normalization Trace (expandable) */}
              {diag?.normalization && Object.keys(diag.normalization).length > 0 && (
                <div>
                  <button onClick={() => setShowNorm(!showNorm)} className="flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground" data-testid="matching-debug-norm-toggle">
                    Normalization Trace
                    {showNorm ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showNorm && (
                    <div className="mt-1 space-y-2 pl-2">
                      {Object.entries(diag.normalization).map(([raw, info]) => (
                        <div key={raw} className="bg-muted/30 rounded p-2">
                          <div className="font-mono">
                            <span className="text-muted-foreground">"{info.raw}"</span>
                            <ArrowRight className="w-3 h-3 inline mx-1" />
                            <span className="font-semibold">"{info.normalized}"</span>
                          </div>
                          {info.steps?.map((s, i) => (
                            <div key={i} className="pl-4 text-muted-foreground">
                              {s.step}: <span className="font-mono">{s.value}</span>
                            </div>
                          ))}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Cache + API Results */}
              <div>
                <button onClick={() => setShowCache(!showCache)} className="flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground" data-testid="matching-debug-cache-toggle">
                  <Database className="w-3 h-3" />
                  Cache/API Results ({(diag?.cache_results?.length || 0) + (diag?.bc_fallback_results?.length || 0)})
                  {showCache ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showCache && (
                  <div className="mt-1 space-y-1 pl-2">
                    {diag?.cache_results?.map((r, i) => (
                      <div key={`c-${i}`} className="flex items-center gap-2">
                        <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]">Cache</Badge>
                        <span className="font-mono">{r.reference}</span>
                        <ArrowRight className="w-3 h-3" />
                        <span>{r.entity}: {r.doc_no}</span>
                      </div>
                    ))}
                    {diag?.bc_fallback_results?.map((r, i) => (
                      <div key={`b-${i}`} className="flex items-center gap-2">
                        <Badge className="bg-blue-500/20 text-blue-400 text-[10px]">API</Badge>
                        <span className="font-mono">{r.reference}</span>
                        <ArrowRight className="w-3 h-3" />
                        <span>{r.entity}: {r.doc_no}</span>
                      </div>
                    ))}
                    {(!diag?.cache_results?.length && !diag?.bc_fallback_results?.length) && (
                      <p className="text-muted-foreground">No results from cache or API</p>
                    )}
                  </div>
                )}
              </div>

              {/* Score Breakdown (expandable) */}
              {diag?.candidate_scores?.length > 0 && (
                <div>
                  <button onClick={() => setShowScores(!showScores)} className="flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground" data-testid="matching-debug-scores-toggle">
                    Score Breakdown ({diag.candidate_scores.length} candidates)
                    {showScores ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showScores && (
                    <div className="mt-1 space-y-2 pl-2">
                      {diag.candidate_scores.map((s, i) => (
                        <div key={i} className="bg-muted/30 rounded p-2">
                          <div className="flex items-center gap-2 mb-1">
                            <span className="font-mono font-semibold">{s.bc_document_no}</span>
                            <Badge variant="outline" className="text-[10px]">{s.entity_type}</Badge>
                            <span className={`font-bold ${s.final_score >= 0.7 ? 'text-emerald-400' : s.final_score >= 0.4 ? 'text-amber-400' : 'text-red-400'}`}>
                              {(s.final_score * 100).toFixed(1)}%
                            </span>
                          </div>
                          {s.score_breakdown && (
                            <div className="grid grid-cols-2 gap-1 pl-2">
                              {Object.entries(s.score_breakdown).filter(([, v]) => v > 0).map(([k, v]) => (
                                <div key={k} className="flex items-center gap-1 text-muted-foreground">
                                  <div className="w-16 h-1.5 bg-muted rounded-full overflow-hidden">
                                    <div
                                      className={`h-full rounded-full ${
                                        k === 'label_correction_boost' ? 'bg-violet-500/60' :
                                        k === 'cluster_match_bonus' ? 'bg-blue-500/60' :
                                        k === 'reference_context_match' ? 'bg-cyan-500/60' :
                                        k === 'date_proximity' ? 'bg-orange-500/60' :
                                        'bg-emerald-500/60'
                                      }`}
                                      style={{ width: `${Math.min(v * 200, 100)}%` }}
                                    />
                                  </div>
                                  <span className={
                                    k === 'label_correction_boost' ? 'text-violet-400' :
                                    k === 'cluster_match_bonus' ? 'text-blue-400' : ''
                                  }>
                                    {k.replace(/_/g, ' ')}: {(v * 100).toFixed(0)}%
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Label Correction Feedback Loop Section */}
              {(corrections.length > 0 || vendorPatterns?.has_patterns) && (
                <div data-testid="matching-debug-feedback-loop">
                  <button
                    onClick={() => setShowCorrections(!showCorrections)}
                    className="flex items-center gap-1 font-semibold text-muted-foreground hover:text-foreground"
                    data-testid="matching-debug-corrections-toggle"
                  >
                    <Repeat className="w-3 h-3" />
                    Feedback Loop
                    {corrections.length > 0 && (
                      <Badge className="bg-violet-500/20 text-violet-400 text-[10px] ml-1">
                        {corrections.length} correction{corrections.length > 1 ? 's' : ''}
                      </Badge>
                    )}
                    {showCorrections ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showCorrections && (
                    <div className="mt-2 space-y-3 pl-2">
                      {/* Document-Level Corrections */}
                      {corrections.length > 0 && (
                        <div>
                          <p className="text-muted-foreground font-semibold mb-1">Corrections from this Document</p>
                          {corrections.map((c, i) => (
                            <div key={i} className="flex items-center gap-2 py-0.5">
                              <Badge variant="outline" className="text-[10px] text-red-400 border-red-400/30">{c.predicted_label}</Badge>
                              <ArrowRight className="w-3 h-3 text-muted-foreground" />
                              <Badge className="bg-emerald-500/20 text-emerald-400 text-[10px]">{c.correct_label}</Badge>
                              <span className="text-muted-foreground font-mono text-[10px]">{c.reference_value}</span>
                              <span className="text-muted-foreground text-[10px]">({c.actual_entity_type})</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Vendor Patterns */}
                      {vendorPatterns?.has_patterns && (
                        <div>
                          <p className="text-muted-foreground font-semibold mb-1">
                            Vendor Learned Patterns ({vendorPatterns.total_corrections} total)
                          </p>
                          {vendorPatterns.patterns?.slice(0, 5).map((p, i) => (
                            <div key={i} className="flex items-center gap-2 py-0.5">
                              <Badge variant="outline" className="text-[10px]">{p.predicted_label}</Badge>
                              <ArrowRight className="w-3 h-3 text-muted-foreground" />
                              <Badge className="bg-violet-500/20 text-violet-400 text-[10px]">{p.correct_label}</Badge>
                              <span className="text-muted-foreground text-[10px]">
                                {p.count}x ({(p.frequency * 100).toFixed(0)}%)
                              </span>
                              <span className="text-muted-foreground text-[10px]">avg score: {(p.avg_score * 100).toFixed(0)}%</span>
                            </div>
                          ))}

                          {/* Label Remaps */}
                          {vendorPatterns.label_remaps && Object.keys(vendorPatterns.label_remaps).length > 0 && (
                            <div className="mt-1 p-2 bg-violet-500/10 rounded">
                              <p className="text-violet-400 font-semibold text-[10px] mb-1">Active Label Remaps</p>
                              {Object.entries(vendorPatterns.label_remaps).map(([from, info]) => (
                                <div key={from} className="flex items-center gap-2 text-[10px]">
                                  <Zap className="w-3 h-3 text-violet-400" />
                                  <span className="font-mono">{from}</span>
                                  <ArrowRight className="w-3 h-3" />
                                  <span className="font-mono text-violet-400">{info.remap_to}</span>
                                  <span className="text-muted-foreground">
                                    ({info.count}x, conf: {(info.confidence * 100).toFixed(0)}%)
                                  </span>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* Decision */}
              {diag?.decision && (
                <div className="p-2.5 bg-muted/40 rounded-md" data-testid="matching-debug-decision">
                  <p className="font-semibold text-muted-foreground mb-1">Decision</p>
                  <div className="space-y-0.5">
                    <div>
                      Outcome: <Badge className={`${outcomeConfig.bg} text-[10px] ml-1`}>{diag.decision.outcome}</Badge>
                    </div>
                    {diag.decision.best_score != null && (
                      <div>Best: <span className="font-mono font-semibold">{(diag.decision.best_score * 100).toFixed(1)}%</span>
                        {diag.decision.best_entity && <span className="ml-2">{diag.decision.best_entity}: {diag.decision.best_doc_no}</span>}
                      </div>
                    )}
                    {diag.decision.second_best_score > 0 && (
                      <div>Second: <span className="font-mono">{(diag.decision.second_best_score * 100).toFixed(1)}%</span></div>
                    )}
                    {diag.decision.failure_reason && (
                      <div className="text-red-400">
                        <XCircle className="w-3 h-3 inline mr-1" />
                        Failure: {diag.decision.failure_reason}
                      </div>
                    )}
                    {/* Part 8: Feedback loop diagnostics */}
                    <div className="flex flex-wrap gap-3 mt-1 pt-1 border-t border-border/50">
                      <span className="text-muted-foreground">
                        Label correction: {diag.decision.label_correction_applied ?
                          <Badge className="bg-violet-500/20 text-violet-400 text-[10px]">applied</Badge> :
                          <span className="text-[10px]">none</span>}
                      </span>
                      {diag.decision.vendor_pattern_weight > 0 && (
                        <span className="text-muted-foreground">
                          Vendor weight: <span className="font-mono text-violet-400">{(diag.decision.vendor_pattern_weight * 100).toFixed(1)}%</span>
                        </span>
                      )}
                      {diag.decision.cluster_match_bonus > 0 && (
                        <span className="text-muted-foreground">
                          Cluster bonus: <span className="font-mono text-blue-400">+{(diag.decision.cluster_match_bonus * 100).toFixed(1)}%</span>
                        </span>
                      )}
                    </div>
                    {/* Dynamic strategy */}
                    {diag.dynamic_strategy?.applied && (
                      <div className="mt-1 text-violet-400 text-[10px]">
                        <Zap className="w-3 h-3 inline mr-1" />
                        Dynamic strategy: {diag.dynamic_strategy.reason}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
}
