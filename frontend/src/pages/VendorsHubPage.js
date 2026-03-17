import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import VendorIntelligencePage from './VendorIntelligencePage';
import StableVendorsPage from './StableVendorsPage';

const TABS = [
  { key: 'intelligence', label: 'Vendor Intelligence' },
  { key: 'stable', label: 'Stable Vendors' },
];

export default function VendorsHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'intelligence';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="vendors-hub-page">
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
      {activeTab === 'intelligence' && <VendorIntelligencePage />}
      {activeTab === 'stable' && <StableVendorsPage />}
    </div>
  );
}
