import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Progress } from '../components/ui/progress';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { toast } from 'sonner';
import {
  Activity, Brain, GitBranch, FolderSync, Users, RefreshCw,
  Loader2, CheckCircle2, Clock, Zap, BarChart3, ArrowRight,
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL;

function MetricCard({ icon: Icon, label, value, sub, accent }) {
  const accentCls = accent || 'text-foreground';
  return (
    <Card className="border border-border" data-testid={`metric-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      <CardContent className="p-4 flex items-center gap-3">
        <div className="p-2 rounded-lg bg-muted/50">
          <Icon className="w-4 h-4 text-muted-foreground" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-muted-foreground truncate">{label}</p>
          <p className={`text-lg font-bold font-mono ${accentCls}`}>{value}</p>
          {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

const EVENT_LABELS = {
  vendor_correction: { label: 'Vendor Fix', cls: 'bg-violet-500/20 text-violet-400 border-violet-700' },
  classification_correction: { label: 'Reclassify', cls: 'bg-sky-500/20 text-sky-400 border-sky-700' },
  amount_correction: { label: 'Amount Edit', cls: 'bg-amber-500/20 text-amber-400 border-amber-700' },
  po_correction: { label: 'PO Edit', cls: 'bg-teal-500/20 text-teal-400 border-teal-700' },
  folder_correction: { label: 'Folder Move', cls: 'bg-pink-500/20 text-pink-400 border-pink-700' },
  approval: { label: 'Approval', cls: 'bg-emerald-500/20 text-emerald-400 border-emerald-700' },
  rejection: { label: 'Rejection', cls: 'bg-red-500/20 text-red-400 border-red-700' },
  field_edit: { label: 'Field Edit', cls: 'bg-orange-500/20 text-orange-400 border-orange-700' },
  benchmark_mismatch: { label: 'Benchmark', cls: 'bg-blue-500/20 text-blue-400 border-blue-700' },
};

function EventTypeBadge({ type }) {
  const info = EVENT_LABELS[type] || { label: type, cls: 'bg-gray-500/20 text-gray-400 border-gray-600' };
  return (
    <Badge className={`text-[10px] font-semibold border ${info.cls}`} data-testid={`event-badge-${type}`}>
      {info.label}
    </Badge>
  );
}

export default function FeedbackLoopHealthPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [replaying, setReplaying] = useState(false);

  const fetchHealth = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_URL}/api/feedback-loop/health`);
      if (!res.ok) throw new Error('Failed to fetch');
      setData(await res.json());
    } catch {
      toast.error('Failed to load feedback loop health');
    } finally {
      setLoading(false);
    }
  };

  const replayUnapplied = async () => {
    setReplaying(true);
    try {
      const res = await fetch(`${API_URL}/api/feedback-loop/replay`, { method: 'POST' });
      const result = await res.json();
      if (result.applied > 0) {
        toast.success(`Replayed ${result.applied} events (${result.errors} errors)`);
      } else {
        toast.info('No unapplied events to replay');
      }
      fetchHealth();
    } catch {
      toast.error('Replay failed');
    } finally {
      setReplaying(false);
    }
  };

  useEffect(() => { fetchHealth(); }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20" data-testid="feedback-health-loading">
        <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">Loading feedback health...</span>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-20 text-muted-foreground text-sm" data-testid="feedback-health-empty">
        No feedback data available yet. User interactions will appear here as the system learns.
      </div>
    );
  }

  const { total_events, applied_events, pending_events, events_by_type,
    learning_signals, recent_events, daily_activity, top_corrected_vendors } = data;

  const appliedPct = total_events > 0 ? Math.round((applied_events / total_events) * 100) : 0;

  return (
    <div className="space-y-6" data-testid="feedback-loop-health-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
            Feedback Loop Health
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Every interaction is training data. Here is how much the system has learned.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchHealth} className="h-8 text-xs gap-1" data-testid="refresh-feedback-health">
            <RefreshCw className="w-3 h-3" /> Refresh
          </Button>
          {pending_events > 0 && (
            <Button
              variant="default"
              size="sm"
              onClick={replayUnapplied}
              disabled={replaying}
              className="h-8 text-xs gap-1 bg-emerald-600 hover:bg-emerald-700"
              data-testid="replay-feedback-btn"
            >
              {replaying ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
              Replay {pending_events} Unapplied
            </Button>
          )}
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="feedback-summary-cards">
        <MetricCard icon={Activity} label="Total Events" value={total_events} />
        <MetricCard icon={CheckCircle2} label="Applied" value={applied_events} accent="text-emerald-500" sub={`${appliedPct}% of total`} />
        <MetricCard icon={Clock} label="Pending" value={pending_events} accent={pending_events > 0 ? 'text-amber-400' : 'text-muted-foreground'} />
        <MetricCard icon={Users} label="Vendor Aliases" value={learning_signals?.vendor_aliases_learned ?? 0} accent="text-violet-400" />
        <MetricCard icon={Brain} label="Classification Examples" value={learning_signals?.classification_examples ?? 0} accent="text-sky-400" />
      </div>

      {/* Applied Progress */}
      <Card className="border border-border" data-testid="applied-progress-card">
        <CardContent className="p-4">
          <div className="flex items-center justify-between text-xs mb-1.5">
            <span className="text-muted-foreground font-medium">Learning Signal Application Rate</span>
            <span className="font-mono font-bold">{appliedPct}%</span>
          </div>
          <Progress value={appliedPct} className="h-2" />
          <p className="text-[10px] text-muted-foreground mt-1">
            {applied_events} of {total_events} feedback events have been consumed as learning signals
          </p>
        </CardContent>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Events by Type */}
        <Card className="border border-border" data-testid="events-by-type-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <BarChart3 className="w-3 h-3" /> Events by Type
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0 space-y-2">
            {events_by_type && Object.keys(events_by_type).length > 0 ? (
              Object.entries(events_by_type)
                .sort((a, b) => b[1] - a[1])
                .map(([type, count]) => {
                  const pct = total_events > 0 ? Math.round((count / total_events) * 100) : 0;
                  return (
                    <div key={type} className="flex items-center gap-3">
                      <EventTypeBadge type={type} />
                      <div className="flex-1">
                        <Progress value={pct} className="h-1.5" />
                      </div>
                      <span className="text-xs font-mono w-12 text-right">{count}</span>
                    </div>
                  );
                })
            ) : (
              <p className="text-xs text-muted-foreground py-4 text-center">No events recorded yet</p>
            )}
          </CardContent>
        </Card>

        {/* Top Corrected Vendors */}
        <Card className="border border-border" data-testid="top-vendors-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Zap className="w-3 h-3" /> Most Corrected Vendors
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            {top_corrected_vendors && top_corrected_vendors.length > 0 ? (
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="text-[10px]">Vendor</TableHead>
                    <TableHead className="text-[10px] text-right">Events</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {top_corrected_vendors.map((v) => (
                    <TableRow key={v.vendor_id} data-testid={`top-vendor-${v.vendor_id}`}>
                      <TableCell className="py-1.5">
                        <span className="text-xs font-medium truncate block max-w-[200px]">{v.vendor_id}</span>
                      </TableCell>
                      <TableCell className="py-1.5 text-right">
                        <span className="text-xs font-mono font-bold">{v.event_count}</span>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="text-xs text-muted-foreground py-4 text-center">No vendor corrections yet</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Daily Activity */}
      {daily_activity && daily_activity.length > 0 && (
        <Card className="border border-border" data-testid="daily-activity-card">
          <CardHeader className="pb-2">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <GitBranch className="w-3 h-3" /> Daily Activity (Last 30 Days)
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="flex items-end gap-[2px] h-16" data-testid="daily-activity-bars">
              {(() => {
                const maxCount = Math.max(...daily_activity.map(d => d.count), 1);
                return daily_activity.map((d) => (
                  <div
                    key={d.date}
                    className="flex-1 bg-primary/60 rounded-t-sm hover:bg-primary transition-colors min-w-[3px]"
                    style={{ height: `${Math.max((d.count / maxCount) * 100, 4)}%` }}
                    title={`${d.date}: ${d.count} events`}
                  />
                ));
              })()}
            </div>
            <div className="flex justify-between text-[10px] text-muted-foreground mt-1">
              <span>{daily_activity[0]?.date}</span>
              <span>{daily_activity[daily_activity.length - 1]?.date}</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Recent Events */}
      <Card className="border border-border" data-testid="recent-events-card">
        <CardHeader className="pb-2">
          <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Clock className="w-3 h-3" /> Recent Events
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          {recent_events && recent_events.length > 0 ? (
            <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
              {recent_events.map((ev, i) => (
                <div key={i} className="flex items-center gap-3 text-xs px-2 py-1.5 bg-muted/30 rounded" data-testid={`recent-event-${i}`}>
                  <EventTypeBadge type={ev.event_type} />
                  <div className="flex-1 min-w-0">
                    {ev.vendor_id && (
                      <span className="font-medium truncate block max-w-[180px]">{ev.vendor_id}</span>
                    )}
                    {ev.document_id && (
                      <span className="text-[10px] text-muted-foreground truncate block max-w-[200px]">{ev.document_id}</span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant="outline" className="text-[10px]">{ev.source}</Badge>
                    {ev.applied ? (
                      <CheckCircle2 className="w-3 h-3 text-emerald-500" />
                    ) : (
                      <Clock className="w-3 h-3 text-amber-400" />
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground whitespace-nowrap shrink-0">
                    {ev.created_at ? new Date(ev.created_at).toLocaleString('en-GB', {
                      day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
                    }) : ''}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-muted-foreground py-4 text-center">
              No recent events. User corrections and interactions will appear here.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
