import { useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from './ui/select';
import { toast } from 'sonner';
import {
  Truck, ArrowDown, ArrowUp, ArrowLeftRight, HelpCircle,
  RefreshCw, Loader2, CheckCircle2, Edit3, Save
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const DIRECTION_CONFIG = {
  inbound: { label: 'Inbound', icon: ArrowDown, color: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400' },
  outbound: { label: 'Outbound', icon: ArrowUp, color: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400' },
  transfer: { label: 'Transfer', icon: ArrowLeftRight, color: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400' },
  unknown: { label: 'Unknown', icon: HelpCircle, color: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300' },
};

export default function FreightGLRoutingPanel({ document: doc, onUpdate }) {
  const [classification, setClassification] = useState(null);
  const [accounts, setAccounts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [classifying, setClassifying] = useState(false);
  const [overrideMode, setOverrideMode] = useState(false);
  const [selectedOverride, setSelectedOverride] = useState('');

  useEffect(() => {
    if (doc?.freight_gl_classification) {
      setClassification(doc.freight_gl_classification);
    }
    fetchAccounts();
  }, [doc?.id]);

  const fetchAccounts = async () => {
    try {
      const res = await fetch(`${API}/api/freight-routing/accounts`);
      if (res.ok) {
        const data = await res.json();
        setAccounts(data.accounts || []);
      }
    } catch (err) {
      // silent
    }
  };

  const handleClassify = async () => {
    setClassifying(true);
    try {
      const res = await fetch(`${API}/api/freight-routing/classify/${doc.id}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        setClassification(data);
        toast.success(data.is_freight ? `Classified as ${data.direction} freight` : 'Not freight-related');
        if (onUpdate) onUpdate();
      } else {
        toast.error('Classification failed');
      }
    } catch (err) {
      toast.error('Classification error');
    } finally {
      setClassifying(false);
    }
  };

  const handleOverride = async () => {
    if (!selectedOverride) return;
    setLoading(true);
    try {
      const res = await fetch(`${API}/api/freight-routing/override/${doc.id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gl_account_id: selectedOverride, reason: 'Manual override from UI' }),
      });
      if (res.ok) {
        const data = await res.json();
        toast.success(`G/L overridden to ${data.gl_number}`);
        setOverrideMode(false);
        // Refresh classification from document
        const acct = accounts.find(a => a.account_id === selectedOverride);
        if (acct) {
          setClassification({
            ...classification,
            gl_number: acct.gl_number,
            gl_name: acct.gl_name,
            account_id: acct.account_id,
            direction: acct.direction,
            confidence: 1.0,
            override: true,
          });
        }
        if (onUpdate) onUpdate();
      } else {
        toast.error('Override failed');
      }
    } catch (err) {
      toast.error('Override error');
    } finally {
      setLoading(false);
    }
  };

  // Determine if this doc could be freight-related (show panel)
  const docType = (doc?.document_type || doc?.suggested_job_type || '').toLowerCase();
  const vendorName = (doc?.vendor_canonical || doc?.vendor_raw || '').toLowerCase();
  const isLikelyFreight = ['freight', 'shipping', 'bol', 'bill_of_lading'].some(k => docType.includes(k))
    || ['freight', 'trucking', 'logistics', 'transport', 'ups', 'fedex', 'xpo', 'old dominion', 'estes', 'saia'].some(k => vendorName.includes(k))
    || doc?.unified_vendor_match?.is_freight_carrier
    || doc?.freight_gl_classification;

  if (!isLikelyFreight && !classification) return null;

  const dirConfig = classification?.direction ? DIRECTION_CONFIG[classification.direction] : DIRECTION_CONFIG.unknown;
  const DirIcon = dirConfig?.icon || HelpCircle;

  return (
    <Card className="border border-border" data-testid="freight-gl-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <Truck className="w-4 h-4" />
            Freight G/L Routing
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleClassify}
            disabled={classifying}
            data-testid="freight-classify-btn"
          >
            {classifying ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            <span className="ml-1 text-xs">{classification ? 'Re-classify' : 'Classify'}</span>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!classification ? (
          <div className="text-center py-4" data-testid="freight-no-classification">
            <p className="text-sm text-muted-foreground mb-2">No freight classification yet</p>
            <Button variant="outline" size="sm" onClick={handleClassify} disabled={classifying} data-testid="freight-classify-initial-btn">
              {classifying ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Truck className="w-3.5 h-3.5 mr-1" />}
              Run Classification
            </Button>
          </div>
        ) : (
          <>
            {/* Direction + Confidence */}
            <div className="flex items-center gap-3" data-testid="freight-direction-display">
              <Badge className={`${dirConfig.color} text-xs px-2 py-1`}>
                <DirIcon className="w-3 h-3 mr-1" />
                {dirConfig.label}
              </Badge>
              {classification.confidence != null && (
                <span className="text-xs text-muted-foreground">
                  {(classification.confidence * 100).toFixed(0)}% confidence
                </span>
              )}
              {classification.override && (
                <Badge variant="outline" className="text-xs border-amber-300 text-amber-600">
                  <Edit3 className="w-3 h-3 mr-0.5" /> Override
                </Badge>
              )}
            </div>

            {/* G/L Account */}
            {classification.gl_number && (
              <div className="bg-muted/50 rounded-md p-3" data-testid="freight-gl-account">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-muted-foreground">Recommended G/L Account</p>
                    <p className="font-mono text-sm font-semibold">{classification.gl_number}</p>
                    <p className="text-xs text-muted-foreground">{classification.gl_name}</p>
                  </div>
                  <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                </div>
              </div>
            )}

            {/* Sub-type */}
            {classification.sub_type && (
              <div className="text-xs text-muted-foreground">
                <span className="font-medium">Sub-type:</span>{' '}
                {classification.sub_type.replace(/_/g, ' ')}
              </div>
            )}

            {/* Reasoning */}
            {classification.reasoning?.length > 0 && (
              <div className="text-xs space-y-0.5" data-testid="freight-reasoning">
                <p className="font-medium text-muted-foreground mb-1">Reasoning:</p>
                {classification.reasoning.slice(0, 4).map((r, i) => (
                  <p key={i} className="text-muted-foreground pl-2">
                    <span className="text-emerald-500 mr-1">+</span>{typeof r === 'string' ? r : r.signal}
                  </p>
                ))}
              </div>
            )}

            {/* Override Section */}
            <div className="pt-2 border-t border-border">
              {!overrideMode ? (
                <Button variant="ghost" size="sm" onClick={() => setOverrideMode(true)} className="text-xs" data-testid="freight-override-toggle">
                  <Edit3 className="w-3 h-3 mr-1" /> Override G/L Account
                </Button>
              ) : (
                <div className="space-y-2" data-testid="freight-override-form">
                  <Select value={selectedOverride} onValueChange={setSelectedOverride}>
                    <SelectTrigger className="h-8 text-xs" data-testid="freight-override-select">
                      <SelectValue placeholder="Select G/L Account" />
                    </SelectTrigger>
                    <SelectContent>
                      {accounts.filter(a => a.enabled).map(a => (
                        <SelectItem key={a.account_id} value={a.account_id}>
                          {a.gl_number} - {a.gl_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <div className="flex gap-2">
                    <Button size="sm" variant="default" onClick={handleOverride} disabled={loading || !selectedOverride} className="text-xs" data-testid="freight-override-save">
                      {loading ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Save className="w-3 h-3 mr-1" />}
                      Save Override
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setOverrideMode(false)} className="text-xs" data-testid="freight-override-cancel">
                      Cancel
                    </Button>
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
