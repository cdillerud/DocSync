/**
 * Reviewer Assist Panel — AI-powered one-click suggestions
 * Shows when a document needs_review, offering actionable suggestions
 * that can be accepted with a single click.
 */
import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import {
  Sparkles, Check, X, Loader2, User, Building2, Link2,
  FileText, Copy, AlertTriangle, ChevronDown, ChevronUp
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const ACTION_ICON = {
  confirm_vendor: Building2,
  resolve_vendor: Building2,
  confirm_customer: User,
  link_po: Link2,
  resolve_duplicate: Copy,
  correct_field: FileText,
};

const ACTION_LABEL = {
  confirm_vendor: 'Confirm Vendor',
  resolve_vendor: 'Resolve Vendor',
  confirm_customer: 'Confirm Customer',
  link_po: 'Link PO',
  resolve_duplicate: 'Resolve Duplicate',
  correct_field: 'Correct Field',
};

function ConfidenceDot({ confidence }) {
  const pct = Math.round((confidence || 0) * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-1">
      <div className={`w-1.5 h-1.5 rounded-full ${color}`} />
      <span className="text-[10px] text-muted-foreground">{pct}%</span>
    </div>
  );
}

export default function ReviewerAssistPanel({ document, onRefresh }) {
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [accepting, setAccepting] = useState(null);
  const [accepted, setAccepted] = useState(new Set());
  const [dismissed, setDismissed] = useState(new Set());
  const [expanded, setExpanded] = useState(true);

  const docId = document?.id;
  const readiness = document?.readiness || {};

  // Only show for documents that need review
  const showPanel = readiness.status === 'needs_review' ||
                    readiness.status === 'blocked' ||
                    readiness.status === 'ambiguous';

  const fetchSuggestions = async () => {
    if (!docId) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/documents/${docId}/review-assist`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setSuggestions(data.suggested_actions || []);
      }
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  useEffect(() => {
    if (showPanel && docId && suggestions.length === 0) {
      fetchSuggestions();
    }
  }, [docId, showPanel]);

  const handleAccept = async (suggestion, idx) => {
    setAccepting(idx);
    try {
      const res = await fetch(`${API}/api/documents/${docId}/accept-suggestion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: suggestion.action,
          field: suggestion.field,
          value: suggestion.suggested_value,
          accepted_by: 'reviewer',
        }),
      });
      if (res.ok) {
        setAccepted(prev => new Set([...prev, idx]));
        onRefresh?.();
      }
    } catch (e) { console.error(e); }
    setAccepting(null);
  };

  const handleDismiss = (idx) => {
    setDismissed(prev => new Set([...prev, idx]));
  };

  if (!showPanel || !docId) return null;

  const activeSuggestions = suggestions.filter((_, i) => !accepted.has(i) && !dismissed.has(i));
  const completedCount = accepted.size;

  return (
    <Card className="border-2 border-violet-500/30 bg-gradient-to-br from-violet-500/5 to-transparent" data-testid="reviewer-assist-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-violet-400" />
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Reviewer Assist
            </CardTitle>
            {suggestions.length > 0 && (
              <Badge variant="secondary" className="text-xs" data-testid="suggestion-count-badge">
                {activeSuggestions.length} suggestion{activeSuggestions.length !== 1 ? 's' : ''}
              </Badge>
            )}
            {completedCount > 0 && (
              <Badge className="bg-emerald-500/15 text-emerald-400 border-0 text-xs">
                {completedCount} applied
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1">
            <Button size="sm" variant="ghost" onClick={fetchSuggestions} disabled={loading} data-testid="refresh-suggestions-btn">
              {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => setExpanded(!expanded)}>
              {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </Button>
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="space-y-2 pt-0">
          {loading && suggestions.length === 0 && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
              <Loader2 className="w-4 h-4 animate-spin" /> Analyzing document...
            </div>
          )}

          {!loading && suggestions.length === 0 && (
            <p className="text-sm text-muted-foreground">No suggestions available for this document.</p>
          )}

          {activeSuggestions.map((s, displayIdx) => {
            const origIdx = suggestions.indexOf(s);
            const Icon = ACTION_ICON[s.action] || FileText;
            const label = ACTION_LABEL[s.action] || s.action;
            const isAccepting = accepting === origIdx;

            return (
              <div
                key={origIdx}
                className="flex items-start gap-2 p-2 rounded-lg bg-background/50 border border-border/50"
                data-testid={`suggestion-${s.action}-${origIdx}`}
              >
                <Icon className="w-4 h-4 text-violet-400 mt-0.5 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-semibold">{label}</span>
                    <ConfidenceDot confidence={s.confidence} />
                  </div>
                  {s.suggested_value && (
                    <p className="text-xs font-medium text-foreground mt-0.5 truncate" title={s.suggested_value}>
                      {s.suggested_value}
                    </p>
                  )}
                  <p className="text-[10px] text-muted-foreground leading-tight mt-0.5">{s.reason}</p>
                </div>
                <div className="flex gap-1 flex-shrink-0">
                  <Button
                    size="sm" variant="ghost"
                    className="h-7 w-7 p-0 text-emerald-500 hover:bg-emerald-500/10"
                    onClick={() => handleAccept(s, origIdx)}
                    disabled={isAccepting || !s.suggested_value}
                    data-testid={`accept-suggestion-${origIdx}`}
                    title="Accept suggestion"
                  >
                    {isAccepting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
                  </Button>
                  <Button
                    size="sm" variant="ghost"
                    className="h-7 w-7 p-0 text-muted-foreground hover:bg-red-500/10 hover:text-red-500"
                    onClick={() => handleDismiss(origIdx)}
                    data-testid={`dismiss-suggestion-${origIdx}`}
                    title="Dismiss"
                  >
                    <X className="w-3.5 h-3.5" />
                  </Button>
                </div>
              </div>
            );
          })}

          {/* Show accepted */}
          {accepted.size > 0 && (
            <div className="text-[10px] text-emerald-500/70 pt-1 border-t flex items-center gap-1">
              <Check className="w-3 h-3" />
              {accepted.size} suggestion{accepted.size !== 1 ? 's' : ''} applied — re-evaluate readiness to update status
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
