import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import UnifiedQueuePage from './UnifiedQueuePage';
import UploadPage from './UploadPage';
import { Upload } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger,
} from '@/components/ui/dialog';

export default function DocumentsHubPage() {
  const [uploadOpen, setUploadOpen] = useState(false);
  const [searchParams] = useSearchParams();

  // Support legacy ?tab=upload URL
  const showUpload = searchParams.get('tab') === 'upload' || uploadOpen;

  return (
    <div data-testid="documents-hub-page">
      {/* Upload button in top-right corner */}
      <div className="flex items-center justify-between mb-4">
        <div />
        <Dialog open={showUpload} onOpenChange={setUploadOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5 text-xs" data-testid="upload-btn">
              <Upload className="w-3.5 h-3.5" /> Upload Documents
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Upload Documents</DialogTitle>
            </DialogHeader>
            <UploadPage />
          </DialogContent>
        </Dialog>
      </div>
      <UnifiedQueuePage />
    </div>
  );
}
