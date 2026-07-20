import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  ArrowLeft,
  Brain,
  Check,
  ChevronRight,
  Folder,
  FolderOpen,
  Home,
  Loader2,
  RefreshCw,
  Save,
} from 'lucide-react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import api from '@/lib/api';

function normalizeFolder(path) {
  return (path || '')
    .replaceAll('\\', '/')
    .split('/')
    .map(part => part.trim())
    .filter(Boolean)
    .join('/')
    .toLowerCase();
}

function buildBreadcrumbs(rootLabel, currentPath) {
  const parts = (currentPath || '').split('/').filter(Boolean);
  const items = [{ label: rootLabel || 'Destination root', path: '' }];
  let path = '';

  for (const part of parts) {
    path = path ? `${path}/${part}` : part;
    items.push({ label: part, path });
  }

  return items;
}

function learningMessage(result) {
  const status = result?.learning?.status;
  if (status === 'created') return 'The AI learned a new reusable routing pattern.';
  if (status === 'strengthened') {
    return `The existing AI routing pattern was reinforced to confidence ${result.learning.confidence}.`;
  }
  if (status === 'conflict') {
    return `The document was assigned, but the learner preserved the established rule for ${result.learning.existing_folder}.`;
  }
  if (status === 'skipped_no_vendor') {
    return 'The document was assigned, but no reusable vendor or sender signal was available.';
  }
  return 'The destination folder was assigned.';
}

export default function HumanRoutingBrowserDialog({ open, onOpenChange, document }) {
  const [routingInfo, setRoutingInfo] = useState(null);
  const [browser, setBrowser] = useState(null);
  const [selectedFolder, setSelectedFolder] = useState('');
  const [loading, setLoading] = useState(false);
  const [folderLoading, setFolderLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [result, setResult] = useState(null);

  const loadFolder = useCallback(async (path = '') => {
    setFolderLoading(true);
    setError('');
    try {
      const { data } = await api.get('/human-routing-review/sharepoint-folders', {
        params: { path },
      });
      setBrowser(data);
      return data;
    } catch (requestError) {
      const message = requestError.response?.data?.detail || 'Could not browse SharePoint folders';
      setError(message);
      toast.error(message);
      return null;
    } finally {
      setFolderLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open || !document?.doc_id) return undefined;

    let cancelled = false;
    setLoading(true);
    setRoutingInfo(null);
    setBrowser(null);
    setSelectedFolder('');
    setResult(null);
    setError('');

    const initialize = async () => {
      try {
        const [{ data: suggestion }] = await Promise.all([
          api.get(`/human-routing-review/document/${encodeURIComponent(document.doc_id)}/suggestion`),
          loadFolder(''),
        ]);

        if (cancelled) return;
        setRoutingInfo(suggestion);
      } catch (requestError) {
        if (cancelled) return;
        const message = requestError.response?.data?.detail || 'Could not load routing review';
        setError(message);
        toast.error(message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    initialize();
    return () => {
      cancelled = true;
    };
  }, [document?.doc_id, loadFolder, open]);

  const breadcrumbs = useMemo(
    () => buildBreadcrumbs(browser?.root_label, browser?.current_path),
    [browser?.current_path, browser?.root_label]
  );

  const comparisonFolder = routingInfo?.current_folder || routingInfo?.suggested_folder || '';
  const isConfirmation = Boolean(selectedFolder) &&
    normalizeFolder(selectedFolder) === normalizeFolder(comparisonFolder);

  const chooseAndBrowse = async (path) => {
    if (!path) return;
    setSelectedFolder(path);
    setResult(null);
    await loadFolder(path);
  };

  const chooseFolder = (path) => {
    setSelectedFolder(path);
    setResult(null);
  };

  const saveRoutingDecision = async () => {
    if (!selectedFolder) {
      toast.error('Choose a destination folder from the browser first');
      return;
    }

    setSaving(true);
    try {
      const { data } = await api.post(
        `/human-routing-review/document/${encodeURIComponent(document.doc_id)}/assign`,
        { folder_path: selectedFolder, source: 'human_decision_queue_folder_browser' }
      );
      setResult(data);
      setRoutingInfo(previous => ({
        ...(previous || {}),
        current_folder: data.folder_path,
        suggested_folder: data.suggested_folder,
        reason: data.suggested_reason,
      }));

      if (data.learning?.status === 'conflict') {
        toast.warning('Folder assigned; the existing learned rule was preserved because the signals conflict');
      } else {
        toast.success('Destination assigned and routing feedback recorded');
      }
    } catch (requestError) {
      const message = requestError.response?.data?.detail || 'The routing decision did not save';
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[92vh] max-w-5xl overflow-hidden p-0">
        <DialogHeader className="border-b border-border px-6 py-5 pr-12">
          <DialogTitle className="flex items-center gap-2">
            <FolderOpen className="h-5 w-5 text-sky-400" />
            Review routing
          </DialogTitle>
          <DialogDescription className="break-all font-mono text-xs">
            {document?.file_name || document?.doc_id}
          </DialogDescription>
        </DialogHeader>

        <div className="grid min-h-0 gap-0 lg:grid-cols-[310px_minmax(0,1fr)]">
          <aside className="space-y-4 border-b border-border bg-muted/20 p-5 lg:border-b-0 lg:border-r">
            <div>
              <p className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-sky-400">
                <Brain className="h-3.5 w-3.5" /> AI suggestion
              </p>
              <p className="break-all font-mono text-sm">
                {routingInfo?.suggested_folder || 'No suggestion available'}
              </p>
              {routingInfo?.reason && (
                <p className="mt-1 text-xs text-muted-foreground">{routingInfo.reason}</p>
              )}
              {routingInfo?.suggested_folder && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-2 w-full"
                  onClick={() => chooseAndBrowse(routingInfo.suggested_folder)}
                  disabled={folderLoading}
                >
                  Browse AI destination
                </Button>
              )}
            </div>

            <div className="border-t border-border pt-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Current assignment
              </p>
              <p className="break-all font-mono text-sm">
                {routingInfo?.current_folder || 'Not assigned'}
              </p>
              {routingInfo?.current_folder && (
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  className="mt-2 w-full"
                  onClick={() => chooseAndBrowse(routingInfo.current_folder)}
                  disabled={folderLoading}
                >
                  Browse current folder
                </Button>
              )}
            </div>

            <div className="border-t border-border pt-4">
              <p className="mb-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                Selected destination
              </p>
              {selectedFolder ? (
                <div className="rounded-md border border-emerald-500/30 bg-emerald-500/10 p-3">
                  <p className="break-all font-mono text-sm text-emerald-300">{selectedFolder}</p>
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Browse the folder tree and choose a folder.</p>
              )}
            </div>

            {browser?.source === 'configured_fallback' && (
              <p className="rounded-md border border-amber-500/30 bg-amber-500/10 p-3 text-xs text-amber-300">
                Live SharePoint browsing is unavailable in this environment. Showing configured routing folders instead.
              </p>
            )}
          </aside>

          <section className="flex min-h-[560px] min-w-0 flex-col">
            <div className="border-b border-border px-5 py-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex min-w-0 flex-wrap items-center gap-1 text-sm">
                  {breadcrumbs.map((crumb, index) => (
                    <div key={`${crumb.path}-${index}`} className="flex min-w-0 items-center gap-1">
                      {index > 0 && <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                      <button
                        type="button"
                        className="max-w-48 truncate rounded px-1.5 py-1 hover:bg-muted"
                        onClick={() => loadFolder(crumb.path)}
                        disabled={folderLoading}
                        title={crumb.label}
                      >
                        {index === 0 && <Home className="mr-1 inline h-3.5 w-3.5" />}
                        {crumb.label}
                      </button>
                    </div>
                  ))}
                </div>
                <Button
                  type="button"
                  size="icon"
                  variant="ghost"
                  onClick={() => loadFolder(browser?.current_path || '')}
                  disabled={folderLoading}
                  title="Refresh this folder"
                >
                  <RefreshCw className={`h-4 w-4 ${folderLoading ? 'animate-spin' : ''}`} />
                </Button>
              </div>
              <p className="mt-1 text-[11px] text-muted-foreground">
                {browser?.target ? `${browser.target} · ` : ''}
                {browser?.library || 'SharePoint'} / {browser?.base_folder || browser?.root_label || ''}
              </p>
            </div>

            <div className="flex items-center gap-2 border-b border-border px-5 py-3">
              <Button
                type="button"
                size="sm"
                variant="outline"
                onClick={() => loadFolder(browser?.parent_path || '')}
                disabled={folderLoading || !browser?.current_path}
              >
                <ArrowLeft className="mr-1.5 h-3.5 w-3.5" /> Up one level
              </Button>
              <Button
                type="button"
                size="sm"
                onClick={() => chooseFolder(browser?.current_path || '')}
                disabled={!browser?.current_path}
              >
                <Check className="mr-1.5 h-3.5 w-3.5" /> Choose open folder
              </Button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {loading || folderLoading ? (
                <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
                  <Loader2 className="mr-2 h-5 w-5 animate-spin" /> Loading SharePoint folders...
                </div>
              ) : error ? (
                <div className="flex h-64 flex-col items-center justify-center gap-3 text-center">
                  <p className="max-w-lg text-sm text-destructive">{error}</p>
                  <Button type="button" variant="outline" onClick={() => loadFolder(browser?.current_path || '')}>
                    Try again
                  </Button>
                </div>
              ) : browser?.folders?.length ? (
                <div className="space-y-2">
                  {browser.folders.map(folder => {
                    const chosen = normalizeFolder(selectedFolder) === normalizeFolder(folder.path);
                    return (
                      <div
                        key={folder.id || folder.path}
                        className={`flex items-center gap-3 rounded-md border p-3 transition-colors ${
                          chosen
                            ? 'border-emerald-500/50 bg-emerald-500/10'
                            : 'border-border hover:bg-muted/50'
                        }`}
                      >
                        <button
                          type="button"
                          className="flex min-w-0 flex-1 items-center gap-3 text-left"
                          onClick={() => loadFolder(folder.path)}
                          disabled={folderLoading}
                          title={`Open ${folder.name}`}
                        >
                          <Folder className={`h-5 w-5 shrink-0 ${chosen ? 'text-emerald-400' : 'text-amber-400'}`} />
                          <span className="min-w-0 flex-1">
                            <span className="block truncate text-sm font-medium">{folder.name}</span>
                            <span className="block text-[11px] text-muted-foreground">
                              {folder.child_count > 0
                                ? `${folder.child_count} item${folder.child_count === 1 ? '' : 's'} inside`
                                : 'No child items reported'}
                            </span>
                          </span>
                          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                        </button>
                        <Button
                          type="button"
                          size="sm"
                          variant={chosen ? 'default' : 'outline'}
                          onClick={() => chooseFolder(folder.path)}
                        >
                          {chosen ? <Check className="mr-1.5 h-3.5 w-3.5" /> : null}
                          {chosen ? 'Chosen' : 'Choose'}
                        </Button>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="flex h-64 flex-col items-center justify-center text-center text-muted-foreground">
                  <FolderOpen className="mb-3 h-10 w-10 opacity-40" />
                  <p className="text-sm font-medium">This folder has no subfolders</p>
                  {browser?.current_path && (
                    <Button
                      type="button"
                      size="sm"
                      className="mt-3"
                      onClick={() => chooseFolder(browser.current_path)}
                    >
                      Choose this folder
                    </Button>
                  )}
                </div>
              )}
            </div>
          </section>
        </div>

        {result && (
          <div className={`mx-6 mb-2 rounded-md border px-4 py-3 text-sm ${
            result.learning?.status === 'conflict'
              ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
              : 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
          }`}>
            <p className="font-medium">
              Assigned to <span className="font-mono">{result.folder_path}</span>
            </p>
            <p className="mt-1 text-xs">{learningMessage(result)}</p>
          </div>
        )}

        <DialogFooter className="border-t border-border px-6 py-4">
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
          <Button
            type="button"
            onClick={saveRoutingDecision}
            disabled={saving || !selectedFolder}
          >
            {saving ? (
              <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />
            ) : (
              <Save className="mr-1.5 h-4 w-4" />
            )}
            {isConfirmation ? 'Confirm selected routing' : 'Save routing correction'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
