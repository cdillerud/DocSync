import { useState, useEffect, useCallback } from 'react';
import { RefreshCw, Play, Mail, FileText, CheckCircle, XCircle, AlertTriangle, TrendingUp, Search, Filter } from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

function StatCard({ label, value, sub, icon: Icon, color = "text-primary" }) {
  return (
    <div className="bg-card border border-border rounded-lg p-4" data-testid={`stat-${label.toLowerCase().replace(/\s/g, '-')}`}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
        {Icon && <Icon className={`h-4 w-4 ${color}`} />}
      </div>
      <div className="text-2xl font-bold tracking-tight">{value}</div>
      {sub && <div className="text-xs text-muted-foreground mt-0.5">{sub}</div>}
    </div>
  );
}

function ProgressBar({ label, value, max, color = "bg-primary" }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="text-muted-foreground">{label}</span>
        <span className="font-medium">{value}/{max} ({pct}%)</span>
      </div>
      <div className="h-2 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${color} rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ScoreBadge({ score }) {
  const color = score >= 75 ? "text-green-400 bg-green-400/10" :
                score >= 50 ? "text-yellow-400 bg-yellow-400/10" :
                score >= 25 ? "text-orange-400 bg-orange-400/10" :
                "text-red-400 bg-red-400/10";
  return <span className={`text-xs font-bold px-2 py-0.5 rounded ${color}`}>{score}%</span>;
}

/**
 * Pure-SVG donut chart for the BC match-tier distribution.
 * Avoids adding a charting dependency.
 */
function MatchTierDonut({ tiers }) {
  const TIER_CONFIG = [
    { key: 'exact',    label: 'Exact',     color: '#22c55e' },  // emerald
    { key: 'scoped',   label: 'Cust-scoped', color: '#0ea5e9' }, // sky
    { key: 'fuzzy',    label: 'Fuzzy',     color: '#eab308' },  // amber
    { key: 'live',     label: 'Live BC',   color: '#a855f7' },  // violet
    { key: 'no_match', label: 'No match',  color: '#ef4444' },  // red
    { key: 'no_ref',   label: 'No ref',    color: '#475569' },  // slate
  ];

  const buckets = tiers?.buckets || {};
  const total = Object.values(buckets).reduce((a, b) => a + (b || 0), 0);

  // Compute cumulative arc offsets
  const RADIUS = 60;
  const CIRCUM = 2 * Math.PI * RADIUS;
  let cursor = 0;
  const segments = TIER_CONFIG.map(t => {
    const v = buckets[t.key] || 0;
    const frac = total > 0 ? v / total : 0;
    const len = frac * CIRCUM;
    const seg = { ...t, value: v, frac, len, offset: cursor };
    cursor += len;
    return seg;
  });

  // Cache Drift Alarm — fires when exact is low vs matched total OR fuzzy is high vs matched total
  const matched = (buckets.exact || 0) + (buckets.scoped || 0) + (buckets.fuzzy || 0) + (buckets.live || 0);
  const exactShareOfMatched = matched > 0 ? (buckets.exact || 0) / matched : 1;
  const fuzzyShareOfMatched = matched > 0 ? (buckets.fuzzy || 0) / matched : 0;
  const EXACT_FLOOR = 0.80;   // if <80% of matches are exact → drift
  const FUZZY_CEILING = 0.10; // if >10% of matches need fuzzy → drift
  const drift =
    matched >= 10 && exactShareOfMatched < EXACT_FLOOR
      ? { level: 'warn', reason: `Only ${(exactShareOfMatched * 100).toFixed(0)}% of matches are exact-tier (threshold ${EXACT_FLOOR * 100}%). Extraction quality or BC cache may be drifting.` }
      : matched >= 10 && fuzzyShareOfMatched > FUZZY_CEILING
      ? { level: 'warn', reason: `Fuzzy tier carrying ${(fuzzyShareOfMatched * 100).toFixed(0)}% of matches (threshold ${FUZZY_CEILING * 100}%). Exact-tier cache hit rate is eroding.` }
      : null;

  if (total === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-muted-foreground" data-testid="match-tier-donut-empty">
        No validated pilot documents yet.
      </div>
    );
  }

  return (
    <div className="space-y-3" data-testid="match-tier-donut">
      {drift && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-2 flex items-start gap-2 text-xs" data-testid="cache-drift-alarm">
          <AlertTriangle className="h-4 w-4 text-amber-400 shrink-0 mt-0.5" />
          <div>
            <div className="font-semibold text-amber-300">Cache Drift Alarm</div>
            <div className="text-amber-200/90">{drift.reason}</div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-5">
        <svg width="160" height="160" viewBox="0 0 160 160" className="shrink-0">
          <g transform="rotate(-90 80 80)">
            {/* Background ring */}
            <circle cx="80" cy="80" r={RADIUS} fill="transparent" stroke="hsl(var(--muted))" strokeWidth="20" />
            {/* Segments */}
            {segments.filter(s => s.len > 0).map(s => (
              <circle
                key={s.key}
                cx="80"
                cy="80"
                r={RADIUS}
                fill="transparent"
                stroke={s.color}
                strokeWidth="20"
                strokeDasharray={`${s.len} ${CIRCUM - s.len}`}
                strokeDashoffset={-s.offset}
              />
            ))}
          </g>
          {/* Center label */}
          <text x="80" y="74" textAnchor="middle" className="fill-foreground font-bold" fontSize="24">
            {tiers?.match_rate_pct ?? 0}%
          </text>
          <text x="80" y="96" textAnchor="middle" className="fill-muted-foreground" fontSize="10">
            {tiers?.matched_docs ?? 0} / {tiers?.total_docs ?? 0}
          </text>
        </svg>
        <div className="flex-1 space-y-1.5">
          {segments.map(s => (
            <div key={s.key} className="flex items-center gap-2 text-xs">
              <span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ backgroundColor: s.color }} />
              <span className="flex-1 text-muted-foreground">{s.label}</span>
              <span className="font-mono font-medium">{s.value}</span>
              <span className="text-muted-foreground/60 text-[10px] w-10 text-right">{(s.frac * 100).toFixed(0)}%</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function InsideSalesPilotPage() {
  const [status, setStatus] = useState(null);
  const [corpusSummary, setCorpusSummary] = useState(null);
  const [recentDocs, setRecentDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [validatingCorpus, setValidatingCorpus] = useState(false);
  const [corpusResult, setCorpusResult] = useState(null);
  const [tierDist, setTierDist] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, corpusRes, docsRes, tierRes] = await Promise.all([
        fetch(`${API}/api/inside-sales-pilot/status`),
        fetch(`${API}/api/inside-sales-pilot/corpus-validation-summary`),
        fetch(`${API}/api/inside-sales-pilot/documents?limit=10`),
        fetch(`${API}/api/inside-sales-pilot/match-tier-distribution`),
      ]);
      setStatus(await statusRes.json());
      setCorpusSummary(await corpusRes.json());
      const docsData = await docsRes.json();
      setRecentDocs(docsData.documents || []);
      setTierDist(await tierRes.json());
    } catch (e) {
      console.error('Failed to load pilot data:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const triggerPoll = async () => {
    setPolling(true);
    try {
      await fetch(`${API}/api/inside-sales-pilot/poll-now`, { method: 'POST' });
      await new Promise(r => setTimeout(r, 2000));
      await fetchData();
    } finally { setPolling(false); }
  };

  const runCorpusValidation = async () => {
    setValidatingCorpus(true);
    setCorpusResult(null);
    try {
      const res = await fetch(`${API}/api/inside-sales-pilot/validate-sales-corpus?batch_size=200`, { method: 'POST' });
      const data = await res.json();
      setCorpusResult(data);
      await fetchData();
    } finally { setValidatingCorpus(false); }
  };

  if (loading) {
    return <div className="flex items-center justify-center py-20 text-muted-foreground">Loading pilot data...</div>;
  }

  const s = status || {};
  const ext = s.extraction || {};
  const bc = s.bc_validation || {};
  const last24 = s.last_24h || {};
  const fieldRates = ext.field_hit_rates || {};
  const corpus = corpusSummary?.corpus || {};
  const pilot = corpusSummary?.pilot || {};

  const parseRate = (str) => {
    if (!str) return [0, 0];
    const parts = str.split('/');
    return [parseInt(parts[0]) || 0, parseInt(parts[1]) || 0];
  };

  return (
    <div className="space-y-6" data-testid="inside-sales-pilot-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-bold tracking-tight">Sales Intake</h2>
          <p className="text-sm text-muted-foreground">
            Monitored mailboxes: {(s.mailboxes || []).join(', ')}
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={triggerPoll}
            disabled={polling || !s.enabled}
            data-testid="poll-now-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            <Play className={`h-3.5 w-3.5 ${polling ? 'animate-spin' : ''}`} />
            {polling ? 'Polling...' : 'Poll Now'}
          </button>
          <button
            onClick={fetchData}
            data-testid="refresh-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-border hover:bg-accent"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        </div>
      </div>

      {/* Enabled/Disabled Banner */}
      {!s.enabled && (
        <div className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg px-4 py-3 flex items-center gap-2 text-yellow-400 text-sm" data-testid="pilot-disabled-banner">
          <AlertTriangle className="h-4 w-4" />
          Sales intake polling is disabled. Set INSIDE_SALES_PILOT_ENABLED=true in .env to activate.
        </div>
      )}

      {/* Top Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Intake Docs" value={s.total_documents || 0} sub={`${Object.keys(s.by_mailbox || {}).length} mailboxes`} icon={FileText} />
        <StatCard label="Extraction Quality" value={`${ext.avg_quality_pct || 0}%`} sub={ext.coverage || '0/0'} icon={TrendingUp} color="text-green-400" />
        <StatCard label="BC Match Score" value={`${bc.avg_score_pct || 0}%`} sub={bc.validated || '0/0'} icon={CheckCircle} color="text-blue-400" />
        <StatCard label="Signal:Noise" value={last24.signal_to_noise || '0:0'} sub={`${last24.poll_runs || 0} runs (24h)`} icon={Filter} color="text-purple-400" />
        <StatCard label="Messages Scanned" value={last24.messages_scanned || 0} sub={`${last24.attachments_ingested || 0} ingested`} icon={Mail} color="text-cyan-400" />
      </div>

      {/* Two Column: Extraction + BC Validation */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Extraction Quality */}
        <div className="bg-card border border-border rounded-lg p-4 space-y-3" data-testid="extraction-quality-card">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <Search className="h-4 w-4 text-primary" />
            Extraction Field Hit Rates
          </h3>
          {s.total_documents > 0 ? (
            <>
              {Object.entries(fieldRates).map(([field, rate]) => {
                const [val, max] = parseRate(rate);
                const label = field.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
                return <ProgressBar key={field} label={label} value={val} max={max} />;
              })}
            </>
          ) : (
            <p className="text-sm text-muted-foreground">No pilot documents yet.</p>
          )}
        </div>

        {/* BC Validation */}
        <div className="bg-card border border-border rounded-lg p-4 space-y-3" data-testid="bc-validation-card">
          <h3 className="text-sm font-semibold flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-blue-400" />
            BC Production Validation
          </h3>
          {bc.validated && bc.validated !== '0/0' ? (
            <>
              <ProgressBar label="Customer Match" {...(() => { const [v,m] = parseRate(bc.customer_match_rate); return {value:v, max:m}; })()} color="bg-green-500" />
              <ProgressBar label="Order Match" {...(() => { const [v,m] = parseRate(bc.order_match_rate); return {value:v, max:m}; })()} color="bg-blue-500" />
            </>
          ) : (
            <p className="text-sm text-muted-foreground">Run validation to see results.</p>
          )}
        </div>
      </div>

      {/* Match Tier Distribution (donut) — canary for extraction / BC sync quality */}
      <div className="bg-card border border-border rounded-lg p-4 space-y-3" data-testid="match-tier-card">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              BC Order Match — Tier Distribution
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Where documents matched: exact (best) → fuzzy (weaker) → no match. A drop in
              the exact slice while fuzzy rises is an early warning of extraction drift or
              BC cache drift.
            </p>
          </div>
        </div>
        <MatchTierDonut tiers={tierDist} />
      </div>

      {/* By Mailbox */}
      {Object.keys(s.by_mailbox || {}).length > 0 && (
        <div className="bg-card border border-border rounded-lg p-4" data-testid="by-mailbox-card">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <Mail className="h-4 w-4 text-primary" />
            Documents by Mailbox
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {Object.entries(s.by_mailbox).map(([mb, count]) => (
              <div key={mb} className="flex items-center justify-between bg-muted/50 rounded-md px-3 py-2">
                <span className="text-sm font-mono truncate">{mb}</span>
                <span className="text-sm font-bold ml-2">{count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent Pilot Documents */}
      {recentDocs.length > 0 && (
        <div className="bg-card border border-border rounded-lg p-4" data-testid="recent-docs-card">
          <h3 className="text-sm font-semibold mb-3 flex items-center gap-2">
            <FileText className="h-4 w-4 text-primary" />
            Recent Pilot Documents
          </h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="pb-2 pr-3">File</th>
                  <th className="pb-2 pr-3">Sender</th>
                  <th className="pb-2 pr-3">Type</th>
                  <th className="pb-2 pr-3">PO</th>
                  <th className="pb-2 pr-3">Customer</th>
                  <th className="pb-2 pr-3">Quality</th>
                  <th className="pb-2 pr-3">BC Match</th>
                  <th className="pb-2">Mailbox</th>
                </tr>
              </thead>
              <tbody>
                {recentDocs.map((doc) => {
                  const ext = doc.sales_pilot_extraction || {};
                  const bcv = doc.bc_prod_validation || {};
                  const ol = bcv.order_lookup || {};
                  const matchEntity = ol.bc_entity_type || null;
                  const matchMethod = ol.match_method || '';
                  const entityConfig = {
                    sales_order: { label: 'Open SO', cls: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40' },
                    posted_sales_invoice: { label: 'Posted Inv', cls: 'bg-amber-500/20 text-amber-300 border-amber-500/40' },
                    posted_sales_shipment: { label: 'Shipment', cls: 'bg-sky-500/20 text-sky-300 border-sky-500/40' },
                  }[matchEntity] || null;
                  const tier = matchMethod.startsWith('fuzzy_normalized') ? 'fuzzy'
                             : matchMethod.startsWith('customer_scoped') ? 'scoped'
                             : matchMethod.startsWith('live_bc') ? 'live'
                             : matchMethod ? 'exact' : null;
                  return (
                    <tr key={doc.id} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-2 pr-3 max-w-[200px] truncate font-mono text-xs">{doc.file_name}</td>
                      <td className="py-2 pr-3 max-w-[150px] truncate text-xs">{doc.email_sender}</td>
                      <td className="py-2 pr-3"><span className="text-xs px-1.5 py-0.5 rounded bg-muted">{doc.doc_type}</span></td>
                      <td className="py-2 pr-3 font-mono text-xs">{ext.po_number || '—'}</td>
                      <td className="py-2 pr-3 text-xs max-w-[140px] truncate">{ext.customer_name || '—'}</td>
                      <td className="py-2 pr-3">{ext.extraction_quality_pct != null ? <ScoreBadge score={ext.extraction_quality_pct} /> : '—'}</td>
                      <td className="py-2 pr-3" data-testid={`bc-match-${doc.id}`}>
                        {entityConfig ? (
                          <div className="flex items-center gap-1">
                            <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${entityConfig.cls}`} title={`Matched via ${matchMethod}`}>
                              {entityConfig.label}
                            </span>
                            {tier === 'fuzzy' && (
                              <span className="text-[9px] text-muted-foreground uppercase tracking-wider" title="Matched via fuzzy/normalized search (lower confidence)">~</span>
                            )}
                            {tier === 'scoped' && (
                              <span className="text-[9px] text-muted-foreground uppercase tracking-wider" title="Matched via customer-scoped search">c</span>
                            )}
                          </div>
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </td>
                      <td className="py-2 text-xs truncate max-w-[180px]">{doc.pilot_mailbox}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Corpus Validation Section */}
      <div className="bg-card border border-border rounded-lg p-4 space-y-4" data-testid="corpus-validation-card">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-semibold flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-orange-400" />
              Sales Corpus Validation
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Compare the Sales Intake pipeline against the existing {corpus.validated_count || 0} validated + {corpus.unvalidated_remaining || 0} remaining sales docs
            </p>
          </div>
          <button
            onClick={runCorpusValidation}
            disabled={validatingCorpus}
            data-testid="run-corpus-validation-btn"
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm rounded-md border border-orange-500/30 text-orange-400 hover:bg-orange-500/10 disabled:opacity-50"
          >
            <Play className={`h-3.5 w-3.5 ${validatingCorpus ? 'animate-spin' : ''}`} />
            {validatingCorpus ? 'Validating...' : `Validate Batch (${corpus.unvalidated_remaining || 0} remaining)`}
          </button>
        </div>

        {corpusResult && (
          <div className="bg-muted/30 rounded-md px-3 py-2 text-xs space-y-1" data-testid="corpus-batch-result">
            <div className="font-medium">Batch complete: {corpusResult.validated}/{corpusResult.processed} validated, avg score {corpusResult.avg_score || 0}%, {corpusResult.remaining} remaining</div>
            {corpusResult.score_distribution && (
              <div className="text-muted-foreground">
                Scores: {Object.entries(corpusResult.score_distribution).map(([k,v]) => `${k}: ${v}`).join(' | ')}
              </div>
            )}
          </div>
        )}

        {/* Side-by-side comparison */}
        {(corpus.validated_count > 0 || pilot.validated_count > 0) && (
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground uppercase">Existing Pipeline</div>
              <div className="text-2xl font-bold">{corpus.avg_score || 0}%<span className="text-sm font-normal text-muted-foreground ml-1">avg</span></div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Validated</span><span>{corpus.validated_count || 0} docs</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Customer Match</span><span>{corpus.customer_match_rate || '0%'}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Order Match</span><span>{corpus.order_match_rate || '0%'}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Item Match</span><span>{corpus.item_match_rate || '0%'}</span></div>
              </div>
            </div>
            <div className="space-y-2">
              <div className="text-xs font-medium text-muted-foreground uppercase">Sales Intake</div>
              <div className="text-2xl font-bold">{pilot.avg_score || 0}%<span className="text-sm font-normal text-muted-foreground ml-1">avg</span></div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span className="text-muted-foreground">Validated</span><span>{pilot.validated_count || 0} docs</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Customer Match</span><span>{pilot.customer_match_rate || '0%'}</span></div>
                <div className="flex justify-between"><span className="text-muted-foreground">Order Match</span><span>{pilot.order_match_rate || '0%'}</span></div>
              </div>
            </div>
          </div>
        )}

        {/* Top Customers */}
        {corpus.top_customers && corpus.top_customers.length > 0 && (
          <div>
            <div className="text-xs font-medium text-muted-foreground uppercase mb-2">Top Validated Customers (Corpus)</div>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
              {corpus.top_customers.slice(0, 10).map((c, i) => (
                <div key={i} className="bg-muted/30 rounded px-2 py-1.5 text-xs">
                  <div className="font-medium truncate">{c.customer_no}</div>
                  <div className="text-muted-foreground truncate">{c.name}</div>
                  <div className="flex justify-between mt-0.5">
                    <span>{c.doc_count} docs</span>
                    <ScoreBadge score={c.avg_score} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
