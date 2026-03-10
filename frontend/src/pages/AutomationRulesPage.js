import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Button } from '../components/ui/button';
import { Badge } from '../components/ui/badge';
import { Input } from '../components/ui/input';
import { Switch } from '../components/ui/switch';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../components/ui/select';
import { toast } from 'sonner';
import {
  Zap, Plus, Trash2, Loader2, RefreshCw, Lightbulb, ChevronRight,
  CheckCircle2, Shield, X, Save, Play, Edit2, ArrowUpDown
} from 'lucide-react';
import {
  listAutomationRules, createAutomationRule, deleteAutomationRule,
  toggleAutomationRule, getRuleSuggestions, updateAutomationRule
} from '../lib/api';

const CONDITION_LABELS = {
  vendor_name: 'Vendor Name',
  vendor_no: 'Vendor No',
  stable_vendor_flag: 'Stable Vendor',
  document_type: 'Document Type',
  validation_state: 'Validation State',
  resolver_match_type: 'Match Type',
  resolver_match_score_gte: 'Match Score >=',
  reference_domain: 'Ref Domain',
  automation_success_rate_gte: 'Automation Rate >=',
  po_reference_frequency_gte: 'PO Freq >=',
  shipment_reference_frequency_gte: 'Ship Freq >=',
  bol_presence_rate_gte: 'BOL Rate >=',
  classification_confidence_gte: 'Confidence >=',
  duplicate_check: 'Duplicate Check',
};

const ACTION_LABELS = {
  route_to_queue: 'Route to Queue',
  assign_review_priority: 'Review Priority',
  flag_for_manual_review: 'Flag for Review',
  auto_mark_ready: 'Auto-Mark Ready',
  auto_route_to_accounting_queue: 'Route to Accounting',
};

function ConditionBadge({ k, v }) {
  const label = CONDITION_LABELS[k] || k;
  const display = typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v);
  return (
    <Badge variant="outline" className="text-[10px] font-mono mr-1 mb-1">
      {label}: {display}
    </Badge>
  );
}

function ActionBadge({ k, v }) {
  const label = ACTION_LABELS[k] || k;
  const display = typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v);
  return (
    <Badge className="text-[10px] bg-blue-100 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300 mr-1 mb-1">
      {label}: {display}
    </Badge>
  );
}

function RuleEditor({ initial, onSave, onCancel }) {
  const [form, setForm] = useState({
    rule_name: '',
    priority: 100,
    conditions: {},
    actions: {},
    enabled: true,
    ...initial,
  });
  const [condKey, setCondKey] = useState('');
  const [condVal, setCondVal] = useState('');
  const [actKey, setActKey] = useState('');
  const [actVal, setActVal] = useState('');

  const addCondition = () => {
    if (!condKey) return;
    let val = condVal;
    if (condVal === 'true') val = true;
    else if (condVal === 'false') val = false;
    else if (!isNaN(Number(condVal)) && condKey.includes('_gte')) val = Number(condVal);
    setForm(f => ({ ...f, conditions: { ...f.conditions, [condKey]: val } }));
    setCondKey(''); setCondVal('');
  };

  const removeCondition = (k) => {
    const c = { ...form.conditions };
    delete c[k];
    setForm(f => ({ ...f, conditions: c }));
  };

  const addAction = () => {
    if (!actKey) return;
    let val = actVal;
    if (actVal === 'true') val = true;
    else if (actVal === 'false') val = false;
    setForm(f => ({ ...f, actions: { ...f.actions, [actKey]: val } }));
    setActKey(''); setActVal('');
  };

  const removeAction = (k) => {
    const a = { ...form.actions };
    delete a[k];
    setForm(f => ({ ...f, actions: a }));
  };

  return (
    <Card className="border-2 border-blue-200 dark:border-blue-800" data-testid="rule-editor">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm">{initial?.rule_id ? 'Edit Rule' : 'New Rule'}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="text-[10px] text-muted-foreground uppercase">Rule Name</label>
            <Input value={form.rule_name} onChange={e => setForm(f => ({ ...f, rule_name: e.target.value }))} className="h-8 text-xs" data-testid="rule-name-input" />
          </div>
          <div>
            <label className="text-[10px] text-muted-foreground uppercase">Priority (lower = higher)</label>
            <Input type="number" value={form.priority} onChange={e => setForm(f => ({ ...f, priority: parseInt(e.target.value) || 100 }))} className="h-8 text-xs" />
          </div>
        </div>

        {/* Conditions */}
        <div>
          <label className="text-[10px] text-muted-foreground uppercase mb-1 block">Conditions</label>
          <div className="flex flex-wrap mb-2">
            {Object.entries(form.conditions).map(([k, v]) => (
              <div key={k} className="flex items-center gap-0.5 mr-1 mb-1">
                <ConditionBadge k={k} v={v} />
                <button onClick={() => removeCondition(k)} className="text-red-400 hover:text-red-600"><X className="w-3 h-3" /></button>
              </div>
            ))}
          </div>
          <div className="flex gap-1.5">
            <Select value={condKey} onValueChange={setCondKey}>
              <SelectTrigger className="h-7 text-[10px] w-[160px]"><SelectValue placeholder="Condition..." /></SelectTrigger>
              <SelectContent>{Object.keys(CONDITION_LABELS).map(k => (
                <SelectItem key={k} value={k} className="text-xs">{CONDITION_LABELS[k]}</SelectItem>
              ))}</SelectContent>
            </Select>
            <Input value={condVal} onChange={e => setCondVal(e.target.value)} placeholder="Value" className="h-7 text-[10px] w-[140px]" />
            <Button variant="outline" size="sm" onClick={addCondition} className="h-7 text-[10px] px-2"><Plus className="w-3 h-3" /></Button>
          </div>
        </div>

        {/* Actions */}
        <div>
          <label className="text-[10px] text-muted-foreground uppercase mb-1 block">Actions</label>
          <div className="flex flex-wrap mb-2">
            {Object.entries(form.actions).map(([k, v]) => (
              <div key={k} className="flex items-center gap-0.5 mr-1 mb-1">
                <ActionBadge k={k} v={v} />
                <button onClick={() => removeAction(k)} className="text-red-400 hover:text-red-600"><X className="w-3 h-3" /></button>
              </div>
            ))}
          </div>
          <div className="flex gap-1.5">
            <Select value={actKey} onValueChange={setActKey}>
              <SelectTrigger className="h-7 text-[10px] w-[160px]"><SelectValue placeholder="Action..." /></SelectTrigger>
              <SelectContent>{Object.keys(ACTION_LABELS).map(k => (
                <SelectItem key={k} value={k} className="text-xs">{ACTION_LABELS[k]}</SelectItem>
              ))}</SelectContent>
            </Select>
            <Input value={actVal} onChange={e => setActVal(e.target.value)} placeholder="Value" className="h-7 text-[10px] w-[140px]" />
            <Button variant="outline" size="sm" onClick={addAction} className="h-7 text-[10px] px-2"><Plus className="w-3 h-3" /></Button>
          </div>
        </div>

        <div className="flex items-center justify-end gap-2 pt-2 border-t">
          <Button variant="ghost" size="sm" onClick={onCancel} className="h-7 text-xs">Cancel</Button>
          <Button size="sm" onClick={() => onSave(form)} className="h-7 text-xs gap-1" data-testid="save-rule-btn">
            <Save className="w-3 h-3" /> Save Rule
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export default function AutomationRulesPage() {
  const [rules, setRules] = useState([]);
  const [suggestions, setSuggestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showEditor, setShowEditor] = useState(false);
  const [editingRule, setEditingRule] = useState(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [loadingSugg, setLoadingSugg] = useState(false);

  const fetchRules = useCallback(async () => {
    try {
      setLoading(true);
      const res = await listAutomationRules();
      setRules(res.data.rules || []);
    } catch { toast.error('Failed to load rules'); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { fetchRules(); }, [fetchRules]);

  const handleSave = async (form) => {
    try {
      if (editingRule?.rule_id) {
        await updateAutomationRule(editingRule.rule_id, form);
        toast.success('Rule updated');
      } else {
        await createAutomationRule(form);
        toast.success('Rule created');
      }
      setShowEditor(false);
      setEditingRule(null);
      fetchRules();
    } catch (e) {
      toast.error(e.response?.data?.detail || 'Failed to save rule');
    }
  };

  const handleDelete = async (ruleId) => {
    try {
      await deleteAutomationRule(ruleId);
      toast.success('Rule deleted');
      fetchRules();
    } catch { toast.error('Failed to delete'); }
  };

  const handleToggle = async (ruleId) => {
    try {
      await toggleAutomationRule(ruleId);
      fetchRules();
    } catch { toast.error('Toggle failed'); }
  };

  const handleLoadSuggestions = async () => {
    try {
      setLoadingSugg(true);
      const res = await getRuleSuggestions();
      setSuggestions(res.data.suggestions || []);
      setShowSuggestions(true);
    } catch { toast.error('Failed to load suggestions'); }
    finally { setLoadingSugg(false); }
  };

  const handleAcceptSuggestion = (s) => {
    setEditingRule(s.suggested_rule);
    setShowEditor(true);
    setShowSuggestions(false);
  };

  return (
    <div className="space-y-6" data-testid="automation-rules-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight" style={{ fontFamily: 'Chivo, sans-serif' }}>Automation Rules</h1>
          <p className="text-sm text-muted-foreground mt-0.5">Configure vendor-aware workflow routing</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleLoadSuggestions} disabled={loadingSugg} className="h-8 text-xs gap-1" data-testid="load-suggestions-btn">
            {loadingSugg ? <Loader2 className="w-3 h-3 animate-spin" /> : <Lightbulb className="w-3 h-3" />}
            Suggestions
          </Button>
          <Button size="sm" onClick={() => { setEditingRule(null); setShowEditor(true); }} className="h-8 text-xs gap-1" data-testid="new-rule-btn">
            <Plus className="w-3 h-3" /> New Rule
          </Button>
        </div>
      </div>

      {/* Suggestions Panel */}
      {showSuggestions && suggestions.length > 0 && (
        <Card className="border border-amber-200 dark:border-amber-800 bg-amber-50/50 dark:bg-amber-950/20" data-testid="suggestions-panel">
          <CardHeader className="pb-2">
            <div className="flex items-center justify-between">
              <CardTitle className="text-sm flex items-center gap-2">
                <Lightbulb className="w-4 h-4 text-amber-500" />
                AI-Suggested Rules ({suggestions.length})
              </CardTitle>
              <Button variant="ghost" size="sm" onClick={() => setShowSuggestions(false)} className="h-6 w-6 p-0"><X className="w-3 h-3" /></Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            {suggestions.map((s, idx) => (
              <div key={idx} className="bg-background border border-border rounded-md p-3 flex items-start justify-between gap-3" data-testid={`suggestion-${idx}`}>
                <div className="flex-1">
                  <p className="text-xs font-medium">{s.description}</p>
                  <div className="flex flex-wrap gap-1 mt-1.5">
                    {Object.entries(s.suggested_rule.conditions).map(([k, v]) => <ConditionBadge key={k} k={k} v={v} />)}
                    <ChevronRight className="w-3 h-3 text-muted-foreground self-center" />
                    {Object.entries(s.suggested_rule.actions).map(([k, v]) => <ActionBadge key={k} k={k} v={v} />)}
                  </div>
                  <div className="flex gap-3 mt-1 text-[10px] text-muted-foreground">
                    <span>Confidence: <strong>{(s.confidence * 100).toFixed(0)}%</strong></span>
                    <span>Invoices: {s.metrics?.invoice_count}</span>
                  </div>
                </div>
                <Button variant="outline" size="sm" onClick={() => handleAcceptSuggestion(s)} className="h-7 text-[10px] gap-1 shrink-0" data-testid={`accept-suggestion-${idx}`}>
                  <CheckCircle2 className="w-3 h-3" /> Accept
                </Button>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {/* Editor */}
      {showEditor && (
        <RuleEditor
          initial={editingRule}
          onSave={handleSave}
          onCancel={() => { setShowEditor(false); setEditingRule(null); }}
        />
      )}

      {/* Rules Table */}
      <Card className="border border-border">
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="text-xs w-8">#</TableHead>
                <TableHead className="text-xs">Rule Name</TableHead>
                <TableHead className="text-xs">Conditions</TableHead>
                <TableHead className="text-xs">Actions</TableHead>
                <TableHead className="text-xs w-16">Enabled</TableHead>
                <TableHead className="text-xs w-20">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {loading && (
                <TableRow><TableCell colSpan={6} className="text-center py-8"><Loader2 className="w-4 h-4 animate-spin mx-auto" /></TableCell></TableRow>
              )}
              {!loading && rules.length === 0 && (
                <TableRow><TableCell colSpan={6} className="text-center py-8 text-muted-foreground text-xs">
                  No automation rules yet. Click "New Rule" or "Suggestions" to get started.
                </TableCell></TableRow>
              )}
              {!loading && rules.map((rule) => (
                <TableRow key={rule.rule_id} data-testid={`rule-row-${rule.rule_id}`}>
                  <TableCell className="text-[10px] font-mono text-muted-foreground">{rule.priority}</TableCell>
                  <TableCell>
                    <p className="text-xs font-medium">{rule.rule_name}</p>
                    <p className="text-[10px] text-muted-foreground font-mono">{rule.rule_id}</p>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap">
                      {Object.entries(rule.conditions || {}).map(([k, v]) => <ConditionBadge key={k} k={k} v={v} />)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap">
                      {Object.entries(rule.actions || {}).map(([k, v]) => <ActionBadge key={k} k={k} v={v} />)}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Switch
                      checked={rule.enabled}
                      onCheckedChange={() => handleToggle(rule.rule_id)}
                      data-testid={`toggle-rule-${rule.rule_id}`}
                    />
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0" onClick={() => { setEditingRule(rule); setShowEditor(true); }}>
                        <Edit2 className="w-3 h-3" />
                      </Button>
                      <Button variant="ghost" size="sm" className="h-6 w-6 p-0 text-red-400 hover:text-red-600" onClick={() => handleDelete(rule.rule_id)}>
                        <Trash2 className="w-3 h-3" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
