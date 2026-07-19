import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  ScanSearch, RefreshCw, Loader2, CheckCircle2, HelpCircle, Building2, Info,
} from 'lucide-react';
import { getHumanDecisionQueue, bulkClassifyDocuments } from '@/lib/api';

// Documents needing a human decision, unified from Bucket A root-cause
// analysis and Meghan's team's manual folder-tag review into one feed.
// Square9's own answer to this is an unstructured "Miscellaneous"
// folder someone has to remember to check, with nothing learned once
// a decision is made - this surfaces exactly what needs attention, and
// every actionable item teaches the system the moment it's resolved
// (same /bulk-classify path that already feeds the classification and
// routing learning loops).

const ISSUE_TYPE_META = {
  isolated_misroute: { label: 'Wrong mailbox', icon: Building2, cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  ambiguous_classification: { label: 'Needs a type picked', icon: HelpCircle, cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  ambiguous_match: { label: 'Match unclear', icon: HelpCircle, cls: 'bg-muted text-muted-foreground border-border' },
  square9_side_issue: { label: 'Square9-side', icon: Info, cls: 'bg-muted text-muted-foreground border-border' },
};

const TAB_ORDER = ['all', 'isolated_misroute', 'ambiguous_classification', 'ambiguous_match', 'square9_side_issue'];

// Groups duplicate rows for the same underlying document (e.g. one
// Hub file flagged as a possible match against several different
// Square9 files) into a single card rather than repeating the same
// filename.
function groupItems(items) {
  const byKey = new Map();
  for (const it of items) {
    const key = `${it.doc_id}|${it.issue_type}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(it);
  }
  return [...byKey.values()];
}

export default function HumanDecisionQueuePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [resolvedKeys, setResolvedKeys] = useState(new Set());
  const [submittingKey, setSubmittingKey] = useState(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await getHumanDecisionQueue();
      setData(data);
    } catch (err) {
      toast.error('Failed to load the decision queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchQueue(); }, [fetchQueue]);

  const groups = useMemo(() => (data ? groupItems(data.items) : []), [data]);

  const visibleGroups = useMemo(() => {
    const filtered = activeTab === 'all' ? groups : groups.filter(g => g[0].issue_type === activeTab);
    return filtered.filter(g => !resolvedKeys.has(`${g[0].doc_id}|${g[0].issue_type}`));
  }, [groups, activeTab, resolvedKeys]);

  const tabCounts = useMemo(() => {
    const counts = { all: 0 };
    for (const g of groups) {
      const key = `${g[0].doc_id}|${g[0].issue_type}`;
      if (resolvedKeys.has(key)) continue;
      counts.all += 1;
      counts[g[0].issue_type] = (counts[g[0].issue_type] || 0) + 1;
    }
    return counts;
  }, [groups, resolvedKeys]);

  const handleDecision = async (group, docType, mailboxCategory) => {
    const primary = group[0];
    const key = `${primary.doc_id}|${primary.issue_type}`;
    setSubmittingKey(key);
    try {
      await bulkClassifyDocuments({
        docIds: [primary.doc_id],
        docType,
        mailboxCategory,
        reclassifyBy: 'human_decision_queue',
      });
      toast.success(`Confirmed \u2014 ${primary.file_name}`);
      setResolvedKeys(prev => new Set(prev).add(key));
    } catch (err) {
      toast.error(err.response?.data?.detail || 'That decision didn\u2019t save');
    } finally {
      setSubmittingKey(null);
    }
  };

  const actionableCount = data ? data.actionable_count : 0;
  const informationalCount = data ? data.informational_only_count : 0;
  const resolvedCount = resolvedKeys.size;

  return (
    <div className="space-y-6" data-testid="human-decision-queue-page">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <ScanSearch className="w-6 h-6 text-primary" />
          <div>
            <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Decision Queue
            </h1>
            <p className="text-xs text-muted-foreground mt-0.5">
              Documents the AI couldn&apos;t confidently place. Confirming here teaches the system, not just this one file.
            </p>
          </div>
        </div>
        <Button variant="outline" size="sm" onClick={fetchQueue} data-testid="refresh-decision-queue-btn">
          <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Refresh
        </Button>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Card className="border border-amber-500/30" data-testid="summary-actionable">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-amber-400 uppercase tracking-wider mb-1">Needs a decision</p>
            <p className="text-2xl font-bold text-amber-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {actionableCount}
            </p>
          </CardContent>
        </Card>
        <Card className="border border-border" data-testid="summary-informational">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-1">For awareness</p>
            <p className="text-2xl font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>{informationalCount}</p>
          </CardContent>
        </Card>
        <Card className="border border-emerald-500/30" data-testid="summary-resolved">
          <CardContent className="p-4 text-center">
            <p className="text-xs font-medium text-emerald-400 uppercase tracking-wider mb-1">Resolved this session</p>
            <p className="text-2xl font-bold text-emerald-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              {resolvedCount}
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="flex items-center gap-1 border-b border-border overflow-x-auto">
        {TAB_ORDER.filter(key => key === 'all' || tabCounts[key] > 0).map((key) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            data-testid={`decision-tab-${key}`}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
            }`}
          >
            {key === 'all' ? 'All' : ISSUE_TYPE_META[key].label} <span className="opacity-60">{tabCounts[key] || 0}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-16 text-muted-foreground">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> Loading...
        </div>
      ) : visibleGroups.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-muted-foreground">
          <CheckCircle2 className="w-10 h-10 mb-3 text-emerald-500/50" />
          <p className="text-sm font-medium">Nothing here</p>
          <p className="text-xs mt-1">Everything in this view has been resolved, or there&apos;s nothing of this kind right now.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {visibleGroups.map((group) => (
            <DecisionCard
              key={`${group[0].doc_id}|${group[0].issue_type}`}
              group={group}
              submitting={submittingKey === `${group[0].doc_id}|${group[0].issue_type}`}
              onDecide={handleDecision}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionCard({ group, submitting, onDecide }) {
  const primary = group[0];
  const meta = ISSUE_TYPE_META[primary.issue_type];
  const Icon = meta.icon;
  const isActionable = !!primary.submit_via;

  return (
    <Card className="border border-border" data-testid="decision-card">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-4 mb-2">
          <div>
            <Badge variant="outline" className={`text-[10px] font-semibold mb-1.5 ${meta.cls}`}>
              <Icon className="w-3 h-3 mr-1" /> {meta.label}
            </Badge>
            <p className="font-mono text-sm break-all">
              {primary.file_name}
              {group.length > 1 && (
                <span className="font-sans font-semibold text-amber-400 text-xs ml-2">
                  {`\u2014 ${group.length} possible Square9 matches`}
                </span>
              )}
            </p>
          </div>
        </div>

        <p className="text-sm mb-3">{primary.question}</p>

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground border-t border-border/60 pt-2 mb-3">
          {primary.context?.vendor_or_sender && (
            <span><span className="text-foreground font-medium">Vendor/sender</span> {primary.context.vendor_or_sender}</span>
          )}
          {primary.context?.square9_name && (
            <span className="font-mono">
              <span className="font-sans text-foreground font-medium">vs</span>{' '}
              {group.length > 1 ? group.map(g => g.context.square9_name).join(', ') : primary.context.square9_name}
            </span>
          )}
          {primary.ai_confidence != null && (
            <span><span className="text-foreground font-medium">AI confidence</span> {Math.round(primary.ai_confidence * 100)}%</span>
          )}
          {primary.context?.folder_label && (
            <span><span className="text-foreground font-medium">Tagged</span> &quot;{primary.context.folder_label}&quot;</span>
          )}
        </div>

        {isActionable ? (
          <div className="flex flex-wrap gap-2">
            {primary.issue_type === 'isolated_misroute' && (
              <Button
                size="sm"
                disabled={submitting}
                onClick={() => onDecide(group, primary.submit_hint.doc_type, primary.submit_hint.mailbox_category)}
                data-testid="decide-route-ap"
              >
                {submitting ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : null}
                Route to AP
              </Button>
            )}
            {primary.issue_type === 'ambiguous_classification' && primary.candidates?.map((c) => (
              <Button
                key={c}
                size="sm"
                variant="outline"
                disabled={submitting}
                onClick={() => onDecide(group, c, undefined)}
                data-testid={`decide-pick-${c}`}
              >
                {submitting ? <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" /> : null}
                {c.replace('_', ' ')}
              </Button>
            ))}
          </div>
        ) : (
          <p className="text-xs italic text-muted-foreground">{primary.note}</p>
        )}
      </CardContent>
    </Card>
  );
}
