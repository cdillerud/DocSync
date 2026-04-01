import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Database, RefreshCw, CheckCircle, AlertTriangle, Loader2 } from 'lucide-react';
import { toast } from 'sonner';
import api from '../lib/api';

const MetricCard = ({ label, value, subtext, healthy }) => (
  <Card data-testid={`metric-${label.toLowerCase().replace(/\s/g, '-')}`}>
    <CardContent className="p-4">
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs text-muted-foreground uppercase tracking-wide">{label}</span>
        {healthy !== undefined && (
          healthy
            ? <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />
            : <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
        )}
      </div>
      <div className="text-2xl font-bold tabular-nums">{typeof value === 'number' ? value.toLocaleString() : value}</div>
      {subtext && <div className="text-xs text-muted-foreground mt-1">{subtext}</div>}
    </CardContent>
  </Card>
);

const SourceBreakdown = ({ data }) => {
  if (!data || Object.keys(data).length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {Object.entries(data).map(([src, count]) => (
        <Badge key={src} variant="secondary" className="text-[10px]">
          {src}: {count.toLocaleString()}
        </Badge>
      ))}
    </div>
  );
};

export default function KnowledgeBasePage() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [seeding, setSeeding] = useState(false);
  const [seedResult, setSeedResult] = useState(null);

  const fetchStatus = useCallback(async () => {
    try {
      setLoading(true);
      const res = await api.get('/knowledge-seed/status');
      setStatus(res.data);
    } catch (err) {
      toast.error('Failed to load knowledge base status');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  const runSeed = async () => {
    setSeeding(true);
    setSeedResult(null);
    try {
      const res = await api.post('/knowledge-seed/run-all');
      setSeedResult(res.data.results);
      toast.success('Knowledge seed complete!');
      fetchStatus();
    } catch (err) {
      toast.error('Seed failed: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSeeding(false);
    }
  };

  const kb = status?.knowledge_base || {};
  const health = status?.health || {};

  return (
    <div data-testid="knowledge-base-page" className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <Database className="w-5 h-5" />
            Knowledge Base
          </h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Intelligence seeded from BC, Spiro, and historical documents
          </p>
        </div>
        <div className="flex items-center gap-3">
          {health.overall && (
            <Badge
              data-testid="kb-health-badge"
              variant={health.overall === 'good' ? 'default' : 'destructive'}
              className={health.overall === 'good' ? 'bg-emerald-500/15 text-emerald-400' : ''}
            >
              {health.overall === 'good' ? 'Healthy' : 'Needs Seeding'}
            </Badge>
          )}
          <Button
            data-testid="run-seed-button"
            onClick={runSeed}
            disabled={seeding}
            size="sm"
            variant="outline"
          >
            {seeding ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <RefreshCw className="w-4 h-4 mr-2" />}
            {seeding ? 'Seeding...' : 'Run Full Seed'}
          </Button>
        </div>
      </div>

      {loading ? (
        <div className="flex justify-center py-12"><Loader2 className="w-6 h-6 animate-spin text-muted-foreground" /></div>
      ) : (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <MetricCard
              label="Vendor Aliases"
              value={kb.vendor_aliases?.total || 0}
              healthy={health.aliases_healthy}
              subtext="Name variants → BC vendor #"
            />
            <MetricCard
              label="Domain Mappings"
              value={kb.sender_domain_mappings?.total || 0}
              healthy={health.domains_healthy}
              subtext="Email domains → vendors"
            />
            <MetricCard
              label="Vendor Profiles"
              value={kb.vendor_invoice_profiles || 0}
              healthy={health.profiles_healthy}
              subtext="Amount stats, PO patterns"
            />
            <MetricCard
              label="BC Reference Cache"
              value={kb.bc_reference_cache || 0}
              subtext="Posted invoices, shipments, POs"
            />
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <MetricCard
              label="Classification Corrections"
              value={kb.classification_corrections || 0}
              subtext="Human corrections → LLM few-shot"
            />
            <MetricCard
              label="Feedback Examples"
              value={kb.classification_feedback_examples || 0}
              subtext="Classification feedback records"
            />
            <MetricCard
              label="Vendor Type Patterns"
              value={kb.vendor_type_patterns || 0}
              subtext="Vendor → doc type hints"
            />
          </div>

          {kb.vendor_aliases?.by_source && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Alias Sources</CardTitle></CardHeader>
              <CardContent><SourceBreakdown data={kb.vendor_aliases.by_source} /></CardContent>
            </Card>
          )}

          {kb.sender_domain_mappings?.by_source && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-sm">Domain Mapping Sources</CardTitle></CardHeader>
              <CardContent><SourceBreakdown data={kb.sender_domain_mappings.by_source} /></CardContent>
            </Card>
          )}
        </>
      )}

      {seedResult && (
        <Card data-testid="seed-result">
          <CardHeader className="pb-2"><CardTitle className="text-sm">Last Seed Result</CardTitle></CardHeader>
          <CardContent className="space-y-2 text-sm">
            <div>
              <span className="font-medium">Aliases:</span>{' '}
              {seedResult.vendor_aliases?.aliases_created || 0} created,{' '}
              {seedResult.vendor_aliases?.aliases_skipped || 0} skipped
              {seedResult.vendor_aliases?.spiro_aliases_created > 0 && (
                <span> + {seedResult.vendor_aliases.spiro_aliases_created} from Spiro</span>
              )}
            </div>
            <div>
              <span className="font-medium">Domains:</span>{' '}
              {seedResult.sender_domains?.domains_from_documents || 0} from docs,{' '}
              {seedResult.sender_domains?.domains_from_spiro || 0} from Spiro
            </div>
            <div>
              <span className="font-medium">Profiles:</span>{' '}
              {seedResult.vendor_profiles?.profiles_created || 0} created,{' '}
              {seedResult.vendor_profiles?.profiles_updated || 0} updated
            </div>
            <div className="text-xs text-muted-foreground">
              Completed in {seedResult.total_elapsed_seconds}s
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
