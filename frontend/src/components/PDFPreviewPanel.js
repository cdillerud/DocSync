import { useState, useEffect, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { FileText, ExternalLink, ZoomIn, ZoomOut, Maximize2, Download, Loader2, ChevronLeft, ChevronRight } from 'lucide-react';
import * as pdfjsLib from 'pdfjs-dist';

// Set the worker source
pdfjsLib.GlobalWorkerOptions.workerSrc = `//cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js`;

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

const MIN_ZOOM = 0.5;
const MAX_ZOOM = 4;

export function PDFPreviewPanel({ document }) {
  const canvasRef = useRef(null);
  const viewerRef = useRef(null);
  const renderTaskRef = useRef(null);
  // zoom is relative to "fit the page to the panel width" (100% = fit).
  // The canvas used to carry max-w-full, so CSS shrank every zoomed render
  // back to the panel width and the buttons only changed the number.
  const [zoom, setZoom] = useState(1.0);
  const [fitWidth, setFitWidth] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [pdfDoc, setPdfDoc] = useState(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [totalPages, setTotalPages] = useState(0);

  // Get the backend file endpoint URL
  const backendFileUrl = document?.id ? `${API_BASE}/api/documents/${document.id}/file` : null;

  // SharePoint URL for external link
  const sharePointUrl = document?.sharepoint_share_link_url || document?.sharepoint_web_url;

  const clampZoom = (z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.round(z * 100) / 100));

  // Load PDF document
  useEffect(() => {
    if (!backendFileUrl) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setZoom(1.0);

    const token = localStorage.getItem('gpi_token');

    // Fetch the PDF file
    fetch(backendFileUrl, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.arrayBuffer();
      })
      .then(data => {
        if (cancelled) return;
        // Load PDF with pdf.js
        return pdfjsLib.getDocument({ data }).promise;
      })
      .then(pdf => {
        if (cancelled || !pdf) return;
        setPdfDoc(pdf);
        setTotalPages(pdf.numPages);
        setCurrentPage(1);
        setLoading(false);
      })
      .catch(err => {
        if (cancelled) return;
        console.error('PDF load error:', err);
        setError(err.message);
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [backendFileUrl]);

  // Track the panel width (it changes with fullscreen and window size)
  useEffect(() => {
    const el = viewerRef.current;
    if (!el) return;
    const measure = () => setFitWidth(Math.max(200, el.clientWidth - 16));
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [pdfDoc, fullscreen]);

  // Ctrl + mouse wheel / trackpad pinch zooms the page, not the browser
  useEffect(() => {
    const el = viewerRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (!e.ctrlKey) return;
      e.preventDefault();
      setZoom(z => clampZoom(z * (e.deltaY < 0 ? 1.1 : 1 / 1.1)));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [pdfDoc, fullscreen]);

  // Render current page
  useEffect(() => {
    if (!pdfDoc || !canvasRef.current || !fitWidth) return;

    let cancelled = false;

    pdfDoc.getPage(currentPage).then(page => {
      if (cancelled) return;

      const canvas = canvasRef.current;
      if (!canvas) return;
      const context = canvas.getContext('2d');

      // Display size: fit-to-width times zoom; drawn at the screen's pixel
      // density so text stays sharp when zoomed in.
      const base = page.getViewport({ scale: 1 });
      const cssScale = (fitWidth / base.width) * zoom;
      const dpr = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: cssScale * dpr });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = `${Math.floor(viewport.width / dpr)}px`;
      canvas.style.height = `${Math.floor(viewport.height / dpr)}px`;

      // A new zoom click while the last render is still drawing: pdf.js
      // refuses two renders on one canvas, so cancel the old one first.
      if (renderTaskRef.current) {
        try { renderTaskRef.current.cancel(); } catch (e) { /* already done */ }
      }
      const task = page.render({ canvasContext: context, viewport });
      renderTaskRef.current = task;
      task.promise.catch(err => {
        if (err?.name !== 'RenderingCancelledException') console.error('PDF render error:', err);
      });
    });

    return () => {
      cancelled = true;
    };
  }, [pdfDoc, currentPage, zoom, fitWidth]);

  if (!document?.id) {
    return (
      <Card className="border border-border">
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <FileText className="w-4 h-4" />
            Document Preview
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-64 flex items-center justify-center bg-muted/50 rounded-md">
            <p className="text-sm text-muted-foreground">No document available for preview</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  const containerClass = fullscreen
    ? 'fixed inset-0 z-50 bg-background p-4'
    : '';

  return (
    <Card className={`border border-border ${containerClass}`} data-testid="pdf-preview-panel">
      <CardHeader className="pb-2">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <FileText className="w-4 h-4" />
            Document Preview
          </CardTitle>
          <div className="flex items-center gap-1">
            {/* Page navigation */}
            {totalPages > 1 && (
              <>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => setCurrentPage(p => Math.max(1, p - 1))}
                  disabled={currentPage <= 1}
                >
                  <ChevronLeft className="w-3 h-3" />
                </Button>
                <span className="text-xs text-muted-foreground w-16 text-center">
                  {currentPage} / {totalPages}
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7"
                  onClick={() => setCurrentPage(p => Math.min(totalPages, p + 1))}
                  disabled={currentPage >= totalPages}
                >
                  <ChevronRight className="w-3 h-3" />
                </Button>
                <div className="w-px h-4 bg-border mx-1" />
              </>
            )}

            {/* Zoom controls */}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setZoom(z => clampZoom(z - 0.25))}
              disabled={zoom <= MIN_ZOOM}
              title="Zoom out (Ctrl + scroll)"
            >
              <ZoomOut className="w-3 h-3" />
            </Button>
            <button
              type="button"
              className="text-xs text-muted-foreground w-10 text-center hover:text-foreground"
              onClick={() => setZoom(1.0)}
              title="Fit to width"
            >
              {Math.round(zoom * 100)}%
            </button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setZoom(z => clampZoom(z + 0.25))}
              disabled={zoom >= MAX_ZOOM}
              title="Zoom in (Ctrl + scroll)"
            >
              <ZoomIn className="w-3 h-3" />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={() => setFullscreen(f => !f)}
            >
              <Maximize2 className="w-3 h-3" />
            </Button>
            {sharePointUrl && (
              <Button
                variant="ghost"
                size="sm"
                className="h-7 ml-2"
                asChild
              >
                <a href={sharePointUrl} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="w-3 h-3 mr-1" />
                  Open
                </a>
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-2">
        <div
          ref={viewerRef}
          className={`overflow-auto rounded-md border bg-muted/30 p-2 ${fullscreen ? 'h-[calc(100vh-120px)]' : 'h-[500px]'}`}
        >
          {loading ? (
            <div className="w-full h-full flex items-center justify-center">
              <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
              <span className="ml-2 text-muted-foreground">Loading document...</span>
            </div>
          ) : error ? (
            <div className="w-full h-full flex flex-col items-center justify-center p-4">
              <p className="text-sm text-muted-foreground mb-2">Unable to load document preview</p>
              <p className="text-xs text-red-500 mb-4">{error}</p>
              {sharePointUrl && (
                <Button variant="outline" size="sm" asChild>
                  <a href={sharePointUrl} target="_blank" rel="noopener noreferrer">
                    <ExternalLink className="w-3 h-3 mr-1" />
                    Open in SharePoint
                  </a>
                </Button>
              )}
            </div>
          ) : pdfDoc ? (
            // block + mx-auto (not flex centring): a page wider than the
            // panel scrolls to its left edge instead of being cut off.
            <canvas ref={canvasRef} className="block mx-auto shadow-sm bg-white" />
          ) : (
            <div className="w-full h-full flex items-center justify-center">
              <p className="text-sm text-muted-foreground">No preview available</p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default PDFPreviewPanel;
