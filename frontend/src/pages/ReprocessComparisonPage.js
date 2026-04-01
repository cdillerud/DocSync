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
  Upload, Rocket, Shield, TrendingUp,
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

function StatCard({ label, value, color = '', icon: Icon }) {
  return (
    <Card className="border border-border">
      <CardContent className="p-3 text-center">
        <div className="flex items-center justify-center gap-1.5 mb-1">
          {Icon && <Icon className={`w-3.5 h-3.5 ${color || 'text-muted-foreground'}`} />}
          <p className="text-[10px] text-muted-foreground">{label}</p>
        </div>
        <p className={`text-xl font-bold font-mono ${color}`}>{value}</p>
      </CardContent>
    </Card>
  );
}

export default function ReprocessComparisonPage() {
  const [status, setStatus] = useState(null);
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [changesOnly, setChangesOnly] = useState(false);
  const [polling, setPolling] = useState(false);
  const [applyState, setApplyState] = useState(null);
  const [applyPolling, setApplyPolling] = useState(false);
  const [fullState, setFullState] = useState(null);
  const [fullPolling, setFullPolling] = useState(false);
  const [startingFull, setStartingFull] = useState(false);
  const [applying, setApplying] = useState(false);

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

  const fetchApplyStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/reprocess-comparison/apply-status`);
      const data = await res.json();
      setApplyState(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  const fetchFullStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_URL}/api/reprocess-comparison/full-status`);
      const data = await res.json();
      setFullState(data);
      return data;
    } catch {
      return null;
    }
  }, []);

  // Poll comparison while running
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

  // Poll apply status
  useEffect(() => {
    if (!applyPolling) return;
    const interval = setInterval(async () => {
      const s = await fetchApplyStatus();
      if (s && s.status !== 'running') {
        setApplyPolling(false);
        if (s.status === 'completed') {
          toast.success(`Applied ${s.applied} improvements to production!`);
        }
      }
    }, 2000);
    return () => clearInterval(interval);
  }, [applyPolling, fetchApplyStatus]);

  // Poll full reprocess status
  useEffect(() => {
    if (!fullPolling) return;
    const interval = setInterval(async () => {
      const s = await fetchFullStatus();
      if (s && s.status !== 'running') {
        setFullPolling(false);
        if (s.status === 'completed') {
          toast.success(`Full reprocess complete: ${s.success} docs updated, ${s.improved} improved`);
        }
      }
    }, 3000);
    return () => clearInterval(interval);
  }, [fullPolling, fetchFullStatus]);

  useEffect(() => {
    fetchStatus();
    fetchApplyStatus();
    fetchFullStatus();
  }, [fetchStatus, fetchApplyStatus, fetchFullStatus]);

  const startRun = async () => {
    setStarting(true);
    try {
      const res = await fetch(`${API_URL}/api/reprocess-comparison/run?limit=500`, { method: 'POST' });
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

  const applyImprovements = async () => {
    if (!status?.run_id) return;
    setApplying(true);
    try {
      const res = await fetch(
        `${API_URL}/api/reprocess-comparison/apply/${status.run_id}?improved_only=true`,
        { method: 'POST' }
      );
      const data = await res.json();
      if (data.error) {
        toast.error(data.error);
      } else {
        toast.success('Applying improvements...');
        setApplyPolling(true);
      }
    } catch {
      toast.error('Failed to start apply');
    } finally {
      setApplying(false);
    }
  };

  const startFullReprocess = async () => {
    setStartingFull(true);
    try {
      const res = await fetch(
        `${API_URL}/api/reprocess-comparison/run-full?limit=500&skip_terminal=true`,
        { method: 'POST' }
      );
      const data = await res.json();
      if (data.error) {
        toast.error(data.error);
      } else {
        toast.success(`Full reprocess started: ${data.run_id}`);
        setFullPolling(true);
      }
    } catch {
      toast.error('Failed to start full reprocess');
    } finally {
      setStartingFull(false);
    }
  };

  const isRunning = status?.status === 'running';
  const isComplete = status?.status === 'completed';
  const hasResults = isComplete && (status.total > 0 || status.total_documents > 0 || status.processed > 0);
  const progressPct = isRunning && status.total > 0
    ? Math.round((status.processed / status.total) * 100)
    : 0;

  const isFullRunning = fullState?.status === 'running';
  const isFullComplete = fullState?.status === 'completed';
  const fullProgressPct = isFullRunning && fullState.total > 0
    ? Math.round((fullState.processed / fullState.total) * 100)
    : 0;

  const isApplyRunning = applyState?.status === 'running';

  return (
    <div className="space-y-6" data-testid="reprocess-comparison-page">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            AI Reprocess & Comparison
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Re-run the knowledge-seeded AI pipeline on documents. Compare results, then apply improvements.
          </p>
        </div>
        <div className="flex gap-2 flex-wrap">
          {!isRunning && (
            <Button
              onClick={startRun}
              disabled={starting}
              className="h-9 gap-1.5"
              data-testid="start-comparison-btn"
            >
              {starting ? <Loader2 className="w-4 h-4 animate-spin" /> : <PlayCircle className="w-4 h-4" />}
              Compare (Preview)
            </Button>
          )}
          {hasResults && (status.improved ?? 0) > 0 && !isApplyRunning && (
            <Button
              onClick={applyImprovements}
              disabled={applying}
              variant="default"
              className="h-9 gap-1.5 bg-emerald-600 hover:bg-emerald-700"
              data-testid="apply-improvements-btn"
            >
              {applying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Upload className="w-4 h-4" />}
              Apply {status.improved} Improvements
            </Button>
          )}
          {!isFullRunning && (
            <Button
              onClick={startFullReprocess}
              disabled={startingFull}
              variant="outline"
              className="h-9 gap-1.5 border-amber-700 text-amber-400 hover:bg-amber-900/20"
              data-testid="start-full-reprocess-btn"
            >
              {startingFull ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
              Full Pipeline Reprocess
            </Button>
          )}
        </div>
      </div>

      {/* Apply status */}
      {isApplyRunning && applyState && (
        <Card className="border border-emerald-700/50" data-testid="apply-progress">
          <CardContent className="p-4">
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="w-4 h-4 animate-spin text-emerald-400" />
              <span className="text-sm font-medium">Applying improvements to production...</span>
              <span className="text-xs text-muted-foreground ml-auto font-mono">
                {applyState.applied ?? 0} / {applyState.total ?? 0}
              </span>
            </div>
            <Progress value={applyState.total > 0 ? Math.round(((applyState.applied || 0) / applyState.total) * 100) : 0} className="h-2" />
          </CardContent>
        </Card>
      )}

      {applyState?.status === 'completed' && (
        <Card className="border border-emerald-700/50 bg-emerald-950/20" data-testid="apply-complete">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <CheckCircle2 className="w-5 h-5 text-emerald-400" />
              <div>
                <p className="text-sm font-medium text-emerald-300">
                  Applied {applyState.applied} improvements to production
                </p>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  {applyState.skipped} skipped | {applyState.errors} errors | {applyState.finished_at?.split('T')[0]}
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Full Reprocess Progress */}
      {isFullRunning && fullState && (
        <Card className="border border-amber-700/50" data-testid="full-reprocess-progress">
          <CardContent className="p-4">
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="w-4 h-4 animate-spin text-amber-400" />
              <span className="text-sm font-medium">Full pipeline reprocess running...</span>
              <span className="text-xs text-muted-foreground ml-auto font-mono">
                {fullState.processed} / {fullState.total}
              </span>
            </div>
            <Progress value={fullProgressPct} className="h-2" />
            <div className="flex gap-4 mt-2 text-[10px] text-muted-foreground">
              <span className="text-emerald-400">Success: {fullState.success}</span>
              <span className="text-blue-400">Improved: {fullState.improved}</span>
              <span className="text-red-400">Errors: {fullState.errors}</span>
              <span>No File: {fullState.skipped_no_file}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {isFullComplete && fullState && (
        <Card className="border border-amber-700/50 bg-amber-950/20" data-testid="full-reprocess-complete">
          <CardContent className="p-4">
            <div className="flex items-center gap-3">
              <Rocket className="w-5 h-5 text-amber-400" />
              <div>
                <p className="text-sm font-medium text-amber-300">
                  Full reprocess complete: {fullState.success}/{fullState.total} documents updated
                </p>
                <p className="text-[10px] text-muted-foreground mt-0.5">
                  {fullState.improved} improved | {fullState.errors} errors | {fullState.skipped_no_file} no file
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Comparison Progress (while running) */}
      {isRunning && (
        <Card className="border border-blue-700/50" data-testid="comparison-progress">
          <CardContent className="p-4">
            <div className="flex items-center gap-3 mb-2">
              <Loader2 className="w-4 h-4 animate-spin text-blue-400" />
              <span className="text-sm font-medium">Comparing documents (preview only)...</span>
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

      {/* Summary (when comparison complete) */}
      {hasResults && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3" data-testid="comparison-summary-cards">
            <StatCard label="Total" value={status.processed || status.total_documents || status.total} icon={FileText} />
            <StatCard label="Changed" value={status.changed ?? 0} color="text-amber-400" icon={BarChart3} />
            <StatCard label="Improved" value={status.improved ?? 0} color="text-emerald-400" icon={TrendingUp} />
            <StatCard label="Regressed" value={status.regressed ?? 0} color="text-red-400" icon={ArrowDownRight} />
            <StatCard label="Unchanged" value={status.unchanged ?? 0} icon={Shield} />
            <StatCard label="Skipped" value={status.skipped ?? 0} color="text-muted-foreground" icon={Minus} />
            <Card className="border border-border">
              <CardContent className="p-3 text-center">
                <div className="flex items-center justify-center gap-1.5 mb-1">
                  <Zap className="w-3.5 h-3.5 text-blue-400" />
                  <p className="text-[10px] text-muted-foreground">Avg Conf Delta</p>
                </div>
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
      {isComplete && !hasResults && (
        <Card className="border border-border" data-testid="no-data-card">
          <CardContent className="p-8 text-center">
            <FileText className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">
              No comparison data yet. Click "Compare (Preview)" to re-run the AI pipeline and see before/after results.
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
              <div className="flex gap-2">
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
                {isComplete && status.run_id && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-7 text-[10px] gap-1"
                    onClick={() => fetchResults(status.run_id, changesOnly)}
                    data-testid="refresh-results-btn"
                  >
                    <RefreshCw className="w-3 h-3" /> Refresh
                  </Button>
                )}
              </div>
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
