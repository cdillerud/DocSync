import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import SettingsPage from './SettingsPage';
import EmailParserPage from './EmailParserPage';
import AutomationRulesPage from './AutomationRulesPage';
import ItemMappingsPage from './ItemMappingsPage';
import VendorIntelligencePage from './VendorIntelligencePage';
import StableVendorsPage from './StableVendorsPage';

const TABS = [
  { key: 'general', label: 'General' },
  { key: 'email', label: 'Email Config' },
  { key: 'automation', label: 'Automation Rules' },
  { key: 'item-mappings', label: 'Item Mappings' },
  { key: 'vendors', label: 'Vendor Intelligence' },
  { key: 'stable-vendors', label: 'Stable Vendors' },
];

export default function SettingsHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'general';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="settings-hub-page">
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
      {activeTab === 'general' && <SettingsPage />}
      {activeTab === 'email' && <EmailParserPage />}
      {activeTab === 'automation' && <AutomationRulesPage />}
      {activeTab === 'item-mappings' && <ItemMappingsPage />}
      {activeTab === 'vendors' && <VendorIntelligencePage />}
      {activeTab === 'stable-vendors' && <StableVendorsPage />}
    </div>
  );
}
