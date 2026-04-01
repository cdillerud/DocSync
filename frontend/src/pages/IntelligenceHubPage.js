import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import DocumentReviewQueuePage from './DocumentReviewQueuePage';
import DocumentBundleReviewPage from './DocumentBundleReviewPage';
import DocumentLifecyclePage from './DocumentLifecyclePage';
import LabelCorrectionInsightsPage from './LabelCorrectionInsightsPage';
import LayoutFingerprintsPage from './LayoutFingerprintsPage';
import KnowledgeBasePage from './KnowledgeBasePage';

const TABS = [
  { key: 'review', label: 'Doc Intelligence' },
  { key: 'bundles', label: 'Bundles' },
  { key: 'lifecycle', label: 'Lifecycle' },
  { key: 'labels', label: 'Label Insights' },
  { key: 'layouts', label: 'Layout Families' },
  { key: 'knowledge', label: 'Knowledge Base' },
];

export default function IntelligenceHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'review';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="intelligence-hub-page">
      <div className="flex items-center gap-1 border-b border-border mb-6 overflow-x-auto">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            data-testid={`tab-${key}`}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap ${
              activeTab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {activeTab === 'review' && <DocumentReviewQueuePage />}
      {activeTab === 'bundles' && <DocumentBundleReviewPage />}
      {activeTab === 'lifecycle' && <DocumentLifecyclePage />}
      {activeTab === 'labels' && <LabelCorrectionInsightsPage />}
      {activeTab === 'layouts' && <LayoutFingerprintsPage />}
      {activeTab === 'knowledge' && <KnowledgeBasePage />}
    </div>
  );
}
