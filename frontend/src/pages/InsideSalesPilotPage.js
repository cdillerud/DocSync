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

export default function InsideSalesPilotPage() {
  const [status, setStatus] = useState(null);
  const [corpusSummary, setCorpusSummary] = useState(null);
  const [recentDocs, setRecentDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [polling, setPolling] = useState(false);
  const [validatingCorpus, setValidatingCorpus] = useState(false);
  const [corpusResult, setCorpusResult] = useState(null);

  const fetchData = useCallback(async () => {
    try {
      const [statusRes, corpusRes, docsRes] = await Promise.all([
        fetch(`${API}/api/inside-sales-pilot/status`),
        fetch(`${API}/api/inside-sales-pilot/corpus-validation-summary`),
        fetch(`${API}/api/inside-sales-pilot/documents?limit=10`),
      ]);
      setStatus(await statusRes.json());
      setCorpusSummary(await corpusRes.json());
      const docsData = await docsRes.json();
      setRecentDocs(docsData.documents || []);
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
          <h2 className="text-lg font-bold tracking-tight">Inside Sales Pilot</h2>
          <p className="text-sm text-muted-foreground">
            Controlled ingest-only monitoring for {(s.mailboxes || []).join(', ')}
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
          Pilot is disabled. Set INSIDE_SALES_PILOT_ENABLED=true in .env to activate.
        </div>
      )}

      {/* Top Stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Pilot Docs" value={s.total_documents || 0} sub={`${Object.keys(s.by_mailbox || {}).length} mailboxes`} icon={FileText} />
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
                  <th className="pb-2">Mailbox</th>
                </tr>
              </thead>
              <tbody>
                {recentDocs.map((doc) => {
                  const ext = doc.sales_pilot_extraction || {};
                  return (
                    <tr key={doc.id} className="border-b border-border/50 hover:bg-muted/30">
                      <td className="py-2 pr-3 max-w-[200px] truncate font-mono text-xs">{doc.file_name}</td>
                      <td className="py-2 pr-3 max-w-[150px] truncate text-xs">{doc.email_sender}</td>
                      <td className="py-2 pr-3"><span className="text-xs px-1.5 py-0.5 rounded bg-muted">{doc.doc_type}</span></td>
                      <td className="py-2 pr-3 font-mono text-xs">{ext.po_number || '—'}</td>
                      <td className="py-2 pr-3 text-xs max-w-[140px] truncate">{ext.customer_name || '—'}</td>
                      <td className="py-2 pr-3">{ext.extraction_quality_pct != null ? <ScoreBadge score={ext.extraction_quality_pct} /> : '—'}</td>
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
              Compare Inside Sales Pilot against the existing {corpus.validated_count || 0} validated + {corpus.unvalidated_remaining || 0} remaining sales docs
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
              <div className="text-xs font-medium text-muted-foreground uppercase">Inside Sales Pilot</div>
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
