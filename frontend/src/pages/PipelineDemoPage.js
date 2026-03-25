import { useState, useEffect, useRef } from 'react';
import { Card, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import { toast } from 'sonner';
import {
  Loader2, Play, CheckCircle2, XCircle, FileText, Brain, Building2,
  ShieldCheck, UserCheck, ClipboardCheck, ChevronRight, Zap, RotateCcw,
  AlertTriangle, Clock, ArrowRight, Inbox,
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const STEP_CONFIG = {
  1: { icon: FileText, label: 'Document Generation', color: 'blue' },
  2: { icon: Inbox, label: 'Ingestion & Processing', color: 'violet' },
  3: { icon: Brain, label: 'AI Classification & Extraction', color: 'amber' },
  4: { icon: Building2, label: 'Vendor / Customer Resolution', color: 'cyan' },
  5: { icon: ShieldCheck, label: 'Business Central Validation', color: 'emerald' },
  6: { icon: UserCheck, label: 'Sales Rep Auto-Assignment', color: 'orange' },
  7: { icon: ClipboardCheck, label: 'Final Status', color: 'green' },
};

export default function PipelineDemoPage() {
  const [scenarios, setScenarios] = useState([]);
  const [selectedScenario, setSelectedScenario] = useState('');
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState([]);
  const [result, setResult] = useState(null);
  const [animatingStep, setAnimatingStep] = useState(0);
  const timerRef = useRef(null);

  // Batch demo state
  const [batchRunning, setBatchRunning] = useState(false);
  const [batchSteps, setBatchSteps] = useState([]);
  const [batchResult, setBatchResult] = useState(null);

  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/sales-dashboard/demo/scenarios`);
        const data = await res.json();
        setScenarios(data.scenarios || []);
        if (data.scenarios?.length > 0) setSelectedScenario(data.scenarios[0].id);
      } catch {
        toast.error('Failed to load demo scenarios');
      }
    })();
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const runDemo = async () => {
    if (!selectedScenario || running) return;
    setRunning(true);
    setSteps([]);
    setResult(null);
    setAnimatingStep(1);

    // Animate steps appearing one by one
    const stepDelay = 600;
    let currentStep = 1;
    timerRef.current = setInterval(() => {
      currentStep++;
      if (currentStep <= 7) {
        setAnimatingStep(currentStep);
      } else {
        clearInterval(timerRef.current);
      }
    }, stepDelay);

    try {
      const res = await fetch(`${API}/api/sales-dashboard/demo/run?scenario_id=${selectedScenario}`, { method: 'POST' });
      if (!res.ok) throw new Error('Pipeline demo failed');
      const data = await res.json();

      // Stop animation and show real results
      clearInterval(timerRef.current);
      setAnimatingStep(8); // All done
      setSteps(data.steps || []);
      setResult(data);
      toast.success(`Pipeline complete in ${data.total_duration_ms}ms`);
    } catch (err) {
      clearInterval(timerRef.current);
      setAnimatingStep(0);
      toast.error('Pipeline demo failed: ' + err.message);
    } finally {
      setRunning(false);
    }
  };

  const reset = () => {
    setSteps([]);
    setResult(null);
    setAnimatingStep(0);
  };

  const selectedInfo = scenarios.find(s => s.id === selectedScenario);

  return (
    <div className="max-w-[1100px] mx-auto space-y-6" data-testid="pipeline-demo-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Zap className="w-5 h-5 text-amber-500" />
            Pipeline Demo
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Watch a PO flow through the entire pipeline &mdash; ingestion to sales rep queue
          </p>
        </div>
      </div>

      {/* Controls */}
      <Card className="border border-border" data-testid="pipeline-demo-controls">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex-1 min-w-[240px]">
              <label className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1.5 block">
                Select PO Scenario
              </label>
              <Select value={selectedScenario} onValueChange={setSelectedScenario} disabled={running}>
                <SelectTrigger className="h-10" data-testid="scenario-selector">
                  <SelectValue placeholder="Choose a scenario..." />
                </SelectTrigger>
                <SelectContent>
                  {scenarios.map(s => (
                    <SelectItem key={s.id} value={s.id}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button
              size="lg"
              className="h-10 px-6"
              onClick={runDemo}
              disabled={running || !selectedScenario}
              data-testid="run-pipeline-btn"
            >
              {running ? (
                <><Loader2 className="w-4 h-4 animate-spin mr-2" /> Running Pipeline...</>
              ) : (
                <><Play className="w-4 h-4 mr-2" /> Run Pipeline</>
              )}
            </Button>
            {steps.length > 0 && (
              <Button variant="outline" size="lg" className="h-10" onClick={reset} data-testid="reset-pipeline-btn">
                <RotateCcw className="w-4 h-4 mr-2" /> Reset
              </Button>
            )}
          </div>

          {/* Scenario details */}
          {selectedInfo && (
            <div className="mt-4 flex flex-wrap gap-4 text-xs text-muted-foreground">
              <span><strong>Customer:</strong> {selectedInfo.customer}</span>
              <span><strong>PO:</strong> {selectedInfo.po_number}</span>
              <span><strong>Items:</strong> {selectedInfo.item_count}</span>
              <span><strong>Total:</strong> ${selectedInfo.total?.toLocaleString()}</span>
              <span>
                <strong>Expected:</strong>{' '}
                {selectedInfo.will_auto_assign ? (
                  <Badge variant="outline" className="text-[10px] bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-200 dark:border-emerald-700">Auto-Assign to Rep</Badge>
                ) : (
                  <Badge variant="outline" className="text-[10px] bg-orange-100 text-orange-800 dark:bg-orange-900/40 dark:text-orange-300 border-orange-200 dark:border-orange-700">Triage Queue</Badge>
                )}
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Pipeline Steps */}
      {(animatingStep > 0 || steps.length > 0) && (
        <div className="space-y-3" data-testid="pipeline-steps">
          {[1, 2, 3, 4, 5, 6, 7].map(num => {
            const cfg = STEP_CONFIG[num];
            const Icon = cfg.icon;
            const realStep = steps.find(s => s.step === num);
            const isAnimating = animatingStep === num && !realStep;
            const isWaiting = animatingStep < num && !realStep;
            const isComplete = !!realStep;

            if (isWaiting && steps.length === 0) return null;

            return (
              <StepCard
                key={num}
                num={num}
                Icon={Icon}
                label={cfg.label}
                color={cfg.color}
                isAnimating={isAnimating}
                isWaiting={isWaiting}
                isComplete={isComplete}
                step={realStep}
              />
            );
          })}
        </div>
      )}

      {/* Result Summary */}
      {result && (
        <Card className="border-2 border-primary/30 bg-primary/5" data-testid="pipeline-result">
          <CardContent className="p-5">
            <div className="flex items-center gap-3 mb-3">
              <CheckCircle2 className="w-6 h-6 text-emerald-500" />
              <div>
                <p className="font-bold text-base">Pipeline Complete</p>
                <p className="text-xs text-muted-foreground">
                  {result.scenario} &mdash; {result.total_duration_ms}ms total
                </p>
              </div>
            </div>
            <div className="flex flex-wrap gap-4 text-sm">
              <div>
                <span className="text-muted-foreground">Document ID: </span>
                <code className="text-xs bg-muted px-1.5 py-0.5 rounded">{result.document_id?.slice(0, 12)}...</code>
              </div>
              {steps[5]?.details?.assigned !== undefined && (
                <div>
                  <span className="text-muted-foreground">Destination: </span>
                  {steps[6]?.details?.queue_destination === 'My Queue' ? (
                    <Badge className="bg-emerald-600 text-white text-xs">
                      {steps[6]?.details?.assigned_rep}'s Queue
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-xs bg-orange-100 text-orange-800 border-orange-300">
                      Triage Queue
                    </Badge>
                  )}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      {/* Batch PO Split Demo */}
      <div className="border-t border-border pt-6 mt-2" data-testid="batch-demo-section">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-4">
          <div>
            <h2 className="text-xl font-bold tracking-tight flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
              <FileText className="w-5 h-5 text-cyan-500" />
              Batch PO Split Demo
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Watch a multi-page PO get split into individual orders &mdash; each page through the full pipeline
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              size="lg"
              className="h-10 px-6"
              onClick={async () => {
                setBatchRunning(true);
                setBatchSteps([]);
                setBatchResult(null);
                try {
                  const res = await fetch(`${API}/api/sales-dashboard/demo/run-batch`, { method: 'POST' });
                  if (!res.ok) throw new Error('Batch demo failed');
                  const data = await res.json();
                  setBatchSteps(data.steps || []);
                  setBatchResult(data);
                  toast.success(`Batch split: ${data.children_created} child documents created`);
                } catch (err) {
                  toast.error('Batch demo failed: ' + err.message);
                } finally {
                  setBatchRunning(false);
                }
              }}
              disabled={batchRunning}
              data-testid="run-batch-btn"
            >
              {batchRunning ? (
                <><Loader2 className="w-4 h-4 animate-spin mr-2" /> Splitting & Processing...</>
              ) : (
                <><Play className="w-4 h-4 mr-2" /> Run Batch Split</>
              )}
            </Button>
            {batchSteps.length > 0 && (
              <Button variant="outline" size="lg" className="h-10" onClick={() => { setBatchSteps([]); setBatchResult(null); }}>
                <RotateCcw className="w-4 h-4 mr-2" /> Reset
              </Button>
            )}
          </div>
        </div>

        <div className="mb-4 flex flex-wrap gap-4 text-xs text-muted-foreground">
          <span><strong>Customer:</strong> Giovanni Food Co., Inc.</span>
          <span><strong>POs:</strong> 61312 – 61316 (5 pages)</span>
          <span><strong>Items:</strong> Glass jars, caps, labels</span>
          <span><strong>Total Value:</strong> $35,564</span>
          <Badge variant="outline" className="text-[10px] bg-cyan-100 text-cyan-800 dark:bg-cyan-900/40 dark:text-cyan-300 border-cyan-200 dark:border-cyan-700">
            1 PDF → 5 Sales Orders
          </Badge>
        </div>

        {/* Batch Steps */}
        {batchSteps.length > 0 && (
          <div className="space-y-3">
            {batchSteps.map((step, i) => {
              const BATCH_STEP_CFG = {
                1: { icon: FileText, color: 'blue' },
                2: { icon: Inbox, color: 'violet' },
                3: { icon: Brain, color: 'amber' },
                4: { icon: Zap, color: 'cyan' },
                5: { icon: ClipboardCheck, color: 'green' },
              };
              const cfg = BATCH_STEP_CFG[step.step] || { icon: CheckCircle2, color: 'blue' };

              return (
                <StepCard
                  key={step.step}
                  num={step.step}
                  Icon={cfg.icon}
                  label={step.name}
                  color={cfg.color}
                  isAnimating={false}
                  isWaiting={false}
                  isComplete={true}
                  step={step}
                />
              );
            })}

            {/* Children table */}
            {batchResult && batchSteps[4]?.details?.children?.length > 0 && (
              <Card className="border border-border" data-testid="batch-children-table">
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="border-b border-border bg-muted/40 text-xs text-muted-foreground uppercase tracking-wider">
                          <th className="text-left py-2.5 px-4 font-medium">Page</th>
                          <th className="text-left py-2.5 px-3 font-medium">PO Number</th>
                          <th className="text-left py-2.5 px-3 font-medium">Type</th>
                          <th className="text-left py-2.5 px-3 font-medium">Customer</th>
                          <th className="text-right py-2.5 px-3 font-medium">Amount</th>
                          <th className="text-center py-2.5 px-3 font-medium">Confidence</th>
                          <th className="text-left py-2.5 px-3 font-medium">Assigned Rep</th>
                          <th className="text-left py-2.5 px-4 font-medium">Queue</th>
                        </tr>
                      </thead>
                      <tbody>
                        {batchSteps[4].details.children.map((child, ci) => (
                          <tr key={ci} className="border-b border-border/50 hover:bg-muted/30">
                            <td className="py-2.5 px-4 text-xs font-mono">{child.page}</td>
                            <td className="py-2.5 px-3 text-xs font-mono font-medium">{child.po_number || '-'}</td>
                            <td className="py-2.5 px-3 text-xs">{child.type || '-'}</td>
                            <td className="py-2.5 px-3 text-xs">{child.customer || '-'}</td>
                            <td className="py-2.5 px-3 text-xs text-right font-mono">
                              {child.amount ? `$${Number(child.amount).toLocaleString()}` : '-'}
                            </td>
                            <td className="py-2.5 px-3 text-xs text-center">
                              {child.confidence ? `${(child.confidence * 100).toFixed(0)}%` : '-'}
                            </td>
                            <td className="py-2.5 px-3 text-xs">{child.assigned_rep || 'Unassigned'}</td>
                            <td className="py-2.5 px-4">
                              {child.queue === 'My Queue' ? (
                                <Badge className="text-[10px] bg-emerald-600 text-white">{child.assigned_rep}'s Queue</Badge>
                              ) : (
                                <Badge variant="outline" className="text-[10px] bg-orange-100 text-orange-800 border-orange-300">Triage</Badge>
                              )}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        )}

        {batchResult && (
          <Card className="border-2 border-cyan-500/30 bg-cyan-500/5 mt-3" data-testid="batch-result">
            <CardContent className="p-5">
              <div className="flex items-center gap-3">
                <CheckCircle2 className="w-6 h-6 text-emerald-500" />
                <div>
                  <p className="font-bold text-base">Batch Split Complete</p>
                  <p className="text-xs text-muted-foreground">
                    {batchResult.total_pages} pages → {batchResult.children_created} child documents &mdash; {batchResult.total_duration_ms}ms total
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>
    </div>
  );
}

function StepCard({ num, Icon, label, color, isAnimating, isWaiting, isComplete, step }) {
  const colorMap = {
    blue:    'border-blue-500/30 bg-blue-500/5',
    violet:  'border-violet-500/30 bg-violet-500/5',
    amber:   'border-amber-500/30 bg-amber-500/5',
    cyan:    'border-cyan-500/30 bg-cyan-500/5',
    emerald: 'border-emerald-500/30 bg-emerald-500/5',
    orange:  'border-orange-500/30 bg-orange-500/5',
    green:   'border-green-500/30 bg-green-500/5',
  };
  const iconColorMap = {
    blue: 'text-blue-500', violet: 'text-violet-500', amber: 'text-amber-500',
    cyan: 'text-cyan-500', emerald: 'text-emerald-500', orange: 'text-orange-500',
    green: 'text-green-500',
  };

  const borderClass = isComplete
    ? colorMap[color]
    : isAnimating
    ? 'border-primary/50 bg-primary/5 animate-pulse'
    : 'border-border/30 bg-muted/20 opacity-50';

  return (
    <Card className={`border ${borderClass} transition-all duration-500`} data-testid={`pipeline-step-${num}`}>
      <CardContent className="p-4">
        <div className="flex items-start gap-3">
          <div className={`flex-shrink-0 w-8 h-8 rounded-lg flex items-center justify-center ${isComplete ? 'bg-emerald-500/10' : 'bg-muted'}`}>
            {isComplete ? (
              step?.status === 'error'
                ? <XCircle className="w-4 h-4 text-red-500" />
                : <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            ) : isAnimating ? (
              <Loader2 className="w-4 h-4 animate-spin text-primary" />
            ) : (
              <span className="text-xs font-bold text-muted-foreground">{num}</span>
            )}
          </div>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <Icon className={`w-4 h-4 ${isComplete ? iconColorMap[color] : 'text-muted-foreground'}`} />
              <span className={`text-sm font-medium ${isComplete ? '' : 'text-muted-foreground'}`}>{label}</span>
              {step?.duration_ms != null && (
                <span className="text-[10px] text-muted-foreground ml-auto">{step.duration_ms}ms</span>
              )}
            </div>
            {isComplete && step?.details && (
              <div className="mt-2 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-1">
                {Object.entries(step.details).map(([key, val]) => {
                  if (val === '' || val === null || val === undefined) return null;
                  if (Array.isArray(val) && val.length === 0) return null;
                  const displayVal = typeof val === 'boolean' ? (val ? 'Yes' : 'No')
                    : Array.isArray(val) ? val.join(', ')
                    : typeof val === 'number' ? (key.includes('amount') || key.includes('total') ? `$${val.toLocaleString()}` : key.includes('confidence') || key.includes('score') ? `${(val * 100).toFixed(1)}%` : val.toString())
                    : String(val);

                  const displayKey = key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                  const isHighlight = key === 'assigned' || key === 'rep_email' || key === 'review_status'
                    || key === 'document_type' || key === 'ai_confidence' || key === 'queue_destination';

                  return (
                    <div key={key} className="text-xs">
                      <span className="text-muted-foreground">{displayKey}: </span>
                      <span className={isHighlight ? 'font-semibold' : ''}>{displayVal}</span>
                    </div>
                  );
                })}
              </div>
            )}
            {isAnimating && (
              <p className="text-xs text-muted-foreground mt-1 animate-pulse">Processing...</p>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
