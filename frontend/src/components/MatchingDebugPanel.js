import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { toast } from 'sonner';
import {
  Bug, RefreshCw, Loader2, ChevronDown, ChevronUp,
  Search, Database, ArrowRight, CheckCircle2, XCircle, AlertTriangle
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
                          <TableCell><Badge variant="outline" className="text-[10px]">{c.label}</Badge></TableCell>
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
                                    <div className="h-full bg-emerald-500/60 rounded-full" style={{ width: `${Math.min(v * 200, 100)}%` }} />
                                  </div>
                                  <span>{k.replace(/_/g, ' ')}: {(v * 100).toFixed(0)}%</span>
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
