import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Switch } from '../components/ui/switch';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter
} from '../components/ui/dialog';
import { ScrollArea } from '../components/ui/scroll-area';
import {
  Brain, RefreshCw, FileText, CheckCircle2, AlertTriangle, ChevronRight,
  Settings2, Play, Eye, Loader2, ArrowUpDown, Shield
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const CONFIDENCE_COLORS = {
  high: 'bg-emerald-500/10 text-emerald-600 border-emerald-200 dark:text-emerald-400',
  medium: 'bg-amber-500/10 text-amber-600 border-amber-200 dark:text-amber-400',
  low: 'bg-red-500/10 text-red-600 border-red-200 dark:text-red-400',
  none: 'bg-gray-500/10 text-gray-500 border-gray-200',
};

function ConfidenceBadge({ confidence }) {
  return (
    <Badge variant="outline" className={`text-xs font-mono ${CONFIDENCE_COLORS[confidence] || CONFIDENCE_COLORS.none}`} data-testid={`confidence-${confidence}`}>
      {(confidence || 'none').toUpperCase()}
    </Badge>
  );
}

function StatCard({ label, value, sub, icon: Icon }) {
  return (
    <div className="flex items-center gap-3 p-4 rounded-lg bg-card border border-border" data-testid={`stat-${label.toLowerCase().replace(/\s+/g, '-')}`}>
      {Icon && <Icon className="w-5 h-5 text-muted-foreground" />}
      <div>
        <p className="text-2xl font-bold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground">{label}</p>
        {sub && <p className="text-[10px] text-muted-foreground mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

function VendorRow({ vendor, onPreviewDraft, onAnalyze }) {
  return (
    <div
      className="flex items-center gap-4 py-3 px-4 border-b border-border/50 hover:bg-accent/30 transition-colors"
      data-testid={`vendor-row-${vendor.vendor_no}`}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="font-medium text-sm truncate">{vendor.vendor_name || vendor.vendor_no}</span>
          <span className="text-[10px] font-mono text-muted-foreground">{vendor.vendor_no}</span>
        </div>
        <div className="flex items-center gap-3 mt-1 text-xs text-muted-foreground">
          <span>{vendor.invoices_analyzed} invoices studied</span>
          <span className="text-border">|</span>
          <span>{vendor.lines_analyzed} lines</span>
          {vendor.top_gl_accounts?.length > 0 && (
            <>
              <span className="text-border">|</span>
              <span className="font-mono">GL: {vendor.top_gl_accounts.join(', ')}</span>
            </>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <ConfidenceBadge confidence={vendor.confidence} />
        {vendor.ready_docs > 0 && (
          <Badge variant="secondary" className="text-xs" data-testid={`ready-count-${vendor.vendor_no}`}>
            {vendor.ready_docs} ready
          </Badge>
        )}
        {vendor.auto_post_eligible && (
          <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-600 border-emerald-200" data-testid={`auto-post-eligible-${vendor.vendor_no}`}>
            <Shield className="w-3 h-3 mr-1" />AUTO
          </Badge>
        )}
        <span className="text-xs text-muted-foreground font-mono">${(vendor.avg_amount || 0).toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}</span>
      </div>
    </div>
  );
}

function ReadyDocRow({ doc, onPreview, onCreateDraft }) {
  const [loading, setLoading] = useState(false);

  const handleCreate = async () => {
    setLoading(true);
    await onCreateDraft(doc.id);
    setLoading(false);
  };

  return (
    <div
      className="flex items-center gap-3 py-2.5 px-4 border-b border-border/50 hover:bg-accent/30 transition-colors"
      data-testid={`ready-doc-${doc.id}`}
    >
      <FileText className="w-4 h-4 text-muted-foreground shrink-0" />
      <div className="flex-1 min-w-0">
        <p className="text-sm truncate font-medium">{doc.filename}</p>
        <div className="flex items-center gap-2 mt-0.5 text-xs text-muted-foreground">
          <span className="font-mono">{doc.vendor_no}</span>
          {doc.invoice_number && <span>INV# {doc.invoice_number}</span>}
          {doc.amount && <span>${doc.amount}</span>}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <ConfidenceBadge confidence={doc.template_confidence} />
        {doc.has_draft ? (
          <Badge variant="outline" className="text-xs bg-emerald-500/10 text-emerald-600">
            <CheckCircle2 className="w-3 h-3 mr-1" />Draft {doc.draft_no}
          </Badge>
        ) : (
          <>
            <Button size="sm" variant="ghost" className="h-7 text-xs" onClick={() => onPreview(doc.id)} data-testid={`preview-btn-${doc.id}`}>
              <Eye className="w-3 h-3 mr-1" />Preview
            </Button>
            <Button size="sm" className="h-7 text-xs" onClick={handleCreate} disabled={loading} data-testid={`create-draft-btn-${doc.id}`}>
              {loading ? <Loader2 className="w-3 h-3 mr-1 animate-spin" /> : <Play className="w-3 h-3 mr-1" />}
              Create Draft
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function DraftPreviewDialog({ open, onClose, preview, onConfirm }) {
  const [creating, setCreating] = useState(false);

  if (!preview) return null;

  const handleConfirm = async () => {
    setCreating(true);
    await onConfirm(preview.doc_id);
    setCreating(false);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={onClose}>
      <DialogContent className="max-w-lg" data-testid="draft-preview-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Eye className="w-5 h-5" />
            Draft PI Preview
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div>
              <p className="text-muted-foreground text-xs">Vendor</p>
              <p className="font-medium">{preview.vendor_name || preview.vendor_no}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Confidence</p>
              <ConfidenceBadge confidence={preview.template_confidence} />
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Invoice #</p>
              <p className="font-mono">{preview.preview?.vendorInvoiceNumber || 'N/A'}</p>
            </div>
            <div>
              <p className="text-muted-foreground text-xs">Date</p>
              <p>{preview.preview?.invoiceDate || 'N/A'}</p>
            </div>
          </div>

          <div>
            <p className="text-xs font-medium text-muted-foreground mb-2">Line Items (from template)</p>
            <div className="border rounded-lg overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-muted/50">
                  <tr>
                    <th className="px-3 py-1.5 text-left font-medium">Type</th>
                    <th className="px-3 py-1.5 text-left font-medium">GL/Item</th>
                    <th className="px-3 py-1.5 text-left font-medium">Description</th>
                    <th className="px-3 py-1.5 text-right font-medium">Amount</th>
                  </tr>
                </thead>
                <tbody>
                  {(preview.preview?.lines || []).map((line, i) => (
                    <tr key={i} className="border-t border-border/50">
                      <td className="px-3 py-1.5 font-mono">{line.lineType}</td>
                      <td className="px-3 py-1.5 font-mono">{line.lineObjectNumber || '-'}</td>
                      <td className="px-3 py-1.5 truncate max-w-[150px]">{line.description}</td>
                      <td className="px-3 py-1.5 text-right font-mono">${(line.unitCost || 0).toLocaleString(undefined, { minimumFractionDigits: 2 })}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {preview.template_details?.reference_handling?.pattern && (
            <div className="text-xs p-2 bg-muted/50 rounded">
              <span className="font-medium">Reference pattern:</span>{' '}
              {preview.template_details.reference_handling.description || preview.template_details.reference_handling.pattern}
            </div>
          )}

          {preview.already_has_draft && (
            <div className="flex items-center gap-2 p-2 bg-amber-500/10 rounded text-xs text-amber-600">
              <AlertTriangle className="w-4 h-4" />
              Draft PI already exists: {preview.existing_draft_no}. Creating will replace it.
            </div>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button onClick={handleConfirm} disabled={creating} data-testid="confirm-create-draft-btn">
            {creating ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
            Create Draft in BC
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function SettingsPanel({ settings, onSave }) {
  const [local, setLocal] = useState(settings);
  const [saving, setSaving] = useState(false);

  useEffect(() => { setLocal(settings); }, [settings]);

  const handleSave = async () => {
    setSaving(true);
    await onSave(local);
    setSaving(false);
  };

  return (
    <Card data-testid="auto-post-settings-card">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Settings2 className="w-4 h-4" />Auto-Post Settings
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium">Enable Auto-Post</p>
            <p className="text-xs text-muted-foreground">Automatically create draft PIs for qualifying documents</p>
          </div>
          <Switch
            checked={local.auto_post_enabled || false}
            onCheckedChange={(v) => setLocal(s => ({ ...s, auto_post_enabled: v }))}
            data-testid="auto-post-toggle"
          />
        </div>

        <div>
          <p className="text-sm font-medium mb-1">Minimum Confidence</p>
          <Select value={local.min_confidence || 'high'} onValueChange={(v) => setLocal(s => ({ ...s, min_confidence: v }))}>
            <SelectTrigger className="w-full" data-testid="min-confidence-select">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="high">High (50+ invoices, 50+ lines)</SelectItem>
              <SelectItem value="medium">Medium (10+ invoices)</SelectItem>
              <SelectItem value="low">Low (3+ invoices)</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div>
          <p className="text-sm font-medium mb-1">Min. Invoices Analyzed</p>
          <input
            type="number"
            min={1}
            max={500}
            value={local.min_invoices_analyzed || 10}
            onChange={(e) => setLocal(s => ({ ...s, min_invoices_analyzed: parseInt(e.target.value) || 10 }))}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
            data-testid="min-invoices-input"
          />
        </div>

        <Button onClick={handleSave} disabled={saving} className="w-full" data-testid="save-settings-btn">
          {saving ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
          Save Settings
        </Button>
      </CardContent>
    </Card>
  );
}

export default function PostingPatternsDashboard() {
  const [vendorSummary, setVendorSummary] = useState(null);
  const [readyQueue, setReadyQueue] = useState(null);
  const [settings, setSettings] = useState({});
  const [loading, setLoading] = useState(true);
  const [analysisStatus, setAnalysisStatus] = useState(null);
  const [previewData, setPreviewData] = useState(null);
  const [previewOpen, setPreviewOpen] = useState(false);
  const [analyzing, setAnalyzing] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, queueRes, settingsRes, statusRes] = await Promise.all([
        fetch(`${API}/api/posting-patterns/vendor-summary?limit=100`),
        fetch(`${API}/api/posting-patterns/ready-queue?limit=50`),
        fetch(`${API}/api/posting-patterns/settings`),
        fetch(`${API}/api/posting-patterns/analyze-top/status`),
      ]);
      if (summaryRes.ok) setVendorSummary(await summaryRes.json());
      if (queueRes.ok) setReadyQueue(await queueRes.json());
      if (settingsRes.ok) setSettings(await settingsRes.json());
      if (statusRes.ok) setAnalysisStatus(await statusRes.json());
    } catch (err) {
      console.error('[PostingPatterns] Fetch error:', err);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleAnalyzeTop = async () => {
    setAnalyzing(true);
    try {
      await fetch(`${API}/api/posting-patterns/analyze-top?top_n=20`, { method: 'POST' });
      setTimeout(fetchData, 2000);
    } catch (err) {
      console.error(err);
    }
    setAnalyzing(false);
  };

  const handlePreview = async (docId) => {
    try {
      const res = await fetch(`${API}/api/posting-patterns/draft-preview/${docId}`, { method: 'POST' });
      if (res.ok) {
        setPreviewData(await res.json());
        setPreviewOpen(true);
      }
    } catch (err) { console.error(err); }
  };

  const handleCreateDraft = async (docId) => {
    try {
      const res = await fetch(`${API}/api/posting-patterns/create-draft/${docId}`, { method: 'POST' });
      if (res.ok) {
        fetchData();
      }
    } catch (err) { console.error(err); }
  };

  const handleSaveSettings = async (newSettings) => {
    try {
      await fetch(`${API}/api/posting-patterns/settings`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newSettings),
      });
      setSettings(newSettings);
    } catch (err) { console.error(err); }
  };

  const vendors = vendorSummary?.vendors || [];
  const readyDocs = readyQueue?.documents || [];
  const highConf = vendors.filter(v => v.confidence === 'high').length;
  const medConf = vendors.filter(v => v.confidence === 'medium').length;
  const autoEligible = vendors.filter(v => v.auto_post_eligible).length;

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64" data-testid="loading-spinner">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto" data-testid="posting-patterns-dashboard">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Brain className="w-6 h-6" />BC Posting Intelligence
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Learned posting patterns from {vendors.length} vendors ({vendorSummary?.ready_total || 0} documents ready)
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={fetchData} data-testid="refresh-btn">
            <RefreshCw className="w-4 h-4 mr-1" />Refresh
          </Button>
          <Button size="sm" onClick={handleAnalyzeTop} disabled={analyzing || analysisStatus?.running} data-testid="analyze-top-btn">
            {analyzing || analysisStatus?.running ? (
              <Loader2 className="w-4 h-4 mr-1 animate-spin" />
            ) : (
              <Play className="w-4 h-4 mr-1" />
            )}
            {analysisStatus?.running ? analysisStatus.progress : 'Analyze Top 20'}
          </Button>
        </div>
      </div>

      {/* Stats Row */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Vendors Analyzed" value={vendors.length} icon={Brain} />
        <StatCard label="High Confidence" value={highConf} sub={`${medConf} medium`} icon={CheckCircle2} />
        <StatCard label="Ready to Post" value={vendorSummary?.ready_total || 0} icon={FileText} />
        <StatCard label="Auto-Post Eligible" value={autoEligible} icon={Shield} />
        <StatCard
          label="Analysis Status"
          value={analysisStatus?.running ? 'Running' : 'Idle'}
          sub={analysisStatus?.progress || ''}
          icon={RefreshCw}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Vendor Profiles (2/3 width) */}
        <div className="lg:col-span-2 space-y-4">
          <Card data-testid="vendor-profiles-card">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between">
                <CardTitle className="text-sm flex items-center gap-2">
                  <ArrowUpDown className="w-4 h-4" />
                  Vendor Posting Profiles ({vendors.length})
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="max-h-[400px]">
                {vendors.length === 0 ? (
                  <div className="p-8 text-center text-muted-foreground text-sm">
                    No vendor profiles found. Click "Analyze Top 20" to start learning from BC.
                  </div>
                ) : (
                  vendors.map(v => (
                    <VendorRow
                      key={v.vendor_no}
                      vendor={v}
                      onAnalyze={() => {}}
                      onPreviewDraft={() => {}}
                    />
                  ))
                )}
              </ScrollArea>
            </CardContent>
          </Card>

          {/* Ready Queue */}
          <Card data-testid="ready-queue-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm flex items-center gap-2">
                <FileText className="w-4 h-4" />
                Ready for Posting ({readyDocs.length})
              </CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <ScrollArea className="max-h-[350px]">
                {readyDocs.length === 0 ? (
                  <div className="p-8 text-center text-muted-foreground text-sm">
                    No documents currently in ReadyForPost status.
                  </div>
                ) : (
                  readyDocs.map(doc => (
                    <ReadyDocRow
                      key={doc.id}
                      doc={doc}
                      onPreview={handlePreview}
                      onCreateDraft={handleCreateDraft}
                    />
                  ))
                )}
              </ScrollArea>
            </CardContent>
          </Card>
        </div>

        {/* Settings (1/3 width) */}
        <div className="space-y-4">
          <SettingsPanel settings={settings} onSave={handleSaveSettings} />

          {/* Quick Stats */}
          <Card data-testid="confidence-breakdown-card">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Confidence Breakdown</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2">
                {[
                  { label: 'High', count: highConf, color: 'bg-emerald-500' },
                  { label: 'Medium', count: medConf, color: 'bg-amber-500' },
                  { label: 'Low', count: vendors.length - highConf - medConf, color: 'bg-red-500' },
                ].map(({ label, count, color }) => (
                  <div key={label} className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${color}`} />
                    <span className="text-xs flex-1">{label}</span>
                    <span className="text-xs font-mono">{count}</span>
                    <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full ${color} rounded-full`}
                        style={{ width: `${vendors.length ? (count / vendors.length * 100) : 0}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Draft Preview Dialog */}
      <DraftPreviewDialog
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        preview={previewData}
        onConfirm={handleCreateDraft}
      />
    </div>
  );
}
