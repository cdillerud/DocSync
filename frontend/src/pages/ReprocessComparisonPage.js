import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { toast } from 'sonner';
import {
  PlayCircle, RefreshCw, Loader2, CheckCircle2, XCircle, ArrowUpRight,
  ArrowDownRight, Minus, AlertTriangle, FileText, BarChart3, Zap,
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL;

function DeltaBadge({ delta }) {
  if (!delta || !delta.has_changes) {
    return <Badge variant="outline" className="text-[10px] text-muted-foreground"><Minus className="w-2.5 h-2.5 mr-0.5" />No Change</Badge>;
  }
  if (delta.fields_improved > delta.fields_regressed) {
    return <Badge className="text-[10px] bg-emerald-500/20 text-emerald-400 border border-emerald-700"><ArrowUpRight className="w-2.5 h-2.5 mr-0.5" />Improved</Badge>;
  }
  if (delta.fields_regressed > delta.fields_improved) {
    return <Badge className="text-[10px] bg-red-500/20 text-red-400 border border-red-700"><ArrowDownRight className="w-2.5 h-2.5 mr-0.5" />Regressed</Badge>;
  }
  return <Badge className="text-[10px] bg-amber-500/20 text-amber-400 border border-amber-700"><AlertTriangle className="w-2.5 h-2.5 mr-0.5" />Mixed</Badge>;
}

function FieldChange({ field, change }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <span className="text-muted-foreground font-medium w-24 shrink-0">{field}</span>
      <span className="text-red-400 line-through truncate max-w-[120px]">{String(change.before || '(empty)')}</span>
      <ArrowUpRight className="w-3 h-3 text-muted-foreground shrink-0" />
      <span className="text-emerald-400 truncate max-w-[120px]">{String(change.after || '(empty)')}</span>
      {change.delta !== undefined && (
        <span className={`font-mono text-[10px] ${change.delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
          ({change.delta > 0 ? '+' : ''}{change.delta})
        </span>
      )}
    </div>
  );
}

export default function ReprocessComparisonPage() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [changesOnly, setChangesOnly] = useState(false);
  const [polling, setPolling] = useState(false);

  const fetchResults = useCallback(async (runId, onlyChanges = false) => {
    try {
      const res = await fetch(
        `${API_URL}/api/reprocess-comparison/results/${runId}?changes_only=${onlyChanges}`
      );
      const data = await res.json();
      setResults(data);
    } catch {
      toast.error('Failed to fetch results');
    }
  }, []);

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/reprocess-comparison/status`);
      const data = await res.json();
      setStatus(data);
      if (data.status === 'completed' && data.run_id) {
        fetchResults(data.run_id, changesOnly);
      }
      return data;
    } catch {
      return null;
    }
  }, [changesOnly, fetchResults]);

  // Poll while running
  useEffect(() => {
    if (!polling) return;
    const interval = setInterval(async () => {
      const s = await fetchStatus();
      if (s && s.status !== 'running') {
        setPolling(false);
        if (s.run_id) fetchResults(s.run_id, changesOnly);
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [polling, changesOnly, fetchStatus, fetchResults]);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const startRun = async () => {
    setStarting(true);
    try {
      const res = await fetch(`${API_URL}/api/reprocess-comparison/run`, { method: 'POST' });
      const data = await res.json();
      if (data.error) {
        toast.error(data.error);
      } else {
        toast.success(`Comparison started: ${data.run_id}`);
        setPolling(true);
        setResults(null);
      }
    } catch {
      toast.error('Failed to start comparison');
    } finally {
      setStarting(false);
    }
  };

  const isRunning = status?.status === 'running';
  const isComplete = status?.status === 'completed';
  const progressPct = isRunning && status.total > 0
    ? Math.round((status.processed / status.total) * 100)
    : 0;

  return (
    <div className="space-y-6" data-testid="reprocess-comparison-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Before / After Comparison
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Re-run the improved LLM pipeline on all documents. Compare old vs new results without overwriting production data.
          </p>
        </div>
        <div className="flex gap-2">
          {!isRunning && (
            <Button
              onClick={startRun}
              disabled={starting}
              className="h-9 gap-1.5"
              data-testid="start-comparison-btn"
            >
              {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
              Run Comparison
            </Button>
          )}
          {isComplete && status.run_id && (
            <Button
              variant="outline"
              size="sm"
              className="h-9 text-xs gap-1"
              onClick={() => fetchResults(status.run_id, changesOnly)}
              data-testid="refresh-results-btn"
            >
              <RefreshCw className="w-3 h-3" /> Refresh
            </Button>
          )}
        </div>
      </div>

      {/* Progress (while running) */}
      {isRunning && (
        <Card className="border border-amber-700/50" data-testid="comparison-progress">
          <CardContent className="p-4">
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
              <span className="text-sm font-medium">Processing documents...</span>
              <span className="text-xs text-muted-foreground ml-auto font-mono">
                {status.processed} / {status.total}
              </span>
            </div>
            <Progress value={progressPct} className="h-2" />
            <div className="flex gap-4 mt-2 text-[10px] text-muted-foreground">
              <span className="text-emerald-400">Improved: {status.improved}</span>
              <span className="text-red-400">Regressed: {status.regressed}</span>
              <span>Unchanged: {status.unchanged}</span>
              <span>Errors: {status.errors}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Summary (when complete) */}
      {isComplete && (status.total > 0 || status.total_documents > 0 || status.processed > 0) && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" data-testid="comparison-summary-cards">
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Total</p>
                <p className="text-xl font-bold font-mono">{status.processed || status.total_documents || status.total}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Changed</p>
                <p className="text-xl font-bold font-mono text-amber-400">{status.changed ?? 0}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Improved</p>
                <p className="text-xl font-bold font-mono text-emerald-400">{status.improved ?? 0}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Regressed</p>
                <p className="text-xl font-bold font-mono text-red-400">{status.regressed ?? 0}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Unchanged</p>
                <p className="text-xl font-bold font-mono">{status.unchanged ?? 0}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Skipped</p>
                <p className="text-xl font-bold font-mono text-muted-foreground">{status.skipped ?? 0}</p>
              </CardContent>
            </Card>
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <p className="text-[10px] text-muted-foreground">Avg Conf &Delta;</p>
                <p className={`text-xl font-bold font-mono ${(status.avg_confidence_delta ?? 0) > 0 ? 'text-emerald-400' : (status.avg_confidence_delta ?? 0) < 0 ? 'text-red-400' : ''}`}>
                  {(status.avg_confidence_delta ?? 0) > 0 ? '+' : ''}{status.avg_confidence_delta ?? 0}
                </p>
              </CardContent>
            </Card>
          </div>

          {/* Field change breakdown */}
          {status.field_change_counts && Object.keys(status.field_change_counts).length > 0 && (
            <Card className="border border-border" data-testid="field-changes-card">
              <CardHeader className="pb-2">
                <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                  <BarChart3 className="w-3 h-3" /> Fields That Changed
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <div className="flex flex-wrap gap-2">
                  {Object.entries(status.field_change_counts)
                    .sort((a, b) => b[1] - a[1])
                    .map(([field, count]) => (
                      <Badge key={field} variant="outline" className="text-xs gap-1">
                        {field}: <span className="font-mono font-bold">{count}</span>
                      </Badge>
                    ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* No data message */}
      {isComplete && !status.total && !status.total_documents && !status.processed && (
        <Card className="border border-border" data-testid="no-data-card">
          <CardContent className="p-8 text-center">
            <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              No documents found to compare. Upload or process documents first, then run the comparison.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Document-level Results */}
      {results && results.results && results.results.length > 0 && (
        <Card className="border border-border" data-testid="comparison-results-table">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
                <Zap className="w-3 h-3" /> Document Results ({results.total_results})
              </CardTitle>
              <Button
                variant="ghost"
                size="sm"
                className="h-7 text-[10px]"
                onClick={() => {
                  setChangesOnly(!changesOnly);
                  if (status?.run_id) fetchResults(status.run_id, !changesOnly);
                }}
                data-testid="toggle-changes-only"
              >
                {changesOnly ? 'Show All' : 'Changes Only'}
              </Button>
            </div>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="max-h-[500px] overflow-y-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-[10px] w-[180px]">Document</TableHead>
                    <TableHead className="text-[10px] w-[80px]">Status</TableHead>
                    <TableHead className="text-[10px]">Before Type</TableHead>
                    <TableHead className="text-[10px]">After Type</TableHead>
                    <TableHead className="text-[10px]">Before Conf</TableHead>
                    <TableHead className="text-[10px]">After Conf</TableHead>
                    <TableHead className="text-[10px]">Verdict</TableHead>
                    <TableHead className="text-[10px]">Details</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {results.results.map((r, i) => (
                    <TableRow key={i} data-testid={`result-row-${i}`}>
                      <TableCell className="py-2">
                        <span className="text-xs font-medium truncate block max-w-[180px]" title={r.file_name}>
                          {r.file_name}
                        </span>
                      </TableCell>
                      <TableCell className="py-2">
                        {r.status === 'compared' && <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />}
                        {r.status === 'skipped' && <Minus className="w-3.5 h-3.5 text-muted-foreground" />}
                        {r.status === 'error' && <XCircle className="w-3.5 h-3.5 text-red-500" />}
                      </TableCell>
                      <TableCell className="py-2 text-xs font-mono">{r.before?.doc_type || '-'}</TableCell>
                      <TableCell className="py-2 text-xs font-mono">{r.after?.doc_type || '-'}</TableCell>
                      <TableCell className="py-2 text-xs font-mono">{r.before?.confidence ?? '-'}</TableCell>
                      <TableCell className="py-2 text-xs font-mono">
                        {r.after?.confidence ?? '-'}
                        {r.delta?.changes?.confidence?.delta && (
                          <span className={`ml-1 text-[10px] ${r.delta.changes.confidence.delta > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            ({r.delta.changes.confidence.delta > 0 ? '+' : ''}{r.delta.changes.confidence.delta})
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="py-2">
                        <DeltaBadge delta={r.delta} />
                      </TableCell>
                      <TableCell className="py-2">
                        {r.delta?.changes && Object.keys(r.delta.changes).length > 0 && (
                          <div className="space-y-0.5">
                            {Object.entries(r.delta.changes).map(([field, change]) => (
                              <FieldChange key={field} field={field} change={change} />
                            ))}
                          </div>
                        )}
                        {r.status === 'skipped' && (
                          <span className="text-[10px] text-muted-foreground">{r.reason}</span>
                        )}
                        {r.status === 'error' && (
                          <span className="text-[10px] text-red-400">{r.reason}</span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
