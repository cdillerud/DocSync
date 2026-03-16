/**
 * Decision Explainability Panel — "Why this decision?"
 * Shows structured explanation of automation decisions with confidence,
 * supporting evidence, and risk flags.
 */
import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Brain, ChevronDown, ChevronUp, CheckCircle2, AlertTriangle,
  XCircle, Shield, Lightbulb, Target, Loader2, Gauge
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const ACTION_STYLE = {
  auto_draft: { label: 'Auto Draft', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  auto_link: { label: 'Auto Link', color: 'text-blue-400', bg: 'bg-blue-500/15' },
  auto_execute: { label: 'Auto Execute', color: 'text-emerald-400', bg: 'bg-emerald-500/15' },
  assisted_review: { label: 'Assisted Review', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  review: { label: 'Manual Review', color: 'text-amber-400', bg: 'bg-amber-500/15' },
  hold: { label: 'Hold', color: 'text-red-400', bg: 'bg-red-500/15' },
  manual_review: { label: 'Manual Review', color: 'text-orange-400', bg: 'bg-orange-500/15' },
};

function ConfidenceBar({ score, thresholds }) {
  const pct = Math.round((score || 0) * 100);
  const autoThresh = (thresholds?.auto_execute || 0.9) * 100;
  const reviewThresh = (thresholds?.review || 0.7) * 100;

  let barColor = 'bg-red-500';
  if (pct >= autoThresh) barColor = 'bg-emerald-500';
  else if (pct >= reviewThresh) barColor = 'bg-amber-500';

  return (
    <div className="space-y-1" data-testid="confidence-bar">
      <div className="flex items-center justify-between text-xs text-muted-foreground">
        <span>Automation Confidence</span>
        <span className="font-bold text-sm text-foreground">{pct}%</span>
      </div>
      <div className="relative h-2.5 bg-muted/30 rounded-full overflow-hidden">
        <div className={`${barColor} h-full rounded-full transition-all duration-500`} style={{ width: `${pct}%` }} />
        {/* Threshold markers */}
        <div className="absolute top-0 h-full w-px bg-amber-400/60" style={{ left: `${reviewThresh}%` }} title={`Review: ${reviewThresh}%`} />
        <div className="absolute top-0 h-full w-px bg-emerald-400/60" style={{ left: `${autoThresh}%` }} title={`Auto: ${autoThresh}%`} />
      </div>
      <div className="flex justify-between text-[9px] text-muted-foreground">
        <span>Manual</span>
        <span style={{ marginLeft: `${reviewThresh - 10}%` }}>Review {reviewThresh}%</span>
        <span>Auto {autoThresh}%</span>
      </div>
    </div>
  );
}

function SignalBreakdown({ signals }) {
  if (!signals || !Object.keys(signals).length) return null;

  const SIGNAL_META = {
    vendor_resolution_score: { label: 'Vendor', weight: '25%' },
    entity_resolution_confidence: { label: 'Entity', weight: '20%' },
    extraction_confidence: { label: 'Extraction', weight: '20%' },
    transaction_graph_strength: { label: 'Graph', weight: '15%' },
    policy_pass_score: { label: 'Policy', weight: '10%' },
    duplicate_risk_penalty: { label: 'Dup Risk', weight: '-10%' },
  };

  return (
    <div className="space-y-1.5">
      {Object.entries(signals).map(([key, val]) => {
        const meta = SIGNAL_META[key] || { label: key, weight: '?' };
        const pct = Math.round(val * 100);
        const isDup = key === 'duplicate_risk_penalty';
        const barColor = isDup ? (pct > 0 ? 'bg-red-500' : 'bg-emerald-500') :
          pct >= 70 ? 'bg-emerald-500' : pct >= 40 ? 'bg-amber-500' : 'bg-red-500';

        return (
          <div key={key} className="flex items-center gap-2 text-xs" data-testid={`signal-${key}`}>
            <span className="w-[70px] text-muted-foreground truncate">{meta.label}</span>
            <span className="w-[32px] text-[10px] text-muted-foreground text-right">{meta.weight}</span>
            <div className="flex-1 h-1.5 bg-muted/30 rounded-full overflow-hidden">
              <div className={`${barColor} h-full rounded-full transition-all`} style={{ width: `${pct}%` }} />
            </div>
            <span className="w-[32px] text-right font-medium">{pct}%</span>
          </div>
        );
      })}
    </div>
  );
}

export default function DecisionExplainabilityPanel({ document, onRefresh }) {
  const [expanded, setExpanded] = useState(false);
  const [loading, setLoading] = useState(false);
  const [explanation, setExplanation] = useState(document?.decision_explanation || null);
  const [confidence, setConfidence] = useState(document?.automation_confidence || null);

  const docId = document?.id;

  useEffect(() => {
    setExplanation(document?.decision_explanation || null);
    setConfidence(document?.automation_confidence || null);
  }, [document]);

  const fetchExplanation = async () => {
    if (!docId) return;
    setLoading(true);
    try {
      const [expRes, confRes] = await Promise.all([
        fetch(`${API}/api/documents/${docId}/decision-explanation`),
        fetch(`${API}/api/documents/${docId}/automation-confidence`),
      ]);
      if (expRes.ok) setExplanation(await expRes.json());
      if (confRes.ok) setConfidence(await confRes.json());
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  if (!docId) return null;

  const action = explanation?.decision || explanation?.recommended_action || 'unknown';
  const actionStyle = ACTION_STYLE[action] || ACTION_STYLE.review;
  const evidence = explanation?.supporting_evidence || [];
  const risks = explanation?.risk_flags || [];
  const score = confidence?.score || explanation?.confidence || 0;

  return (
    <Card className="border-2 border-indigo-500/30 bg-gradient-to-br from-indigo-500/5 to-transparent" data-testid="decision-explainability-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="w-5 h-5 text-indigo-400" />
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Why this decision?
            </CardTitle>
            {explanation && (
              <Badge className={`${actionStyle.bg} ${actionStyle.color} border-0 text-xs`} data-testid="decision-action-badge">
                {actionStyle.label}
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            {!explanation && (
              <Button size="sm" variant="ghost" onClick={fetchExplanation} disabled={loading} data-testid="fetch-explanation-btn">
                {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Lightbulb className="w-3.5 h-3.5" />}
                <span className="ml-1 text-xs">Explain</span>
              </Button>
            )}
            {explanation && (
              <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)}>
                {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
              </Button>
            )}
          </div>
        </div>
      </CardHeader>

      {explanation && (
        <CardContent className="space-y-3 pt-0">
          {/* Confidence bar */}
          <ConfidenceBar score={score} thresholds={confidence?.thresholds} />

          {/* Evidence & Risks summary */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                <CheckCircle2 className="w-3 h-3 text-emerald-500" /> Evidence ({evidence.length})
              </h4>
              <div className="space-y-0.5">
                {evidence.slice(0, expanded ? 20 : 3).map((e, i) => (
                  <p key={i} className="text-[11px] text-muted-foreground leading-tight">+ {e}</p>
                ))}
                {!expanded && evidence.length > 3 && (
                  <button className="text-[10px] text-indigo-400 underline" onClick={() => setExpanded(true)}>
                    +{evidence.length - 3} more
                  </button>
                )}
              </div>
            </div>
            <div>
              <h4 className="text-xs font-semibold mb-1 flex items-center gap-1">
                <AlertTriangle className="w-3 h-3 text-amber-500" /> Risks ({risks.length})
              </h4>
              {risks.length > 0 ? (
                <div className="space-y-0.5">
                  {risks.slice(0, expanded ? 20 : 3).map((r, i) => (
                    <p key={i} className="text-[11px] text-red-400/80 leading-tight">! {r}</p>
                  ))}
                </div>
              ) : (
                <p className="text-[11px] text-emerald-500/70">No risk flags</p>
              )}
            </div>
          </div>

          {/* Expanded: Signal breakdown */}
          {expanded && confidence?.signals && (
            <div className="border-t pt-2">
              <h4 className="text-xs font-semibold mb-2 flex items-center gap-1">
                <Target className="w-3 h-3 text-indigo-400" /> Signal Breakdown
              </h4>
              <SignalBreakdown signals={confidence.signals} />
            </div>
          )}

          {/* Expanded: Boolean signals from readiness */}
          {expanded && explanation?.signals && Object.keys(explanation.signals).length > 0 && (
            <div className="border-t pt-2">
              <h4 className="text-xs font-semibold mb-1.5 flex items-center gap-1">
                <Shield className="w-3 h-3 text-indigo-400" /> Readiness Signals
              </h4>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(explanation.signals).map(([k, v]) => (
                  <Badge
                    key={k}
                    variant="outline"
                    className={`text-[10px] ${v ? 'border-emerald-500/40 text-emerald-400' : 'border-red-500/40 text-red-400'}`}
                  >
                    {v ? <CheckCircle2 className="w-2.5 h-2.5 mr-0.5" /> : <XCircle className="w-2.5 h-2.5 mr-0.5" />}
                    {k.replace(/_/g, ' ')}
                  </Badge>
                ))}
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
