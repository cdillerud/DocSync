import { useState, useEffect, useRef, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Scissors, Loader2, CheckCircle, AlertTriangle, ChevronDown, ChevronUp, Layers } from 'lucide-react';
import { toast } from 'sonner';
import * as pdfjsLib from 'pdfjs-dist';
import api from '../lib/api';

pdfjsLib.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js`;

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

const THUMB_HEIGHT = 160;

const GroupColorMap = [
  'border-blue-500 bg-blue-500/10',
  'border-emerald-500 bg-emerald-500/10',
  'border-amber-500 bg-amber-500/10',
  'border-purple-500 bg-purple-500/10',
  'border-rose-500 bg-rose-500/10',
  'border-cyan-500 bg-cyan-500/10',
  'border-orange-500 bg-orange-500/10',
];

const GroupBadgeColors = [
  'bg-blue-500/20 text-blue-400',
  'bg-emerald-500/20 text-emerald-400',
  'bg-amber-500/20 text-amber-400',
  'bg-purple-500/20 text-purple-400',
  'bg-rose-500/20 text-rose-400',
  'bg-cyan-500/20 text-cyan-400',
  'bg-orange-500/20 text-orange-400',
];

function PageThumbnail({ pdfDoc, pageNum, groupIdx, isFirstInGroup, vendorHint, refNumbers, onRender }) {
  const canvasRef = useRef(null);
  const [rendered, setRendered] = useState(false);

  useEffect(() => {
    if (!pdfDoc || !canvasRef.current) return;
    let cancelled = false;
    pdfDoc.getPage(pageNum).then(page => {
      if (cancelled) return;
      const vp = page.getViewport({ scale: 0.4 });
      const canvas = canvasRef.current;
      canvas.width = vp.width;
      canvas.height = vp.height;
      page.render({ canvasContext: canvas.getContext('2d'), viewport: vp }).promise.then(() => {
        if (!cancelled) { setRendered(true); onRender?.(); }
      });
    });
    return () => { cancelled = true; };
  }, [pdfDoc, pageNum, onRender]);

  const borderColor = GroupColorMap[groupIdx % GroupColorMap.length];

  return (
    <div className="flex flex-col items-center">
      {isFirstInGroup && groupIdx > 0 && (
        <div data-testid={`boundary-marker-${pageNum}`} className="w-full flex items-center gap-1 mb-1.5">
          <div className="flex-1 border-t-2 border-dashed border-red-500/60" />
          <Scissors className="w-3 h-3 text-red-500/70 shrink-0" />
          <div className="flex-1 border-t-2 border-dashed border-red-500/60" />
        </div>
      )}
      <div
        data-testid={`page-thumb-${pageNum}`}
        className={`relative rounded-md border-2 overflow-hidden transition-all ${borderColor}`}
        style={{ height: THUMB_HEIGHT }}
      >
        <canvas ref={canvasRef} className="h-full w-auto" />
        <div className="absolute top-1 left-1">
          <span className="text-[9px] font-mono bg-black/60 text-white px-1 rounded">{pageNum}</span>
        </div>
        {isFirstInGroup && (
          <div className="absolute top-1 right-1">
            <Badge className={`text-[8px] px-1 py-0 ${GroupBadgeColors[groupIdx % GroupBadgeColors.length]}`}>
              Doc {groupIdx + 1}
            </Badge>
          </div>
        )}
      </div>
      {vendorHint && isFirstInGroup && (
        <p className="text-[9px] text-muted-foreground mt-1 max-w-[100px] truncate text-center" title={vendorHint}>
          {vendorHint}
        </p>
      )}
    </div>
  );
}

export default function SplitPreviewPanel({ document: doc, onSplitComplete }) {
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(false);
  const [splitting, setSplitting] = useState(false);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [expanded, setExpanded] = useState(false);

  const isMultiPage = (doc?.batch_page_count > 1) || (doc?.batch_detected);

  const fetchAnalysis = useCallback(async () => {
    if (!doc?.id) return;
    setLoading(true);
    try {
      const res = await api.get(`/documents/${doc.id}/boundary-analysis`);
      setAnalysis(res.data.analysis);
      if (res.data.analysis?.should_split) setExpanded(true);
    } catch (err) {
      console.error('Boundary analysis failed:', err);
    } finally {
      setLoading(false);
    }
  }, [doc?.id]);

  useEffect(() => {
    if (isMultiPage || (doc?.batch_split_suggested)) {
      fetchAnalysis();
    }
  }, [fetchAnalysis, isMultiPage, doc?.batch_split_suggested]);

  // Load PDF for thumbnails
  useEffect(() => {
    if (!doc?.id || !analysis?.should_split) return;
    const token = localStorage.getItem('gpi_token');
    fetch(`${API_BASE}/api/documents/${doc.id}/file`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then(r => r.arrayBuffer())
      .then(data => pdfjsLib.getDocument({ data }).promise)
      .then(pdf => setPdfDoc(pdf))
      .catch(e => console.error('PDF load for split preview:', e));
  }, [doc?.id, analysis?.should_split]);

  const handleSplit = async () => {
    setSplitting(true);
    try {
      const res = await api.post(`/documents/${doc.id}/auto-split`);
      if (res.data.success) {
        const r = res.data.result;
        toast.success(`Split into ${r.children_count} documents (${r.children_success} successful)`);
        onSplitComplete?.();
      } else {
        toast.info(res.data.reason || 'No split needed');
      }
    } catch (err) {
      toast.error('Split failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSplitting(false);
    }
  };

  // Don't show if not multi-page or already split
  if (doc?.batch_split || doc?.batch_parent_id) return null;
  if (!analysis && !isMultiPage) return null;

  const groups = analysis?.groups || [];
  const shouldSplit = analysis?.should_split;
  const docCount = analysis?.document_count || 0;

  // Build a page→group lookup
  const pageGroupMap = {};
  groups.forEach((g, idx) => {
    (g.pages || []).forEach(p => { pageGroupMap[p] = idx; });
  });
  const firstPageInGroup = new Set(groups.map(g => g.pages?.[0]));

  return (
    <Card data-testid="split-preview-panel" className="border border-border">
      <CardHeader className="pb-2 cursor-pointer" onClick={() => setExpanded(!expanded)}>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Layers className="w-4 h-4" />
            Split Preview
            {shouldSplit && (
              <Badge data-testid="split-badge" className="bg-amber-500/15 text-amber-400 text-[10px] ml-1">
                {docCount} documents detected
              </Badge>
            )}
            {!shouldSplit && analysis && (
              <Badge className="bg-emerald-500/15 text-emerald-400 text-[10px] ml-1">Single document</Badge>
            )}
          </CardTitle>
          <div className="flex items-center gap-2">
            {shouldSplit && (
              <Button
                data-testid="confirm-split-btn"
                size="sm"
                onClick={(e) => { e.stopPropagation(); handleSplit(); }}
                disabled={splitting}
                className="h-7 text-xs"
              >
                {splitting ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Scissors className="w-3 h-3 mr-1" />}
                {splitting ? 'Splitting...' : `Split into ${docCount} docs`}
              </Button>
            )}
            {expanded ? <ChevronUp className="w-4 h-4 text-muted-foreground" /> : <ChevronDown className="w-4 h-4 text-muted-foreground" />}
          </div>
        </div>
      </CardHeader>

      {expanded && (
        <CardContent className="pt-0">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground mr-2" />
              <span className="text-sm text-muted-foreground">Analyzing pages...</span>
            </div>
          ) : analysis ? (
            <div className="space-y-3">
              <p className="text-xs text-muted-foreground">{analysis.analysis}</p>

              {/* Page thumbnail strip */}
              {pdfDoc && (
                <div data-testid="page-strip" className="flex flex-wrap gap-2 items-end">
                  {Array.from({ length: analysis.total_pages }, (_, i) => i + 1).map(pageNum => {
                    const groupIdx = pageGroupMap[pageNum] ?? 0;
                    const isFirst = firstPageInGroup.has(pageNum);
                    const group = groups[groupIdx] || {};
                    return (
                      <PageThumbnail
                        key={pageNum}
                        pdfDoc={pdfDoc}
                        pageNum={pageNum}
                        groupIdx={groupIdx}
                        isFirstInGroup={isFirst}
                        vendorHint={isFirst ? group.vendor_hint : ''}
                        refNumbers={isFirst ? group.ref_numbers : {}}
                        onRender={() => {}}
                      />
                    );
                  })}
                </div>
              )}

              {/* Group summary */}
              <div className="space-y-1.5">
                {groups.map((g, idx) => (
                  <div
                    key={idx}
                    data-testid={`group-summary-${idx + 1}`}
                    className={`flex items-center gap-2 text-xs rounded px-2 py-1.5 border ${GroupColorMap[idx % GroupColorMap.length]}`}
                  >
                    <Badge className={`text-[9px] px-1.5 py-0 ${GroupBadgeColors[idx % GroupBadgeColors.length]}`}>
                      Doc {idx + 1}
                    </Badge>
                    <span>
                      {g.page_count === 1 ? `Page ${g.pages[0]}` : `Pages ${g.page_range}`}
                    </span>
                    {g.vendor_hint && (
                      <span className="text-muted-foreground truncate max-w-[200px]" title={g.vendor_hint}>
                        — {g.vendor_hint}
                      </span>
                    )}
                    {g.doc_type_hints?.[0] && (
                      <Badge variant="outline" className="text-[8px] px-1 py-0">{g.doc_type_hints[0]}</Badge>
                    )}
                    {Object.entries(g.ref_numbers || {}).slice(0, 1).map(([k, v]) => (
                      <span key={k} className="text-muted-foreground text-[10px]">#{v}</span>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="py-4 text-center">
              <Button
                data-testid="analyze-btn"
                variant="outline"
                size="sm"
                onClick={fetchAnalysis}
                disabled={loading}
              >
                <Layers className="w-3 h-3 mr-1" />
                Analyze Pages
              </Button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
