import { useState, useCallback, useMemo } from 'react';
import { salesOrderPreflight, createSalesOrderFromDocument, createIncomingFromShortage, reconcileSalesOrder } from '../lib/api';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '../components/ui/select';
import { toast } from 'sonner';
import {
  ShoppingCart, Loader2, CheckCircle2, AlertCircle,
  AlertTriangle, ChevronRight, User, Calendar,
  FileText, Hash, Shield, XCircle, Pencil, RotateCcw,
  Plus, Trash2, Copy, Server, Warehouse, Package, TruckIcon,
} from 'lucide-react';

const ELIGIBLE_TYPES = new Set(['Sales_Order', 'SalesOrder', 'Order_Confirmation', 'PurchaseOrder']);
const LINE_TYPES = ['Item', 'Account', 'Comment'];

function isEligible(doc) {
  return ELIGIBLE_TYPES.has(doc?.document_type);
}

export default function CreateBCSalesOrderPanel({ document, onUpdate }) {
  const [state, setState] = useState('idle');
  const [preflight, setPreflight] = useState(null);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const [customerOverride, setCustomerOverride] = useState('');
  // Editable lines: null = not yet loaded, array = user's working copy
  const [editedLines, setEditedLines] = useState(null);
  // Snapshot of the original resolved lines from preflight (for reset)
  const [originalLines, setOriginalLines] = useState(null);

  const existingSO = document?.bc_sales_order;
  const eligible = isEligible(document);

  const runPreflight = useCallback(async () => {
    setState('loading');
    setError(null);
    try {
      const res = await salesOrderPreflight(document.id);
      const data = res.data;
      setPreflight(data);
      if (data.already_created) {
        setResult(data.existing_sales_order);
        setState('success');
      } else {
        // Deep clone resolved lines into editable state
        const cloned = JSON.parse(JSON.stringify(data.resolved_lines || []));
        setEditedLines(cloned);
        setOriginalLines(JSON.parse(JSON.stringify(data.resolved_lines || [])));
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
      const override = customerOverride.trim();
      const wsId = preflight?.inventory_workspace?.id || '';
      const res = await createSalesOrderFromDocument(document.id, {
        customerNoOverride: override,
        editedLines: editedLines,
        inventoryWorkspaceId: wsId,
      });
      setResult(res.data);
      if (res.data.success || res.data.already_exists) {
        setState('success');
        const commitInfo = res.data.inventory_commitments;
        const commitMsg = commitInfo?.committed ? ` (${commitInfo.committed} inventory commitments)` : '';
        toast.success(res.data.already_exists
          ? 'Sales Order already exists'
          : `Sales Order ${res.data.bc_record_no} created${commitMsg}`
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
  }, [document.id, customerOverride, editedLines, preflight, onUpdate]);

  const resetLines = useCallback(() => {
    if (originalLines) {
      setEditedLines(JSON.parse(JSON.stringify(originalLines)));
      toast.info('Lines reset to extracted values');
    }
  }, [originalLines]);

  const handleCreateShortageSupply = useCallback(async (shortageLines) => {
    const wsId = preflight?.inventory_workspace?.id;
    if (!wsId) {
      toast.error('No inventory workspace linked');
      return;
    }
    // Use external doc no or idempotency key as the SO reference
    const soRef = preflight?.mapped_values?.external_doc_no
      || preflight?.mapped_values?.idempotency_key || document.id;
    try {
      const res = await createIncomingFromShortage(soRef, shortageLines);
      const d = res.data;
      if (d.created > 0) {
        toast.success(`Created ${d.created} incoming supply record(s)`);
        // Re-run preflight to refresh inventory data
        runPreflight();
      } else if (d.duplicates?.length > 0) {
        toast.warning(`Incoming supply already exists for: ${d.duplicates.join(', ')}`);
      }
    } catch (err) {
      const detail = err.response?.data?.detail;
      const msg = typeof detail === 'object' ? detail.message : detail;
      toast.error(msg || 'Failed to create incoming supply');
    }
  }, [preflight, document.id, runPreflight]);

  const handleCancelOrder = useCallback(async () => {
    const soRef = existingSO?.bc_record_no || existingSO?.external_doc_no || document.id;
    if (!soRef) return;
    setState('creating');
    try {
      const res = await reconcileSalesOrder(soRef, [], true);
      const d = res.data;
      if (d.adjustments > 0) {
        toast.success(`Order cancelled — ${d.adjustments} inventory release(s) created`);
      } else {
        toast.info('Order cancelled — no remaining commitments to release');
      }
      onUpdate?.();
      setState('idle');
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Failed to cancel order inventory');
      setState('idle');
    }
  }, [existingSO, document.id, onUpdate]);

  if (!eligible && !existingSO) return null;

  if (existingSO && state === 'idle') {
    return (
      <Card className="border border-emerald-300 dark:border-emerald-700 bg-emerald-50/50 dark:bg-emerald-950/20" data-testid="bc-sales-order-panel">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-emerald-500" />
              <CardTitle className="text-sm font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400" style={{ fontFamily: 'Chivo, sans-serif' }}>
                BC Sales Order Created
              </CardTitle>
            </div>
            <Button variant="ghost" size="sm" className="h-6 text-[10px] text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/30"
              onClick={handleCancelOrder} data-testid="bc-so-cancel-order-btn">
              <XCircle className="w-3 h-3 mr-1" /> Cancel & Release Inventory
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <SuccessDisplay data={existingSO} isAlreadyExists={false} />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border border-border" data-testid="bc-sales-order-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <ShoppingCart className="w-4 h-4 text-blue-500" />
            <CardTitle className="text-sm font-bold uppercase tracking-wider text-muted-foreground" style={{ fontFamily: 'Chivo, sans-serif' }}>
              Create BC Sales Order
            </CardTitle>
          </div>
          {state === 'idle' && (
            <Button size="sm" className="h-7 text-xs" onClick={runPreflight} data-testid="bc-so-preflight-btn">
              <ChevronRight className="w-3 h-3 mr-1" /> Check Readiness
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {state === 'loading' && <LoadingState />}
        {state === 'preflight' && preflight && (
          <PreflightReview
            data={preflight}
            editedLines={editedLines}
            setEditedLines={setEditedLines}
            originalLines={originalLines}
            resetLines={resetLines}
            customerOverride={customerOverride}
            setCustomerOverride={setCustomerOverride}
            onConfirm={handleCreate}
            onCancel={() => { setState('idle'); setPreflight(null); setEditedLines(null); }}
            onCreateShortageSupply={handleCreateShortageSupply}
          />
        )}
        {state === 'creating' && <LoadingState message="Creating Sales Order in BC..." />}
        {state === 'success' && result && (
          <SuccessDisplay data={result} isAlreadyExists={result.already_exists} />
        )}
        {state === 'error' && (
          <ErrorDisplay error={error} onRetry={runPreflight} onDismiss={() => { setState('idle'); setError(null); }} />
        )}
        {state === 'idle' && !existingSO && (
          <p className="text-xs text-muted-foreground">
            Run a readiness check to review and confirm before creating a BC Sales Order.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function LoadingState({ message = 'Running preflight checks...' }) {
  return (
    <div className="flex items-center gap-3 py-4" data-testid="bc-so-loading">
      <Loader2 className="w-5 h-5 animate-spin text-blue-500" />
      <span className="text-sm text-muted-foreground">{message}</span>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// PREFLIGHT REVIEW — the main panel
// ════════════════════════════════════════════════════════════════

function PreflightReview({
  data, editedLines, setEditedLines, originalLines, resetLines,
  customerOverride, setCustomerOverride, onConfirm, onCancel, onCreateShortageSupply,
}) {
  const mv = data.mapped_values || {};
  const ds = data.document_summary || {};
  const checklist = data.validation_checklist || [];
  const hasCustomer = !!(customerOverride.trim() || mv.customer_no);
  const hasLines = editedLines && editedLines.length > 0;
  const linesEdited = JSON.stringify(editedLines) !== JSON.stringify(originalLines);

  // Live order total
  const orderTotal = useMemo(() => {
    if (!editedLines) return 0;
    return editedLines.reduce((sum, ln) => sum + (parseFloat(ln.quantity) || 0) * (parseFloat(ln.unitPrice) || 0), 0);
  }, [editedLines]);

  return (
    <div className="space-y-5" data-testid="bc-so-preflight-view">
      {/* ─── A. Environment Banner ─── */}
      <EnvironmentBanner mv={mv} />

      {/* ─── B. Document Summary ─── */}
      <DocumentSummary ds={ds} mv={mv} />

      {/* ─── C. Validation Checklist ─── */}
      <ValidationChecklist checklist={checklist} />

      {/* ─── C2. Inventory Summary ─── */}
      <InventorySummary invSummary={data.inventory_summary} invWorkspace={data.inventory_workspace} />

      {/* ─── Customer override if missing ─── */}
      {!mv.customer_no && (
        <div className="border border-amber-200 dark:border-amber-800 rounded-md p-3 bg-amber-50/50 dark:bg-amber-950/20">
          <Label className="text-xs font-medium text-amber-700 dark:text-amber-300">BC Customer Number (required)</Label>
          <Input
            className="h-8 text-xs mt-1.5"
            placeholder="e.g. C00100"
            value={customerOverride}
            onChange={(e) => setCustomerOverride(e.target.value)}
            data-testid="bc-so-customer-override-input"
          />
        </div>
      )}

      {/* ─── D. Editable Line Preview ─── */}
      <EditableLineTable
        lines={editedLines}
        setLines={setEditedLines}
        linesEdited={linesEdited}
        resetLines={resetLines}
        orderTotal={orderTotal}
        onCreateShortageSupply={onCreateShortageSupply}
      />

      {/* ─── E. Warnings ─── */}
      {data.warnings?.length > 0 && (
        <div className="space-y-1">
          {data.warnings.map((w, i) => (
            <p key={i} className="text-[11px] text-amber-600 dark:text-amber-400 flex items-start gap-1.5">
              <AlertTriangle className="w-3 h-3 shrink-0 mt-0.5" />{w}
            </p>
          ))}
        </div>
      )}

      {/* ─── F. Errors ─── */}
      {data.errors?.length > 0 && (
        <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-2.5">
          <p className="text-xs font-medium text-red-700 dark:text-red-300 mb-1">Blocking Issues</p>
          {data.errors.map((e, i) => (
            <p key={i} className="text-xs text-red-600 dark:text-red-400 flex items-start gap-1">
              <XCircle className="w-3 h-3 shrink-0 mt-0.5" />{e}
            </p>
          ))}
        </div>
      )}

      {/* ─── G. Confirmation ─── */}
      <ConfirmationBar
        mv={mv}
        customerOverride={customerOverride}
        hasCustomer={hasCustomer}
        hasLines={hasLines}
        lineCount={editedLines?.length || 0}
        orderTotal={orderTotal}
        linesEdited={linesEdited}
        errors={data.errors}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// A. ENVIRONMENT BANNER
// ════════════════════════════════════════════════════════════════

function EnvironmentBanner({ mv }) {
  return (
    <div className="flex items-center gap-3 bg-slate-900 text-slate-100 dark:bg-slate-800 rounded-md p-3" data-testid="bc-so-env-banner">
      <Server className="w-4 h-4 text-slate-400 shrink-0" />
      <div className="flex-1 text-xs space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="text-slate-400 w-16">Read</span>
          <Badge variant="outline" className="text-[10px] h-5 border-emerald-500/50 text-emerald-400 font-mono">{mv.bc_read_environment || 'Production'}</Badge>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-slate-400 w-16">Write</span>
          <Badge variant="outline" className="text-[10px] h-5 border-amber-500/50 text-amber-400 font-mono">{mv.bc_write_environment || 'Sandbox'}</Badge>
        </div>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// B. DOCUMENT SUMMARY
// ════════════════════════════════════════════════════════════════

function DocumentSummary({ ds, mv }) {
  return (
    <div data-testid="bc-so-doc-summary">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Document Summary</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs bg-muted/30 rounded-md p-3 border border-border">
        <SummaryRow label="Document ID" value={ds.document_id ? ds.document_id.slice(0, 12) + '...' : '-'} mono icon={<Hash className="w-3 h-3" />} />
        <SummaryRow label="Source" value={ds.source || '-'} icon={<FileText className="w-3 h-3" />} />
        <SummaryRow label="Document Type" value={ds.document_type || '-'} />
        <SummaryRow label="Extraction" value={ds.extraction_completeness != null ? `${Math.round(ds.extraction_completeness * 100)}%` : '-'} />
        <SummaryRow label="Customer" value={mv.customer_no ? `${mv.customer_no} — ${mv.customer_name || ''}` : 'Not resolved'} missing={!mv.customer_no} icon={<User className="w-3 h-3" />} />
        {mv.customer_match_method && mv.customer_match_method !== 'none' && (
          <SummaryRow label="Match" value={`${mv.customer_match_method} (${Math.round((mv.customer_match_confidence || 0) * 100)}%)`} />
        )}
        <SummaryRow label="External Doc (PO)" value={ds.external_doc_no || 'Not found'} missing={!ds.external_doc_no} icon={<FileText className="w-3 h-3" />} />
        <SummaryRow label="Order Date" value={ds.order_date || '-'} badge={ds.order_date_source === 'fallback_today' ? 'fallback' : null} icon={<Calendar className="w-3 h-3" />} />
        {ds.total_amount != null && (
          <SummaryRow label="Total Amount" value={`$${Number(ds.total_amount).toLocaleString(undefined, { minimumFractionDigits: 2 })}`} icon={<Hash className="w-3 h-3" />} />
        )}
        <SummaryRow label="Idempotency" value={mv.idempotency_key || '-'} mono icon={<Shield className="w-3 h-3" />} />
      </div>
    </div>
  );
}

function SummaryRow({ label, value, mono, missing, badge, icon }) {
  return (
    <div className="flex items-center gap-1.5 min-w-0">
      {icon && <span className="text-muted-foreground shrink-0">{icon}</span>}
      <span className="text-muted-foreground shrink-0 text-[11px]">{label}:</span>
      <span className={`truncate text-[11px] ${mono ? 'font-mono' : ''} ${missing ? 'text-amber-500 italic' : ''}`}>
        {value}
      </span>
      {badge && <Badge variant="outline" className="text-[8px] h-4 px-1 ml-1">{badge}</Badge>}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// C. VALIDATION CHECKLIST
// ════════════════════════════════════════════════════════════════

function ValidationChecklist({ checklist }) {
  if (!checklist || checklist.length === 0) return null;
  return (
    <div data-testid="bc-so-validation-checklist">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Validation Checklist</p>
      <div className="space-y-1">
        {checklist.map((item, i) => (
          <div key={i} className="flex items-center gap-2 text-xs" data-testid={`checklist-item-${i}`}>
            {item.passed ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
            ) : item.blocking === false ? (
              <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
            ) : (
              <XCircle className="w-3.5 h-3.5 text-red-500 shrink-0" />
            )}
            <span className={item.passed ? '' : item.blocking === false ? 'text-amber-600 dark:text-amber-400' : 'text-red-600 dark:text-red-400'}>
              {item.label}
            </span>
            <span className="text-muted-foreground text-[10px] truncate ml-auto">{item.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// C2. INVENTORY SUMMARY
// ════════════════════════════════════════════════════════════════

const INV_STATUS_BADGE = {
  OK: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300 border-emerald-200',
  LOW: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 border-amber-200',
  SHORT: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300 border-red-200',
  'NO_MATCH': 'bg-gray-100 text-gray-500 dark:bg-gray-800 dark:text-gray-400 border-gray-200',
};

function InventorySummary({ invSummary, invWorkspace }) {
  if (!invSummary && !invWorkspace) return null;

  return (
    <div data-testid="bc-so-inventory-summary">
      <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold mb-2">Customer Inventory</p>
      {invWorkspace ? (
        <div className="bg-muted/30 rounded-md p-3 border border-border space-y-2">
          <div className="flex items-center gap-2 text-xs">
            <Warehouse className="w-3.5 h-3.5 text-primary" />
            <span className="font-medium">{invWorkspace.name}</span>
            <span className="font-mono text-[10px] text-muted-foreground">{invWorkspace.code}</span>
            <Badge variant="outline" className="text-[8px] h-4 px-1 ml-auto">
              {invWorkspace.negative_balance_policy === 'block_commitment' ? 'Block on Short' : 'Warn Only'}
            </Badge>
          </div>
          {invSummary && (
            <div className="flex gap-4 text-[11px]">
              <span className="text-emerald-600 dark:text-emerald-400">
                <Package className="w-3 h-3 inline mr-0.5" />{invSummary.lines_matched} matched
              </span>
              {invSummary.lines_short > 0 && (
                <span className="text-red-600 dark:text-red-400 font-medium">
                  <AlertTriangle className="w-3 h-3 inline mr-0.5" />{invSummary.lines_short} short
                </span>
              )}
              <span className="text-muted-foreground">{invSummary.lines_no_match} no match</span>
            </div>
          )}
        </div>
      ) : invSummary?.available_workspaces?.length > 0 ? (
        <div className="bg-amber-50/50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800 rounded-md p-2.5">
          <p className="text-[11px] text-amber-700 dark:text-amber-300">
            <AlertTriangle className="w-3 h-3 inline mr-1" />
            No inventory workspace matched this customer. Available: {invSummary.available_workspaces.map(w => w.name).join(', ')}
          </p>
        </div>
      ) : (
        <p className="text-[11px] text-muted-foreground">No inventory workspaces configured.</p>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// D. EDITABLE LINE TABLE
// ════════════════════════════════════════════════════════════════

function EditableLineTable({ lines, setLines, linesEdited, resetLines, orderTotal, onCreateShortageSupply }) {
  if (!lines || lines.length === 0) return null;

  const updateLine = (idx, field, value) => {
    setLines(prev => {
      const next = [...prev];
      next[idx] = { ...next[idx], [field]: value };
      // If changing lineType, update lineObjectNumber accordingly
      if (field === 'lineType') {
        if (value === 'Comment') {
          next[idx].lineObjectNumber = '';
          next[idx].mapping = { ...next[idx].mapping, matched: false, target_type: 'comment', target_no: '' };
        }
      }
      return next;
    });
  };

  const removeLine = (idx) => {
    setLines(prev => prev.filter((_, i) => i !== idx));
  };

  const addLine = () => {
    setLines(prev => [...prev, {
      lineType: 'Comment',
      lineObjectNumber: '',
      description: '',
      quantity: 1,
      unitPrice: 0,
      source: 'manual',
      mapping: { matched: false, target_type: 'comment', target_no: '', confidence: 0, method: 'manual' },
    }]);
  };

  return (
    <div data-testid="bc-so-line-table">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-bold">
            Line Preview ({lines.length})
          </p>
          {linesEdited && (
            <Badge variant="outline" className="text-[9px] h-4 px-1.5 border-blue-300 text-blue-600 dark:text-blue-400">
              <Pencil className="w-2.5 h-2.5 mr-0.5" /> Edited
            </Badge>
          )}
        </div>
        <div className="flex gap-1">
          {linesEdited && (
            <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2" onClick={resetLines} data-testid="bc-so-reset-lines-btn">
              <RotateCcw className="w-3 h-3 mr-1" /> Reset
            </Button>
          )}
          <Button variant="ghost" size="sm" className="h-6 text-[10px] px-2" onClick={addLine} data-testid="bc-so-add-line-btn">
            <Plus className="w-3 h-3 mr-1" /> Add Line
          </Button>
        </div>
      </div>

      <div className="bg-muted/30 rounded-md overflow-hidden border border-border">
        <table className="w-full text-[11px]">
          <thead>
            <tr className="border-b border-border bg-muted/80">
              <th className="text-left py-1.5 px-2 font-medium text-muted-foreground w-[80px]">Type</th>
              <th className="text-left py-1.5 px-2 font-medium text-muted-foreground">Description</th>
              <th className="text-left py-1.5 px-2 font-medium text-muted-foreground w-[80px]">Target</th>
              <th className="text-right py-1.5 px-2 font-medium text-muted-foreground w-[55px]">Qty</th>
              <th className="text-right py-1.5 px-2 font-medium text-muted-foreground w-[70px]">Price</th>
              <th className="text-right py-1.5 px-2 font-medium text-muted-foreground w-[70px]">Total</th>
              <th className="text-right py-1.5 px-2 font-medium text-muted-foreground w-[55px]">Avail</th>
              <th className="text-center py-1.5 px-2 font-medium text-muted-foreground w-[50px]">Inv</th>
              <th className="w-[26px]"></th>
            </tr>
          </thead>
          <tbody>
            {lines.map((ln, i) => (
              <EditableLine key={i} index={i} line={ln} updateLine={updateLine} removeLine={removeLine} onCreateShortageSupply={onCreateShortageSupply} />
            ))}
          </tbody>
          <tfoot>
            <tr className="bg-muted/80 border-t border-border">
              <td colSpan={5} className="py-2 px-2 text-right font-medium text-muted-foreground">Order Total</td>
              <td className="py-2 px-2 text-right font-mono font-bold" data-testid="bc-so-order-total">
                ${orderTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}
              </td>
              <td colSpan={3}></td>
            </tr>
          </tfoot>
        </table>
      </div>
    </div>
  );
}

function EditableLine({ index, line, updateLine, removeLine, onCreateShortageSupply }) {
  const mp = line.mapping || {};
  const inv = line.inventory || {};
  const lineTotal = (parseFloat(line.quantity) || 0) * (parseFloat(line.unitPrice) || 0);
  const ordered = parseFloat(line.quantity) || 0;

  const typeBadgeClass = {
    Item: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    Account: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    Comment: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
  }[line.lineType] || '';

  // Compute inventory status relative to ordered qty
  let invStatus = inv.status || (inv.matched ? 'OK' : 'NO_MATCH');
  if (inv.matched && inv.available < ordered) {
    invStatus = inv.available <= 0 ? 'SHORT' : 'LOW';
  }

  const isShort = invStatus === 'SHORT' || invStatus === 'LOW';
  const itemKey = line.lineObjectNumber || '';

  const handleSupplyClick = () => {
    if (!onCreateShortageSupply || !itemKey) return;
    onCreateShortageSupply([{
      item: itemKey,
      qty_needed: ordered,
      qty_available: inv.available ?? 0,
    }]);
  };

  return (
    <tr className="border-b border-border/50 last:border-0 group" data-testid={`so-line-${index}`}>
      {/* Type */}
      <td className="py-1 px-1.5">
        <Select value={line.lineType} onValueChange={(v) => updateLine(index, 'lineType', v)}>
          <SelectTrigger className="h-6 text-[10px] px-1.5 border-0 bg-transparent">
            <SelectValue>
              <Badge variant="secondary" className={`text-[9px] h-4 px-1 ${typeBadgeClass}`}>{line.lineType}</Badge>
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {LINE_TYPES.map(t => <SelectItem key={t} value={t} className="text-xs">{t}</SelectItem>)}
          </SelectContent>
        </Select>
      </td>
      {/* Description */}
      <td className="py-1 px-1.5">
        <Input
          className="h-6 text-[11px] border-0 bg-transparent px-1 focus:bg-white dark:focus:bg-slate-900 rounded"
          value={line.description || ''}
          onChange={(e) => updateLine(index, 'description', e.target.value)}
          data-testid={`so-line-${index}-desc`}
        />
      </td>
      {/* Target Number */}
      <td className="py-1 px-1.5">
        {line.lineType !== 'Comment' ? (
          <Input
            className="h-6 text-[10px] font-mono border-0 bg-transparent px-1 focus:bg-white dark:focus:bg-slate-900 rounded w-full"
            value={line.lineObjectNumber || ''}
            onChange={(e) => updateLine(index, 'lineObjectNumber', e.target.value)}
            placeholder={line.lineType === 'Account' ? 'GL #' : 'Item #'}
            data-testid={`so-line-${index}-target`}
          />
        ) : (
          <span className="text-[10px] text-muted-foreground italic px-1">-</span>
        )}
      </td>
      {/* Qty */}
      <td className="py-1 px-1.5">
        <Input
          type="number" min="0" step="1"
          className="h-6 text-[11px] font-mono border-0 bg-transparent px-1 text-right focus:bg-white dark:focus:bg-slate-900 rounded w-full"
          value={line.quantity ?? ''}
          onChange={(e) => updateLine(index, 'quantity', parseFloat(e.target.value) || 0)}
          data-testid={`so-line-${index}-qty`}
        />
      </td>
      {/* Unit Price */}
      <td className="py-1 px-1.5">
        <Input
          type="number" min="0" step="0.01"
          className="h-6 text-[11px] font-mono border-0 bg-transparent px-1 text-right focus:bg-white dark:focus:bg-slate-900 rounded w-full"
          value={line.unitPrice ?? ''}
          onChange={(e) => updateLine(index, 'unitPrice', parseFloat(e.target.value) || 0)}
          data-testid={`so-line-${index}-price`}
        />
      </td>
      {/* Line Total */}
      <td className="py-1 px-1.5 text-right font-mono font-medium text-[11px]" data-testid={`so-line-${index}-total`}>
        ${lineTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}
      </td>
      {/* Inventory Available */}
      <td className="py-1 px-1.5 text-right" data-testid={`so-line-${index}-inv-avail`}>
        {inv.matched ? (
          <span className={`text-[10px] font-mono font-medium ${inv.available < ordered ? 'text-red-600 dark:text-red-400' : 'text-emerald-600 dark:text-emerald-400'}`}
            title={`OH:${inv.on_hand} IN:${inv.incoming} CM:${inv.committed} ${inv.unit_of_measure}`}>
            {inv.available}
          </span>
        ) : (
          <span className="text-[10px] text-muted-foreground/40">-</span>
        )}
      </td>
      {/* Inventory Status Badge + Shortage Supply Button */}
      <td className="py-1 px-1.5 text-center" data-testid={`so-line-${index}-inv-status`}>
        <div className="flex items-center justify-center gap-0.5">
          <Badge variant="outline" className={`text-[8px] h-4 px-1 ${INV_STATUS_BADGE[invStatus] || INV_STATUS_BADGE['NO_MATCH']}`}>
            {invStatus === 'NO_MATCH' ? '—' : invStatus}
          </Badge>
          {isShort && inv.matched && itemKey && (
            <Button
              variant="ghost" size="sm"
              className="h-4 w-4 p-0 text-amber-500 hover:text-amber-700 dark:hover:text-amber-300"
              onClick={handleSupplyClick}
              title="Create Incoming Supply"
              data-testid={`so-line-${index}-create-supply-btn`}
            >
              <TruckIcon className="w-3 h-3" />
            </Button>
          )}
        </div>
      </td>
      {/* Remove */}
      <td className="py-1 px-0.5">
        <Button
          variant="ghost" size="sm"
          className="h-5 w-5 p-0 opacity-0 group-hover:opacity-100 transition-opacity text-red-400 hover:text-red-600"
          onClick={() => removeLine(index)} data-testid={`so-line-${index}-remove`}
        >
          <Trash2 className="w-3 h-3" />
        </Button>
      </td>
    </tr>
  );
}

// ════════════════════════════════════════════════════════════════
// G. CONFIRMATION BAR
// ════════════════════════════════════════════════════════════════

function ConfirmationBar({ mv, customerOverride, hasCustomer, hasLines, lineCount, orderTotal, linesEdited, errors, onConfirm, onCancel }) {
  const customer = customerOverride.trim() || mv.customer_no || '?';
  const env = mv.bc_write_environment || 'Sandbox';
  const blocked = !hasCustomer || !hasLines || (errors?.length > 0);

  return (
    <div className="pt-3 border-t border-border space-y-2" data-testid="bc-so-confirmation">
      <div className="flex items-center justify-between text-[11px] text-muted-foreground">
        <span>{lineCount} line{lineCount !== 1 ? 's' : ''} &middot; Customer {customer} &middot; {env}</span>
        <span className="font-mono font-bold">${orderTotal.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
      </div>
      {linesEdited && (
        <p className="text-[10px] text-blue-600 dark:text-blue-400 flex items-center gap-1">
          <Pencil className="w-3 h-3" /> Lines have been edited. Edited values will be submitted.
        </p>
      )}
      <div className="flex gap-2">
        <Button
          size="sm"
          className="h-8 text-xs flex-1"
          onClick={onConfirm}
          disabled={blocked}
          data-testid="bc-so-confirm-create-btn"
        >
          <ShoppingCart className="w-3.5 h-3.5 mr-1.5" />
          Create Sales Order in {env}
        </Button>
        <Button variant="ghost" size="sm" className="h-8 text-xs" onClick={onCancel} data-testid="bc-so-cancel-btn">
          Cancel
        </Button>
      </div>
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// SUCCESS DISPLAY
// ════════════════════════════════════════════════════════════════

function SuccessDisplay({ data, isAlreadyExists }) {
  return (
    <div className="space-y-3" data-testid="bc-so-success-view">
      {/* Distinct banner for created vs already exists */}
      {isAlreadyExists ? (
        <div className="flex items-center gap-2 p-2.5 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
          <Copy className="w-4 h-4 text-amber-500 shrink-0" />
          <div>
            <p className="text-xs font-medium text-amber-700 dark:text-amber-300">Sales Order Already Exists</p>
            <p className="text-[10px] text-amber-600 dark:text-amber-400">This document was previously used to create a BC Sales Order. No new record was created.</p>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-2 p-2.5 rounded-md bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
          <CheckCircle2 className="w-4 h-4 text-emerald-500 shrink-0" />
          <div>
            <p className="text-xs font-medium text-emerald-700 dark:text-emerald-300">Sales Order Created Successfully</p>
            <p className="text-[10px] text-emerald-600 dark:text-emerald-400">The order has been created in Business Central.</p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 gap-2 text-xs">
        {data.bc_record_no && (
          <div className="flex items-center justify-between bg-slate-50 dark:bg-slate-900/50 rounded-md p-2.5">
            <span className="text-muted-foreground font-medium">BC Sales Order No</span>
            <span className="font-mono font-bold text-lg">{data.bc_record_no}</span>
          </div>
        )}
        {(data.lines_added != null || data.lines_total != null) && (
          <div className="flex items-center justify-between rounded-md p-2.5 bg-blue-50 dark:bg-blue-950/30">
            <span className="text-blue-700 dark:text-blue-300 font-medium">Sales Lines</span>
            <span className="font-mono font-bold text-blue-800 dark:text-blue-200">
              {data.lines_added ?? 0}/{data.lines_total ?? 0} added
            </span>
          </div>
        )}
        {data.customer_no && (
          <SummaryRow icon={<User className="w-3 h-3" />} label="Customer" value={`${data.customer_no}${data.customer_name ? ' — ' + data.customer_name : ''}`} />
        )}
        {data.external_doc_no && (
          <SummaryRow icon={<FileText className="w-3 h-3" />} label="External Doc" value={data.external_doc_no} />
        )}
        {data.idempotency_key && (
          <SummaryRow icon={<Shield className="w-3 h-3" />} label="Idempotency Key" value={data.idempotency_key} mono />
        )}
        {data.created_at && (
          <SummaryRow icon={<Calendar className="w-3 h-3" />} label="Created" value={new Date(data.created_at).toLocaleString()} />
        )}
      </div>
      {data.line_errors?.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 rounded-md p-2.5">
          <p className="text-[10px] font-medium text-amber-700 dark:text-amber-300 mb-1">Line Warnings</p>
          {data.line_errors.map((e, i) => (
            <p key={i} className="text-[10px] text-amber-600 dark:text-amber-400">
              Line {e.line}: {typeof e.error === 'string' ? e.error.slice(0, 100) : JSON.stringify(e.error).slice(0, 100)}
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

// ════════════════════════════════════════════════════════════════
// ERROR DISPLAY
// ════════════════════════════════════════════════════════════════

function ErrorDisplay({ error, onRetry, onDismiss }) {
  let errorType = 'unknown';
  let errorMsg = typeof error === 'string' ? error : JSON.stringify(error);

  if (errorMsg.includes('missing_customer') || errorMsg.includes('customer')) errorType = 'missing_customer';
  else if (errorMsg.includes('not eligible')) errorType = 'ineligible';
  else if (errorMsg.includes('credentials') || errorMsg.includes('503')) errorType = 'credentials';
  else if (errorMsg.includes('catalog_validation')) errorType = 'catalog_validation';
  else if (errorMsg.includes('already')) errorType = 'duplicate';

  const labels = {
    missing_customer: 'Customer Mapping Required',
    ineligible: 'Not Eligible',
    credentials: 'BC Connection Issue',
    catalog_validation: 'Catalog Validation Failed',
    duplicate: 'Duplicate Request',
    unknown: 'Creation Failed',
  };

  return (
    <div className="space-y-3" data-testid="bc-so-error-view">
      <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-md p-3">
        <div className="flex items-center gap-2 mb-1">
          <AlertCircle className="w-4 h-4 text-red-500" />
          <span className="text-xs font-medium text-red-700 dark:text-red-300">{labels[errorType]}</span>
        </div>
        <p className="text-xs text-red-600 dark:text-red-400">{errorMsg}</p>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" className="h-7 text-xs" onClick={onRetry} data-testid="bc-so-retry-btn">Retry</Button>
        <Button variant="ghost" size="sm" className="h-7 text-xs" onClick={onDismiss} data-testid="bc-so-dismiss-btn">Dismiss</Button>
      </div>
    </div>
  );
}
