import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  FileText, Brain, Database, ShieldCheck, Route,
  CheckCircle2, XCircle, AlertTriangle, Clock, Loader2,
  ChevronDown, ChevronUp, Zap, Timer
} from 'lucide-react';
import { getDocumentIntelligence } from '@/lib/api';

const STAGES = [
  { key: 'parse', label: 'Parse', icon: FileText, desc: 'Extract text from file' },
  { key: 'classify', label: 'Classify', icon: Brain, desc: 'Determine document type' },
  { key: 'extract', label: 'Extract', icon: Database, desc: 'Pull structured fields' },
  { key: 'validate', label: 'Validate', icon: ShieldCheck, desc: 'Check against BC rules' },
  { key: 'route', label: 'Route', icon: Route, desc: 'Decide automation path' },
];

const STATUS_CONFIG = {
  passed: { color: 'text-emerald-500', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', icon: CheckCircle2, label: 'Passed' },
  failed: { color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/30', icon: XCircle, label: 'Failed' },
  skipped: { color: 'text-gray-400', bg: 'bg-gray-500/10', border: 'border-gray-500/20', icon: Clock, label: 'Skipped' },
  not_run: { color: 'text-gray-300', bg: 'bg-gray-500/5', border: 'border-gray-500/10', icon: Clock, label: 'Not Run' },
};

function formatDuration(ms) {
  if (!ms && ms !== 0) return '-';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

export default function PipelineVisualization({ documentId }) {
  const [intel, setIntel] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!documentId) return;
    setLoading(true);
    getDocumentIntelligence(documentId)
      .then(res => setIntel(res.data))
      .catch(() => setIntel(null))
      .finally(() => setLoading(false));
  }, [documentId]);

  if (loading) {
    return (
      <Card data-testid="pipeline-visualization-loading">
        <CardContent className="py-6 flex items-center justify-center">
          <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const stages = intel?.pipeline_stages;
  if (!stages || Object.keys(stages).length === 0) return null;

  const pipelineStatus = intel?.pipeline_status || 'incomplete';
  const totalMs = STAGES.reduce((sum, s) => sum + (stages[s.key]?.ms || 0), 0);
  const failureStage = intel?.pipeline_failure_stage;

  return (
    <Card data-testid="pipeline-visualization" className="border border-border">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Processing Pipeline
            </CardTitle>
          </div>
          <div className="flex items-center gap-2">
            <Badge
              data-testid="pipeline-status-badge"
              className={`text-[10px] ${
                pipelineStatus === 'passed' ? 'bg-emerald-500/10 text-emerald-500 border-emerald-500/30' :
                pipelineStatus === 'failed' ? 'bg-red-500/10 text-red-500 border-red-500/30' :
                'bg-gray-500/10 text-gray-500 border-gray-500/20'
              }`}
              variant="outline"
            >
              {pipelineStatus === 'passed' ? <CheckCircle2 className="w-3 h-3 mr-1" /> :
               pipelineStatus === 'failed' ? <XCircle className="w-3 h-3 mr-1" /> :
               <Clock className="w-3 h-3 mr-1" />}
              {pipelineStatus.toUpperCase()}
            </Badge>
            <span className="text-[10px] text-muted-foreground font-mono flex items-center gap-1">
              <Timer className="w-3 h-3" />
              {formatDuration(totalMs)}
            </span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-1">
        {/* Stage indicators - compact horizontal */}
        <div className="flex items-center gap-0.5 mb-2" data-testid="pipeline-stages-bar">
          {STAGES.map((stage, idx) => {
            const data = stages[stage.key] || {};
            const status = data.status || 'not_run';
            const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.not_run;
            const isFailure = stage.key === failureStage;
            const StageIcon = stage.icon;
            const StatusIcon = cfg.icon;

            return (
              <div key={stage.key} className="flex items-center flex-1 min-w-0" data-testid={`pipeline-stage-${stage.key}`}>
                <div className={`flex-1 relative group`}>
                  <div className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md ${cfg.bg} ${isFailure ? 'ring-1 ring-red-500/50' : ''}`}>
                    <StageIcon className={`w-3.5 h-3.5 shrink-0 ${cfg.color}`} />
                    <span className={`text-[10px] font-medium truncate ${cfg.color}`}>
                      {stage.label}
                    </span>
                    <StatusIcon className={`w-3 h-3 shrink-0 ${cfg.color}`} />
                  </div>
                  {/* Duration underneath */}
                  <div className="text-center mt-0.5">
                    <span className="text-[9px] text-muted-foreground font-mono">
                      {formatDuration(data.ms)}
                    </span>
                  </div>
                </div>
                {idx < STAGES.length - 1 && (
                  <div className={`w-2 h-px mx-0.5 shrink-0 ${status === 'passed' ? 'bg-emerald-500/40' : 'bg-border'}`} />
                )}
              </div>
            );
          })}
        </div>

        {/* Failure message */}
        {intel?.pipeline_failure_reason && (
          <div className="bg-red-500/5 border border-red-500/20 rounded-md p-2 mt-1" data-testid="pipeline-failure-reason">
            <p className="text-[11px] text-red-500">
              <span className="font-semibold">Failed at {failureStage}:</span>{' '}
              {intel.pipeline_failure_reason}
            </p>
          </div>
        )}

        {/* Expandable details */}
        <Button
          variant="ghost"
          size="sm"
          className="w-full h-6 text-[10px] text-muted-foreground mt-1"
          onClick={() => setExpanded(!expanded)}
          data-testid="pipeline-expand-btn"
        >
          {expanded ? <ChevronUp className="w-3 h-3 mr-1" /> : <ChevronDown className="w-3 h-3 mr-1" />}
          {expanded ? 'Hide Details' : 'Show Details'}
        </Button>

        {expanded && (
          <div className="space-y-2 mt-2 border-t border-border pt-2" data-testid="pipeline-details">
            {STAGES.map(stage => {
              const data = stages[stage.key] || {};
              const status = data.status || 'not_run';
              const cfg = STATUS_CONFIG[status] || STATUS_CONFIG.not_run;
              const StageIcon = stage.icon;
              const gatePassed = data.quality_gate;

              return (
                <div key={stage.key} className={`rounded-md p-2.5 ${cfg.bg} border ${cfg.border}`} data-testid={`pipeline-detail-${stage.key}`}>
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex items-center gap-2">
                      <StageIcon className={`w-4 h-4 ${cfg.color}`} />
                      <span className={`text-xs font-semibold ${cfg.color}`}>{stage.label}</span>
                      <Badge variant="outline" className={`text-[9px] px-1 py-0 h-4 ${cfg.color}`}>
                        {cfg.label}
                      </Badge>
                    </div>
                    <div className="flex items-center gap-2">
                      {gatePassed !== undefined && (
                        <span className={`text-[9px] flex items-center gap-0.5 ${gatePassed ? 'text-emerald-500' : 'text-red-400'}`}>
                          {gatePassed ? <CheckCircle2 className="w-2.5 h-2.5" /> : <XCircle className="w-2.5 h-2.5" />}
                          Gate
                        </span>
                      )}
                      <span className="text-[10px] text-muted-foreground font-mono">
                        {formatDuration(data.ms)}
                      </span>
                    </div>
                  </div>
                  <p className="text-[10px] text-muted-foreground">{stage.desc}</p>
                  {data.error && (
                    <p className="text-[10px] text-red-400 mt-1 bg-red-500/5 rounded px-1.5 py-0.5">
                      {data.error}
                    </p>
                  )}
                </div>
              );
            })}

            {/* Summary row */}
            <div className="flex items-center justify-between text-[10px] text-muted-foreground pt-1 border-t border-border">
              <span>Method: <code className="font-mono">{intel?.classification_method || '-'}</code></span>
              <span>Fields: <code className="font-mono">{intel?.meaningful_field_count ?? '-'}</code></span>
              <span>Total: <code className="font-mono">{formatDuration(totalMs)}</code></span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
