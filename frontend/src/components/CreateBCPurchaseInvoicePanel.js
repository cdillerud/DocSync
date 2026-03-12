import { useState, useCallback } from 'react';
import { purchaseInvoicePreflight, createPurchaseInvoiceFromDocument } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { toast } from 'sonner';
import {
  FileInput, Loader2, CheckCircle2, AlertCircle,
  AlertTriangle, ChevronRight, Package, Building2, Calendar,
  FileText, Hash, Shield, XCircle, Receipt
} from 'lucide-react';

const ELIGIBLE_TYPES = new Set(['AP_Invoice']);

function isEligible(doc) {
  return ELIGIBLE_TYPES.has(doc?.document_type);
}

export default function CreateBCPurchaseInvoicePanel({ document, onUpdate }) {
  const [state, setState] = useState('idle');
  const [preflight, setPreflight] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [vendorOverride, setVendorOverride] = useState('');

  const existingPI = document?.bc_purchase_invoice;
  const eligible = isEligible(document);

  const runPreflight = useCallback(async () => {
    setState('loading');
    setError(null);
    try {
      const res = await purchaseInvoicePreflight(document.id);
      setPreflight(res.data);
      if (res.data.already_created) {
        setResult(res.data.existing_purchase_invoice);
        setState('success');
      } else {
        setState('preflight');
      }
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'Preflight check failed');
      setState('error');
    }
  }, [document.id]);

  const handleCreate = useCallback(async () => {
    setState('creating');
    setError(null);
    try {
      const override = vendorOverride.trim();
      const res = await createPurchaseInvoiceFromDocument(document.id, override);
      setResult(res.data);
      if (res.data.success || res.data.already_exists) {
        setState('success');
        toast.success(res.data.already_exists
          ? 'Purchase Invoice already exists'
          : `Purchase Invoice ${res.data.bc_record_no} created`
        );
        onUpdate?.();
      } else {
        setError(res.data.error_message || res.data.message || 'Creation failed');
        setState('error');
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      if (typeof detail === 'object') {
        setError(detail.message || JSON.stringify(detail));
      } else {
        setError(detail || err.message || 'Creation failed');
      }
      setState('error');
    }
  }, [document.id, vendorOverride, onUpdate]);

  if (!eligible && !existingPI) return null;

  // Already created — show success
  if (existingPI && state === 'idle') {
    return (
      <Card className="border border-emerald-300 dark:border-emerald-700 bg-emerald-50/50 dark:bg-emerald-950/20" data-testid="bc-purchase-invoice-panel">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-500" />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
              BC Purchase Invoice Created
            </CardTitle>
          </div>
        </CardHeader>
        <CardContent>
          <SuccessDisplay data={existingPI} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border border-border" data-testid="bc-purchase-invoice-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <FileInput className="w-4 h-4 text-violet-500" />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Create BC Purchase Invoice
            </CardTitle>
          </div>
          {state === 'idle' && (
            <Button size="sm" className="h-7 text-xs" onClick={runPreflight} data-testid="bc-pi-preflight-btn">
              <ChevronRight className="w-3 h-3 mr-1" /> Check Readiness
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state === 'loading' && <LoadingState />}
        {state === 'preflight' && preflight && (
          <PreflightView
            data={preflight}
            vendorOverride={vendorOverride}
            setVendorOverride={setVendorOverride}
            onConfirm={handleCreate}
            onCancel={() => { setState('idle'); setPreflight(null); }}
          />
        )}
        {state === 'creating' && <LoadingState message="Creating Purchase Invoice in BC..." />}
        {state === 'success' && result && <SuccessDisplay data={result} />}
        {state === 'error' && (
          <ErrorDisplay
            error={error}
            onRetry={runPreflight}
            onDismiss={() => { setState('idle'); setError(null); }}
          />
        )}
        {state === 'idle' && !existingPI && (
          <p className="text-xs text-muted-foreground">
            Run a readiness check to validate this document before creating a BC Purchase Invoice.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function LoadingState({ message = 'Running preflight checks...' }) {
  return (
    <div className="flex items-center gap-3 py-4" data-testid="bc-pi-loading">
      <Loader2 className="w-5 h-5 animate-spin text-violet-500" />
      <span className="text-sm text-muted-foreground">{message}</span>
    </div>
  );
}

function PreflightView({ data, vendorOverride, setVendorOverride, onConfirm, onCancel }) {
  const mv = data.mapped_values || {};
  const hasVendor = !!(vendorOverride.trim() || mv.vendor_no);

  return (
    <div className="space-y-4" data-testid="bc-pi-preflight-view">
      {/* Readiness summary */}
      <div className={`flex items-center gap-2 p-2.5 rounded-md ${data.ready ? 'bg-emerald-50 dark:bg-emerald-950/30' : 'bg-amber-50 dark:bg-amber-950/30'}`}>
        {data.ready ? (
          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
        ) : (
          <AlertTriangle className="w-4 h-4 text-amber-500 shrink-0" />
        )}
        <span className="text-xs font-medium">
          {data.ready ? 'Document is ready for Purchase Invoice creation' : 'Some issues need attention before creation'}
        </span>
      </div>

      {/* Errors */}
      {data.errors?.length > 0 && (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5">
          <p className="text-xs font-medium text-red-700 dark:text-red-300 mb-1">Blocking Issues</p>
          {data.errors.map((e, i) => (
            <p key={i} className="text-xs text-red-600 dark:text-red-400">
              <XCircle className="w-3 h-3 inline mr-1" />{e}
            </p>
          ))}
        </div>
      )}

      {/* Mapped values */}
      <div className="space-y-2">
        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">Mapped Values</p>
        <div className="grid grid-cols-1 gap-2 text-xs">
          <FieldRow icon={<Package className="w-3.5 h-3.5" />} label="BC Environment" value={mv.bc_environment || '-'} />
          <FieldRow icon={<Building2 className="w-3.5 h-3.5" />} label="Vendor" value={mv.vendor_no ? `${mv.vendor_no} — ${mv.vendor_name}` : ''} missing={!mv.vendor_no} />
          {mv.vendor_match_method && mv.vendor_match_method !== 'none' && (
            <div className="ml-7 text-[10px] text-muted-foreground">
              Match: {mv.vendor_match_method} ({(mv.vendor_match_confidence * 100).toFixed(0)}%)
            </div>
          )}
          <FieldRow icon={<Receipt className="w-3.5 h-3.5" />} label="Vendor Invoice No" value={mv.vendor_invoice_no} missing={!mv.vendor_invoice_no} />
          <FieldRow icon={<Calendar className="w-3.5 h-3.5" />} label="Document Date" value={mv.document_date} badge={mv.document_date_source === 'fallback_today' ? 'fallback' : null} />
          <FieldRow icon={<Calendar className="w-3.5 h-3.5" />} label="Posting Date" value={mv.posting_date} badge={mv.posting_date_source === 'fallback_today' ? 'fallback' : null} />
          {mv.due_date && <FieldRow icon={<Calendar className="w-3.5 h-3.5" />} label="Due Date" value={mv.due_date} />}
          {mv.po_number && <FieldRow icon={<FileText className="w-3.5 h-3.5" />} label="PO Number" value={mv.po_number} />}
          <FieldRow icon={<Hash className="w-3.5 h-3.5" />} label="Line Items" value={`${data.line_count} line(s)`} />
          {mv.total_amount != null && (
            <FieldRow icon={<Hash className="w-3.5 h-3.5" />} label="Total Amount" value={typeof mv.total_amount === 'number' ? `$${mv.total_amount.toLocaleString()}` : `$${mv.total_amount}`} />
          )}
          <FieldRow icon={<Shield className="w-3.5 h-3.5" />} label="Idempotency Key" value={mv.idempotency_key} mono />
        </div>
      </div>

      {/* Line items preview */}
      {data.line_items?.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-1.5">Line Items</p>
          <div className="bg-muted/50 rounded-md p-2 space-y-1 max-h-36 overflow-y-auto">
            {data.line_items.map((li, i) => (
              <div key={i} className="flex justify-between text-[11px]">
                <span className="truncate mr-2">{li.description}</span>
                <span className="font-mono shrink-0">{li.quantity} x ${li.unit_price} = ${li.total}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Vendor override if missing */}
      {!mv.vendor_no && (
        <div className="border border-amber-200 dark:border-amber-800 rounded-md p-3 bg-amber-50/50 dark:bg-amber-950/20">
          <Label className="text-xs font-medium text-amber-700 dark:text-amber-300">BC Vendor Number (required)</Label>
          <Input
            className="h-8 text-xs mt-1.5"
            placeholder="e.g. CARGOMO"
            value={vendorOverride}
            onChange={(e) => setVendorOverride(e.target.value)}
            data-testid="bc-pi-vendor-override-input"
          />
          <p className="text-[10px] text-muted-foreground mt-1">
            No vendor mapping found. Enter the BC vendor number manually.
          </p>
        </div>
      )}

      {/* Warnings */}
      {data.warnings?.length > 0 && (
        <div className="space-y-1">
          {data.warnings.map((w, i) => (
            <p key={i} className="text-[11px] text-amber-600 dark:text-amber-400 flex items-start gap-1.5">
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />{w}
            </p>
          ))}
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2 pt-2 border-t border-border">
        <Button
          size="sm"
          className="h-8 text-xs"
          onClick={onConfirm}
          disabled={!hasVendor || data.errors?.length > 0}
          data-testid="bc-pi-confirm-create-btn"
        >
          <FileInput className="w-3 h-3 mr-1.5" />
          Create Purchase Invoice
        </Button>
        <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={onCancel} data-testid="bc-pi-cancel-btn">
          Cancel
        </Button>
      </div>
    </div>
  );
}

function SuccessDisplay({ data }) {
  return (
    <div className="space-y-3" data-testid="bc-pi-success-view">
      <div className="grid grid-cols-1 gap-2 text-xs">
        {data.bc_record_no && (
          <div className="flex items-center justify-between bg-emerald-50 dark:bg-emerald-950/30 rounded-md p-2.5">
            <span className="text-emerald-700 dark:text-emerald-300 font-medium">BC Purchase Invoice No</span>
            <span className="font-mono font-bold text-emerald-800 dark:text-emerald-200">{data.bc_record_no}</span>
          </div>
        )}
        {data.bc_system_id && (
          <FieldRow icon={<Hash className="w-3.5 h-3.5" />} label="System ID" value={String(data.bc_system_id).slice(0, 24) + '...'} mono />
        )}
        {data.idempotency_key && (
          <FieldRow icon={<Shield className="w-3.5 h-3.5" />} label="Idempotency Key" value={data.idempotency_key} mono />
        )}
        {data.vendor_no && (
          <FieldRow icon={<Building2 className="w-3.5 h-3.5" />} label="Vendor" value={`${data.vendor_no}${data.vendor_name ? ' — ' + data.vendor_name : ''}`} />
        )}
        {data.vendor_invoice_no && (
          <FieldRow icon={<Receipt className="w-3.5 h-3.5" />} label="Invoice No" value={data.vendor_invoice_no} />
        )}
        {data.status && (
          <FieldRow
            icon={<CheckCircle2 className="w-3.5 h-3.5" />}
            label="Status"
            value={<Badge variant="secondary" className="text-[10px]">{data.status}</Badge>}
          />
        )}
        {data.created_at && (
          <FieldRow icon={<Calendar className="w-3.5 h-3.5" />} label="Created" value={new Date(data.created_at).toLocaleString()} />
        )}
      </div>
    </div>
  );
}

function ErrorDisplay({ error, onRetry, onDismiss }) {
  let errorType = 'unknown';
  let errorMsg = typeof error === 'string' ? error : JSON.stringify(error);

  if (errorMsg.includes('missing_vendor') || errorMsg.includes('vendor')) errorType = 'missing_vendor';
  else if (errorMsg.includes('not eligible')) errorType = 'ineligible';
  else if (errorMsg.includes('credentials') || errorMsg.includes('503')) errorType = 'credentials';
  else if (errorMsg.includes('permission') || errorMsg.includes('403')) errorType = 'permission';
  else if (errorMsg.includes('already')) errorType = 'duplicate';

  const labels = {
    missing_vendor: 'Vendor Mapping Required',
    ineligible: 'Not Eligible',
    credentials: 'BC Connection Issue',
    permission: 'Permission Denied',
    duplicate: 'Duplicate Request',
    unknown: 'Creation Failed',
  };

  return (
    <div className="space-y-3" data-testid="bc-pi-error-view">
      <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-3">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="w-4 h-4 text-red-500" />
          <span className="text-xs font-medium text-red-700 dark:text-red-300">{labels[errorType]}</span>
        </div>
        <p className="text-xs text-red-600 dark:text-red-400">{errorMsg}</p>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onRetry} data-testid="bc-pi-retry-btn">
          Retry
        </Button>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onDismiss} data-testid="bc-pi-dismiss-btn">
          Dismiss
        </Button>
      </div>
    </div>
  );
}

function FieldRow({ icon, label, value, mono, missing, badge }) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground shrink-0">{icon}</span>
      <span className="text-muted-foreground shrink-0">{label}:</span>
      <span className={`truncate ${mono ? 'font-mono' : ''} ${missing ? 'text-amber-500 italic' : ''}`}>
        {missing ? 'Not mapped' : (value || '-')}
      </span>
      {badge && <Badge variant="outline" className="text-[9px] h-4 px-1">{badge}</Badge>}
    </div>
  );
}
