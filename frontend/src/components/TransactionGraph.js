import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { RefreshCw, GitBranch, FileText, Link2, ArrowRight } from 'lucide-react';
import { useNavigate } from 'react-router-dom';

const API = process.env.REACT_APP_BACKEND_URL;

const NODE_TYPE_ICONS = {
  document: FileText,
  purchase_order: FileText,
  sales_order: FileText,
  invoice: FileText,
  bill_of_lading: FileText,
  shipment: FileText,
  customs_entry: FileText,
  bc_record: Link2,
};

const NODE_TYPE_COLORS = {
  document: 'bg-blue-500/20 text-blue-400 border-blue-600',
  purchase_order: 'bg-emerald-500/20 text-emerald-400 border-emerald-700',
  sales_order: 'bg-purple-500/20 text-purple-400 border-purple-600',
  invoice: 'bg-amber-500/20 text-amber-400 border-amber-700',
  bill_of_lading: 'bg-cyan-500/20 text-cyan-400 border-cyan-600',
  shipment: 'bg-teal-500/20 text-teal-400 border-teal-600',
  customs_entry: 'bg-orange-500/20 text-orange-400 border-orange-600',
  bc_record: 'bg-indigo-500/20 text-indigo-400 border-indigo-600',
};

const PROV_COLORS = {
  linked_by_extraction: 'bg-blue-500/20 text-blue-400',
  linked_by_resolver: 'bg-emerald-500/20 text-emerald-400',
  linked_by_processor: 'bg-purple-500/20 text-purple-400',
  linked_by_shared_reference: 'bg-amber-500/20 text-amber-400',
  linked_by_bc_linkage: 'bg-indigo-500/20 text-indigo-400',
  manual: 'bg-gray-500/20 text-gray-400',
};

function ConfidenceBar({ value }) {
  const pct = Math.round((value || 0) * 100);
  const color = pct >= 80 ? 'bg-emerald-500' : pct >= 50 ? 'bg-amber-500' : 'bg-red-500';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] font-mono text-muted-foreground">{pct}%</span>
    </div>
  );
}

export function TransactionGraphPanel({ docId }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  useEffect(() => {
    if (!docId) return;
    setLoading(true);
    fetch(`${API}/api/graph/document/${docId}/connections`)
      .then(r => r.json())
      .then(d => setData(d))
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [docId]);

  if (loading) return <div className="text-xs text-muted-foreground py-4">Loading graph...</div>;
  if (!data?.found) return <div className="text-xs text-muted-foreground py-4">Not in transaction graph yet.</div>;

  const docNodes = (data.nodes || []).filter(n => n.node_type !== 'document');
  const docEdges = data.edges || [];
  const connectedDocs = data.connected_documents || [];

  return (
    <div className="space-y-4" data-testid="transaction-graph-panel">
      {/* Summary */}
      <div className="flex gap-3">
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <GitBranch className="w-3 h-3" />
          <span data-testid="graph-node-count">{data.node_count} nodes</span>
        </div>
        <div className="flex items-center gap-1 text-xs text-muted-foreground">
          <Link2 className="w-3 h-3" />
          <span data-testid="graph-edge-count">{data.edge_count} edges</span>
        </div>
        {connectedDocs.length > 0 && (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            <FileText className="w-3 h-3" />
            <span data-testid="connected-doc-count">{connectedDocs.length} connected docs</span>
          </div>
        )}
      </div>

      {/* Reference nodes */}
      {docNodes.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Reference Nodes</h4>
          <div className="space-y-1">
            {docNodes.map(n => (
              <div key={n.node_id} className="flex items-center gap-2 text-xs py-1 px-2 rounded bg-muted/20" data-testid={`graph-node-${n.node_id}`}>
                <Badge className={`text-[9px] border ${NODE_TYPE_COLORS[n.node_type] || 'bg-gray-500/20 text-gray-400'}`}>
                  {n.node_type.replace(/_/g, ' ')}
                </Badge>
                <span className="font-mono">{n.reference_value}</span>
                {n.vendor_name && <span className="text-muted-foreground">({n.vendor_name})</span>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Edges */}
      {docEdges.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Connections</h4>
          <div className="space-y-1.5">
            {docEdges.slice(0, 15).map(e => (
              <div key={e.edge_id} className="flex items-center gap-2 text-xs" data-testid={`graph-edge-${e.edge_id}`}>
                <Badge className={`text-[9px] ${PROV_COLORS[e.provenance] || 'bg-gray-500/20 text-gray-400'}`}>
                  {e.provenance?.replace('linked_by_', '') || 'unknown'}
                </Badge>
                <span className="text-muted-foreground">{e.edge_type.replace(/_/g, ' ')}</span>
                <div className="flex-1"><ConfidenceBar value={e.confidence} /></div>
              </div>
            ))}
            {docEdges.length > 15 && <p className="text-[10px] text-muted-foreground">...and {docEdges.length - 15} more</p>}
          </div>
        </div>
      )}

      {/* Connected documents */}
      {connectedDocs.length > 0 && (
        <div>
          <h4 className="text-xs font-semibold text-muted-foreground mb-2">Connected Documents</h4>
          <div className="space-y-1">
            {connectedDocs.map(cd => (
              <div
                key={cd.doc_id}
                className="flex items-center gap-2 text-xs py-1.5 px-2 rounded bg-muted/20 hover:bg-muted/40 cursor-pointer transition-colors"
                onClick={() => navigate(`/documents/${cd.doc_id}`)}
                data-testid={`connected-doc-${cd.doc_id}`}
              >
                <Badge variant="outline" className="text-[9px]">{cd.doc_type || 'Unknown'}</Badge>
                <span className="truncate flex-1">{cd.file_name || cd.doc_id.slice(0, 12)}</span>
                {cd.vendor_name && <span className="text-muted-foreground truncate max-w-[120px]">{cd.vendor_name}</span>}
                <ArrowRight className="w-3 h-3 text-muted-foreground" />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Dashboard Widget ─────────────────────────────────────────
export function TransactionGraphWidget() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = () => {
    setLoading(true);
    fetch(`${API}/api/graph/stats`)
      .then(r => r.json())
      .then(d => setStats(d))
      .catch(() => {})
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  if (loading || !stats) return null;
  if (stats.total_nodes === 0) return null;

  return (
    <Card data-testid="graph-widget">
      <CardHeader className="pb-2">
        <CardTitle className="text-sm flex items-center justify-between">
          <span className="flex items-center gap-2"><GitBranch className="w-4 h-4" />Transaction Graph</span>
          <Button variant="ghost" size="sm" onClick={load} className="h-6 w-6 p-0"><RefreshCw className="w-3 h-3" /></Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid grid-cols-3 gap-2">
          <div className="text-center">
            <p className="text-lg font-bold" data-testid="graph-total-nodes">{stats.total_nodes}</p>
            <p className="text-[10px] text-muted-foreground">Nodes</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold" data-testid="graph-total-edges">{stats.total_edges}</p>
            <p className="text-[10px] text-muted-foreground">Edges</p>
          </div>
          <div className="text-center">
            <p className="text-lg font-bold" data-testid="graph-total-docs">{stats.documents_in_graph}</p>
            <p className="text-[10px] text-muted-foreground">Documents</p>
          </div>
        </div>

        {/* Node type breakdown */}
        <div>
          <p className="text-[10px] text-muted-foreground mb-1">By Node Type</p>
          <div className="flex flex-wrap gap-1">
            {Object.entries(stats.nodes_by_type || {}).map(([type, count]) => (
              <Badge key={type} className={`text-[9px] border ${NODE_TYPE_COLORS[type] || 'bg-gray-500/20 text-gray-400'}`}>
                {type.replace(/_/g, ' ')}: {count}
              </Badge>
            ))}
          </div>
        </div>

        {/* Provenance breakdown */}
        <div>
          <p className="text-[10px] text-muted-foreground mb-1">By Provenance</p>
          <div className="flex flex-wrap gap-1">
            {Object.entries(stats.edges_by_provenance || {}).map(([prov, count]) => (
              <Badge key={prov} className={`text-[9px] ${PROV_COLORS[prov] || 'bg-gray-500/20 text-gray-400'}`}>
                {prov.replace('linked_by_', '')}: {count}
              </Badge>
            ))}
          </div>
        </div>

        <div className="text-[10px] text-muted-foreground">
          Avg. confidence: <span className="font-mono">{((stats.avg_edge_confidence || 0) * 100).toFixed(0)}%</span>
        </div>
      </CardContent>
    </Card>
  );
}
