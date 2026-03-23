import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '../components/ui/sheet';
import { Fingerprint, Layers, AlertTriangle, RefreshCw, ChevronRight, FolderTree } from 'lucide-react';
import { toast } from 'sonner';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ title, value, icon: Icon, subtitle, color = "slate" }) {
  const colorMap = {
    slate: "text-slate-400", blue: "text-blue-400", green: "text-emerald-400",
    amber: "text-amber-400", red: "text-red-400", violet: "text-violet-400",
  };
  return (
    <Card data-testid={`stat-card-${title.toLowerCase().replace(/\s+/g,'-')}`} className="bg-slate-900 border-slate-700">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-400 uppercase tracking-wider">{title}</span>
          {Icon && <Icon className={`h-4 w-4 ${colorMap[color]}`} />}
        </div>
        <div className="text-2xl font-bold text-white">{value}</div>
        {subtitle && <p className="text-xs text-slate-500 mt-1">{subtitle}</p>}
      </CardContent>
    </Card>
  );
}

function FamilyRow({ family, onClick }) {
  const pm = family.performance_metrics || {};
  const resRate = (pm.resolution_success_rate || 0) * 100;
  const autoRate = (pm.automation_success_rate || 0) * 100;
  return (
    <tr
      data-testid={`family-row-${family.layout_family_id}`}
      className="border-b border-slate-700/50 hover:bg-slate-800/50 cursor-pointer transition-colors"
      onClick={() => onClick(family)}
    >
      <td className="p-3">
        <div className="flex items-center gap-2">
          <FolderTree className="h-3.5 w-3.5 text-blue-400 flex-shrink-0" />
          <span className="text-sm font-mono text-blue-300 truncate max-w-[200px]">{family.layout_family_id}</span>
        </div>
      </td>
      <td className="p-3 text-sm text-slate-300 truncate max-w-[140px]">{family.vendor_no || '-'}</td>
      <td className="p-3">
        <Badge variant="outline" className="text-xs border-slate-600 text-slate-300">{family.document_type}</Badge>
      </td>
      <td className="p-3 text-sm text-white font-medium text-right">{family.documents_count}</td>
      <td className="p-3 text-right">
        <span className={`text-sm font-medium ${resRate >= 70 ? 'text-emerald-400' : resRate >= 40 ? 'text-amber-400' : 'text-slate-500'}`}>
          {resRate > 0 ? `${resRate.toFixed(0)}%` : '-'}
        </span>
      </td>
      <td className="p-3 text-right">
        <span className={`text-sm font-medium ${autoRate >= 70 ? 'text-emerald-400' : autoRate >= 40 ? 'text-amber-400' : 'text-slate-500'}`}>
          {autoRate > 0 ? `${autoRate.toFixed(0)}%` : '-'}
        </span>
      </td>
      <td className="p-3 text-right">
        {pm.mislabel_count > 0 ? (
          <Badge variant="outline" className="text-xs border-amber-600 text-amber-400">{pm.mislabel_count}</Badge>
        ) : <span className="text-slate-600">0</span>}
      </td>
      <td className="p-3 text-xs text-slate-500">{family.last_seen ? new Date(family.last_seen).toLocaleDateString() : '-'}</td>
      <td className="p-3"><ChevronRight className="h-4 w-4 text-slate-600" /></td>
    </tr>
  );
}

function FamilyDetailSheet({ family, open, onClose }) {
  if (!family) return null;
  const pm = family.performance_metrics || {};
  const entityDist = pm.bc_entity_distribution || {};
  const labelDist = pm.reference_label_distribution || {};
  const recentDocs = family.recent_documents || [];

  return (
    <Sheet open={open} onOpenChange={onClose}>
      <SheetContent className="bg-slate-900 border-slate-700 w-[480px] sm:max-w-[480px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="text-white flex items-center gap-2">
            <Fingerprint className="h-5 w-5 text-blue-400" />
            {family.layout_family_id}
          </SheetTitle>
        </SheetHeader>
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-slate-800 rounded p-3">
              <span className="text-xs text-slate-500">Vendor</span>
              <p className="text-sm text-white truncate">{family.vendor_no || '-'}</p>
            </div>
            <div className="bg-slate-800 rounded p-3">
              <span className="text-xs text-slate-500">Doc Type</span>
              <p className="text-sm text-white">{family.document_type}</p>
            </div>
            <div className="bg-slate-800 rounded p-3">
              <span className="text-xs text-slate-500">Documents</span>
              <p className="text-sm text-white font-bold">{family.documents_count}</p>
            </div>
            <div className="bg-slate-800 rounded p-3">
              <span className="text-xs text-slate-500">Status</span>
              <Badge className={family.status === 'active' ? 'bg-emerald-900 text-emerald-300' : 'bg-slate-700 text-slate-400'}>{family.status}</Badge>
            </div>
          </div>

          <Card className="bg-slate-800 border-slate-700">
            <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-300">Performance</CardTitle></CardHeader>
            <CardContent className="grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-lg font-bold text-emerald-400">{((pm.resolution_success_rate || 0) * 100).toFixed(0)}%</p>
                <p className="text-[10px] text-slate-500">Resolution</p>
              </div>
              <div>
                <p className="text-lg font-bold text-blue-400">{((pm.automation_success_rate || 0) * 100).toFixed(0)}%</p>
                <p className="text-[10px] text-slate-500">Automation</p>
              </div>
              <div>
                <p className="text-lg font-bold text-amber-400">{pm.mislabel_count || 0}</p>
                <p className="text-[10px] text-slate-500">Mislabels</p>
              </div>
            </CardContent>
          </Card>

          {Object.keys(entityDist).length > 0 && (
            <Card className="bg-slate-800 border-slate-700">
              <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-300">BC Entity Distribution</CardTitle></CardHeader>
              <CardContent className="space-y-1.5">
                {Object.entries(entityDist).sort((a,b) => b[1]-a[1]).map(([entity, count]) => (
                  <div key={entity} className="flex justify-between text-xs">
                    <span className="text-slate-400 font-mono">{entity}</span>
                    <span className="text-white font-medium">{count}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {Object.keys(labelDist).length > 0 && (
            <Card className="bg-slate-800 border-slate-700">
              <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-300">Reference Labels</CardTitle></CardHeader>
              <CardContent className="space-y-1.5">
                {Object.entries(labelDist).sort((a,b) => b[1]-a[1]).map(([label, count]) => (
                  <div key={label} className="flex justify-between text-xs">
                    <span className="text-slate-400">{label}</span>
                    <span className="text-white font-medium">{count}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {recentDocs.length > 0 && (
            <Card className="bg-slate-800 border-slate-700">
              <CardHeader className="pb-2"><CardTitle className="text-sm text-slate-300">Recent Documents ({recentDocs.length})</CardTitle></CardHeader>
              <CardContent className="space-y-1.5">
                {recentDocs.map(d => (
                  <div key={d.document_id} className="flex justify-between items-center text-xs py-1 border-b border-slate-700/50 last:border-0">
                    <a href={`/documents/${encodeURIComponent(d.document_id)}`} className="text-blue-400 hover:underline font-mono truncate max-w-[180px]">{d.document_id.substring(0, 12)}...</a>
                    <span className="text-slate-500">{d.layout_similarity_score ? `${(d.layout_similarity_score * 100).toFixed(0)}%` : '-'}</span>
                    <span className="text-slate-600">{d.created_at ? new Date(d.created_at).toLocaleDateString() : ''}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <div className="text-[10px] text-slate-600 space-y-0.5">
            <p>First seen: {family.first_seen ? new Date(family.first_seen).toLocaleString() : '-'}</p>
            <p>Last seen: {family.last_seen ? new Date(family.last_seen).toLocaleString() : '-'}</p>
          </div>
        </div>
      </SheetContent>
    </Sheet>
  );
}

export default function LayoutFingerprintsPage() {
  const [stats, setStats] = useState(null);
  const [families, setFamilies] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedFamily, setSelectedFamily] = useState(null);
  const [detailOpen, setDetailOpen] = useState(false);
  const [vendorFilter, setVendorFilter] = useState('');
  const [docTypeFilter, setDocTypeFilter] = useState('all');
  const [backfilling, setBackfilling] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (vendorFilter) params.set('vendor_no', vendorFilter);
      if (docTypeFilter && docTypeFilter !== 'all') params.set('doc_type', docTypeFilter);

      const [statsRes, familiesRes, alertsRes] = await Promise.all([
        fetch(`${API}/api/layout-fingerprints/stats`),
        fetch(`${API}/api/layout-fingerprints/families?${params}`),
        fetch(`${API}/api/layout-fingerprints/alerts`),
      ]);
      if (statsRes.ok) setStats(await statsRes.json());
      if (familiesRes.ok) { const d = await familiesRes.json(); setFamilies(d.families || []); }
      if (alertsRes.ok) { const d = await alertsRes.json(); setAlerts(d.alerts || []); }
    } catch (e) { console.error('Fetch error:', e); }
    setLoading(false);
  }, [vendorFilter, docTypeFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleFamilyClick = async (family) => {
    try {
      const res = await fetch(`${API}/api/layout-fingerprints/families/${family.layout_family_id}`);
      if (res.ok) { setSelectedFamily(await res.json()); setDetailOpen(true); }
    } catch (e) { console.error(e); }
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      const res = await fetch(`${API}/api/layout-fingerprints/backfill?limit=200`, { method: 'POST' });
      if (res.ok) {
        const r = await res.json();
        toast.success(`Backfill complete: ${r.generated} fingerprints generated, ${r.skipped} skipped`);
        fetchData();
      }
    } catch (e) { toast.error('Backfill failed'); }
    setBackfilling(false);
  };

  const docTypes = [...new Set(families.map(f => f.document_type))];
  const vendors = [...new Set(families.map(f => f.vendor_no).filter(Boolean))];

  return (
    <div data-testid="layout-fingerprints-page" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <Fingerprint className="h-6 w-6 text-blue-400" />
            Layout Fingerprints
          </h1>
          <p className="text-sm text-slate-400 mt-1">Structural document families — soft signals, not templates</p>
        </div>
        <div className="flex gap-2">
          <Button data-testid="backfill-btn" variant="outline" size="sm" onClick={handleBackfill} disabled={backfilling}
            className="border-slate-600 text-slate-300 hover:bg-slate-800">
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${backfilling ? 'animate-spin' : ''}`} />
            {backfilling ? 'Backfilling...' : 'Backfill'}
          </Button>
          <Button variant="outline" size="sm" onClick={fetchData} className="border-slate-600 text-slate-300 hover:bg-slate-800">
            <RefreshCw className="h-3.5 w-3.5 mr-1.5" /> Refresh
          </Button>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard title="Layout Families" value={stats?.total_families ?? '-'} icon={Layers} color="blue" subtitle="Active families" />
        <StatCard title="Fingerprints" value={stats?.total_fingerprints ?? '-'} icon={Fingerprint} color="green" subtitle="Documents analyzed" />
        <StatCard title="Vendors" value={stats?.vendors_with_families ?? '-'} icon={FolderTree} color="violet" subtitle="With known layouts" />
        <StatCard title="New Layouts" value={stats?.new_layouts_detected ?? '-'} icon={AlertTriangle} color="amber" subtitle="Format changes detected" />
      </div>

      {/* Alerts */}
      {alerts.length > 0 && (
        <Card data-testid="layout-alerts" className="bg-slate-900 border-l-4 border-l-amber-500 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-amber-400 flex items-center gap-2">
              <AlertTriangle className="h-4 w-4" /> Families Needing Attention ({alerts.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {alerts.slice(0, 5).map((a, i) => (
              <div key={i} className="flex items-center justify-between text-xs bg-slate-800 rounded p-2">
                <div className="flex items-center gap-2">
                  <Badge variant="outline" className={a.severity === 'critical' ? 'border-red-600 text-red-400' : 'border-amber-600 text-amber-400'}>
                    {a.severity}
                  </Badge>
                  <span className="text-slate-300 font-mono">{a.layout_family_id}</span>
                </div>
                <span className="text-slate-500">{a.message}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Doc Type Distribution */}
      {stats?.document_type_distribution?.length > 0 && (
        <Card className="bg-slate-900 border-slate-700">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm text-slate-300">By Document Type</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {stats.document_type_distribution.map(d => (
                <div key={d.doc_type} className="bg-slate-800 rounded px-3 py-1.5 text-xs">
                  <span className="text-slate-400">{d.doc_type}</span>
                  <span className="text-white font-bold ml-2">{d.family_count} families</span>
                  <span className="text-slate-500 ml-1">({d.total_docs} docs)</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex gap-3 items-center">
        <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
          <SelectTrigger data-testid="doctype-filter" className="w-[180px] bg-slate-800 border-slate-700 text-slate-300 h-8 text-xs">
            <SelectValue placeholder="All doc types" />
          </SelectTrigger>
          <SelectContent className="bg-slate-800 border-slate-700">
            <SelectItem value="all" className="text-slate-300 text-xs">All doc types</SelectItem>
            {docTypes.map(t => <SelectItem key={t} value={t} className="text-slate-300 text-xs">{t}</SelectItem>)}
          </SelectContent>
        </Select>
        {vendors.length > 0 && (
          <Select value={vendorFilter || 'all'} onValueChange={v => setVendorFilter(v === 'all' ? '' : v)}>
            <SelectTrigger data-testid="vendor-filter" className="w-[200px] bg-slate-800 border-slate-700 text-slate-300 h-8 text-xs">
              <SelectValue placeholder="All vendors" />
            </SelectTrigger>
            <SelectContent className="bg-slate-800 border-slate-700">
              <SelectItem value="all" className="text-slate-300 text-xs">All vendors</SelectItem>
              {vendors.map(v => <SelectItem key={v} value={v} className="text-slate-300 text-xs truncate">{v}</SelectItem>)}
            </SelectContent>
          </Select>
        )}
        <span className="text-xs text-slate-500 ml-auto">{families.length} families</span>
      </div>

      {/* Families Table */}
      <Card className="bg-slate-900 border-slate-700">
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-slate-700 text-xs text-slate-500 uppercase tracking-wider">
                  <th className="p-3 text-left font-medium">Family ID</th>
                  <th className="p-3 text-left font-medium">Vendor</th>
                  <th className="p-3 text-left font-medium">Doc Type</th>
                  <th className="p-3 text-right font-medium">Docs</th>
                  <th className="p-3 text-right font-medium">Resolution</th>
                  <th className="p-3 text-right font-medium">Automation</th>
                  <th className="p-3 text-right font-medium">Mislabels</th>
                  <th className="p-3 text-left font-medium">Last Seen</th>
                  <th className="p-3 w-8"></th>
                </tr>
              </thead>
              <tbody>
                {loading ? (
                  <tr><td colSpan={9} className="text-center text-sm text-slate-500 p-8">Loading...</td></tr>
                ) : families.length === 0 ? (
                  <tr><td colSpan={9} className="text-center text-sm text-slate-500 p-8">
                    No layout families yet. Fingerprints are generated during document processing or via Backfill.
                  </td></tr>
                ) : families.map(f => (
                  <FamilyRow key={f.layout_family_id} family={f} onClick={handleFamilyClick} />
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      <FamilyDetailSheet family={selectedFamily} open={detailOpen} onClose={() => setDetailOpen(false)} />
    </div>
  );
}
