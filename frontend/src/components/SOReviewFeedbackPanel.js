import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import {
  MessageSquare, ThumbsUp, ThumbsDown, AlertTriangle,
  ChevronDown, ChevronUp, Send, Loader2, CheckCircle2
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const ASSESSMENTS = [
  { value: 'correct', label: 'Correct', icon: ThumbsUp, color: 'text-emerald-600 bg-emerald-500/10 border-emerald-300 hover:bg-emerald-500/20' },
  { value: 'partially_correct', label: 'Partially', icon: AlertTriangle, color: 'text-amber-600 bg-amber-500/10 border-amber-300 hover:bg-amber-500/20' },
  { value: 'incorrect', label: 'Incorrect', icon: ThumbsDown, color: 'text-red-600 bg-red-500/10 border-red-300 hover:bg-red-500/20' },
  { value: 'helpful_but_not_decisive', label: 'Helpful', icon: MessageSquare, color: 'text-blue-600 bg-blue-500/10 border-blue-300 hover:bg-blue-500/20' },
  { value: 'not_helpful', label: 'Not Helpful', icon: ThumbsDown, color: 'text-muted-foreground bg-muted/50 border-border hover:bg-muted' },
];

const DISAGREED_OPTIONS = [
  'ship_to', 'amount_range', 'item_match', 'uom',
  'po_pattern', 'customer_profile_assumption', 'line_count',
  'readiness_status', 'confidence', 'other',
];

const DECISIONS = ['ready', 'needs_review', 'suspicious', 'incomplete'];

export default function SOReviewFeedbackPanel({ document }) {
  const [explainer, setExplainer] = useState(null);
  const [loadingExplainer, setLoadingExplainer] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [assessment, setAssessment] = useState('');
  const [decision, setDecision] = useState('');
  const [disagreed, setDisagreed] = useState([]);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [existingFeedback, setExistingFeedback] = useState(null);

  const docId = document?.id;
  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const isSalesType = ['Sales_Order', 'SalesOrder', 'SALES_ORDER', 'SALES_INVOICE', 'SalesInvoice'].includes(document?.document_type || document?.doc_type);

  const fetchExplainer = useCallback(async () => {
    if (!docId || !token) return;
    setLoadingExplainer(true);
    try {
      const res = await fetch(`${API}/api/documents/${docId}/sales-order-explainer`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setExplainer(data);
      }
    } catch { /* ignore */ }
    setLoadingExplainer(false);
  }, [docId, token]);

  const fetchFeedback = useCallback(async () => {
    if (!docId || !token) return;
    try {
      const res = await fetch(`${API}/api/documents/${docId}/sales-order-review-feedback`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        if (data.feedback?.length > 0) {
          setExistingFeedback(data.feedback[0]);
          setSubmitted(true);
        }
      }
    } catch { /* ignore */ }
  }, [docId, token]);

  useEffect(() => {
    if (isSalesType) {
      fetchExplainer();
      fetchFeedback();
    }
  }, [isSalesType, fetchExplainer, fetchFeedback]);

  if (!isSalesType) return null;

  const handleSubmit = async () => {
    if (!assessment) return;
    setSubmitting(true);
    try {
      const res = await fetch(`${API}/api/documents/${docId}/sales-order-review-feedback`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          reviewer_assessment: assessment,
          final_human_decision: decision || null,
          disagreed_fields: disagreed.length ? disagreed : null,
          notes: notes || null,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        setExistingFeedback(data);
        setSubmitted(true);
      }
    } catch { /* ignore */ }
    setSubmitting(false);
  };

  const toggleDisagreed = (field) => {
    setDisagreed(prev => prev.includes(field) ? prev.filter(f => f !== field) : [...prev, field]);
  };

  const statusColor = {
    ready: 'bg-emerald-500/10 text-emerald-600 border-emerald-300',
    needs_review: 'bg-amber-500/10 text-amber-600 border-amber-300',
    suspicious: 'bg-red-500/10 text-red-600 border-red-300',
    incomplete: 'bg-orange-500/10 text-orange-600 border-orange-300',
  };

  return (
    <Card data-testid="so-review-feedback-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-muted-foreground" />
            AI Advisory Review
            {explainer?.readiness_status && (
              <Badge variant="outline" className={`text-[10px] ${statusColor[explainer.readiness_status] || ''}`} data-testid="so-explainer-status">
                {explainer.readiness_status}
              </Badge>
            )}
            {explainer?.reviewer_confidence > 0 && (
              <span className="text-[10px] text-muted-foreground font-mono" data-testid="so-explainer-confidence">
                {Math.round(explainer.reviewer_confidence * 100)}%
              </span>
            )}
          </CardTitle>
          <Button
            size="sm" variant="ghost" className="h-6 text-xs px-2"
            onClick={() => setExpanded(!expanded)}
            data-testid="so-feedback-toggle"
          >
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </CardHeader>

      {/* Collapsed: show headline only */}
      {!expanded && explainer && (
        <CardContent className="pt-0 pb-3">
          <p className="text-xs text-muted-foreground" data-testid="so-explainer-headline">{explainer.headline}</p>
          {submitted && existingFeedback && (
            <div className="flex items-center gap-1.5 mt-1.5">
              <CheckCircle2 className="w-3 h-3 text-emerald-500" />
              <span className="text-[10px] text-emerald-600">Feedback submitted: {existingFeedback.reviewer_assessment || existingFeedback.assessment}</span>
            </div>
          )}
        </CardContent>
      )}

      {/* Expanded: full explainer + feedback form */}
      {expanded && (
        <CardContent className="pt-0 space-y-3">
          {loadingExplainer && (
            <div className="flex items-center gap-2 py-2">
              <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
              <span className="text-xs text-muted-foreground">Loading advisory review...</span>
            </div>
          )}

          {explainer && (
            <div className="space-y-2" data-testid="so-explainer-detail">
              <p className="text-sm font-medium">{explainer.headline}</p>
              <p className="text-xs text-muted-foreground">{explainer.plain_english_summary}</p>

              {explainer.why_it_was_flagged?.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-red-600 mb-0.5">Flagged:</p>
                  {explainer.why_it_was_flagged.map((f, i) => (
                    <p key={i} className="text-[11px] text-red-600/80 pl-2">- {f}</p>
                  ))}
                </div>
              )}

              {explainer.what_looks_normal?.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-emerald-600 mb-0.5">Normal:</p>
                  {explainer.what_looks_normal.map((n, i) => (
                    <p key={i} className="text-[11px] text-emerald-600/80 pl-2">- {n}</p>
                  ))}
                </div>
              )}

              {explainer.recommended_next_steps?.length > 0 && (
                <div>
                  <p className="text-[10px] font-semibold text-blue-600 mb-0.5">Next steps:</p>
                  {explainer.recommended_next_steps.map((s, i) => (
                    <p key={i} className="text-[11px] text-blue-600/80 pl-2">- {s}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {!explainer && !loadingExplainer && (
            <p className="text-xs text-muted-foreground py-2">No advisory review available for this document.</p>
          )}

          {/* Feedback form */}
          <div className="border-t border-border/40 pt-3 space-y-2" data-testid="so-feedback-form">
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">Your Feedback</p>

            {submitted && existingFeedback ? (
              <div className="flex items-center gap-2 py-1">
                <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                <span className="text-xs text-emerald-600">
                  Feedback recorded: <strong>{existingFeedback.reviewer_assessment || existingFeedback.assessment}</strong>
                  {(existingFeedback.final_human_decision || existingFeedback.decision) && (
                    <> — decision: <strong>{existingFeedback.final_human_decision || existingFeedback.decision}</strong></>
                  )}
                </span>
              </div>
            ) : (
              <>
                {/* Assessment buttons */}
                <div className="flex flex-wrap gap-1.5" data-testid="so-feedback-assessments">
                  {ASSESSMENTS.map(a => {
                    const Icon = a.icon;
                    const selected = assessment === a.value;
                    return (
                      <button
                        key={a.value}
                        onClick={() => setAssessment(a.value)}
                        className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] transition-colors ${selected ? a.color + ' ring-1 ring-offset-1' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                        data-testid={`so-feedback-${a.value}`}
                      >
                        <Icon className="w-3 h-3" />
                        {a.label}
                      </button>
                    );
                  })}
                </div>

                {/* Decision override */}
                {assessment && (
                  <div>
                    <p className="text-[10px] text-muted-foreground mb-1">Your decision (optional):</p>
                    <div className="flex gap-1.5" data-testid="so-feedback-decisions">
                      {DECISIONS.map(d => (
                        <button
                          key={d}
                          onClick={() => setDecision(prev => prev === d ? '' : d)}
                          className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${decision === d ? 'bg-primary/10 text-primary border-primary/30' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                          data-testid={`so-feedback-decision-${d}`}
                        >
                          {d.replace('_', ' ')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Disagreed fields */}
                {assessment && assessment !== 'correct' && (
                  <div>
                    <p className="text-[10px] text-muted-foreground mb-1">Disagreed with (optional):</p>
                    <div className="flex flex-wrap gap-1" data-testid="so-feedback-disagreed">
                      {DISAGREED_OPTIONS.map(f => (
                        <button
                          key={f}
                          onClick={() => toggleDisagreed(f)}
                          className={`px-1.5 py-0.5 rounded text-[9px] border transition-colors ${disagreed.includes(f) ? 'bg-red-500/10 text-red-600 border-red-300' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                          data-testid={`so-feedback-field-${f}`}
                        >
                          {f.replace(/_/g, ' ')}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {/* Notes */}
                {assessment && (
                  <textarea
                    value={notes}
                    onChange={e => setNotes(e.target.value)}
                    placeholder="Optional notes..."
                    className="w-full text-xs p-2 rounded-md border border-border bg-background resize-none h-14"
                    data-testid="so-feedback-notes"
                  />
                )}

                {/* Submit */}
                {assessment && (
                  <Button
                    size="sm" className="h-7 text-xs"
                    onClick={handleSubmit}
                    disabled={submitting}
                    data-testid="so-feedback-submit"
                  >
                    {submitting ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Send className="w-3 h-3 mr-1" />}
                    Submit Feedback
                  </Button>
                )}
              </>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}
