import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import UnifiedQueuePage from './UnifiedQueuePage';
import UploadPage from './UploadPage';
import FileImportPage from './FileImportPage';

const TABS = [
  { key: 'queue', label: 'Queue' },
  { key: 'upload', label: 'Upload' },
  { key: 'import', label: 'File Import' },
];

export default function DocumentsHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'queue';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="documents-hub-page">
      <div className="flex items-center gap-1 border-b border-border mb-6">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            data-testid={`tab-${key}`}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
              activeTab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === 'queue' && <UnifiedQueuePage />}
      {activeTab === 'upload' && <UploadPage />}
      {activeTab === 'import' && <FileImportPage />}
    </div>
  );
}
