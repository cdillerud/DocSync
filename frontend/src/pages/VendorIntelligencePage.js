import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Progress } from '../components/ui/progress';
import { toast } from 'sonner';
import {
  Brain, Users, TrendingUp, Shield, Search, RefreshCw, Loader2,
  ChevronRight, ChevronLeft, ArrowUpDown, Activity, Target,
  Truck, Package, FileText, CheckCircle2, AlertTriangle
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const api = (path) => fetch(`${API_URL}/api${path}`).then(r => r.json());
const apiPost = (path) => fetch(`${API_URL}/api${path}`, { method: 'POST' }).then(r => r.json());

const DOMAIN_ICONS = {
  purchase: Package,
  sales: FileText,
  shipping: Truck,
  unknown: Activity,
};

const DOMAIN_COLORS = {
  purchase: 'bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300',
  sales: 'bg-sky-100 text-sky-700 dark:bg-sky-900/30 dark:text-sky-300',
  shipping: 'bg-teal-100 text-teal-700 dark:bg-teal-900/30 dark:text-teal-300',
  unknown: 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400',
};

function MetricCard({ icon: Icon, label, value, sub, color = 'text-foreground' }) {
  return (
    <Card className="border border-border">
      <CardContent className="p-4 flex items-center gap-3">
        <div className="p-2 rounded-lg bg-muted/50">
          <Icon className="w-4 h-4 text-muted-foreground" />
        </div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className={`text-lg font-bold ${color}`}>{value}</p>
          {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
        </div>
      </CardContent>
    </Card>
  );
}

function RateBar({ label, value, color = 'bg-emerald-500' }) {
  const pct = Math.round((value || 0) * 100);
  return (
    <div className="space-y-0.5">
      <div className="flex items-center justify-between text-[11px]">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-mono font-medium">{pct}%</span>
      </div>
      <Progress value={pct} className="h-1.5" />
    </div>
  );
}

function VendorDetailPanel({ profile, onClose }) {
  if (!profile) return null;
  const DIcon = DOMAIN_ICONS[profile.typical_reference_domain] || Activity;

  return (
    <div className="fixed inset-y-0 right-0 w-[420px] bg-background border-l border-border shadow-xl z-50 overflow-y-auto" data-testid="vendor-detail-panel">
      <div className="sticky top-0 bg-background border-b border-border px-4 py-3 flex items-center justify-between">
        <div>
          <h3 className="text-sm font-bold">{profile.vendor_name}</h3>
          <p className="text-[10px] text-muted-foreground font-mono">{profile.vendor_no}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose} className="h-7 w-7 p-0">
          <ChevronRight className="w-4 h-4" />
        </Button>
      </div>

      <div className="p-4 space-y-4">
        {/* Stable badge */}
        <div className="flex items-center gap-2">
          {profile.stable_vendor_flag ? (
            <Badge className="bg-emerald-100 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300">
              <Shield className="w-3 h-3 mr-1" /> Stable Vendor
            </Badge>
          ) : (
            <Badge variant="outline" className="text-muted-foreground">
              <Activity className="w-3 h-3 mr-1" /> Learning
            </Badge>
          )}
          <Badge variant="outline" className={DOMAIN_COLORS[profile.typical_reference_domain] || DOMAIN_COLORS.unknown}>
            <DIcon className="w-3 h-3 mr-1" />
            {profile.typical_reference_domain || 'unknown'}
          </Badge>
        </div>

        {/* Volume */}
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Document Volume</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 grid grid-cols-3 gap-2 text-center">
            <div>
              <p className="text-lg font-bold">{profile.invoice_count}</p>
              <p className="text-[10px] text-muted-foreground">Total</p>
            </div>
            <div>
              <p className="text-lg font-bold">{profile.freight_invoice_count || 0}</p>
              <p className="text-[10px] text-muted-foreground">Freight</p>
            </div>
            <div>
              <p className="text-lg font-bold">{profile.shipping_document_count || 0}</p>
              <p className="text-[10px] text-muted-foreground">Shipping</p>
            </div>
          </CardContent>
        </Card>

        {/* Reference Behavior */}
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Reference Behavior</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-2">
            <RateBar label="PO References" value={profile.po_reference_frequency} />
            <RateBar label="Shipment References" value={profile.shipment_reference_frequency} />
            <RateBar label="BOL Present" value={profile.bol_presence_rate} />
          </CardContent>
        </Card>

        {/* Automation Performance */}
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Automation Performance</CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-2">
            <RateBar label="Resolution Success" value={profile.reference_resolution_success_rate} />
            <RateBar label="Automation Success" value={profile.automation_success_rate} />
            <RateBar label="Validation Pass" value={profile.validation_pass_rate} />
          </CardContent>
        </Card>

        {/* Typical BC Match Types */}
        {profile.typical_bc_match_types?.length > 0 && (
          <Card className="border border-border">
            <CardHeader className="pb-2 pt-3 px-3">
              <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground">Typical BC Matches</CardTitle>
            </CardHeader>
            <CardContent className="px-3 pb-3 flex flex-wrap gap-1.5">
              {profile.typical_bc_match_types.map((t, i) => (
                <Badge key={i} variant="outline" className="text-[10px] font-mono">
                  {t.replace(/_/g, ' ')}
                  {profile.bc_match_type_counts?.[t] && (
                    <span className="ml-1 text-muted-foreground">({profile.bc_match_type_counts[t]})</span>
                  )}
                </Badge>
              ))}
            </CardContent>
          </Card>
        )}

        {/* Timeline */}
        <div className="text-[10px] text-muted-foreground space-y-1">
          <div className="flex justify-between"><span>First seen:</span><span>{profile.first_document_seen ? new Date(profile.first_document_seen).toLocaleDateString() : '-'}</span></div>
          <div className="flex justify-between"><span>Last seen:</span><span>{profile.last_document_seen ? new Date(profile.last_document_seen).toLocaleDateString() : '-'}</span></div>
          <div className="flex justify-between"><span>Avg match score:</span><span className="font-mono">{((profile.avg_match_score || 0) * 100).toFixed(0)}%</span></div>
        </div>
      </div>
    </div>
  );
}

export default function VendorIntelligencePage() {
  const [stats, setStats] = useState(null);
  const [profiles, setProfiles] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(0);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [rebuilding, setRebuilding] = useState(false);
  const [selectedVendor, setSelectedVendor] = useState(null);
  const [sortBy, setSortBy] = useState('invoice_count');
  const limit = 20;

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      const [s, p] = await Promise.all([
        api('/vendor-intelligence/stats'),
        api(`/vendor-intelligence/profiles?skip=${page * limit}&limit=${limit}&sort_by=${sortBy}`)
      ]);
      setStats(s);
      setProfiles(p.profiles || []);
      setTotal(p.total || 0);
    } catch {
      toast.error('Failed to load vendor intelligence data');
    } finally {
      setLoading(false);
    }
  }, [page, sortBy]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRebuild = async () => {
    try {
      setRebuilding(true);
      await apiPost('/vendor-intelligence/rebuild');
      toast.success('Vendor profile rebuild started');
      setTimeout(fetchData, 5000);
    } catch {
      toast.error('Rebuild failed');
    } finally {
      setRebuilding(false);
    }
  };

  const filtered = search
    ? profiles.filter(p =>
        (p.vendor_name || '').toLowerCase().includes(search.toLowerCase()) ||
        (p.vendor_no || '').toLowerCase().includes(search.toLowerCase())
      )
    : profiles;

  return (
    <div className="space-y-6" data-testid="vendor-intelligence-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Vendor Intelligence</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Behavioral profiles learned from document processing</p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchData} className="h-8 text-xs gap-1" data-testid="refresh-vendor-intel">
            <RefreshCw className="w-3 h-3" /> Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={handleRebuild} disabled={rebuilding} className="h-8 text-xs gap-1" data-testid="rebuild-vendor-profiles">
            {rebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
            Rebuild Profiles
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="vendor-stats-grid">
          <MetricCard icon={Users} label="Total Vendors" value={stats.total_vendors} />
          <MetricCard icon={Shield} label="Stable Vendors" value={stats.stable_vendors} color="text-emerald-600 dark:text-emerald-400" />
          <MetricCard icon={TrendingUp} label="Avg Automation" value={`${Math.round((stats.avg_automation_rate || 0) * 100)}%`} />
          <MetricCard icon={Target} label="Avg Resolution" value={`${Math.round((stats.avg_resolution_rate || 0) * 100)}%`} />
        </div>
      )}

      {/* Search */}
      <div className="relative max-w-sm">
        <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
        <Input
          placeholder="Search vendors..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          className="pl-8 h-8 text-xs"
          data-testid="vendor-search"
        />
      </div>

      {/* Table */}
      <Card className="border border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs">Vendor</TableHead>
                <TableHead className="text-xs cursor-pointer" onClick={() => setSortBy('invoice_count')}>
                  <div className="flex items-center gap-1">Docs <ArrowUpDown className="w-3 h-3" /></div>
                </TableHead>
                <TableHead className="text-xs">Domain</TableHead>
                <TableHead className="text-xs">PO Rate</TableHead>
                <TableHead className="text-xs">BOL Rate</TableHead>
                <TableHead className="text-xs cursor-pointer" onClick={() => setSortBy('automation_success_rate')}>
                  <div className="flex items-center gap-1">Automation <ArrowUpDown className="w-3 h-3" /></div>
                </TableHead>
                <TableHead className="text-xs cursor-pointer" onClick={() => setSortBy('reference_resolution_success_rate')}>
                  <div className="flex items-center gap-1">Resolution <ArrowUpDown className="w-3 h-3" /></div>
                </TableHead>
                <TableHead className="text-xs">Stable</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && (
                <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground text-xs"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></TableCell></TableRow>
              )}
              {!loading && filtered.length === 0 && (
                <TableRow><TableCell colSpan={8} className="text-center py-8 text-muted-foreground text-xs">
                  {total === 0 ? 'No vendor profiles yet. Click "Rebuild Profiles" to generate from historical data.' : 'No vendors match your search.'}
                </TableCell></TableRow>
              )}
              {!loading && filtered.map((p, idx) => {
                const DIcon = DOMAIN_ICONS[p.typical_reference_domain] || Activity;
                return (
                  <TableRow
                    key={idx}
                    className="cursor-pointer hover:bg-muted/50 transition-colors"
                    onClick={() => setSelectedVendor(p)}
                    data-testid={`vendor-row-${p.vendor_no || idx}`}
                  >
                    <TableCell>
                      <div>
                        <p className="text-xs font-medium truncate max-w-[200px]">{p.vendor_name}</p>
                        {p.vendor_no && p.vendor_no !== p.vendor_name && (
                          <p className="text-[10px] text-muted-foreground font-mono">{p.vendor_no}</p>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="text-xs font-mono">{p.invoice_count}</TableCell>
                    <TableCell>
                      <Badge variant="outline" className={`text-[10px] ${DOMAIN_COLORS[p.typical_reference_domain] || DOMAIN_COLORS.unknown}`}>
                        <DIcon className="w-2.5 h-2.5 mr-0.5" />
                        {p.typical_reference_domain || '?'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-xs font-mono">{Math.round((p.po_reference_frequency || 0) * 100)}%</TableCell>
                    <TableCell className="text-xs font-mono">{Math.round((p.bol_presence_rate || 0) * 100)}%</TableCell>
                    <TableCell className="text-xs font-mono">{Math.round((p.automation_success_rate || 0) * 100)}%</TableCell>
                    <TableCell className="text-xs font-mono">{Math.round((p.reference_resolution_success_rate || 0) * 100)}%</TableCell>
                    <TableCell>
                      {p.stable_vendor_flag ? (
                        <CheckCircle2 className="w-4 h-4 text-emerald-500" />
                      ) : p.invoice_count >= 20 ? (
                        <AlertTriangle className="w-4 h-4 text-amber-400" />
                      ) : (
                        <span className="text-[10px] text-muted-foreground">-</span>
                      )}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* Pagination */}
      {total > limit && (
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span>Showing {page * limit + 1}-{Math.min((page + 1) * limit, total)} of {total}</span>
          <div className="flex gap-1">
            <Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(p => p - 1)} className="h-7 w-7 p-0">
              <ChevronLeft className="w-3 h-3" />
            </Button>
            <Button variant="outline" size="sm" disabled={(page + 1) * limit >= total} onClick={() => setPage(p => p + 1)} className="h-7 w-7 p-0">
              <ChevronRight className="w-3 h-3" />
            </Button>
          </div>
        </div>
      )}

      {/* Vendor Detail Side Panel */}
      {selectedVendor && (
        <>
          <div className="fixed inset-0 bg-black/20 z-40" onClick={() => setSelectedVendor(null)} />
          <VendorDetailPanel profile={selectedVendor} onClose={() => setSelectedVendor(null)} />
        </>
      )}
    </div>
  );
}
