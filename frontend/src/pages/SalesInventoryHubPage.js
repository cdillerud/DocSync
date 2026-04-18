import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import SalesDashboardPage from './SalesDashboardPage';
import InventoryLedgerPage from './InventoryLedgerPage';
import SalespersonDashboardPage from './SalespersonDashboardPage';
import MyQueuePage from './MyQueuePage';
import TriageQueuePage from './TriageQueuePage';
import InsideSalesPilotPage from './InsideSalesPilotPage';
import SpiroBCCrossRefDashboard from './SpiroBCCrossRefDashboard';
import { Badge } from '../components/ui/badge';

const API = process.env.REACT_APP_BACKEND_URL;

const TABS = [
  { key: 'my-queue', label: 'My Queue' },
  { key: 'triage', label: 'Triage' },
  { key: 'sales', label: 'Sales Orders' },
  { key: 'rep-performance', label: 'Rep Performance' },
  { key: 'inside-sales-pilot', label: 'Sales Intake' },
  { key: 'spiro-bc', label: 'Spiro ↔ BC' },
  { key: 'inventory', label: 'Inventory Ledger' },
];

export default function SalesInventoryHubPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const activeTab = searchParams.get('tab') || 'my-queue';
  const [triageCount, setTriageCount] = useState(0);

  const setTab = (tab) => setSearchParams({ tab }, { replace: true });

  // Fetch triage count for badge
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch(`${API}/api/sales-dashboard/triage-queue?limit=0`);
        const data = await res.json();
        setTriageCount(data.total || 0);
      } catch { /* ignore */ }
    })();
  }, [activeTab]);

  return (
    <div data-testid="sales-inventory-hub-page">
      <div className="flex items-center gap-1 border-b border-border mb-6 overflow-x-auto">
        {TABS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            data-testid={`tab-${key}`}
            className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap flex items-center gap-1.5 ${
              activeTab === key
                ? 'border-primary text-primary'
                : 'border-transparent text-muted-foreground hover:text-foreground hover:border-border'
            }`}
          >
            {label}
            {key === 'triage' && triageCount > 0 && (
              <Badge variant="destructive" className="text-[10px] px-1.5 py-0 h-4 min-w-[18px] justify-center" data-testid="triage-badge">
                {triageCount}
              </Badge>
            )}
          </button>
        ))}
      </div>
      {activeTab === 'my-queue' && <MyQueuePage />}
      {activeTab === 'triage' && <TriageQueuePage />}
      {activeTab === 'sales' && <SalesDashboardPage />}
      {activeTab === 'rep-performance' && <SalespersonDashboardPage />}
      {activeTab === 'inside-sales-pilot' && <InsideSalesPilotPage />}
      {activeTab === 'spiro-bc' && <SpiroBCCrossRefDashboard />}
      {activeTab === 'inventory' && <InventoryLedgerPage />}
    </div>
  );
}
