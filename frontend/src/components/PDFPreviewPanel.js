import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { FileText, ExternalLink, ZoomIn, ZoomOut, Maximize2, Download, Loader2 } from 'lucide-react';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

export function PDFPreviewPanel({ document }) {
  const [zoom, setZoom] = useState(100);
  const [fullscreen, setFullscreen] = useState(false);
  const [pdfBlobUrl, setPdfBlobUrl] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Get the backend file endpoint URL
  const backendFileUrl = document?.id ? `${API_BASE}/api/documents/${document.id}/file` : null;
  
  // SharePoint URL for external link
  const sharePointUrl = document?.sharepoint_share_link_url || document?.sharepoint_web_url;
  
  // Load PDF from backend when document changes
  useEffect(() => {
    if (!backendFileUrl) return;
    
    let cancelled = false;
    let blobUrl = null;
    setLoading(true);
    setError(null);
    
    // Fetch PDF from backend and create blob URL
    const token = localStorage.getItem('gpi_token');
    fetch(backendFileUrl, {
      headers: token ? { 'Authorization': `Bearer ${token}` } : {}
    })
      .then(res => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return res.blob();
      })
      .then(blob => {
        if (cancelled) return;
        // Create object URL for the blob
        blobUrl = URL.createObjectURL(blob);
        setPdfBlobUrl(blobUrl);
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
      // Clean up blob URL when component unmounts or document changes
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [backendFileUrl]);
  
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
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-7 w-7"
              onClick={() => setZoom(z => Math.max(50, z - 25))}
            >
              <ZoomOut className="w-3 h-3" />
            </Button>
            <span className="text-xs text-muted-foreground w-10 text-center">{zoom}%</span>
            <Button 
              variant="ghost" 
              size="icon" 
              className="h-7 w-7"
              onClick={() => setZoom(z => Math.min(200, z + 25))}
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
          className={`overflow-auto rounded-md border bg-muted/30 ${fullscreen ? 'h-[calc(100vh-120px)]' : 'h-[500px]'}`}
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
          ) : pdfBlobUrl ? (
            <object
              data={pdfBlobUrl}
              type="application/pdf"
              className="w-full h-full"
              style={{ minHeight: '600px' }}
            >
              <div className="w-full h-full flex flex-col items-center justify-center p-4">
                <p className="text-sm text-muted-foreground mb-4">PDF preview not available in this browser</p>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" asChild>
                    <a href={pdfBlobUrl} download={document?.file_name || 'document.pdf'}>
                      <Download className="w-3 h-3 mr-1" />
                      Download
                    </a>
                  </Button>
                  {sharePointUrl && (
                    <Button variant="outline" size="sm" asChild>
                      <a href={sharePointUrl} target="_blank" rel="noopener noreferrer">
                        <ExternalLink className="w-3 h-3 mr-1" />
                        Open in SharePoint
                      </a>
                    </Button>
                  )}
                </div>
              </div>
            </object>
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
