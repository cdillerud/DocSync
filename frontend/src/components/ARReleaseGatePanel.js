/**
 * AR Release Gate Panel — Shows the prepay/terms approval status
 * for sales documents on the DocumentDetailPage.
 */
import React, { useState } from 'react';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '../components/ui/card';
import { Badge } from '../components/ui/badge';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import {
  ShieldCheck, ShieldAlert, ShieldOff, Lock, Unlock, User,
  CreditCard, DollarSign, MapPin, FileText, Loader2, CheckCircle2,
  XCircle, AlertTriangle, RefreshCw
} from 'lucide-react';

const API = process.env.REACT_APP_BACKEND_URL;

const CHECK_META = {
  customer_resolution: { icon: User, label: 'Customer Resolution' },
  prepay_hold: { icon: Lock, label: 'Prepay Hold' },
  credit_limit: { icon: DollarSign, label: 'Credit Limit' },
  payment_terms: { icon: CreditCard, label: 'Payment Terms' },
  ship_to: { icon: MapPin, label: 'Ship-to Address' },
};

const STATUS_STYLE = {
  released: { icon: ShieldCheck, color: 'text-emerald-500', bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', label: 'Released' },
  held: { icon: ShieldAlert, color: 'text-red-500', bg: 'bg-red-500/10', border: 'border-red-500/30', label: 'Held' },
  override: { icon: Unlock, color: 'text-amber-500', bg: 'bg-amber-500/10', border: 'border-amber-500/30', label: 'Override' },
  pending: { icon: ShieldOff, color: 'text-muted-foreground', bg: 'bg-muted/10', border: 'border-muted', label: 'Pending' },
};

const RESULT_ICON = {
  pass: { icon: CheckCircle2, color: 'text-emerald-500' },
  warning: { icon: AlertTriangle, color: 'text-amber-500' },
  fail: { icon: XCircle, color: 'text-red-500' },
};

export default function ARReleaseGatePanel({ gate, documentId, onRefresh }) {
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [approver, setApprover] = useState('');
  const [notes, setNotes] = useState('');
  const [loading, setLoading] = useState(false);
  const [evaluating, setEvaluating] = useState(false);

  // Only show for documents that have gate data or have a documentId to evaluate
  if (!gate && !documentId) return null;

  const status = gate?.status || 'pending';
  const style = STATUS_STYLE[status] || STATUS_STYLE.pending;
  const StatusIcon = style.icon;
  const checks = gate?.checks || {};

  const handleEvaluate = async () => {
    setEvaluating(true);
    try {
      await fetch(`${API}/api/ar-release/evaluate/${documentId}`, { method: 'POST' });
      onRefresh?.();
    } catch (e) { console.error(e); }
    setEvaluating(false);
  };

  const handleOverride = async () => {
    if (!approver.trim()) return;
    setLoading(true);
    try {
      await fetch(`${API}/api/ar-release/override/${documentId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved_by: approver, notes }),
      });
      setOverrideOpen(false);
      onRefresh?.();
    } catch (e) { console.error(e); }
    setLoading(false);
  };

  return (
    <Card className={`border-2 ${style.border} ${style.bg}`} data-testid="ar-release-gate-panel">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <StatusIcon className={`w-5 h-5 ${style.color}`} />
            <CardTitle className="text-base font-bold" style={{ fontFamily: 'Chivo, sans-serif' }}>
              AR Release Gate
            </CardTitle>
            <Badge className={`${style.bg} ${style.color} border-0 text-xs`} data-testid="ar-gate-status">
              {style.label}
            </Badge>
          </div>
          <Button size="sm" variant="ghost" onClick={handleEvaluate} disabled={evaluating} data-testid="ar-gate-evaluate-btn">
            {evaluating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <RefreshCw className="w-3.5 h-3.5" />}
          </Button>
        </div>
        <CardDescription>Prepay, credit, and terms approval checks for sales documents</CardDescription>
      </CardHeader>

      <CardContent className="space-y-3">
        {/* Individual checks */}
        {Object.keys(checks).length > 0 ? (
          <div className="space-y-1.5">
            {Object.entries(checks).map(([key, check]) => {
              const meta = CHECK_META[key] || { icon: FileText, label: key };
              const Icon = meta.icon;
              const ri = RESULT_ICON[check.result] || RESULT_ICON.warning;
              const ResultIcon = ri.icon;
              return (
                <div key={key} className="flex items-center gap-2 text-sm" data-testid={`ar-check-${key}`}>
                  <Icon className="w-3.5 h-3.5 text-muted-foreground flex-shrink-0" />
                  <span className="font-medium min-w-[130px]">{meta.label}</span>
                  <ResultIcon className={`w-3.5 h-3.5 ${ri.color} flex-shrink-0`} />
                  <span className="text-xs text-muted-foreground truncate">{check.detail}</span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Not yet evaluated.{' '}
            <button className="underline" onClick={handleEvaluate} data-testid="ar-gate-evaluate-link">
              Run evaluation
            </button>
          </p>
        )}

        {/* Override info */}
        {gate?.override && (
          <div className="text-xs text-muted-foreground border-t pt-2 mt-2">
            Overridden by <span className="font-semibold">{gate.override.approved_by}</span>
            {gate.override.approved_at && ` on ${new Date(gate.override.approved_at).toLocaleDateString()}`}
            {gate.override.notes && ` — "${gate.override.notes}"`}
          </div>
        )}

        {/* Override action */}
        {status === 'held' && !overrideOpen && (
          <Button
            size="sm" variant="outline" className="mt-2 w-full text-xs"
            onClick={() => setOverrideOpen(true)}
            data-testid="ar-gate-override-btn"
          >
            <Unlock className="w-3 h-3 mr-1" /> Manual Override
          </Button>
        )}

        {overrideOpen && (
          <div className="space-y-2 border-t pt-2 mt-2" data-testid="ar-gate-override-form">
            <Input
              placeholder="Approved by (name)" value={approver}
              onChange={e => setApprover(e.target.value)}
              className="h-8 text-xs"
              data-testid="ar-gate-override-approver"
            />
            <Input
              placeholder="Notes (optional)" value={notes}
              onChange={e => setNotes(e.target.value)}
              className="h-8 text-xs"
              data-testid="ar-gate-override-notes"
            />
            <div className="flex gap-2">
              <Button size="sm" className="flex-1 text-xs h-7" onClick={handleOverride} disabled={loading || !approver.trim()} data-testid="ar-gate-override-confirm">
                {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Approve & Release'}
              </Button>
              <Button size="sm" variant="ghost" className="text-xs h-7" onClick={() => setOverrideOpen(false)}>
                Cancel
              </Button>
            </div>
          </div>
        )}

        {/* Timestamp */}
        {gate?.evaluated_at && (
          <div className="text-[10px] text-muted-foreground pt-1">
            Evaluated: {new Date(gate.evaluated_at).toLocaleString()}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
