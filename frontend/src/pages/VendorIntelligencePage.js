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
  Truck, Package, FileText, CheckCircle2, AlertTriangle, ArrowRight,
  ToggleLeft, ToggleRight, RotateCcw, Zap, Eye, GitMerge
} from 'lucide-react';

const API_URL = process.env.REACT_APP_BACKEND_URL;
const api = (path) => fetch(`${API_URL}/api${path}`).then(r => r.json());
const apiPost = (path) => fetch(`${API_URL}/api${path}`, { method: 'POST' }).then(r => {
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
});

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

function VendorExtractionProfileSection({ vendorId }) {
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);

  useEffect(() => {
    if (!vendorId) return;
    setLoading(true);
    api(`/vendor-extraction-profiles/${encodeURIComponent(vendorId)}`)
      .then(p => setProfile(p))
      .catch(() => setProfile(null))
      .finally(() => setLoading(false));
  }, [vendorId]);

  const handleGenerate = async () => {
    setGenerating(true);
    try {
      const p = await apiPost(`/vendor-extraction-profiles/${encodeURIComponent(vendorId)}/generate`);
      setProfile(p);
      toast.success('Profile generated');
    } catch { toast.error('Generation failed'); }
    finally { setGenerating(false); }
  };

  const handleToggle = async () => {
    try {
      await apiPost(`/vendor-extraction-profiles/${encodeURIComponent(vendorId)}/toggle?enabled=${!profile.enabled}`);
      setProfile(prev => ({ ...prev, enabled: !prev.enabled }));
      toast.success(profile.enabled ? 'Profile disabled' : 'Profile enabled');
    } catch { toast.error('Toggle failed'); }
  };

  const handleReset = async () => {
    try {
      await apiPost(`/vendor-extraction-profiles/${encodeURIComponent(vendorId)}/reset`);
      setProfile(null);
      toast.success('Profile reset');
    } catch { toast.error('Reset failed'); }
  };

  if (loading) return <div className="text-xs text-muted-foreground py-2"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading profile...</div>;

  return (
    <Card className="border border-border" data-testid="vendor-extraction-profile-section">
      <CardHeader className="pb-2 pt-3 px-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
            <Zap className="w-3 h-3" /> Extraction Profile
          </CardTitle>
          <div className="flex items-center gap-1">
            {profile ? (
              <>
                <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={handleToggle}
                  data-testid="vep-toggle-btn">
                  {profile.enabled ? <ToggleRight className="w-3 h-3 text-emerald-400" /> : <ToggleLeft className="w-3 h-3 text-muted-foreground" />}
                </Button>
                <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={handleReset}
                  data-testid="vep-reset-btn">
                  <RotateCcw className="w-3 h-3" />
                </Button>
              </>
            ) : (
              <Button variant="ghost" size="sm" className="h-5 px-1.5 text-[10px]" onClick={handleGenerate}
                disabled={generating} data-testid="vep-generate-btn">
                {generating ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3" />}
                <span className="ml-0.5">Generate</span>
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent className="px-3 pb-3">
        {!profile ? (
          <p className="text-[10px] text-muted-foreground">No profile yet. Click Generate to create one from existing data.</p>
        ) : (
          <div className="space-y-2 text-xs">
            <div className="flex items-center gap-2">
              <Badge className={profile.enabled ? 'bg-emerald-500/20 text-emerald-400 text-[10px]' : 'bg-gray-500/20 text-gray-400 text-[10px]'}>
                {profile.enabled ? 'Active' : 'Disabled'}
              </Badge>
              <span className="text-[10px] text-muted-foreground">Type: {profile.document_type_bias || 'unknown'}</span>
              <span className="text-[10px] text-muted-foreground">Source: {(profile.learning_source || []).join(', ')}</span>
            </div>

            {profile.reference_priority_order?.length > 0 && (
              <div>
                <span className="text-[10px] text-muted-foreground">Reference Priority</span>
                <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                  {profile.reference_priority_order.map((p, i, arr) => (
                    <span key={p} className="flex items-center gap-0.5">
                      <Badge variant="outline" className="text-[10px] font-mono">{p.replace('posted_', '').replace('_', ' ')}</Badge>
                      {i < arr.length - 1 && <ArrowRight className="w-2.5 h-2.5 text-muted-foreground" />}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {profile.reference_label_bias && Object.keys(profile.reference_label_bias).length > 0 && (
              <div>
                <span className="text-[10px] text-muted-foreground">Label Bias</span>
                {Object.entries(profile.reference_label_bias).map(([label, info]) => (
                  <div key={label} className="flex items-center gap-1.5 text-[10px] mt-0.5">
                    <Badge variant="outline" className="text-[10px]">{label}</Badge>
                    <ArrowRight className="w-2.5 h-2.5 text-muted-foreground" />
                    <span className="font-mono text-teal-400">{info.target_label}</span>
                    <span className="text-emerald-400">+{((info.boost || 0) * 100).toFixed(0)}%</span>
                    <span className="text-muted-foreground">({info.count}x)</span>
                  </div>
                ))}
              </div>
            )}

            {profile.confidence_adjustments && Object.keys(profile.confidence_adjustments).length > 0 && (
              <div>
                <span className="text-[10px] text-muted-foreground">Confidence Adjustments</span>
                <div className="flex flex-wrap gap-1 mt-0.5">
                  {Object.entries(profile.confidence_adjustments).map(([k, v]) => (
                    <Badge key={k} variant="outline" className={`text-[10px] font-mono ${v > 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                      {k.replace('posted_', '').replace('_', ' ')}: {v > 0 ? '+' : ''}{(v * 100).toFixed(0)}%
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="text-[10px] text-muted-foreground pt-1 flex items-center gap-3">
              <span>Docs: {profile.source_invoice_count || 0}</span>
              <span>Corrections: {profile.source_correction_count || 0}</span>
              <span>Updated: {profile.last_updated ? new Date(profile.last_updated).toLocaleString('en-GB', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }) : '-'}</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function VendorDeepLearningSection({ vendorNo }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!vendorNo) return;
    setLoading(true);
    Promise.all([
      api(`/posting-patterns/deep-learning/vendor-maturity/${encodeURIComponent(vendorNo)}`).catch(() => null),
      api(`/posting-patterns/deep-learning/extraction-patterns/${encodeURIComponent(vendorNo)}`).catch(() => null),
      api(`/posting-patterns/advanced-learning/line-items/${encodeURIComponent(vendorNo)}`).catch(() => null),
      api(`/posting-patterns/advanced-learning/amount-check/${encodeURIComponent(vendorNo)}?amount=0`).catch(() => null),
      api(`/posting-patterns/advanced-learning/predict-next/${encodeURIComponent(vendorNo)}`).catch(() => null),
      api(`/posting-patterns/learning-pulse/vendor/${encodeURIComponent(vendorNo)}`).catch(() => null),
    ]).then(([maturity, patterns, lineItems, amountCheck, nextPred, pulse]) => {
      setData({ maturity, patterns, lineItems, amountCheck, nextPred, pulse });
    }).finally(() => setLoading(false));
  }, [vendorNo]);

  if (loading) return <div className="text-xs text-muted-foreground py-2"><Loader2 className="w-3 h-3 animate-spin inline mr-1" />Loading deep learning...</div>;
  if (!data) return null;

  const m = data.maturity;
  const maturityColors = {
    mastered: 'bg-emerald-500', proficient: 'bg-blue-500', developing: 'bg-amber-500',
    learning: 'bg-orange-500', novice: 'bg-red-500/80', unknown: 'bg-muted',
  };

  return (
    <div className="space-y-3" data-testid="vendor-deep-learning">
      {/* Maturity Score */}
      {m && m.composite_score > 0 && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Target className="w-3 h-3" /> Maturity Score
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3">
            <div className="flex items-center gap-3 mb-2">
              <div className="text-2xl font-bold">{m.composite_score}</div>
              <Badge className={`${maturityColors[m.maturity_level] || 'bg-muted'} text-white text-[10px]`}>
                {m.maturity_level}
              </Badge>
            </div>
            {m.dimensions && (
              <div className="space-y-1.5">
                {Object.entries(m.dimensions).map(([dim, info]) => (
                  <div key={dim} className="space-y-0.5">
                    <div className="flex items-center justify-between text-[10px]">
                      <span className="text-muted-foreground capitalize">{dim.replace(/_/g, ' ')}</span>
                      <span className="font-mono">{info.score}/100</span>
                    </div>
                    <div className="h-1 rounded-full bg-muted overflow-hidden">
                      <div className="h-full bg-violet-500 rounded-full" style={{ width: `${info.score}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Extraction Patterns */}
      {data.patterns && data.patterns.field_reliability && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Zap className="w-3 h-3" /> Learned Extraction Patterns
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3">
            <p className="text-[10px] text-muted-foreground mb-1.5">{data.patterns.total_documents || 0} documents analyzed</p>
            <div className="flex flex-wrap gap-1">
              {Object.entries(data.patterns.field_reliability).map(([field, reliability]) => (
                <Badge key={field} variant="outline"
                  className={`text-[10px] font-mono ${reliability >= 0.8 ? 'border-emerald-500/50 text-emerald-400' : reliability >= 0.5 ? 'border-amber-500/50 text-amber-400' : ''}`}>
                  {field} <span className="ml-1">{Math.round(reliability * 100)}%</span>
                </Badge>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Line Item Intelligence */}
      {data.lineItems?.suggestions?.length > 0 && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <FileText className="w-3 h-3" /> Line Item Patterns
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3 space-y-1">
            {data.lineItems.suggestions.slice(0, 5).map((s, i) => (
              <div key={i} className="flex items-center gap-2 text-[10px] p-1 rounded bg-muted/30">
                <span className="font-medium truncate flex-1">{s.description}</span>
                <span className="font-mono text-muted-foreground">{s.seen_count}x</span>
                {s.suggested_gl && <Badge variant="outline" className="text-[10px]">GL: {s.suggested_gl}</Badge>}
                <span className="text-emerald-400 font-mono">${s.avg_amount?.toLocaleString()}</span>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Amount Intelligence */}
      {data.amountCheck && !data.amountCheck.reason && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <TrendingUp className="w-3 h-3" /> Amount Intelligence
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3">
            <div className="grid grid-cols-3 gap-2 text-center">
              <div>
                <p className="text-sm font-bold">${(data.amountCheck.avg_amount || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
                <p className="text-[10px] text-muted-foreground">Average</p>
              </div>
              <div>
                <p className="text-sm font-bold">${(data.amountCheck.min_seen || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
                <p className="text-[10px] text-muted-foreground">Min</p>
              </div>
              <div>
                <p className="text-sm font-bold">${(data.amountCheck.max_seen || 0).toLocaleString(undefined, {maximumFractionDigits: 0})}</p>
                <p className="text-[10px] text-muted-foreground">Max</p>
              </div>
            </div>
            {data.amountCheck.typical_range && (
              <p className="text-[10px] text-muted-foreground mt-1 text-center">
                Normal range: ${data.amountCheck.typical_range[0]?.toLocaleString()} – ${data.amountCheck.typical_range[1]?.toLocaleString()}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Next Document Prediction */}
      {data.nextPred && data.nextPred.predicted_next && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Activity className="w-3 h-3" /> Document Flow Prediction
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3">
            <div className="flex items-center gap-2 text-xs">
              <Badge variant="outline" className="text-[10px]">{data.nextPred.last_type}</Badge>
              <ArrowRight className="w-3 h-3 text-muted-foreground" />
              <Badge className="bg-violet-500 text-white text-[10px]">{data.nextPred.predicted_next}</Badge>
              <span className="text-muted-foreground">({Math.round((data.nextPred.confidence || 0) * 100)}% confident)</span>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Per-Document Learning Stats */}
      {data.pulse?.intelligence && (
        <Card className="border border-border">
          <CardHeader className="pb-2 pt-3 px-3">
            <CardTitle className="text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-1.5">
              <Brain className="w-3 h-3" /> Real-Time Learning
            </CardTitle>
          </CardHeader>
          <CardContent className="px-3 pb-3">
            <div className="grid grid-cols-4 gap-2 text-center text-[10px]">
              <div>
                <p className="text-sm font-bold">{data.pulse.intelligence.total_documents || 0}</p>
                <p className="text-muted-foreground">Total</p>
              </div>
              <div>
                <p className="text-sm font-bold text-emerald-400">{data.pulse.intelligence.success_count || 0}</p>
                <p className="text-muted-foreground">Success</p>
              </div>
              <div>
                <p className="text-sm font-bold">{((data.pulse.intelligence.auto_validation_rate || 0) * 100).toFixed(0)}%</p>
                <p className="text-muted-foreground">Auto Rate</p>
              </div>
              <div>
                <p className="text-sm font-bold">{((data.pulse.intelligence.avg_confidence || 0) * 100).toFixed(0)}%</p>
                <p className="text-muted-foreground">Avg Conf</p>
              </div>
            </div>
            {data.pulse.intelligence.confidence_to_validation_gap > 0.05 && (
              <p className="text-[10px] text-amber-400 text-center mt-1">
                Confidence gap: {((data.pulse.intelligence.confidence_to_validation_gap || 0) * 100).toFixed(0)}%
              </p>
            )}
          </CardContent>
        </Card>
      )}
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

        {/* Vendor Extraction Profile (Part 6) */}
        <VendorExtractionProfileSection vendorId={profile.vendor_no || profile.vendor_name} />

        {/* Deep Learning Intelligence (Phase 5-7) */}
        <VendorDeepLearningSection vendorNo={profile.vendor_no || profile.vendor_name} />

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
  const [maturityMap, setMaturityMap] = useState({});
  const [consolidationPreview, setConsolidationPreview] = useState(null);
  const [showConsolidation, setShowConsolidation] = useState(false);
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

      // Fetch maturity for visible vendors
      const vendorNos = (p.profiles || []).map(v => v.vendor_no).filter(Boolean);
      const matMap = {};
      await Promise.all(vendorNos.map(async (vno) => {
        try {
          const m = await api(`/posting-patterns/deep-learning/vendor-maturity/${encodeURIComponent(vno)}`);
          if (m && m.composite_score > 0) matMap[vno] = m;
        } catch {}
      }));
      setMaturityMap(matMap);
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
      const result = await apiPost('/vendor-profiles/rebuild/run');
      if (result.status === 'error') {
        toast.error(`Rebuild error: ${result.message || 'Unknown error'}`);
      } else {
        const errCount = (result.errors || []).length;
        const msg = `Profiles rebuilt: ${result.profiles_created} created, ${result.stable_vendors} stable${errCount > 0 ? `, ${errCount} errors` : ''}`;
        toast.success(msg);
      }
      setTimeout(fetchData, 2000);
    } catch (err) {
      toast.error(`Rebuild failed: ${err.message || 'Network error'}`);
    } finally {
      setRebuilding(false);
    }
  };

  const handleConsolidationPreview = async () => {
    try {
      const data = await apiPost('/vendor-profiles/rebuild/dry-run');
      setConsolidationPreview(data);
      setShowConsolidation(true);
    } catch {
      toast.error('Failed to load consolidation preview');
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
          <Button variant="outline" size="sm" onClick={handleConsolidationPreview} className="h-8 text-xs gap-1" data-testid="consolidation-preview">
            <Eye className="w-3 h-3" /> Preview Consolidation
          </Button>
          <Button variant="default" size="sm" onClick={handleRebuild} disabled={rebuilding} className="h-8 text-xs gap-1" data-testid="rebuild-vendor-profiles">
            {rebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : <Brain className="w-3 h-3" />}
            Rebuild Profiles
          </Button>
        </div>
      </div>

      {/* Consolidation Preview */}
      {showConsolidation && consolidationPreview && (
        <Card className="border border-amber-500/30 bg-amber-950/10">
          <CardContent className="p-4">
            <div className="flex items-center justify-between mb-3">
              <div>
                <h3 className="text-sm font-semibold flex items-center gap-2">
                  <GitMerge className="w-4 h-4 text-amber-400" />
                  Vendor Profile Consolidation Preview
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5">
                  {consolidationPreview.current_profiles} current profiles → {consolidationPreview.new_profiles} consolidated
                  {consolidationPreview.would_merge > 0 && (
                    <span className="text-amber-400 font-medium ml-1">
                      ({consolidationPreview.would_merge} profiles will merge)
                    </span>
                  )}
                </p>
              </div>
              <Button variant="ghost" size="sm" onClick={() => setShowConsolidation(false)} className="h-6 text-xs">
                Close
              </Button>
            </div>

            {consolidationPreview.consolidation_report?.length > 0 ? (
              <div className="space-y-2 max-h-[300px] overflow-y-auto">
                {consolidationPreview.consolidation_report.map((merge, i) => (
                  <div key={i} className="p-2 rounded bg-background/50 border border-border/50">
                    <div className="flex items-center justify-between">
                      <div>
                        <p className="text-xs font-medium">{merge.canonical} <span className="text-muted-foreground">({merge.vendor_no || 'no BC match'})</span></p>
                        <p className="text-[10px] text-muted-foreground">{merge.total_docs} docs from {merge.variant_count} name variants</p>
                      </div>
                      <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-500/30">{merge.variant_count} variants</Badge>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {merge.variants.map((v, j) => (
                        <span key={j} className="text-[10px] px-1.5 py-0.5 rounded bg-accent/40 text-muted-foreground">{v}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-xs text-muted-foreground">No duplicate profiles to merge. All vendors are already consolidated.</p>
            )}

            {consolidationPreview.top_vendors?.length > 0 && (
              <div className="mt-3">
                <p className="text-[11px] font-medium text-muted-foreground mb-2">Top vendors after consolidation:</p>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  {consolidationPreview.top_vendors.slice(0, 8).map((v, i) => (
                    <div key={i} className="p-2 rounded bg-background/50 border border-border/30 text-center">
                      <p className="text-[11px] font-medium truncate">{v.name}</p>
                      <p className="text-lg font-bold">{v.docs}</p>
                      <p className="text-[10px] text-muted-foreground">{Math.round(v.auto_rate * 100)}% auto</p>
                      {v.variants?.length > 1 && (
                        <p className="text-[9px] text-amber-400">{v.variants.length} names merged</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      )}

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
                <TableHead className="text-xs">Maturity</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && (
                <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground text-xs"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></TableCell></TableRow>
              )}
              {!loading && filtered.length === 0 && (
                <TableRow><TableCell colSpan={9} className="text-center py-8 text-muted-foreground text-xs">
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
                    <TableCell>
                      {(() => {
                        const mat = maturityMap[p.vendor_no];
                        if (!mat) return <span className="text-[10px] text-muted-foreground">-</span>;
                        const colors = {
                          mastered: 'bg-emerald-500 text-white', proficient: 'bg-blue-500 text-white',
                          developing: 'bg-amber-500 text-white', learning: 'bg-orange-500 text-white',
                          novice: 'bg-red-500/80 text-white',
                        };
                        return (
                          <div className="flex items-center gap-1">
                            <Badge className={`text-[10px] ${colors[mat.maturity_level] || 'bg-muted'}`}>
                              {mat.composite_score}
                            </Badge>
                          </div>
                        );
                      })()}
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
