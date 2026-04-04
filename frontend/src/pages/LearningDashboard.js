import React, { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import {
  Brain, RefreshCw, TrendingUp, CheckCircle2, AlertTriangle,
  Zap, BookOpen, ArrowRight, Activity, Database, Loader2,
  RotateCcw, Sparkles
} from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ title, value, icon: Icon, subtitle, color = "text-emerald-500" }) {
  return (
    <Card data-testid={`stat-${title.toLowerCase().replace(/\s/g, '-')}`}>
      <CardContent className="pt-4 pb-3 px-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wide">{title}</p>
            <p className="text-2xl font-bold mt-1">{value}</p>
            {subtitle && <p className="text-xs text-muted-foreground mt-0.5">{subtitle}</p>}
          </div>
          <Icon className={`w-8 h-8 ${color} opacity-70`} />
        </div>
      </CardContent>
    </Card>
  );
}

function LearningEnginesSection({ onComplete }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning/run-all`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
        toast.success('All learning engines completed');
        if (onComplete) onComplete();
      } else {
        toast.error('Learning engines failed');
      }
    } catch {
      toast.error('Network error');
    }
    setRunning(false);
  };

  const posted = result?.posted_draft_detection || {};
  const cross = result?.cross_vendor_learning || {};
  const promo = result?.confidence_auto_promotion || {};

  return (
    <Card data-testid="learning-engines-section">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Zap className="w-4 h-4 text-amber-500" />
          Continuous Learning Engines
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-3">
          Runs automatically every 2h. Detects posted drafts in BC, propagates corrections across similar vendors,
          and auto-promotes vendor confidence based on approval ratio.
        </p>
        <Button onClick={handleRun} disabled={running} data-testid="run-engines-btn">
          {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <Zap className="w-4 h-4 mr-2" />}
          {running ? 'Running Engines...' : 'Run All Learning Engines'}
        </Button>

        {result && (
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3" data-testid="engines-results">
            {/* A: Posted Draft Detection */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-emerald-400 mb-2">A. Posted Draft Detection</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Checked</span><span>{posted.checked || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Posted Found</span><span className="text-emerald-400">{posted.posted_found || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Changes Learned</span><span className="text-violet-400">{posted.changes_learned || 0}</span></div>
              </div>
            </div>

            {/* B: Cross-Vendor Learning */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-blue-400 mb-2">B. Cross-Vendor Propagation</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Corrections Checked</span><span>{cross.corrections_checked || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Vendors Propagated To</span><span className="text-blue-400">{cross.propagated_to_vendors || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Adjustments Applied</span><span className="text-violet-400">{cross.propagations_applied || 0}</span></div>
              </div>
            </div>

            {/* C: Confidence Auto-Promotion */}
            <div className="bg-muted/50 rounded p-3">
              <p className="text-xs font-medium text-amber-400 mb-2">C. Confidence Promotion</p>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Promoted</span><span className="text-emerald-400">{promo.promoted?.length || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Demoted</span><span className="text-rose-400">{promo.demoted?.length || 0}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Unchanged</span><span>{promo.unchanged || 0}</span></div>
              </div>
              {promo.promoted?.length > 0 && (
                <div className="mt-2 space-y-1">
                  {promo.promoted.map((p, i) => (
                    <div key={i} className="flex items-center gap-1 text-xs">
                      <span className="font-mono">{p.vendor}</span>
                      <Badge variant="outline" className="text-xs text-rose-400">{p.from}</Badge>
                      <ArrowRight className="w-3 h-3" />
                      <Badge variant="outline" className="text-xs text-emerald-400">{p.to}</Badge>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function ReEvaluateSection({ onComplete }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState(null);

  const handleRun = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await fetch(`${API}/api/readiness/reevaluate-all`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setResult(data);
        toast.success(
          `Re-evaluated ${data.total_processed} docs — ${data.total_corrections} corrections applied`
        );
        if (onComplete) onComplete();
      } else {
        toast.error('Re-evaluation failed');
      }
    } catch {
      toast.error('Network error');
    }
    setRunning(false);
  };

  return (
    <Card data-testid="reevaluate-section">
      <CardHeader className="pb-2">
        <CardTitle className="text-base flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-500" />
          Batch Re-evaluate & Learn
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-3">
          Re-run readiness evaluation across all documents. Detects and corrects signal contradictions
          (stale duplicate flags, premature PO resolved, etc.) — every correction feeds into the learning pipeline.
        </p>
        <Button onClick={handleRun} disabled={running} data-testid="reevaluate-all-btn">
          {running ? <Loader2 className="w-4 h-4 animate-spin mr-2" /> : <RotateCcw className="w-4 h-4 mr-2" />}
          {running ? 'Re-evaluating...' : 'Re-evaluate All Documents'}
        </Button>

        {result && (
          <div className="mt-4 space-y-3" data-testid="reevaluate-results">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold">{result.total_processed}</p>
                <p className="text-xs text-muted-foreground">Processed</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-violet-400">{result.total_corrections}</p>
                <p className="text-xs text-muted-foreground">Corrections Learned</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-amber-400">{result.status_transitions?.length || 0}</p>
                <p className="text-xs text-muted-foreground">Status Changes</p>
              </div>
              <div className="bg-muted/50 rounded p-2 text-center">
                <p className="text-lg font-bold text-rose-400">{result.errors}</p>
                <p className="text-xs text-muted-foreground">Errors</p>
              </div>
            </div>

            {/* Status Distribution */}
            {result.by_status && Object.keys(result.by_status).length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">Status Distribution</p>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(result.by_status).map(([status, count]) => (
                    <Badge key={status} variant="outline" className="text-xs">
                      {status}: {count}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Status Transitions */}
            {result.status_transitions?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  Status Transitions ({result.status_transitions.length})
                </p>
                <div className="max-h-[200px] overflow-y-auto space-y-1">
                  {result.status_transitions.map((t, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs bg-muted/50 rounded px-2 py-1">
                      <span className="font-mono">{t.doc_id}</span>
                      {t.vendor_no && <span className="text-muted-foreground">{t.vendor_no}</span>}
                      <Badge variant="outline" className="text-rose-400 border-rose-500/30">{t.from}</Badge>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <Badge variant="outline" className="text-emerald-400 border-emerald-500/30">{t.to}</Badge>
                      <span className="text-muted-foreground ml-auto">
                        {(t.old_confidence * 100).toFixed(0)}% → {(t.new_confidence * 100).toFixed(0)}%
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Vendor Corrections */}
            {result.vendor_corrections?.length > 0 && (
              <div>
                <p className="text-xs font-medium text-muted-foreground mb-1">
                  Vendors with Corrections ({result.vendor_corrections.length})
                </p>
                <div className="max-h-[150px] overflow-y-auto space-y-1">
                  {result.vendor_corrections.map((v, i) => (
                    <div key={i} className="flex items-center gap-2 text-xs bg-muted/50 rounded px-2 py-1">
                      <span className="font-mono font-medium">{v.vendor_no}</span>
                      <Badge variant="secondary">{v.correction_count} corrections</Badge>
                      {v.signals.map((s, j) => (
                        <Badge key={j} variant="outline" className="text-xs text-violet-400 border-violet-500/30">{s}</Badge>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function LearningDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchData = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/posting-patterns/learning-dashboard`);
      if (res.ok) setData(await res.json());
    } catch (err) {
      console.error(err);
    }
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64" data-testid="learning-loading">
      <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
    </div>
  );

  if (!data) return (
    <div className="p-6 text-center text-muted-foreground" data-testid="learning-error">
      Failed to load learning data
    </div>
  );

  const s = data.summary;

  return (
    <div className="p-4 space-y-6 max-w-[1400px] mx-auto" data-testid="learning-dashboard">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <Brain className="w-6 h-6 text-violet-500" />
            AI Learning Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Proof of what the system has learned and continues to learn
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={fetchData} data-testid="refresh-learning-btn">
          <RefreshCw className="w-4 h-4 mr-1" />Refresh
        </Button>
      </div>

      {/* Summary Stats */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3" data-testid="learning-stats">
        <StatCard title="Learning Events" value={s.total_learning_events} icon={Activity}
                  subtitle="From BC postings" color="text-violet-500" />
        <StatCard title="Vendor Templates" value={s.total_posting_profiles} icon={Database}
                  subtitle={`${s.continuously_learning_vendors} continuously learning`} color="text-blue-500" />
        <StatCard title="Corrections Learned" value={s.total_corrections} icon={BookOpen}
                  subtitle="Classification fixes" color="text-amber-500" />
        <StatCard title="Label Corrections" value={s.total_label_corrections} icon={ArrowRight}
                  subtitle="Reference relabeling" color="text-rose-500" />
        <StatCard title="Auto-Drafted PIs" value={s.total_auto_drafted} icon={Zap}
                  subtitle="Template-driven" color="text-emerald-500" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Template Confidence Breakdown */}
        <Card data-testid="confidence-breakdown">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-blue-500" />
              Posting Template Confidence
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.posting_template_confidence.length === 0 ? (
              <p className="text-sm text-muted-foreground">No templates analyzed yet</p>
            ) : (
              <div className="space-y-3">
                {data.posting_template_confidence.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50">
                    <div className="flex items-center gap-2">
                      <Badge variant={p.confidence === 'high' ? 'default' : p.confidence === 'medium' ? 'secondary' : 'outline'}
                             className={p.confidence === 'high' ? 'bg-emerald-600' : ''}>
                        {p.confidence}
                      </Badge>
                      <span className="text-sm font-medium">{p.vendor_count} vendors</span>
                    </div>
                    <span className="text-xs text-muted-foreground">
                      avg {p.avg_invoices_analyzed} invoices analyzed
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Label Correction Patterns */}
        <Card data-testid="label-corrections">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <ArrowRight className="w-4 h-4 text-rose-500" />
              Learned Label Corrections
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.label_correction_patterns.length === 0 ? (
              <p className="text-sm text-muted-foreground">No label corrections recorded yet</p>
            ) : (
              <div className="space-y-2">
                {data.label_correction_patterns.map((p, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50">
                    <div className="flex items-center gap-2">
                      <Badge variant="outline" className="text-rose-600 border-rose-300">{p.from_label}</Badge>
                      <ArrowRight className="w-3 h-3 text-muted-foreground" />
                      <Badge variant="outline" className="text-emerald-600 border-emerald-300">{p.to_label}</Badge>
                    </div>
                    <div className="text-right">
                      <span className="text-sm font-medium">{p.corrections}x</span>
                      <span className="text-xs text-muted-foreground ml-2">{p.vendors_affected} vendors</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Vendor Learning Activity */}
        <Card data-testid="vendor-learning">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="w-4 h-4 text-violet-500" />
              Vendor Learning Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.vendor_learning_activity.length === 0 ? (
              <p className="text-sm text-muted-foreground">No learning events yet</p>
            ) : (
              <div className="space-y-1.5 max-h-[300px] overflow-y-auto">
                {data.vendor_learning_activity.map((v, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50 text-sm">
                    <div>
                      <span className="font-mono font-medium">{v.vendor_no}</span>
                      <span className="text-muted-foreground ml-2">{v.learning_events} events</span>
                    </div>
                    <div className="text-right text-xs text-muted-foreground">
                      <div>${v.total_amount_learned.toLocaleString()}</div>
                      <div>{v.avg_lines_per_invoice} lines/inv</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Auto-Draft Results by Vendor */}
        <Card data-testid="auto-draft-results">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <Zap className="w-4 h-4 text-emerald-500" />
              Auto-Drafted PIs by Vendor
            </CardTitle>
          </CardHeader>
          <CardContent>
            {data.auto_draft_by_vendor.length === 0 ? (
              <p className="text-sm text-muted-foreground">No auto-drafts yet</p>
            ) : (
              <div className="space-y-1.5">
                {data.auto_draft_by_vendor.map((d, i) => (
                  <div key={i} className="flex items-center justify-between p-2 rounded bg-muted/50 text-sm">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      <span className="font-mono font-medium">{d.vendor_no}</span>
                    </div>
                    <div className="text-right">
                      <span className="font-medium">{d.drafts_created} drafts</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {d.last_draft ? new Date(d.last_draft).toLocaleDateString() : ''}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Learning Events */}
      <Card data-testid="recent-events">
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center gap-2">
            <Brain className="w-4 h-4 text-violet-500" />
            Recent Learning Events
          </CardTitle>
        </CardHeader>
        <CardContent>
          {data.recent_learning_events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No learning events recorded yet. Learning starts when PIs are created in BC.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="pb-2 font-medium">Vendor</th>
                    <th className="pb-2 font-medium">When</th>
                    <th className="pb-2 font-medium">Lines</th>
                    <th className="pb-2 font-medium">Items Learned</th>
                    <th className="pb-2 font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {data.recent_learning_events.map((e, i) => (
                    <tr key={i} className="border-b border-muted/50">
                      <td className="py-1.5 font-mono">{e.vendor_no}</td>
                      <td className="py-1.5 text-muted-foreground">
                        {e.posted_at ? new Date(e.posted_at).toLocaleString() : 'N/A'}
                      </td>
                      <td className="py-1.5">{e.line_count}</td>
                      <td className="py-1.5">
                        {(e.items_used || []).map((item, j) => (
                          <Badge key={j} variant="outline" className="mr-1 text-xs">{item}</Badge>
                        ))}
                      </td>
                      <td className="py-1.5">${(e.amount || 0).toLocaleString()}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Recent Corrections */}
      {data.recent_corrections.length > 0 && (
        <Card data-testid="recent-corrections">
          <CardHeader className="pb-2">
            <CardTitle className="text-base flex items-center gap-2">
              <BookOpen className="w-4 h-4 text-amber-500" />
              Recent Classification Corrections
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-1.5">
              {data.recent_corrections.map((c, i) => (
                <div key={i} className="flex items-center gap-3 p-2 rounded bg-muted/50 text-sm">
                  <Badge variant="outline" className="text-xs">{c.correction_type || 'correction'}</Badge>
                  {c.vendor_id && <span className="font-mono text-xs">{c.vendor_id}</span>}
                  {c.original_type && c.corrected_type && (
                    <span className="text-muted-foreground">
                      {c.original_type} <ArrowRight className="w-3 h-3 inline" /> {c.corrected_type}
                    </span>
                  )}
                  <span className="text-xs text-muted-foreground ml-auto">
                    {c.source || ''} {c.confirmed_at ? new Date(c.confirmed_at).toLocaleDateString() : ''}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Learning Engines Section */}
      <LearningEnginesSection onComplete={fetchData} />

      {/* Batch Re-evaluate Section */}
      <ReEvaluateSection onComplete={fetchData} />
    </div>
  );
}
