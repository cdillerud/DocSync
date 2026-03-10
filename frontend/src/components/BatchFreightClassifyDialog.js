import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from './ui/dialog';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Progress } from './ui/progress';
import { Slider } from './ui/slider';
import { Checkbox } from './ui/checkbox';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from './ui/table';
import { ScrollArea } from './ui/scroll-area';
import { toast } from 'sonner';
import {
  Truck, ArrowDown, ArrowUp, ArrowLeftRight, HelpCircle,
  Loader2, AlertTriangle, CheckCircle2, FileText, ChevronDown, ChevronUp
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const DIR_ICON = {
  inbound: { icon: ArrowDown, color: 'text-blue-400', bg: 'bg-blue-500/20' },
  outbound: { icon: ArrowUp, color: 'text-emerald-400', bg: 'bg-emerald-500/20' },
  transfer: { icon: ArrowLeftRight, color: 'text-purple-400', bg: 'bg-purple-500/20' },
  unknown: { icon: HelpCircle, color: 'text-gray-400', bg: 'bg-gray-500/20' },
};

export default function BatchFreightClassifyDialog({ open, onOpenChange, selectedIds, totalInQueue, onComplete }) {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState(null);
  const [confidenceThreshold, setConfidenceThreshold] = useState([50]);
  const [skipOverrides, setSkipOverrides] = useState(true);
  const [showReviewDetails, setShowReviewDetails] = useState(false);
  const [showClassifiedDetails, setShowClassifiedDetails] = useState(false);

  const useSelected = selectedIds && selectedIds.length > 0;
  const targetCount = useSelected ? selectedIds.length : totalInQueue;

  const handleRun = async () => {
    setRunning(true);
    setResults(null);
    try {
      const body = {
        confidence_threshold: confidenceThreshold[0] / 100,
        skip_overrides: skipOverrides,
      };
      if (useSelected) {
        body.document_ids = selectedIds;
      }

      const res = await fetch(`${API}/api/freight-routing/batch-classify`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error('Batch classification failed');
      const data = await res.json();
      setResults(data);
      toast.success(`Batch complete: ${data.freight_detected} freight docs classified`);
      if (onComplete) onComplete();
    } catch (err) {
      toast.error(err.message || 'Batch classification error');
    } finally {
      setRunning(false);
    }
  };

  const handleClose = () => {
    if (!running) {
      setResults(null);
      onOpenChange(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-hidden flex flex-col" data-testid="batch-freight-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2 text-lg">
            <Truck className="w-5 h-5" />
            Batch Freight G/L Classification
          </DialogTitle>
          <DialogDescription>
            Classify freight documents and recommend G/L accounts. Read-only — no BC records will be created or modified.
          </DialogDescription>
        </DialogHeader>

        {!results ? (
          /* === PRE-RUN CONFIG === */
          <div className="space-y-5 py-2">
            {/* Target info */}
            <div className="flex items-center gap-3 p-3 bg-muted/50 rounded-lg">
              <FileText className="w-5 h-5 text-muted-foreground shrink-0" />
              <div className="text-sm">
                {useSelected ? (
                  <><span className="font-semibold">{targetCount}</span> selected document{targetCount !== 1 ? 's' : ''} will be processed</>
                ) : (
                  <>All <span className="font-semibold">{targetCount}</span> documents in current queue view will be processed</>
                )}
              </div>
            </div>

            {/* Confidence Threshold */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <label className="text-sm font-medium">Confidence Threshold</label>
                <span className="text-sm font-mono text-muted-foreground">{confidenceThreshold[0]}%</span>
              </div>
              <Slider
                value={confidenceThreshold}
                onValueChange={setConfidenceThreshold}
                min={10}
                max={90}
                step={5}
                className="w-full"
                data-testid="confidence-slider"
              />
              <p className="text-xs text-muted-foreground">
                Items classified below {confidenceThreshold[0]}% confidence will be flagged for manual review.
              </p>
            </div>

            {/* Skip overrides */}
            <div className="flex items-center gap-2">
              <Checkbox
                id="skip-overrides"
                checked={skipOverrides}
                onCheckedChange={setSkipOverrides}
                data-testid="skip-overrides-checkbox"
              />
              <label htmlFor="skip-overrides" className="text-sm cursor-pointer">
                Skip documents with manual G/L overrides
              </label>
            </div>

            {/* Safety notice */}
            <div className="flex items-start gap-2 p-3 border border-emerald-500/30 bg-emerald-500/5 rounded-lg">
              <CheckCircle2 className="w-4 h-4 text-emerald-500 mt-0.5 shrink-0" />
              <p className="text-xs text-emerald-400">
                This operation is classification-only and read-only. It will not create BC records, move documents into irreversible states, or modify any data in Business Central.
              </p>
            </div>
          </div>
        ) : (
          /* === RESULTS === */
          <ScrollArea className="flex-1 -mx-6 px-6" style={{ maxHeight: 'calc(85vh - 200px)' }}>
            <div className="space-y-4 py-2">
              {/* Summary cards */}
              <div className="grid grid-cols-3 gap-3">
                <div className="p-3 rounded-lg bg-muted/50 text-center">
                  <div className="text-2xl font-bold">{results.total_processed}</div>
                  <div className="text-xs text-muted-foreground">Processed</div>
                </div>
                <div className="p-3 rounded-lg bg-blue-500/10 text-center">
                  <div className="text-2xl font-bold text-blue-400">{results.freight_detected}</div>
                  <div className="text-xs text-blue-400/70">Freight Detected</div>
                </div>
                <div className="p-3 rounded-lg bg-amber-500/10 text-center">
                  <div className="text-2xl font-bold text-amber-400">{results.needs_manual_review?.length || 0}</div>
                  <div className="text-xs text-amber-400/70">Needs Review</div>
                </div>
              </div>

              {/* Direction breakdown */}
              {results.freight_detected > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Direction Breakdown</h4>
                  <div className="grid grid-cols-4 gap-2">
                    {Object.entries(results.by_direction || {}).map(([dir, count]) => {
                      const cfg = DIR_ICON[dir] || DIR_ICON.unknown;
                      const Icon = cfg.icon;
                      return (
                        <div key={dir} className={`p-2.5 rounded-lg ${cfg.bg} flex items-center gap-2`} data-testid={`batch-direction-${dir}`}>
                          <Icon className={`w-4 h-4 ${cfg.color}`} />
                          <div>
                            <div className={`text-lg font-bold ${cfg.color}`}>{count}</div>
                            <div className="text-[10px] text-muted-foreground capitalize">{dir}</div>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* G/L Account breakdown */}
              {Object.keys(results.by_gl_account || {}).length > 0 && (
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">G/L Account Distribution</h4>
                  <div className="space-y-1.5">
                    {Object.entries(results.by_gl_account).map(([gl, info]) => {
                      const pct = results.freight_detected > 0
                        ? Math.round((info.count / results.freight_detected) * 100)
                        : 0;
                      return (
                        <div key={gl} className="flex items-center gap-3">
                          <span className="font-mono text-xs w-16 shrink-0">{gl}</span>
                          <Progress value={pct} className="flex-1 h-2" />
                          <span className="text-xs text-muted-foreground w-20 text-right">
                            {info.count} ({pct}%)
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Skipped counts */}
              <div className="flex gap-4 text-xs text-muted-foreground">
                {results.non_freight > 0 && <span>Non-freight: {results.non_freight}</span>}
                {results.skipped_override > 0 && <span>Skipped (override): {results.skipped_override}</span>}
                {results.skipped_error > 0 && <span className="text-red-400">Errors: {results.skipped_error}</span>}
              </div>

              {/* Manual review items */}
              {results.needs_manual_review?.length > 0 && (
                <div className="space-y-2">
                  <button
                    onClick={() => setShowReviewDetails(!showReviewDetails)}
                    className="flex items-center gap-1 text-sm font-semibold text-amber-400 hover:text-amber-300 transition-colors"
                    data-testid="toggle-review-details"
                  >
                    <AlertTriangle className="w-4 h-4" />
                    Items Requiring Manual Review ({results.needs_manual_review.length})
                    {showReviewDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showReviewDetails && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">Document</TableHead>
                          <TableHead className="text-xs">Vendor</TableHead>
                          <TableHead className="text-xs">Direction</TableHead>
                          <TableHead className="text-xs">G/L</TableHead>
                          <TableHead className="text-xs">Confidence</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {results.needs_manual_review.map((item) => (
                          <TableRow key={item.document_id}>
                            <TableCell className="text-xs truncate max-w-[140px]">{item.file_name || item.document_id.slice(0, 8)}</TableCell>
                            <TableCell className="text-xs truncate max-w-[100px]">{item.vendor || '-'}</TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-[10px] capitalize">{item.direction}</Badge>
                            </TableCell>
                            <TableCell className="font-mono text-xs">{item.gl_number}</TableCell>
                            <TableCell className="text-xs text-amber-400">{(item.confidence * 100).toFixed(0)}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}

              {/* Classified items detail (collapsible) */}
              {results.high_confidence?.length > 0 && (
                <div className="space-y-2">
                  <button
                    onClick={() => setShowClassifiedDetails(!showClassifiedDetails)}
                    className="flex items-center gap-1 text-sm font-semibold text-emerald-400 hover:text-emerald-300 transition-colors"
                    data-testid="toggle-classified-details"
                  >
                    <CheckCircle2 className="w-4 h-4" />
                    High-Confidence Classifications ({results.high_confidence.length})
                    {showClassifiedDetails ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                  </button>
                  {showClassifiedDetails && (
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead className="text-xs">Document</TableHead>
                          <TableHead className="text-xs">Vendor</TableHead>
                          <TableHead className="text-xs">Direction</TableHead>
                          <TableHead className="text-xs">G/L</TableHead>
                          <TableHead className="text-xs">Confidence</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {results.high_confidence.map((item) => (
                          <TableRow key={item.document_id}>
                            <TableCell className="text-xs truncate max-w-[140px]">{item.file_name || item.document_id.slice(0, 8)}</TableCell>
                            <TableCell className="text-xs truncate max-w-[100px]">{item.vendor || '-'}</TableCell>
                            <TableCell>
                              <Badge variant="outline" className="text-[10px] capitalize">{item.direction}</Badge>
                            </TableCell>
                            <TableCell className="font-mono text-xs">{item.gl_number}</TableCell>
                            <TableCell className="text-xs text-emerald-400">{(item.confidence * 100).toFixed(0)}%</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  )}
                </div>
              )}
            </div>
          </ScrollArea>
        )}

        <DialogFooter className="gap-2">
          {!results ? (
            <>
              <Button variant="ghost" onClick={handleClose} disabled={running}>Cancel</Button>
              <Button onClick={handleRun} disabled={running} data-testid="batch-freight-run-btn">
                {running ? (
                  <><Loader2 className="w-4 h-4 mr-2 animate-spin" />Classifying...</>
                ) : (
                  <><Truck className="w-4 h-4 mr-2" />Run Classification</>
                )}
              </Button>
            </>
          ) : (
            <Button onClick={handleClose} data-testid="batch-freight-done-btn">Done</Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
