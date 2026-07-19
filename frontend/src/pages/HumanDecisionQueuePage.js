import { useState, useEffect, useCallback, useMemo } from 'react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import {
  ScanSearch, RefreshCw, Loader2, CheckCircle2, HelpCircle, Building2, Info,
  Eye, EyeOff, ExternalLink, FileWarning, FolderOpen, Brain, Save,
} from 'lucide-react';
import api, { getHumanDecisionQueue, bulkClassifyDocuments } from '@/lib/api';

const ISSUE_TYPE_META = {
  isolated_misroute: { label: 'Wrong mailbox', icon: Building2, cls: 'bg-amber-500/15 text-amber-400 border-amber-500/30' },
  ambiguous_classification: { label: 'Needs a type picked', icon: HelpCircle, cls: 'bg-sky-500/15 text-sky-400 border-sky-500/30' },
  ambiguous_match: { label: 'Match unclear', icon: HelpCircle, cls: 'bg-muted text-muted-foreground border-border' },
  square9_side_issue: { label: 'Square9-side', icon: Info, cls: 'bg-muted text-muted-foreground border-border' },
};

const TAB_ORDER = ['all', 'isolated_misroute', 'ambiguous_classification', 'ambiguous_match', 'square9_side_issue'];

function groupItems(items) {
  const byKey = new Map();
  for (const it of items) {
    const key = `${it.doc_id}|${it.issue_type}`;
    if (!byKey.has(key)) byKey.set(key, []);
    byKey.get(key).push(it);
  }
  return [...byKey.values()];
}

function normalizeFolder(path) {
  return (path || '')
    .replaceAll('\\', '/')
    .split('/')
    .map(part => part.trim())
    .filter(Boolean)
    .join('/')
    .toLowerCase();
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
  const [folderOptions, setFolderOptions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeTab, setActiveTab] = useState('all');
  const [resolvedKeys, setResolvedKeys] = useState(new Set());
  const [submittingKey, setSubmittingKey] = useState(null);

  const fetchQueue = useCallback(async () => {
    setLoading(true);
    try {
      const { data: queueData } = await getHumanDecisionQueue();
      setData(queueData);

      try {
        const { data: folderData } = await api.get('/human-routing-review/folder-options');
        setFolderOptions(folderData.options || []);
      } catch (folderError) {
        setFolderOptions([]);
        toast.warning('Decision queue loaded, but folder choices could not be loaded');
      }
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
      toast.success(`Confirmed — ${primary.file_name}`);
      setResolvedKeys(prev => new Set(prev).add(key));
    } catch (err) {
      toast.error(err.response?.data?.detail || 'That decision didn’t save');
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
              Review the document, correct its type or mailbox, and choose its exact folder. Every routing confirmation becomes reusable AI guidance.
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
              folderOptions={folderOptions}
              submitting={submittingKey === `${group[0].doc_id}|${group[0].issue_type}`}
              onDecide={handleDecision}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function DecisionCard({ group, folderOptions, submitting, onDecide }) {
  const primary = group[0];
  const meta = ISSUE_TYPE_META[primary.issue_type];
  const Icon = meta.icon;
  const isActionable = !!primary.submit_via;

  const [previewOpen, setPreviewOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewUrl, setPreviewUrl] = useState('');
  const [previewContentType, setPreviewContentType] = useState('');
  const [previewError, setPreviewError] = useState('');

  const [routingOpen, setRoutingOpen] = useState(false);
  const [routingLoading, setRoutingLoading] = useState(false);
  const [routingSaving, setRoutingSaving] = useState(false);
  const [routingInfo, setRoutingInfo] = useState(null);
  const [selectedFolder, setSelectedFolder] = useState('');
  const [routingResult, setRoutingResult] = useState(null);

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

  const loadRouting = useCallback(async () => {
    if (routingInfo) return routingInfo;
    setRoutingLoading(true);
    try {
      const { data } = await api.get(
        `/human-routing-review/document/${encodeURIComponent(primary.doc_id)}/suggestion`
      );
      setRoutingInfo(data);
      setSelectedFolder(data.current_folder || data.suggested_folder || '');
      return data;
    } catch (error) {
      toast.error(error.response?.data?.detail || 'Could not load routing details');
      return null;
    } finally {
      setRoutingLoading(false);
    }
  }, [primary.doc_id, routingInfo]);

  const handleRoutingToggle = async () => {
    if (routingOpen) {
      setRoutingOpen(false);
      return;
    }
    setRoutingOpen(true);
    await loadRouting();
  };

  const saveRoutingDecision = async () => {
    const folderPath = selectedFolder.trim();
    if (!folderPath) {
      toast.error('Choose a destination folder first');
      return;
    }

    setRoutingSaving(true);
    try {
      const { data } = await api.post(
        `/human-routing-review/document/${encodeURIComponent(primary.doc_id)}/assign`,
        { folder_path: folderPath, source: 'human_decision_queue' }
      );
      setRoutingResult(data);
      setRoutingInfo(prev => ({
        ...(prev || {}),
        current_folder: data.folder_path,
        suggested_folder: data.suggested_folder,
        reason: data.suggested_reason,
      }));
      setSelectedFolder(data.folder_path);

      const status = data.learning?.status;
      if (status === 'conflict') {
        toast.warning(
          `Folder saved, but the learned rule conflicts with an existing pattern for ${data.learning.existing_folder}`
        );
      } else if (status === 'strengthened') {
        toast.success(`Routing confirmed — AI pattern reinforced to confidence ${data.learning.confidence}`);
      } else if (status === 'created') {
        toast.success('Routing saved — AI learned this folder pattern');
      } else if (status === 'skipped_no_vendor') {
        toast.success('Folder saved; this document had no safe vendor/sender signal for a reusable rule');
      } else {
        toast.success('Folder routing saved');
      }
    } catch (error) {
      toast.error(error.response?.data?.detail || 'The routing decision did not save');
    } finally {
      setRoutingSaving(false);
    }
  };

  const kind = previewKind(previewContentType, primary.file_name);
  const comparisonFolder = routingInfo?.current_folder || routingInfo?.suggested_folder || '';
  const isRoutingConfirmation = Boolean(selectedFolder) &&
    normalizeFolder(selectedFolder) === normalizeFolder(comparisonFolder);
  const datalistId = `folder-options-${primary.doc_id.replace(/[^a-zA-Z0-9_-]/g, '')}`;
  const uniqueFolderOptions = useMemo(() => {
    const paths = new Map();
    for (const option of folderOptions || []) {
      if (option.path) paths.set(normalizeFolder(option.path), option);
    }
    for (const specialPath of [routingInfo?.suggested_folder, routingInfo?.current_folder]) {
      if (specialPath && !paths.has(normalizeFolder(specialPath))) {
        paths.set(normalizeFolder(specialPath), { path: specialPath, description: '' });
      }
    }
    return [...paths.values()];
  }, [folderOptions, routingInfo]);

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
            {previewOpen ? 'Hide document' : 'Review document'}
          </Button>

          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={handleRoutingToggle}
            disabled={routingLoading}
            data-testid={`toggle-routing-review-${primary.doc_id}`}
          >
            {routingLoading ? (
              <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
            ) : (
              <FolderOpen className="w-3.5 h-3.5 mr-1.5" />
            )}
            {routingOpen ? 'Hide routing' : 'Review routing'}
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

        {routingOpen && (
          <div className="mb-4 rounded-md border border-sky-500/25 bg-sky-500/5 p-4" data-testid={`routing-review-${primary.doc_id}`}>
            {routingLoading ? (
              <div className="flex items-center justify-center py-8 text-sm text-muted-foreground">
                <Loader2 className="w-4 h-4 mr-2 animate-spin" /> Loading routing options...
              </div>
            ) : routingInfo ? (
              <div className="space-y-3">
                <div className="flex items-start gap-2">
                  <Brain className="w-4 h-4 mt-0.5 text-sky-400 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-xs font-semibold uppercase tracking-wider text-sky-400">AI suggestion</p>
                    <p className="font-mono text-sm break-all">{routingInfo.suggested_folder || 'No suggestion available'}</p>
                    {routingInfo.reason && <p className="text-xs text-muted-foreground mt-1">{routingInfo.reason}</p>}
                  </div>
                </div>

                {routingInfo.current_folder && (
                  <p className="text-xs text-muted-foreground">
                    <span className="font-medium text-foreground">Currently assigned:</span>{' '}
                    <span className="font-mono">{routingInfo.current_folder}</span>
                  </p>
                )}

                <div>
                  <label htmlFor={`folder-input-${primary.doc_id}`} className="text-xs font-medium text-foreground">
                    Exact destination folder
                  </label>
                  <input
                    id={`folder-input-${primary.doc_id}`}
                    list={datalistId}
                    value={selectedFolder}
                    onChange={event => {
                      setSelectedFolder(event.target.value);
                      setRoutingResult(null);
                    }}
                    placeholder="Choose a folder or type a more specific path"
                    className="mt-1 w-full rounded-md border border-input bg-background px-3 py-2 font-mono text-sm outline-none ring-offset-background focus:ring-2 focus:ring-ring"
                    data-testid={`routing-folder-input-${primary.doc_id}`}
                  />
                  <datalist id={datalistId}>
                    {uniqueFolderOptions.map(option => (
                      <option key={option.path} value={option.path}>{option.description || option.path}</option>
                    ))}
                  </datalist>
                  <p className="mt-1 text-[11px] text-muted-foreground">
                    {folderOptions.length > 0
                      ? `${folderOptions.length} configured folder destinations are available. You can also type an exact subfolder path.`
                      : 'Type the exact relative SharePoint folder path.'}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  {routingInfo.suggested_folder && normalizeFolder(selectedFolder) !== normalizeFolder(routingInfo.suggested_folder) && (
                    <Button
                      type="button"
                      size="sm"
                      variant="outline"
                      onClick={() => setSelectedFolder(routingInfo.suggested_folder)}
                    >
                      <Brain className="w-3.5 h-3.5 mr-1.5" /> Use AI suggestion
                    </Button>
                  )}
                  <Button
                    type="button"
                    size="sm"
                    onClick={saveRoutingDecision}
                    disabled={routingSaving || !selectedFolder.trim()}
                    data-testid={`save-routing-${primary.doc_id}`}
                  >
                    {routingSaving ? (
                      <Loader2 className="w-3.5 h-3.5 mr-1.5 animate-spin" />
                    ) : (
                      <Save className="w-3.5 h-3.5 mr-1.5" />
                    )}
                    {isRoutingConfirmation ? 'Confirm AI routing' : 'Save routing correction'}
                  </Button>
                </div>

                {routingResult && (
                  <div className={`rounded border px-3 py-2 text-xs ${
                    routingResult.learning?.status === 'conflict'
                      ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                      : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                  }`}>
                    <p className="font-medium">
                      Folder saved as <span className="font-mono">{routingResult.folder_path}</span>.
                    </p>
                    {routingResult.learning?.status === 'created' && <p>The AI learned a new reusable routing pattern.</p>}
                    {routingResult.learning?.status === 'strengthened' && <p>The existing AI routing pattern was reinforced.</p>}
                    {routingResult.learning?.status === 'conflict' && (
                      <p>
                        The document was routed, but the learner kept the established rule for{' '}
                        <span className="font-mono">{routingResult.learning.existing_folder}</span> instead of overwriting it.
                      </p>
                    )}
                    {routingResult.learning?.status === 'skipped_no_vendor' && (
                      <p>No reusable vendor/sender signal was available, so only this document was updated.</p>
                    )}
                  </div>
                )}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">Routing details could not be loaded.</p>
            )}
          </div>
        )}

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
