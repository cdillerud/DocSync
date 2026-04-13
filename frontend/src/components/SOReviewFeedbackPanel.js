import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { ScrollArea } from './ui/scroll-area';
import {
  MessageSquare, ThumbsUp, ThumbsDown, AlertTriangle, Shield,
  ChevronDown, ChevronUp, Send, Loader2, CheckCircle2, XCircle,
  Eye, UserCheck, Zap, Clock
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const ASSESSMENTS = [
  { value: 'correct', label: 'Correct', icon: ThumbsUp, color: 'text-emerald-600 bg-emerald-500/10 border-emerald-300 hover:bg-emerald-500/20' },
  { value: 'partially_correct', label: 'Partially', icon: AlertTriangle, color: 'text-amber-600 bg-amber-500/10 border-amber-300 hover:bg-amber-500/20' },
  { value: 'incorrect', label: 'Incorrect', icon: ThumbsDown, color: 'text-red-600 bg-red-500/10 border-red-300 hover:bg-red-500/20' },
  { value: 'helpful_but_not_decisive', label: 'Helpful', icon: MessageSquare, color: 'text-blue-600 bg-blue-500/10 border-blue-300 hover:bg-blue-500/20' },
  { value: 'not_helpful', label: 'Not Helpful', icon: ThumbsDown, color: 'text-muted-foreground bg-muted/50 border-border hover:bg-muted' },
];

const DECISIONS = ['ready', 'needs_review', 'suspicious', 'incomplete'];

const DISAGREED_OPTIONS = [
  'ship_to', 'amount_range', 'item_match', 'uom',
  'po_pattern', 'customer_profile_assumption', 'line_count',
  'readiness_status', 'confidence', 'other',
];

const STATUS_CONFIG = {
  ready:        { icon: CheckCircle2, color: 'text-emerald-600', bg: 'bg-emerald-500/10 border-emerald-300', label: 'Ready' },
  needs_review: { icon: Eye,          color: 'text-amber-600',   bg: 'bg-amber-500/10 border-amber-300',   label: 'Needs Review' },
  suspicious:   { icon: Shield,       color: 'text-red-600',     bg: 'bg-red-500/10 border-red-300',       label: 'Suspicious' },
  incomplete:   { icon: XCircle,      color: 'text-orange-600',  bg: 'bg-orange-500/10 border-orange-300', label: 'Incomplete' },
};

export default function SOReviewFeedbackPanel({ document }) {
  const [advisory, setAdvisory] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [showFeedbackForm, setShowFeedbackForm] = useState(false);
  const [assessment, setAssessment] = useState('');
  const [decision, setDecision] = useState('');
  const [disagreed, setDisagreed] = useState([]);
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const docId = document?.id;
  const token = typeof window !== 'undefined' ? localStorage.getItem('gpi_token') : null;
  const isSalesType = ['Sales_Order', 'SalesOrder', 'SALES_ORDER', 'SALES_INVOICE', 'SalesInvoice'].includes(document?.document_type || document?.doc_type);

  const fetchAdvisory = useCallback(async () => {
    if (!docId || !token) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/documents/${docId}/sales-order-advisory`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) setAdvisory(await res.json());
    } catch { /* ignore */ }
    setLoading(false);
  }, [docId, token]);

  useEffect(() => {
    if (isSalesType) fetchAdvisory();
  }, [isSalesType, fetchAdvisory]);

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
        setShowFeedbackForm(false);
        fetchAdvisory(); // refresh to show new feedback
      }
    } catch { /* ignore */ }
    setSubmitting(false);
  };

  const ex = advisory?.explainer || {};
  const review = advisory?.review || {};
  const profile = advisory?.customer_profile;
  const feedback = advisory?.feedback || [];
  const latestFb = feedback[0];
  const statusCfg = STATUS_CONFIG[ex.readiness_status || review?.readiness_status] || STATUS_CONFIG.needs_review;
  const StatusIcon = statusCfg.icon;
  const confidence = ex.reviewer_confidence || review?.confidence || 0;

  return (
    <Card data-testid="so-advisory-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Zap className="w-4 h-4 text-muted-foreground" />
            <span>SO Advisory</span>
            {!loading && advisory?.has_review && (
              <>
                <Badge variant="outline" className={`text-[10px] ${statusCfg.bg}`} data-testid="advisory-status">
                  <StatusIcon className="w-3 h-3 mr-0.5" />
                  {statusCfg.label}
                </Badge>
                {confidence > 0 && (
                  <span className={`text-[10px] font-mono ${statusCfg.color}`} data-testid="advisory-confidence">
                    {Math.round(confidence * 100)}%
                  </span>
                )}
              </>
            )}
            {!loading && !advisory?.has_review && (
              <Badge variant="outline" className="text-[10px] text-muted-foreground">No Review</Badge>
            )}
            {latestFb && (
              <Badge variant="outline" className="text-[10px] text-blue-600 border-blue-300" data-testid="advisory-feedback-badge">
                <UserCheck className="w-3 h-3 mr-0.5" />
                {latestFb.reviewer_assessment}
              </Badge>
            )}
          </CardTitle>
          <Button size="sm" variant="ghost" className="h-6 px-2" onClick={() => setExpanded(!expanded)} data-testid="advisory-toggle">
            {expanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </Button>
        </div>
      </CardHeader>

      {/* Collapsed summary */}
      {!expanded && !loading && (
        <CardContent className="pt-0 pb-3">
          <p className="text-xs text-muted-foreground" data-testid="advisory-headline">
            {ex.headline || (advisory?.has_review ? review?.readiness_status : 'No advisory review available')}
          </p>
        </CardContent>
      )}

      {/* Loading */}
      {loading && (
        <CardContent className="pt-0 pb-3">
          <div className="flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin text-muted-foreground" /><span className="text-xs text-muted-foreground">Loading advisory...</span></div>
        </CardContent>
      )}

      {/* Expanded */}
      {expanded && !loading && (
        <CardContent className="pt-0 space-y-3">
          {/* Summary */}
          {ex.plain_english_summary && (
            <p className="text-xs leading-relaxed" data-testid="advisory-summary">{ex.plain_english_summary}</p>
          )}

          {/* Status cards row */}
          <div className="grid grid-cols-4 gap-2">
            <MiniStat label="Blocking" count={(review?.blocking_issues || ex.why_it_was_flagged || []).length} color="text-red-600" />
            <MiniStat label="Warnings" count={(review?.warnings || []).length} color="text-amber-600" />
            <MiniStat label="Unusual" count={(review?.unusual_patterns || []).length} color="text-orange-600" />
            <MiniStat label="Matches" count={(review?.profile_matches || ex.what_looks_normal || []).length} color="text-emerald-600" />
          </div>

          {/* Blocking issues */}
          <DetailSection
            items={review?.blocking_issues || []}
            label="Blocking Issues"
            color="text-red-600"
            icon={XCircle}
            testId="advisory-blocking"
          />

          {/* Warnings */}
          <DetailSection
            items={review?.warnings || []}
            label="Warnings"
            color="text-amber-600"
            icon={AlertTriangle}
            testId="advisory-warnings"
          />

          {/* Unusual patterns */}
          <DetailSection
            items={review?.unusual_patterns || []}
            label="Unusual Patterns"
            color="text-orange-600"
            icon={Shield}
            testId="advisory-unusual"
          />

          {/* What looks normal */}
          <DetailSection
            items={ex.what_looks_normal || []}
            label="Matches History"
            color="text-emerald-600"
            icon={CheckCircle2}
            testId="advisory-matches"
          />

          {/* Next steps */}
          {(ex.recommended_next_steps || []).length > 0 && (
            <div data-testid="advisory-nextsteps">
              <p className="text-[10px] font-semibold text-blue-600 mb-0.5">Next Steps</p>
              {ex.recommended_next_steps.map((s, i) => (
                <p key={i} className="text-[11px] text-blue-600/80 pl-2">- {s}</p>
              ))}
            </div>
          )}

          {/* Customer profile context */}
          {profile && (
            <div className="border-t border-border/40 pt-2" data-testid="advisory-profile">
              <p className="text-[10px] font-semibold text-muted-foreground mb-1">Customer Profile</p>
              <div className="flex flex-wrap gap-x-4 gap-y-0.5 text-[10px] text-muted-foreground">
                <span>
                  <span className="font-mono font-semibold text-foreground">{profile.customer_no}</span> {profile.customer_name}
                </span>
                <span>Confidence: <strong>{profile.template_confidence}</strong></span>
                <span>{profile.invoices_analyzed} orders analyzed</span>
                <span>Avg: ${profile.typical_order_value?.toLocaleString()}</span>
                <span>{profile.common_items_count} known items</span>
              </div>
            </div>
          )}
          {advisory && !profile && (
            <div className="border-t border-border/40 pt-2">
              <p className="text-[10px] text-muted-foreground italic">No customer posting profile available</p>
            </div>
          )}

          {/* Feedback section */}
          <div className="border-t border-border/40 pt-2" data-testid="advisory-feedback-section">
            {latestFb && !showFeedbackForm ? (
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <UserCheck className="w-3.5 h-3.5 text-blue-500" />
                  <span className="text-xs">
                    <strong>{latestFb.reviewer_user_id}</strong> assessed as{' '}
                    <Badge variant="outline" className="text-[9px] mx-0.5">{latestFb.reviewer_assessment}</Badge>
                    {latestFb.final_human_decision && (
                      <> decision: <Badge variant="outline" className="text-[9px]">{latestFb.final_human_decision}</Badge></>
                    )}
                  </span>
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-[9px] text-muted-foreground">
                    <Clock className="w-3 h-3 inline mr-0.5" />
                    {latestFb.timestamp ? new Date(latestFb.timestamp).toLocaleDateString() : ''}
                  </span>
                  <Button size="sm" variant="ghost" className="h-5 text-[10px] px-1.5" onClick={() => setShowFeedbackForm(true)} data-testid="advisory-edit-feedback">
                    Update
                  </Button>
                </div>
              </div>
            ) : (
              <>
                <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">
                  {latestFb ? 'Update Feedback' : 'Your Feedback'}
                </p>

                {/* Assessment buttons */}
                <div className="flex flex-wrap gap-1.5 mb-2" data-testid="advisory-assessments">
                  {ASSESSMENTS.map(a => {
                    const Icon = a.icon;
                    const sel = assessment === a.value;
                    return (
                      <button
                        key={a.value}
                        onClick={() => setAssessment(a.value)}
                        className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] transition-colors ${sel ? a.color + ' ring-1 ring-offset-1' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                        data-testid={`advisory-fb-${a.value}`}
                      >
                        <Icon className="w-3 h-3" />{a.label}
                      </button>
                    );
                  })}
                </div>

                {assessment && (
                  <>
                    {/* Decision */}
                    <div className="mb-2">
                      <p className="text-[10px] text-muted-foreground mb-1">Your decision (optional):</p>
                      <div className="flex gap-1.5">
                        {DECISIONS.map(d => (
                          <button key={d} onClick={() => setDecision(p => p === d ? '' : d)}
                            className={`px-2 py-0.5 rounded text-[10px] border transition-colors ${decision === d ? 'bg-primary/10 text-primary border-primary/30' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                            data-testid={`advisory-fb-dec-${d}`}
                          >{d.replace('_', ' ')}</button>
                        ))}
                      </div>
                    </div>

                    {/* Disagreed fields (only if not "correct") */}
                    {assessment !== 'correct' && (
                      <div className="mb-2">
                        <p className="text-[10px] text-muted-foreground mb-1">Disagreed with (optional):</p>
                        <div className="flex flex-wrap gap-1">
                          {DISAGREED_OPTIONS.map(f => (
                            <button key={f}
                              onClick={() => setDisagreed(p => p.includes(f) ? p.filter(x => x !== f) : [...p, f])}
                              className={`px-1.5 py-0.5 rounded text-[9px] border transition-colors ${disagreed.includes(f) ? 'bg-red-500/10 text-red-600 border-red-300' : 'border-border text-muted-foreground hover:bg-muted/50'}`}
                              data-testid={`advisory-fb-field-${f}`}
                            >{f.replace(/_/g, ' ')}</button>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Notes */}
                    <textarea value={notes} onChange={e => setNotes(e.target.value)}
                      placeholder="Optional notes..." className="w-full text-xs p-2 rounded-md border border-border bg-background resize-none h-12 mb-2"
                      data-testid="advisory-fb-notes" />

                    {/* Submit */}
                    <div className="flex items-center gap-2">
                      <Button size="sm" className="h-7 text-xs" onClick={handleSubmit} disabled={submitting} data-testid="advisory-fb-submit">
                        {submitting ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Send className="w-3 h-3 mr-1" />}
                        Submit
                      </Button>
                      {showFeedbackForm && latestFb && (
                        <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => setShowFeedbackForm(false)}>Cancel</Button>
                      )}
                    </div>
                  </>
                )}
              </>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

function MiniStat({ label, count, color }) {
  return (
    <div className="text-center py-1.5 rounded-md bg-muted/30">
      <p className={`text-sm font-bold ${count > 0 ? color : 'text-muted-foreground'}`}>{count}</p>
      <p className="text-[9px] text-muted-foreground">{label}</p>
    </div>
  );
}

function DetailSection({ items, label, color, icon: Icon, testId }) {
  if (!items || items.length === 0) return null;
  return (
    <div data-testid={testId}>
      <p className={`text-[10px] font-semibold ${color} mb-0.5`}>{label}</p>
      <ScrollArea className="max-h-[80px]">
        {items.map((item, i) => (
          <div key={i} className="flex items-start gap-1.5 py-0.5">
            <Icon className={`w-3 h-3 ${color} shrink-0 mt-0.5`} />
            <p className={`text-[11px] ${color}/80`}>{item}</p>
          </div>
        ))}
      </ScrollArea>
    </div>
  );
}
