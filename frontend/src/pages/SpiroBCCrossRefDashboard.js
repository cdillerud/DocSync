import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Link2, Unlink, Building2, Users, DollarSign, AlertTriangle, CheckCircle, ArrowRight, Search } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ label, value, sub, icon: Icon, color = "text-primary" }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
        {Icon && <Icon className={`h-4 w-4 ${color}`} />}
      </div>
      <div className="text-2xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function CompanyRow({ company, type }) {
  const bgColor = type === 'both' ? 'bg-emerald-500/5' : type === 'spiro' ? 'bg-blue-500/5' : 'bg-orange-500/5';
  const dotColor = type === 'both' ? 'bg-emerald-400' : type === 'spiro' ? 'bg-blue-400' : 'bg-orange-400';

  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-md ${bgColor} text-sm`}>
      <div className={`w-2 h-2 rounded-full ${dotColor} flex-shrink-0`} />
      <div className="flex-1 min-w-0">
        <div className="font-medium truncate">{company.name || company.bc_customer_name || '—'}</div>
        <div className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
          {company.spiro_id && <span>Spiro #{company.spiro_id}</span>}
          {company.bc_customer_no && <span>BC: {company.bc_customer_no}</span>}
          {company.external_id && <span>Ext: {company.external_id}</span>}
          {company.relationship_type && <span className="px-1.5 py-0 rounded bg-muted text-[10px]">{company.relationship_type}</span>}
          {company.assigned_isr && <span>ISR: {company.assigned_isr}</span>}
        </div>
      </div>
      <div className="text-right flex-shrink-0">
        <div className="text-xs font-medium">{company.doc_count} doc{company.doc_count !== 1 ? 's' : ''}</div>
        {company.opportunities > 0 && (
          <div className="text-[10px] text-muted-foreground">{company.opportunities} opp</div>
        )}
      </div>
    </div>
  );
}

function ISRRow({ isr }) {
  const bcPct = isr.companies > 0 ? Math.round(isr.with_bc / isr.companies * 100) : 0;
  return (
    <div className="flex items-center gap-3 px-3 py-2 border-b border-border/30 text-sm last:border-0">
      <div className="flex-1 min-w-0">
        <div className="font-medium">{isr.isr}</div>
      </div>
      <div className="grid grid-cols-4 gap-4 text-right text-xs">
        <div>
          <div className="font-medium">{isr.companies}</div>
          <div className="text-muted-foreground">companies</div>
        </div>
        <div>
          <div className="font-medium">{isr.docs}</div>
          <div className="text-muted-foreground">docs</div>
        </div>
        <div>
          <div className="font-medium">{isr.opportunities}</div>
          <div className="text-muted-foreground">opps</div>
        </div>
        <div>
          <div className={`font-medium ${bcPct >= 80 ? 'text-emerald-400' : bcPct >= 50 ? 'text-yellow-400' : 'text-red-400'}`}>{bcPct}%</div>
          <div className="text-muted-foreground">in BC</div>
        </div>
      </div>
    </div>
  );
}

export default function SpiroBCCrossRefDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [matching, setMatching] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [searchResults, setSearchResults] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/inside-sales-pilot/spiro-bc-crossref`);
      setData(await res.json());
    } catch (e) {
      console.error('Failed to load cross-ref data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const runMatchAll = async () => {
    setMatching(true);
    try {
      await fetch(`${API}/api/inside-sales-pilot/spiro-match-all`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 2000));
      await fetchData();
    } finally { setMatching(false); }
  };

  const searchSpiro = async () => {
    if (searchTerm.length < 2) return;
    try {
      const res = await fetch(`${API}/api/inside-sales-pilot/spiro-search?name=${encodeURIComponent(searchTerm)}`);
      setSearchResults(await res.json());
    } catch (e) { console.error(e); }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading cross-reference data...</div>;
  }

  const s = data?.summary || {};
  const pipeline = data?.pipeline || {};
  const xref = data?.cross_reference || {};
  const isrs = data?.isr_coverage || [];
  const unmatched = data?.unmatched_documents || [];

  return (
    <div className="space-y-6" data-testid="spiro-bc-crossref-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Spiro ↔ BC Cross-Reference</h2>
          <p className="text-sm text-muted-foreground">Customer alignment between CRM pipeline and Business Central</p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={runMatchAll}
            disabled={matching}
            data-testid="match-all-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Link2 className={`h-3.5 w-3.5 ${matching ? 'animate-spin' : ''}`} />
            {matching ? 'Matching...' : 'Match All'}
          </button>
          <button onClick={fetchData} className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </button>
        </div>
      </div>

      {/* Top Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <StatCard label="Intake Docs" value={s.total_pilot_docs || 0} icon={Building2} />
        <StatCard label="In Both Systems" value={s.in_both || 0} sub="Fully linked" icon={CheckCircle} color="text-emerald-400" />
        <StatCard label="Spiro Only" value={s.spiro_only || 0} sub="Not in BC" icon={Unlink} color="text-blue-400" />
        <StatCard label="BC Only" value={s.bc_only || 0} sub="Not in Spiro" icon={AlertTriangle} color="text-orange-400" />
        <StatCard label="Pipeline Value" value={`$${(pipeline.total_pipeline_value || 0).toLocaleString()}`} sub={`${pipeline.total_opportunities || 0} opportunities`} icon={DollarSign} color="text-green-400" />
        <StatCard label="No Match" value={s.no_match_either || 0} sub="Neither system" icon={Unlink} color="text-red-400" />
      </div>

      {/* Spiro Search */}
      <div className="bg-card border border-border rounded-lg p-4">
        <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
          <Search className="h-4 w-4 text-primary" /> Spiro Company Lookup
        </h3>
        <div className="flex gap-2">
          <input
            type="text"
            value={searchTerm}
            onChange={e => setSearchTerm(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && searchSpiro()}
            placeholder="Search Spiro by company name..."
            className="flex-1 px-3 py-1.5 text-sm rounded-md border border-border bg-background"
            data-testid="spiro-search-input"
          />
          <button onClick={searchSpiro} className="px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground" data-testid="spiro-search-btn">Search</button>
        </div>
        {searchResults && (
          <div className="mt-3 space-y-1">
            {searchResults.results?.length > 0 ? searchResults.results.map((c, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 bg-muted/30 rounded-md text-sm">
                <div className="w-2 h-2 rounded-full bg-blue-400 flex-shrink-0" />
                <div className="flex-1">
                  <span className="font-medium">{c.name}</span>
                  <span className="text-muted-foreground ml-2 text-xs">
                    {c.city && `${c.city}, ${c.state}`} {c.relationship_type && `· ${c.relationship_type}`} {c.assigned_isr && `· ISR: ${c.assigned_isr}`}
                  </span>
                </div>
                {c.external_id && <span className="text-xs font-mono bg-muted px-1.5 py-0.5 rounded">{c.external_id}</span>}
              </div>
            )) : <p className="text-sm text-muted-foreground">No results found.</p>}
          </div>
        )}
      </div>

      {/* Three-column cross-reference */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* In Both */}
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-emerald-400" />
            In Both Systems ({(xref.matched_both_systems || []).length})
          </h3>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {(xref.matched_both_systems || []).map((c, i) => <CompanyRow key={i} company={c} type="both" />)}
            {!(xref.matched_both_systems || []).length && <p className="text-sm text-muted-foreground">None yet</p>}
          </div>
        </div>

        {/* Spiro Only */}
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Unlink className="h-4 w-4 text-blue-400" />
            Spiro Only — Not in BC ({(xref.spiro_only_no_bc || []).length})
          </h3>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {(xref.spiro_only_no_bc || []).map((c, i) => <CompanyRow key={i} company={c} type="spiro" />)}
            {!(xref.spiro_only_no_bc || []).length && <p className="text-sm text-muted-foreground">None</p>}
          </div>
        </div>

        {/* BC Only */}
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-orange-400" />
            BC Only — Not in Spiro ({(xref.bc_only_no_spiro || []).length})
          </h3>
          <div className="space-y-1.5 max-h-[400px] overflow-y-auto">
            {(xref.bc_only_no_spiro || []).map((c, i) => <CompanyRow key={i} company={c} type="bc" />)}
            {!(xref.bc_only_no_spiro || []).length && <p className="text-sm text-muted-foreground">None</p>}
          </div>
        </div>
      </div>

      {/* ISR Coverage */}
      {isrs.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Users className="h-4 w-4 text-primary" />
            ISR Coverage
          </h3>
          <div>
            {isrs.map((isr, i) => <ISRRow key={i} isr={isr} />)}
          </div>
        </div>
      )}

      {/* Unmatched Documents */}
      {unmatched.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-4">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <AlertTriangle className="h-4 w-4 text-red-400" />
            Documents Not Found in Either System ({unmatched.length})
          </h3>
          <div className="space-y-1 max-h-[300px] overflow-y-auto">
            {unmatched.map((doc, i) => (
              <div key={i} className="flex items-center gap-3 px-3 py-2 bg-red-500/5 rounded-md text-sm">
                <div className="w-2 h-2 rounded-full bg-red-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="font-mono text-xs truncate">{doc.file_name}</div>
                  <div className="text-xs text-muted-foreground">{doc.sender} · {doc.customer || 'no customer'} · {doc.mailbox}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
