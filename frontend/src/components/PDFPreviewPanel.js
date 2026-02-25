import { useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { FileText, ExternalLink, ZoomIn, ZoomOut, Maximize2 } from 'lucide-react';

const API_BASE = process.env.REACT_APP_BACKEND_URL || '';

export function PDFPreviewPanel({ document }) {
  const [zoom, setZoom] = useState(100);
  const [fullscreen, setFullscreen] = useState(false);
  
  // For SharePoint documents, we can use the share link
  // For local files, we'll need a backend endpoint to serve them
  const pdfUrl = document?.sharepoint_share_link_url 
    ? document.sharepoint_share_link_url 
    : document?.id 
      ? `${API_BASE}/api/documents/${document.id}/file`
      : null;
  
  // Use Google Docs viewer for SharePoint links (embeddable)
  // Or direct embed for local files
  const embedUrl = pdfUrl 
    ? (pdfUrl.includes('sharepoint.com') 
        ? pdfUrl.replace(':b:', ':x:') // Convert to embed format
        : pdfUrl)
    : null;
  
  if (!pdfUrl) {
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
            <Button 
              variant="ghost" 
              size="sm" 
              className="h-7 ml-2"
              asChild
            >
              <a href={pdfUrl} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="w-3 h-3 mr-1" />
                Open
              </a>
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-2">
        <div 
          className={`overflow-auto rounded-md border bg-muted/30 ${fullscreen ? 'h-[calc(100vh-120px)]' : 'h-[500px]'}`}
          style={{ transform: `scale(${zoom / 100})`, transformOrigin: 'top left' }}
        >
          {document?.sharepoint_share_link_url ? (
            // For SharePoint, use iframe with embed URL
            <iframe
              src={embedUrl}
              className="w-full h-full min-h-[600px] border-0"
              title="Document Preview"
              sandbox="allow-scripts allow-same-origin"
              loading="lazy"
            />
          ) : (
            // For local files, use object/embed
            <object
              data={pdfUrl}
              type="application/pdf"
              className="w-full h-full min-h-[600px]"
            >
              <embed 
                src={pdfUrl} 
                type="application/pdf"
                className="w-full h-full"
              />
              <p className="text-center p-4 text-muted-foreground">
                Unable to display PDF. 
                <a href={pdfUrl} target="_blank" rel="noopener noreferrer" className="text-primary ml-1">
                  Download instead
                </a>
              </p>
            </object>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

export default PDFPreviewPanel;
