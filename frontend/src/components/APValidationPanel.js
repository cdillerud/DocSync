import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { Button } from './ui/button';
import { Badge } from './ui/badge';
import { toast } from 'sonner';
import {
  ShieldCheck, ShieldAlert, ShieldX, ShieldQuestion,
  RefreshCw, Loader2, CheckCircle2, XCircle, AlertTriangle,
  ChevronDown, ChevronUp, Clock
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const STATE_CONFIG = {
  pass: {
    label: 'Validated',
    icon: ShieldCheck,
    bg: 'bg-emerald-500/10 border-emerald-500/30',
    badge: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-400',
    iconColor: 'text-emerald-500',
  },
  warning: {
    label: 'Validated (Warnings)',
    icon: ShieldAlert,
    bg: 'bg-amber-500/10 border-amber-500/30',
    badge: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400',
    iconColor: 'text-amber-500',
  },
  fail: {
    label: 'Validation Failed',
    icon: ShieldX,
    bg: 'bg-red-500/10 border-red-500/30',
    badge: 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400',
    iconColor: 'text-red-500',
  },
  pending: {
    label: 'Pending',
    icon: ShieldQuestion,
    bg: 'bg-gray-500/10 border-gray-500/30',
    badge: 'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
    iconColor: 'text-gray-400',
  },
};

export default function APValidationPanel({ document: doc, onUpdate }) {
  const [validating, setValidating] = useState(false);
  const [showChecks, setShowChecks] = useState(false);
  const [showWarnings, setShowWarnings] = useState(false);

  const apVal = doc?.ap_validation_result;
  
  // Cross-reference: if BC validation resolved vendor, treat vendor as resolved
  // even if AP validation ran before vendor was matched
  const bcVal = doc?.validation_results;
  const bcResolvedVendor = bcVal?.all_passed && bcVal?.bc_record_info;
  const docHasVendor = !!(doc?.matched_vendor_no || doc?.vendor_id);
  const vendorIsResolved = apVal?.vendor_resolved || bcResolvedVendor || docHasVendor;
  
  // Reconciled validation state: if AP says fail only because vendor wasn't resolved,
  // but BC validation or document fields show vendor IS resolved, upgrade to pass/warning
  let valState = apVal?.validation_state || doc?.validation_state || 'pending';
  if (valState === 'fail' && apVal && vendorIsResolved) {
    const nonVendorBlocking = (apVal.blocking_issues || []).filter(
      i => !i.toLowerCase().includes('vendor')
    );
    if (nonVendorBlocking.length === 0) {
      valState = (apVal.warnings?.length > 0) ? 'warning' : 'pass';
    }
  }
  
  const config = STATE_CONFIG[valState] || STATE_CONFIG.pending;
  const StateIcon = config.icon;

  // Only show for AP-relevant document types
  const docType = (doc?.document_type || doc?.suggested_job_type || '').toLowerCase();
  const isAPRelevant = ['ap_invoice', 'ap invoice', 'freight_invoice', 'freight invoice',
    'freight', 'carrier_invoice', 'carrier invoice'].some(t => docType.includes(t));

  // Also show if validation already exists
  if (!isAPRelevant && !apVal) return null;

  const handleValidate = async () => {
    setValidating(true);
    try {
      const res = await fetch(`${API}/api/ap-validation/validate/${doc.id}`, { method: 'POST' });
      if (res.ok) {
        const data = await res.json();
        const state = data.validation_state;
        const msg = state === 'pass' ? 'Validation passed' :
          state === 'warning' ? 'Validated with warnings' :
            'Validation failed';
        toast[state === 'fail' ? 'error' : state === 'warning' ? 'warning' : 'success'](msg);
        if (onUpdate) onUpdate();
      } else {
        toast.error('Validation failed');
      }
    } catch (err) {
      toast.error('Validation error');
    } finally {
      setValidating(false);
    }
  };

  const checks = apVal?.checks || [];
  const warnings = apVal?.warnings || [];
  // Filter out stale vendor blocking issues if vendor is now resolved
  const blockingIssues = (apVal?.blocking_issues || []).filter(
    issue => !(vendorIsResolved && issue.toLowerCase().includes('vendor'))
  );
  const passedChecks = checks.filter(c => c.passed);
  const failedChecks = checks.filter(c => !c.passed);

  return (
    <Card className={`border ${config.bg}`} data-testid="ap-validation-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground flex items-center gap-2" style={{ fontFamily: 'Chivo, sans-serif' }}>
            <StateIcon className={`w-4 h-4 ${config.iconColor}`} />
            AP Validation
          </CardTitle>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleValidate}
            disabled={validating}
            data-testid="ap-validate-btn"
          >
            {validating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
            <span className="ml-1 text-xs">{apVal ? 'Re-validate' : 'Validate'}</span>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {!apVal ? (
          <div className="text-center py-4" data-testid="ap-validation-empty">
            <p className="text-sm text-muted-foreground mb-2">No AP validation run yet</p>
            <Button variant="outline" size="sm" onClick={handleValidate} disabled={validating} data-testid="ap-validate-initial-btn">
              {validating ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <ShieldCheck className="w-3.5 h-3.5 mr-1" />}
              Run Validation
            </Button>
          </div>
        ) : (
          <>
            {/* State Badge */}
            <div className="flex items-center gap-3" data-testid="ap-validation-state">
              <Badge className={`${config.badge} text-xs px-2.5 py-1`}>
                <StateIcon className="w-3 h-3 mr-1" />
                {config.label}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {passedChecks.length}/{checks.length} checks passed
              </span>
            </div>

            {/* Required Checks Summary */}
            <div className="space-y-1.5" data-testid="ap-validation-checks-summary">
              {[
                { key: 'vendor_resolved', label: 'Vendor resolved to BC', passed: vendorIsResolved },
                { key: 'invoice_number', label: 'Invoice number', passed: apVal.invoice_number_present },
                { key: 'invoice_date', label: 'Invoice date', passed: apVal.invoice_date_present },
                { key: 'total_amount', label: 'Total amount', passed: apVal.total_amount_present },
                { key: 'duplicate', label: 'No duplicate', passed: !apVal.is_duplicate },
              ].map(item => (
                <div key={item.key} className="flex items-center gap-2 text-xs">
                  {item.passed ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                  ) : (
                    <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
                  )}
                  <span className={item.passed ? 'text-muted-foreground' : 'text-red-400 font-medium'}>
                    {item.label}
                  </span>
                </div>
              ))}
            </div>

            {/* Blocking Issues */}
            {blockingIssues.length > 0 && (
              <div className="bg-red-500/5 border border-red-500/20 rounded-md p-2.5" data-testid="ap-validation-blocking">
                <p className="text-xs font-medium text-red-400 mb-1">Blocking Issues:</p>
                {blockingIssues.map((issue, i) => (
                  <p key={i} className="text-xs text-red-400/80 pl-2">
                    <XCircle className="w-3 h-3 inline mr-1" />{issue}
                  </p>
                ))}
              </div>
            )}

            {/* Warnings */}
            {warnings.length > 0 && (
              <div data-testid="ap-validation-warnings">
                <button
                  onClick={() => setShowWarnings(!showWarnings)}
                  className="flex items-center gap-1 text-xs text-amber-400 hover:text-amber-300 transition-colors"
                  data-testid="ap-toggle-warnings"
                >
                  <AlertTriangle className="w-3 h-3" />
                  {warnings.length} Warning{warnings.length !== 1 ? 's' : ''}
                  {showWarnings ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showWarnings && (
                  <div className="mt-1 space-y-0.5 pl-4">
                    {warnings.map((w, i) => (
                      <p key={i} className="text-xs text-amber-400/70">
                        {typeof w === 'string' ? w : w.details || JSON.stringify(w)}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Detailed Checks (expandable) */}
            {checks.length > 0 && (
              <div>
                <button
                  onClick={() => setShowChecks(!showChecks)}
                  className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                  data-testid="ap-toggle-checks"
                >
                  Detailed Checks
                  {showChecks ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
                </button>
                {showChecks && (
                  <div className="mt-1 space-y-1 pl-2">
                    {checks.map((c, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        {c.passed ? (
                          <CheckCircle2 className="w-3 h-3 text-emerald-500 mt-0.5 shrink-0" />
                        ) : (
                          <XCircle className="w-3 h-3 text-red-500 mt-0.5 shrink-0" />
                        )}
                        <span className="text-muted-foreground">{c.details}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Metadata footer */}
            <div className="flex items-center gap-3 pt-1 border-t border-border text-[10px] text-muted-foreground">
              {apVal.validated_at && (
                <span className="flex items-center gap-1">
                  <Clock className="w-3 h-3" />
                  {new Date(apVal.validated_at).toLocaleString()}
                </span>
              )}
              {apVal.validation_version && (
                <span>v{apVal.validation_version}</span>
              )}
              {apVal.validation_source && (
                <span className="capitalize">{apVal.validation_source.replace(/_/g, ' ')}</span>
              )}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}
