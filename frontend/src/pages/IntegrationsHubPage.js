import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import SharePointRoutingPage from './SharePointRoutingPage';
import BCIntegrationDashboard from './BCIntegrationDashboard';

const TABS = [
  { key: 'sharepoint', label: 'SharePoint Routing' },
  { key: 'bc', label: 'Business Central' },
];

export default function IntegrationsHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'sharepoint';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="integrations-hub-page">
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
      {activeTab === 'sharepoint' && <SharePointRoutingPage />}
      {activeTab === 'bc' && <BCIntegrationDashboard />}
    </div>
  );
}
