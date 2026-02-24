import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Progress } from './ui/progress';
import {
  Inbox, Tag, CheckSquare, AlertTriangle, Database, XCircle,
  CheckCircle, RefreshCw, UploadCloud, Trash2, Eye, HelpCircle,
  RotateCcw, ChevronRight
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

// Icon mapping for Square9 stages
const stageIcons = {
  'inbox': Inbox,
  'tag': Tag,
  'check-square': CheckSquare,
  'alert-triangle': AlertTriangle,
  'database': Database,
  'x-circle': XCircle,
  'check-circle': CheckCircle,
  'refresh-cw': RefreshCw,
  'upload-cloud': UploadCloud,
  'trash-2': Trash2,
  'eye': Eye,
  'help-circle': HelpCircle,
  'check': CheckCircle,
  'circle': HelpCircle,
};

// Color mapping
const colorClasses = {
  'blue': 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
  'purple': 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
  'amber': 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
  'green': 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
  'red': 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
  'gray': 'bg-gray-100 text-gray-700 dark:bg-gray-800/50 dark:text-gray-400',
};

const badgeColors = {
  'blue': 'bg-blue-500',
  'purple': 'bg-purple-500',
  'amber': 'bg-amber-500',
  'green': 'bg-emerald-500',
  'red': 'bg-red-500',
  'gray': 'bg-gray-500',
};

export function Square9WorkflowTracker({ documentId, onRetry }) {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [retrying, setRetrying] = useState(false);

  const fetchStatus = async () => {
    try {
      const res = await fetch(`${API}/api/documents/${documentId}/square9-status`);
      if (res.ok) {
        const data = await res.json();
        setStatus(data);
      }
    } catch (err) {
      console.error('Failed to fetch Square9 status:', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (documentId) {
      fetchStatus();
    }
  }, [documentId]);

  const handleRetry = async () => {
    setRetrying(true);
    try {
      const res = await fetch(`${API}/api/documents/${documentId}/retry`, {
        method: 'POST',
      });
      const data = await res.json();
      if (data.success) {
        fetchStatus();
        if (onRetry) onRetry(data);
      }
    } catch (err) {
      console.error('Retry failed:', err);
    } finally {
      setRetrying(false);
    }
  };

  const handleResetRetries = async () => {
    try {
      const res = await fetch(`${API}/api/documents/${documentId}/reset-retries`, {
        method: 'POST',
      });
      if (res.ok) {
        fetchStatus();
      }
    } catch (err) {
      console.error('Reset failed:', err);
    }
  };

  if (loading) {
    return (
      <Card className="border border-border" data-testid="square9-workflow-loading">
        <CardContent className="p-4">
          <div className="flex items-center gap-2 text-muted-foreground">
            <RefreshCw className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading workflow status...</span>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!status) return null;

  const { stage_info, retry_count, max_retries, can_retry, auto_escalated, escalation_reason } = status;
  const Icon = stageIcons[stage_info?.icon] || HelpCircle;
  const colorClass = colorClasses[stage_info?.color] || colorClasses.gray;
  const retryProgress = (retry_count / max_retries) * 100;

  return (
    <Card className="border border-border" data-testid="square9-workflow-tracker">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Workflow Stage
          </CardTitle>
          <Badge variant="outline" className="text-[10px]">
            Square9 Compatible
          </Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Current Stage */}
        <div className={`flex items-center gap-3 p-3 rounded-lg ${colorClass}`} data-testid="current-stage">
          <Icon className="w-5 h-5 shrink-0" />
          <div className="flex-1">
            <p className="font-medium text-sm">{stage_info?.label || 'Unknown'}</p>
            <p className="text-xs opacity-80">{stage_info?.description}</p>
          </div>
        </div>

        {/* Escalation Warning */}
        {auto_escalated && (
          <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg p-3" data-testid="escalation-warning">
            <div className="flex items-center gap-2">
              <Eye className="w-4 h-4 text-red-500" />
              <span className="text-sm font-medium text-red-700 dark:text-red-300">Escalated to Manual Review</span>
            </div>
            {escalation_reason && (
              <p className="text-xs text-red-600 dark:text-red-400 mt-1">{escalation_reason}</p>
            )}
          </div>
        )}

        {/* Retry Counter */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-xs">
            <span className="text-muted-foreground">Retry Attempts</span>
            <span className="font-mono font-medium">{retry_count} / {max_retries}</span>
          </div>
          <Progress value={retryProgress} className="h-2" />
          {retry_count > 0 && retry_count < max_retries && (
            <p className="text-[11px] text-amber-600 dark:text-amber-400">
              {max_retries - retry_count} retries remaining before escalation
            </p>
          )}
        </div>

        {/* Retry History */}
        {status.retry_history?.length > 0 && (
          <div className="space-y-1">
            <p className="text-xs font-medium text-muted-foreground">Recent Retries</p>
            <div className="max-h-24 overflow-y-auto space-y-1">
              {status.retry_history.slice(-3).reverse().map((entry, idx) => (
                <div key={idx} className="flex items-center gap-2 text-[11px] text-muted-foreground bg-muted/50 rounded px-2 py-1">
                  <span className="font-mono">#{entry.attempt}</span>
                  <ChevronRight className="w-3 h-3" />
                  <span className="truncate">{entry.reason}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 pt-2 border-t border-border">
          {can_retry && !auto_escalated && (
            <Button
              variant="outline"
              size="sm"
              onClick={handleRetry}
              disabled={retrying}
              className="flex-1"
              data-testid="retry-btn"
            >
              {retrying ? (
                <RefreshCw className="w-3 h-3 mr-1 animate-spin" />
              ) : (
                <RefreshCw className="w-3 h-3 mr-1" />
              )}
              Retry
            </Button>
          )}
          {retry_count > 0 && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleResetRetries}
              className="flex-1"
              data-testid="reset-retries-btn"
            >
              <RotateCcw className="w-3 h-3 mr-1" />
              Reset Counter
            </Button>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export function Square9StageSummary() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const res = await fetch(`${API}/api/square9/stage-counts`);
        if (res.ok) {
          setData(await res.json());
        }
      } catch (err) {
        console.error('Failed to fetch stage counts:', err);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading || !data) return null;

  // Filter to stages with documents
  const activeStages = data.stages.filter(s => s.count > 0);

  return (
    <Card className="border border-border" data-testid="square9-stage-summary">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Workflow Stages
          </CardTitle>
          <span className="text-xs text-muted-foreground">{data.total_documents} docs</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex flex-wrap gap-2">
          {activeStages.map(stage => {
            const Icon = stageIcons[stage.icon] || HelpCircle;
            return (
              <div
                key={stage.stage}
                className={`flex items-center gap-1.5 px-2 py-1 rounded-md text-xs ${colorClasses[stage.color] || colorClasses.gray}`}
                title={stage.description}
              >
                <Icon className="w-3 h-3" />
                <span className="font-medium">{stage.label}</span>
                <Badge variant="secondary" className="ml-1 h-4 px-1 text-[10px]">
                  {stage.count}
                </Badge>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

export default Square9WorkflowTracker;
