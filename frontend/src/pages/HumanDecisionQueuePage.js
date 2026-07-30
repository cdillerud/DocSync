import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  ScanSearch,
  RefreshCw,
  Loader2,
  CheckCircle2,
  HelpCircle,
  Building2,
  Info,
  Eye,
  EyeOff,
  ExternalLink,
  FileWarning,
  FolderOpen,
  Ban,
} from 'lucide-react';
import api, {
  getHumanDecisionQueue,
  bulkClassifyDocuments,
  confirmCurrentDecision,
  disposeNonTransactionalDocument,
} from '@/lib/api';
import HumanRoutingBrowserDialog from '@/components/HumanRoutingBrowserDialog';
import NonTransactionalDispositionDialog from '@/components/NonTransactionalDispositionDialog';
import DecisionQueueClassificationDialog from '@/components/DecisionQueueClassificationDialog';

const ISSUE_TYPE_META = {
  isolated_misroute: { label: 'Wrong mailbox', icon: Building2, cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  ambiguous_classification: { label: 'Needs a type picked', icon: HelpCircle, cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  ambiguous_match: { label: 'Match unclear', icon: HelpCircle, cls: 'bg-muted text-muted-foreground border-border' },
  square9_side_issue: { label: 'Square9-side', icon: Info, cls: 'bg-muted text-muted-foreground border-border' },
};

const TAB_ORDER = ['all', 'isolated_misroute', 'ambiguous_classification', 'ambiguous_match', 'square9_side_issue'];

function groupItems(items) {
  const byKey = new Map();
  for (const item of items) {
    const key = `${item.doc_id}|${item.issue_type}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(item);
  }
  return [...byKey.values()];
}

function previewKind(contentType, fileName) {
  const type = (contentType || '').toLowerCase();
  const extension = (fileName || '').split('.').pop()?.toLowerCase();

  if (type.includes('pdf') || extension === 'pdf') return 'pdf';

  const browserImageExtensions = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'svg']);
  if (
    (type.startsWith('image/') && !type.includes('tiff')) ||
    browserImageExtensions.has(extension)
  ) {
    return 'image';
  }

  return 'download';
}

async function previewErrorMessage(error) {
  const responseData = error.response?.data;

  if (responseData instanceof Blob) {
    try {
      const text = await responseData.text();
      const parsed = JSON.parse(text);
      return parsed.detail || parsed.message || 'The document could not be loaded.';
    } catch {
      // Fall through to the normal Axios error fields.
    }
  }

  return (
    responseData?.detail ||
    responseData?.message ||
    error.message ||
    'The document could not be loaded.'
  );
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
      const { data: queueData } = await getHumanDecisionQueue();
      setData(queueData);
    } catch (error) {
      toast.error('Failed to load the decision queue');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchQueue();
  }, [fetchQueue]);

  const groups = useMemo(() => (data ? groupItems(data.items) : []), [data]);

  const visibleGroups = useMemo(() => {
    const filtered = activeTab === 'all'
      ? groups
      : groups.filter(group => group[0].issue_type === activeTab);
    return filtered.filter(group => !resolvedKeys.has(`${group[0].doc_id}|${group[0].issue_type}`));
  }, [groups, activeTab, resolvedKeys]);

  const tabCounts = useMemo(() => {
    const counts = { all: 0 };
    for (const group of groups) {
      const key = `${group[0].doc_id}|${group[0].issue_type}`;
      if (resolvedKeys.has(key)) continue;
      counts.all += 1;
      counts[group[0].issue_type] = (counts[group[0].issue_type] || 0) + 1;
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

      await confirmCurrentDecision(
        primary.doc_id,
        primary.issue_type,
        'human_decision_queue',
        'Document state corrected from the Decision Queue',
        'corrected_state'
      );

      toast.success(
        `Saved and resolved — ${primary.file_name}`
      );
      setResolvedKeys(previous => new Set(previous).add(key));
      return true;
    } catch (error) {
      toast.error(error.response?.data?.detail || 'That decision didn’t save');
      return false;
    } finally {
      setSubmittingKey(null);
    }
  };

  const handleConfirmCurrent = async (
    group,
    resolution = 'confirmed_current',
    notes = ''
  ) => {
    const primary = group[0];
    const key =
      `${primary.doc_id}|${primary.issue_type}`;

    const successMessages = {
      confirmed_current:
        `Current type and lane confirmed — ${primary.file_name}`,
      acknowledged:
        `Issue acknowledged — ${primary.file_name}`,
      same_document:
        `Recorded as the same document — ${primary.file_name}`,
      different_document:
        `Recorded as a different document — ${primary.file_name}`,
      unable_to_determine:
        `Recorded as unable to determine — ${primary.file_name}`,
    };

    setSubmittingKey(key);

    try {
      await confirmCurrentDecision(
        primary.doc_id,
        primary.issue_type,
        'human_decision_queue',
        notes,
        resolution
      );

      toast.success(
        successMessages[resolution] ||
        `Issue resolved — ${primary.file_name}`
      );

      setResolvedKeys(previous => {
        const next = new Set(previous);
        next.add(key);
        return next;
      });

      return true;
    } catch (error) {
      toast.error(
        error.response?.data?.detail ||
        'The queue issue could not be resolved'
      );

      return false;
    } finally {
      setSubmittingKey(null);
    }
  };

  const handleDiscard = async (
    group,
    reason,
    notes
  ) => {
    const primary = group[0];
    const key =
      `${primary.doc_id}|${primary.issue_type}`;

    setSubmittingKey(key);

    try {
      const { data: result } =
        await disposeNonTransactionalDocument(
          primary.doc_id,
          reason.value,
          'human_decision_queue',
          notes
        );

      toast.success(
        result?.learning_recorded
          ? `${reason.label} — excluded; AI learning recorded`
          : `${reason.label} — excluded from processing`
      );

      setResolvedKeys(previous => {
        const next = new Set(previous);
        next.add(key);
        return next;
      });

      return true;
    } catch (error) {
      toast.error(
        error.response?.data?.detail ||
        'The document could not be excluded'
      );

      return false;
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
              Review the document, correct its type or mailbox, and browse the actual SharePoint destination folders. Every routing decision becomes reusable AI guidance.
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
        {TAB_ORDER.filter(key => key === 'all' || tabCounts[key] > 0).map(key => (
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
            {key === 'all' ? 'All' : ISSUE_TYPE_META[key].label}{' '}
            <span className="opacity-60">{tabCounts[key] || 0}</span>
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
          {visibleGroups.map(group => (
            <DecisionCard
              key={`${group[0].doc_id}|${group[0].issue_type}`}
              group={group}
              submitting={submittingKey === `${group[0].doc_id}|${group[0].issue_type}`}
              onDecide={handleDecision}
              onConfirmCurrent={handleConfirmCurrent}
              onDiscard={handleDiscard}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionCard({
  group,
  submitting,
  onDecide,
  onConfirmCurrent,
  onDiscard,
}) {
  const primary = group[0];
  const meta = ISSUE_TYPE_META[primary.issue_type];
  const Icon = meta.icon;
  const isActionable = Boolean(primary.submit_via);

  const currentDocType =
    primary.current_state?.doc_type || '';

  const currentMailboxCategory =
    primary.current_state?.mailbox_category || '';

  const currentSourceMailbox =
    primary.current_state?.source_mailbox || '';

  const confirmableIssue = [
    'isolated_misroute',
    'ambiguous_classification',
  ].includes(primary.issue_type);

  const acknowledgeableIssue =
    primary.issue_type === 'square9_side_issue';

  const ambiguousMatchIssue =
    primary.issue_type === 'ambiguous_match';

  const confidenceLabel =
    primary.source === 'bucket_A_root_cause'
      ? 'Match confidence'
      : 'AI confidence';

  const validCurrentType =
    Boolean(currentDocType) &&
    ![
      'Unknown',
      'Unknown_Document',
      'OTHER',
    ].includes(currentDocType);

  const canConfirmCurrent =
    confirmableIssue && validCurrentType;

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewContentType, setPreviewContentType] = useState('');
  const [previewError, setPreviewError] = useState('');
  const [routingOpen, setRoutingOpen] = useState(false);
  const [dispositionOpen, setDispositionOpen] = useState(false);
  const [classificationOpen, setClassificationOpen] = useState(false);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    };
  }, [previewUrl]);

  const loadDocument = useCallback(async () => {
    if (previewUrl) return previewUrl;

    setPreviewLoading(true);
    setPreviewError('');

    try {
      const response = await api.get(
        `/documents/${encodeURIComponent(primary.doc_id)}/file`,
        { responseType: 'blob' }
      );
      const contentType =
        response.headers?.['content-type'] ||
        response.data?.type ||
        'application/octet-stream';
      const blob = response.data instanceof Blob
        ? response.data
        : new Blob([response.data], { type: contentType });
      const objectUrl = URL.createObjectURL(blob);

      setPreviewContentType(contentType);
      setPreviewUrl(objectUrl);
      return objectUrl;
    } catch (error) {
      const message = await previewErrorMessage(error);
      setPreviewError(message);
      toast.error(message);
      return '';
    } finally {
      setPreviewLoading(false);
    }
  }, [previewUrl, primary.doc_id]);

  const handlePreviewToggle = async () => {
    if (previewOpen) {
      setPreviewOpen(false);
      return;
    }

    setPreviewOpen(true);
    await loadDocument();
  };

  const handleOpenInNewTab = async () => {
    let popup = null;
    try {
      popup = window.open('about:blank', '_blank');
      if (popup) {
        popup.opener = null;
        popup.document.title = 'Loading document...';
        popup.document.body.textContent = 'Loading document...';
      }
    } catch {
      popup = null;
    }

    const objectUrl = await loadDocument();

    if (objectUrl && popup) {
      popup.location.replace(objectUrl);
    } else if (objectUrl) {
      window.open(objectUrl, '_blank', 'noopener,noreferrer');
    } else if (popup) {
      popup.close();
    }
  };

  const kind = previewKind(previewContentType, primary.file_name);

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
                  {`— ${group.length} possible Square9 matches`}
                </span>
              )}
            </p>
          </div>
        </div>

        <p className="text-sm mb-3">{primary.question}</p>

        <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground border-t border-border/60 pt-2 mb-3">
          <span>
            <span className="text-foreground font-medium">
              Document type
            </span>{' '}
            {currentDocType || 'Not set'}
          </span>

          <span>
            <span className="text-foreground font-medium">
              Source mailbox
            </span>{' '}
            {currentSourceMailbox || 'Not recorded'}
          </span>

          <span>
            <span className="text-foreground font-medium">
              Current lane
            </span>{' '}
            {currentMailboxCategory || 'Not set'}
          </span>

          {primary.context?.vendor_or_sender && (
            <span><span className="text-foreground font-medium">Vendor/sender</span> {primary.context.vendor_or_sender}</span>
          )}
          {primary.context?.square9_name && (
            <span className="font-mono">
              <span className="font-sans text-foreground font-medium">vs</span>{' '}
              {group.length > 1
                ? group.map(item => item.context.square9_name).join(', ')
                : primary.context.square9_name}
            </span>
          )}
          {primary.ai_confidence != null && (
            <span
              title={
                primary.source === 'bucket_A_root_cause'
                  ? 'Confidence that this Hub document matches the referenced Square9 file'
                  : undefined
              }
            >
              <span className="text-foreground font-medium">
                {confidenceLabel}
              </span>{' '}
              {Math.round(primary.ai_confidence * 100)}%
            </span>
          )}
          {primary.context?.folder_label && (
            <span><span className="text-foreground font-medium">Tagged</span> &quot;{primary.context.folder_label}&quot;</span>
          )}
        </div>

        <div className="flex flex-wrap gap-2 mb-3">
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handlePreviewToggle}
            disabled={previewLoading}
            data-testid={`toggle-document-preview-${primary.doc_id}`}
          >
            {previewLoading ? (
              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
            ) : previewOpen ? (
              <EyeOff className="w-3.5 h-3.5 mr-1.5" />
            ) : (
              <Eye className="w-3.5 h-3.5 mr-1.5" />
            )}
            {previewOpen ? 'Hide preview' : 'Review document'}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={() => setRoutingOpen(true)}
            data-testid={`open-routing-review-${primary.doc_id}`}
          >
            <FolderOpen className="w-3.5 h-3.5 mr-1.5" />
            Review routing
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            disabled={submitting}
            onClick={() => setClassificationOpen(true)}
            data-testid={`change-classification-${primary.doc_id}`}
          >
            <HelpCircle className="w-3.5 h-3.5 mr-1.5" />
            Change classification
          </Button>

          <Button
            type="button"
            size="sm"
            variant="ghost"
            onClick={handleOpenInNewTab}
            disabled={previewLoading}
            data-testid={`open-document-new-tab-${primary.doc_id}`}
          >
            <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
            Open in new tab
          </Button>
        </div>

        {previewOpen && (
          <div
            className="mb-4 overflow-hidden rounded-md border border-border bg-muted/20"
            data-testid={`document-preview-${primary.doc_id}`}
          >
            {previewLoading && (
              <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                Loading document...
              </div>
            )}

            {!previewLoading && previewError && (
              <div className="flex min-h-40 items-center justify-center gap-2 p-6 text-sm text-destructive">
                <FileWarning className="w-5 h-5 shrink-0" />
                <span>{previewError}</span>
              </div>
            )}

            {!previewLoading && !previewError && previewUrl && kind === 'pdf' && (
              <iframe
                src={previewUrl}
                title={`Document preview: ${primary.file_name}`}
                className="h-[70vh] min-h-[520px] w-full bg-white"
              />
            )}

            {!previewLoading && !previewError && previewUrl && kind === 'image' && (
              <div className="flex max-h-[70vh] min-h-64 items-start justify-center overflow-auto bg-white p-3">
                <img
                  src={previewUrl}
                  alt={`Document preview: ${primary.file_name}`}
                  className="max-w-full object-contain"
                />
              </div>
            )}

            {!previewLoading && !previewError && previewUrl && kind === 'download' && (
              <div className="flex min-h-40 flex-col items-center justify-center gap-2 p-6 text-center text-sm text-muted-foreground">
                <FileWarning className="w-6 h-6" />
                <p>This file type cannot be displayed reliably inside the browser.</p>
                <Button type="button" size="sm" variant="outline" onClick={handleOpenInNewTab}>
                  <ExternalLink className="w-3.5 h-3.5 mr-1.5" />
                  Open the document
                </Button>
              </div>
            )}
          </div>
        )}

        {primary.note && (
          <p className="mb-3 text-xs italic text-muted-foreground">
            {primary.note}
          </p>
        )}

        {isActionable && (
          <div className="flex flex-wrap gap-2">
            {confirmableIssue && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                className="border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
                disabled={
                  submitting ||
                  !canConfirmCurrent
                }
                onClick={() =>
                  onConfirmCurrent(group)
                }
                data-testid={`confirm-current-${primary.doc_id}`}
              >
                {submitting ? (
                  <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
                )}
                Confirm current
              </Button>
            )}

            {primary.issue_type === 'isolated_misroute' && (
              <Button
                size="sm"
                disabled={submitting}
                onClick={() =>
                  onDecide(
                    group,
                    primary.submit_hint.doc_type,
                    primary.submit_hint.mailbox_category
                  )
                }
                data-testid="decide-route-ap"
              >
                Route to AP
              </Button>
            )}

            {primary.issue_type === 'ambiguous_classification' &&
              primary.candidates?.map(candidate => (
                <Button
                  key={candidate}
                  size="sm"
                  variant="outline"
                  disabled={submitting}
                  onClick={() =>
                    onDecide(
                      group,
                      candidate,
                      undefined
                    )
                  }
                  data-testid={`decide-pick-${candidate}`}
                >
                  {candidate.replace('_', ' ')}
                </Button>
              ))}
          </div>
        )}

        {acknowledgeableIssue && (
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="border-emerald-500/40 text-emerald-400 hover:bg-emerald-500/10"
            disabled={submitting}
            onClick={() =>
              onConfirmCurrent(
                group,
                'acknowledged',
                'Square9-side observation acknowledged; Hub document unchanged'
              )
            }
            data-testid={`acknowledge-square9-issue-${primary.doc_id}`}
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
            ) : (
              <CheckCircle2 className="w-3.5 h-3.5 mr-1.5" />
            )}
            Acknowledge and hide issue
          </Button>
        )}

        {ambiguousMatchIssue && (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={submitting}
              onClick={() =>
                onConfirmCurrent(
                  group,
                  'same_document',
                  'Human determined the Hub and Square9 files are the same document'
                )
              }
            >
              Same document
            </Button>

            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={submitting}
              onClick={() =>
                onConfirmCurrent(
                  group,
                  'different_document',
                  'Human determined the Hub and Square9 files are different documents'
                )
              }
              data-testid={`match-different-document-${primary.doc_id}`}
            >
              Different document
            </Button>

            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={submitting}
              onClick={() =>
                onConfirmCurrent(
                  group,
                  'unable_to_determine',
                  'Human could not determine whether the documents match'
                )
              }
            >
              Unable to determine
            </Button>
          </div>
        )}

        <div className="mt-3">
          <Button
            type="button"
            size="sm"
            variant="destructive"
            disabled={submitting}
            onClick={() => setDispositionOpen(true)}
            data-testid={`exclude-from-processing-${primary.doc_id}`}
          >
            {submitting ? (
              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
            ) : (
              <Ban className="w-3.5 h-3.5 mr-1.5" />
            )}
            Exclude from processing
          </Button>
        </div>

        <DecisionQueueClassificationDialog
          open={classificationOpen}
          onOpenChange={setClassificationOpen}
          fileName={primary.file_name}
          currentDocType={
            primary.current_state?.doc_type || ''
          }
          currentMailboxCategory={
            primary.current_state?.mailbox_category || ''
          }
          submitting={submitting}
          onSubmit={(docType, mailboxCategory) =>
            onDecide(
              group,
              docType,
              mailboxCategory
            )
          }
        />

        <NonTransactionalDispositionDialog
          open={dispositionOpen}
          onOpenChange={setDispositionOpen}
          fileName={primary.file_name}
          submitting={submitting}
          onSubmit={(reason, notes) =>
            onDiscard(group, reason, notes)
          }
        />

        <HumanRoutingBrowserDialog
          open={routingOpen}
          onOpenChange={setRoutingOpen}
          document={primary}
        />
      </CardContent>
    </Card>
  );
}
