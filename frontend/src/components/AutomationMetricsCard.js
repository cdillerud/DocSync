/**
 * Automation Intelligence Metrics Card — Dashboard component
 * Shows automation rate, confidence distribution, signal averages,
 * and top review/blocking causes.
 */
import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import {
  Brain, Zap, Eye, Ban, TrendingUp, Target, BarChart3, Loader2
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function RateGauge({ label, value, icon: Icon, color }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="text-center" data-testid={`rate-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <Icon className={`w-4 h-4 mx-auto mb-1 ${color}`} />
      <div className={`text-xl font-black ${color}`} style={{ fontFamily: 'Chivo, sans-serif' }}>
        {pct}%
      </div>
      <div className="text-[10px] text-muted-foreground">{label}</div>
    </div>
  );
}

function DistributionBar({ distribution }) {
  if (!distribution || !Object.keys(distribution).length) return null;
  const total = Object.values(distribution).reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  const buckets = [
    { key: '0.0-0.3', color: 'bg-red-500', label: '0-30%' },
    { key: '0.3-0.5', color: 'bg-orange-500', label: '30-50%' },
    { key: '0.5-0.7', color: 'bg-amber-500', label: '50-70%' },
    { key: '0.7-0.9', color: 'bg-sky-500', label: '70-90%' },
    { key: '0.9-1.0', color: 'bg-emerald-500', label: '90-100%' },
  ];

  return (
    <div data-testid="confidence-distribution">
      <div className="text-xs font-semibold mb-1.5">Confidence Distribution</div>
      <div className="flex gap-0.5 h-3 rounded-full overflow-hidden bg-muted/30">
        {buckets.map(b => {
          const count = distribution[b.key] || 0;
          const pct = (count / total) * 100;
          if (pct === 0) return null;
          return (
            <div key={b.key} className={`${b.color} h-full`} style={{ width: `${pct}%` }}
              title={`${b.label}: ${count} docs (${pct.toFixed(0)}%)`} />
          );
        })}
      </div>
      <div className="flex justify-between text-[9px] text-muted-foreground mt-0.5">
        {buckets.map(b => {
          const count = distribution[b.key] || 0;
          if (count === 0) return null;
          return <span key={b.key}>{b.label}: {count}</span>;
        })}
      </div>
    </div>
  );
}

function SignalRadar({ signals }) {
  if (!signals || !Object.keys(signals).length) return null;

  const items = [
    { key: 'vendor_resolution', label: 'Vendor', color: 'bg-blue-500' },
    { key: 'entity_resolution', label: 'Entity', color: 'bg-purple-500' },
    { key: 'extraction_quality', label: 'Extraction', color: 'bg-cyan-500' },
    { key: 'transaction_graph', label: 'Graph', color: 'bg-amber-500' },
    { key: 'policy_compliance', label: 'Policy', color: 'bg-emerald-500' },
  ];

  return (
    <div data-testid="signal-averages">
      <div className="text-xs font-semibold mb-1.5">Average Signal Strength</div>
      <div className="space-y-1">
        {items.map(item => {
          const val = signals[item.key] || 0;
          const pct = Math.round(val * 100);
          return (
            <div key={item.key} className="flex items-center gap-2 text-xs">
              <span className="w-[65px] text-muted-foreground truncate">{item.label}</span>
              <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
                <div className={`${item.color} h-full rounded-full`} style={{ width: `${pct}%` }} />
              </div>
              <span className="w-[28px] text-right text-[10px] font-medium">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function AutomationMetricsCard() {
  const [metrics, setMetrics] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const res = await fetch(`${API}/api/automation/metrics`);
        if (res.ok) setMetrics(await res.json());
      } catch (e) { console.error(e); }
      setLoading(false);
    };
    fetchMetrics();
  }, []);

  if (loading) {
    return (
      <Card className="border-2 border-indigo-500/30">
        <CardContent className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (!metrics || metrics.total_documents === 0) return null;

  const topReview = (metrics.top_review_causes || []).slice(0, 4);
  const topBlocking = (metrics.top_blocking_reasons || []).slice(0, 4);

  return (
    <Card className="border-2 border-indigo-500/30 bg-gradient-to-br from-indigo-500/5 to-transparent" data-testid="automation-metrics-card">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-indigo-400" />
            <CardTitle className="text-lg font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Automation Intelligence
            </CardTitle>
          </div>
          <div className="flex items-center gap-2">
            {metrics.avg_confidence > 0 && (
              <Badge variant="secondary" className="text-sm px-3 py-1" data-testid="avg-confidence-badge">
                Avg {Math.round(metrics.avg_confidence * 100)}%
              </Badge>
            )}
            <Badge variant="outline" className="text-xs" data-testid="scored-docs-badge">
              {metrics.scored_documents || 0} scored
            </Badge>
          </div>
        </div>
        <CardDescription>Weighted automation confidence across all documents</CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Rate gauges */}
        <div className="grid grid-cols-3 gap-3">
          <RateGauge label="Automation" value={metrics.automation_rate} icon={Zap} color="text-emerald-500" />
          <RateGauge label="Review" value={metrics.review_rate} icon={Eye} color="text-amber-500" />
          <RateGauge label="Blocked" value={metrics.blocked_rate} icon={Ban} color="text-red-500" />
        </div>

        {/* Confidence distribution */}
        <DistributionBar distribution={metrics.confidence_distribution} />

        {/* Signal averages */}
        <SignalRadar signals={metrics.signal_averages} />

        {/* Top causes */}
        <div className="grid grid-cols-2 gap-3">
          {topReview.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                <Eye className="w-3 h-3 text-amber-500" /> Top Review Causes
              </h4>
              <div className="space-y-0.5">
                {topReview.map(r => (
                  <div key={r.reason} className="flex items-center justify-between text-xs">
                    <span className="truncate text-muted-foreground">{r.reason.replace(/_/g, ' ')}</span>
                    <Badge variant="secondary" className="text-[10px] h-4 px-1.5">{r.count}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
          {topBlocking.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                <Ban className="w-3 h-3 text-red-500" /> Top Blockers
              </h4>
              <div className="space-y-0.5">
                {topBlocking.map(r => (
                  <div key={r.reason} className="flex items-center justify-between text-xs">
                    <span className="truncate text-muted-foreground">{r.reason.replace(/_/g, ' ')}</span>
                    <Badge variant="destructive" className="text-[10px] h-4 px-1.5">{r.count}</Badge>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
