import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import SalesDashboardPage from './SalesDashboardPage';
import InventoryLedgerPage from './InventoryLedgerPage';
import SalespersonDashboardPage from './SalespersonDashboardPage';

const TABS = [
  { key: 'sales', label: 'Sales Orders' },
  { key: 'rep-performance', label: 'Rep Performance' },
  { key: 'inventory', label: 'Inventory Ledger' },
];

export default function SalesInventoryHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'sales';

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  return (
    <div data-testid="sales-inventory-hub-page">
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
      {activeTab === 'sales' && <SalesDashboardPage />}
      {activeTab === 'rep-performance' && <SalespersonDashboardPage />}
      {activeTab === 'inventory' && <InventoryLedgerPage />}
    </div>
  );
}
